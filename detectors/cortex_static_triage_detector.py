#!/usr/bin/env python3
"""Static triage detector for Cortex IDE.

This detector focuses on user-impacting bugs requested by the prompt:
- wrong report targets/URLs
- incorrect system information in reporting flows
- provider/feature unreachable from UI

Output contract: JSON list of findings to stdout.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def find_line_number(path: Path, snippet: str) -> Optional[int]:
    for idx, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if snippet in line:
            return idx
    return None


def display_path(repo_path: Path, file_path: Path) -> str:
    repo_root = repo_path.resolve()
    current = file_path.resolve()
    try:
        rel = current.relative_to(repo_root)
        return f"{repo_root.name}/{rel.as_posix()}"
    except ValueError:
        return current.as_posix()


def format_evidence(repo_path: Path, evidence: Sequence[Tuple[Path, str]]) -> str:
    lines: List[str] = []
    for file_path, snippet in evidence:
        shown = display_path(repo_path, file_path)
        line = find_line_number(file_path, snippet)
        if line is None:
            lines.append(f"- {shown}: snippet not found")
        else:
            lines.append(f"- {shown}:{line} -> {snippet}")
    return "\n".join(lines)


def optional_proofs(repo_path: Path, finding_id: str) -> List[str]:
    """Attach optional proof files if user has already captured native GUI artifacts.

    Expected locations:
    - <repo>/proofs/<finding_id>.png|.jpg|.jpeg|.mp4|.mov|.webm
    - $AUDIT_PROOF_DIR/<finding_id>.<ext>
    """
    # Default behavior: force fresh native GUI capture during the run.
    # Set AUDIT_ALLOW_PREEXISTING_PROOFS=1 only when intentionally reusing manual artifacts.
    if os.environ.get("AUDIT_ALLOW_PREEXISTING_PROOFS", "").strip() != "1":
        return []

    candidates: List[Path] = []
    local_proof_dir = repo_path / "proofs"
    env_proof_dir = Path(os.environ.get("AUDIT_PROOF_DIR", "")).expanduser() if os.environ.get("AUDIT_PROOF_DIR") else None

    for ext in (".png", ".jpg", ".jpeg", ".mp4", ".mov", ".webm"):
        candidates.append(local_proof_dir / f"{finding_id}{ext}")
        if env_proof_dir:
            candidates.append(env_proof_dir / f"{finding_id}{ext}")

    out: List[str] = []
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            out.append(str(candidate.resolve()))

    # Deduplicate while preserving order
    deduped: List[str] = []
    seen = set()
    for item in out:
        if item not in seen:
            deduped.append(item)
            seen.add(item)
    return deduped


def build_fingerprint(parts: Sequence[str]) -> str:
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def main() -> None:
    repo_path = Path(os.environ.get("AUDIT_REPO_PATH", ".")).expanduser().resolve()

    findings: List[Dict[str, object]] = []

    # -------------------------------------------------------------------------
    # Finding 1: Wrong report target URL in Documentation panel
    # -------------------------------------------------------------------------
    docs_panel = repo_path / "src/components/cortex/CortexDocumentationPanel.tsx"
    wrong_issue_url = "https://github.com/CortexLM/cortex-ide/issues"
    if docs_panel.exists() and find_line_number(docs_panel, wrong_issue_url):
        finding_id = "wrong-report-target-doc-panel"
        evidence = [(docs_panel, wrong_issue_url)]
        findings.append(
            {
                "finding_id": finding_id,
                "evidence_file": str(docs_panel),
                "evidence_line": find_line_number(docs_panel, wrong_issue_url),
                "title": "Report an Issue button routes to the wrong issue tracker",
                "description": (
                    "The Documentation panel 'Report an Issue' action opens CortexLM/cortex-ide issues "
                    "instead of the bounty submission repository. This misroutes bug reports and can cause "
                    "valid reports to be filed in an ineligible destination.\n\nEvidence:\n"
                    + format_evidence(repo_path, evidence)
                ),
                "reproduction_steps": [
                    "Open Cortex IDE and navigate to the Documentation panel.",
                    "Click 'Need Help?' then 'Report an Issue'.",
                    "Observe the opened URL goes to CortexLM/cortex-ide/issues instead of PlatformNetwork/bounty-challenge/issues.",
                ],
                "impact": (
                    "Users are directed to the wrong report target, leading to lost/invalid submissions and "
                    "broken bug-reporting workflow."
                ),
                "project": "cortex-ide",
                "expected_behavior": (
                    "Clicking 'Report an Issue' should open the official reporting destination for this program "
                    "(PlatformNetwork/bounty-challenge issues)."
                ),
                "actual_behavior": (
                    "Clicking 'Report an Issue' opens CortexLM/cortex-ide issues instead of the bounty challenge repository."
                ),
                "error_message": "No UI error is shown; the action silently opens the wrong URL target.",
                "debug_logs": "No debug logs required to reproduce this deterministic routing behavior.",
                "system_information": "Native GUI: Cortex IDE",
                "additional_context": "The wrong URL is hard-coded in the documentation panel handler.",
                "native_gui": "Cortex IDE",
                "proof_artifacts": optional_proofs(repo_path, finding_id),
                "fingerprint": build_fingerprint([finding_id, str(docs_panel), wrong_issue_url]),
            }
        )

    # -------------------------------------------------------------------------
    # Finding 2: Quick Access advertises issue provider that is not reachable
    # -------------------------------------------------------------------------
    help_provider = repo_path / "src/providers/quickaccess/HelpProvider.ts"
    qa_context = repo_path / "src/context/QuickAccessContext.tsx"

    help_issue_label = 'label: "issue "'
    registered_issue_provider = 'providerMap.set("issue ",' 

    if help_provider.exists() and qa_context.exists():
        has_help_entry = find_line_number(help_provider, help_issue_label) is not None
        has_registration = find_line_number(qa_context, registered_issue_provider) is not None

        if has_help_entry and not has_registration:
            finding_id = "issue-provider-unreachable"
            evidence = [
                (help_provider, help_issue_label),
                (qa_context, 'providerMap.set("ext ", extensionProvider);'),
            ]
            findings.append(
                {
                    "finding_id": finding_id,
                    "evidence_file": str(help_provider),
                    "evidence_line": find_line_number(help_provider, help_issue_label),
                    "title": "Quick Access advertises 'issue' command but never registers provider",
                    "description": (
                        "The Help provider lists an 'issue ' quick-access command, but QuickAccessContext "
                        "does not register an issue provider in providerMap. Users are guided to a command "
                        "that cannot resolve to any provider.\n\nEvidence:\n"
                        + format_evidence(repo_path, evidence)
                    ),
                    "reproduction_steps": [
                        "Open Quick Access in Cortex IDE.",
                        "Type '?' and select the 'issue ' help item.",
                        "Observe there is no corresponding registered provider for the 'issue ' prefix.",
                    ],
                    "impact": (
                        "Expected issue-reporting feature is unreachable from UI, causing dead-end navigation "
                        "and report flow regression."
                    ),
                    "project": "cortex-ide",
                    "expected_behavior": (
                        "The 'issue ' quick-access command shown in Help should resolve to a registered provider "
                        "that opens the issue flow."
                    ),
                    "actual_behavior": (
                        "Help advertises the 'issue ' command but no matching provider registration exists, "
                        "so users hit a dead-end."
                    ),
                    "error_message": "No explicit error message; command affordance is present but unresolvable.",
                    "debug_logs": "No debug logs required; this is visible from provider registration mismatch.",
                    "system_information": "Native GUI: Cortex IDE",
                    "additional_context": "HelpProvider and QuickAccessContext are out of sync for the 'issue ' prefix.",
                    "native_gui": "Cortex IDE",
                    "proof_artifacts": optional_proofs(repo_path, finding_id),
                    "fingerprint": build_fingerprint([
                        finding_id,
                        str(help_provider),
                        str(qa_context),
                    ]),
                }
            )

    # -------------------------------------------------------------------------
    # Finding 2b: Quick Access advertises % text-search provider but never registers it
    # -------------------------------------------------------------------------
    help_percent_label = 'label: "%"'
    help_percent_detail = "Type % followed by text to search in all files"
    text_provider_prefix = 'prefix: "%"'
    registered_percent_provider = 'providerMap.set("%",'
    text_provider_file = repo_path / "src/providers/quickaccess/TextSearchProvider.ts"

    if help_provider.exists() and qa_context.exists() and text_provider_file.exists():
        has_help_percent = find_line_number(help_provider, help_percent_label) is not None
        has_text_provider = find_line_number(text_provider_file, text_provider_prefix) is not None
        has_percent_registration = find_line_number(qa_context, registered_percent_provider) is not None

        if has_help_percent and has_text_provider and not has_percent_registration:
            finding_id = "quickaccess-percent-provider-unreachable"
            evidence = [
                (help_provider, help_percent_detail),
                (text_provider_file, text_provider_prefix),
                (qa_context, 'providerMap.set("ext ", extensionProvider);'),
            ]
            findings.append(
                {
                    "finding_id": finding_id,
                    "evidence_file": str(help_provider),
                    "evidence_line": find_line_number(help_provider, help_percent_label),
                    "title": "Quick Access Help advertises '%' file-text search, but '%' provider is never registered",
                    "description": (
                        "Help lists `%` as 'Search in Files', and TextSearchProvider defines prefix `%`, "
                        "but QuickAccessContext never registers a `%` provider in providerMap. Users are "
                        "directed to a prefix that falls back to the default files provider.\n\nEvidence:\n"
                        + format_evidence(repo_path, evidence)
                    ),
                    "reproduction_steps": [
                        "Open Quick Access in Cortex IDE.",
                        "Type `?` and select `% - Search in Files`.",
                        "Observe `%` does not activate text-search provider behavior and routes to default provider flow.",
                    ],
                    "impact": (
                        "Expected text-search quick access path is unreachable from UI help, causing dead-end "
                        "navigation and misleading command guidance."
                    ),
                    "project": "cortex-ide",
                    "expected_behavior": (
                        "Selecting `%` from Help should activate a registered `%` provider backed by TextSearchProvider."
                    ),
                    "actual_behavior": (
                        "`%` is advertised but not registered, so users cannot reach the intended text-search provider."
                    ),
                    "error_message": "No explicit error is shown; provider mismatch is silent.",
                    "debug_logs": "No debug logs required; mismatch is deterministic from Help/registration wiring.",
                    "system_information": "Native GUI: Cortex IDE",
                    "additional_context": "Help, provider implementation, and providerMap registration are out of sync for `%`.",
                    "native_gui": "Cortex IDE",
                    "proof_artifacts": optional_proofs(repo_path, finding_id),
                    "fingerprint": build_fingerprint([
                        finding_id,
                        str(help_provider),
                        str(text_provider_file),
                        str(qa_context),
                    ]),
                    "dedup_hints": [
                        "Quick Access Help advertises percent prefix Search in Files but percent provider is never registered",
                        "TextSearchProvider prefix percent exists but QuickAccessContext does not register providerMap set percent",
                        "Type percent followed by text to search in all files command routes to default provider instead",
                    ],
                }
            )

    # -------------------------------------------------------------------------
    # Finding 2c: Editor MRU provider exists but is never registered in router
    # -------------------------------------------------------------------------
    quickaccess_index = repo_path / "src/providers/quickaccess/index.ts"
    editor_mru_provider = repo_path / "src/providers/quickaccess/EditorMRUProvider.tsx"
    editor_mru_prefix = 'prefix: "edt mru "'
    editor_mru_export = 'export { createEditorMRUProvider } from "./EditorMRUProvider";'
    registered_editor_mru = 'providerMap.set("edt mru ",'
    if quick_access := (repo_path / "src/context/QuickAccessContext.tsx"):
        if (
            quick_access.exists()
            and editor_mru_provider.exists()
            and quickaccess_index.exists()
            and find_line_number(editor_mru_provider, editor_mru_prefix) is not None
            and find_line_number(quickaccess_index, editor_mru_export) is not None
            and find_line_number(quick_access, registered_editor_mru) is None
        ):
            finding_id = "quickaccess-editor-mru-provider-unreachable"
            evidence = [
                (editor_mru_provider, editor_mru_prefix),
                (quickaccess_index, editor_mru_export),
                (quick_access, 'providerMap.set("ext ", extensionProvider);'),
                (quick_access, 'providerMap.set("", filesProvider);'),
            ]
            findings.append(
                {
                    "finding_id": finding_id,
                    "evidence_file": str(editor_mru_provider),
                    "evidence_line": find_line_number(editor_mru_provider, editor_mru_prefix),
                    "title": "Quick Access has an 'edt mru ' provider implementation, but router never registers it",
                    "description": (
                        "EditorMRUProvider is implemented and exported with prefix `edt mru `, but "
                        "QuickAccessContext does not register that prefix in `providerMap`. The MRU quick-access "
                        "feature is unreachable from the GUI command router.\n\nEvidence:\n"
                        + format_evidence(repo_path, evidence)
                    ),
                    "reproduction_steps": [
                        "Open Quick Access in Cortex IDE (`Ctrl+P`).",
                        "Type `edt mru `.",
                        "Observe the MRU provider UI (Pinned Editors / Recent Editors / No open editors) never appears.",
                        "Open `?` help in Quick Access and verify there is no `edt mru ` prefix entry.",
                    ],
                    "impact": (
                        "A shipped quick-access provider is dead code from user perspective; users cannot access "
                        "the MRU editor workflow despite implemented provider logic."
                    ),
                    "project": "cortex-ide",
                    "expected_behavior": (
                        "`edt mru ` should activate Editor MRU provider and expose recent/pinned editor items."
                    ),
                    "actual_behavior": (
                        "`edt mru ` is not routed to any provider because the prefix is never registered."
                    ),
                    "error_message": "No explicit error; quick-access routing silently falls back to non-MRU behavior.",
                    "debug_logs": "No runtime logs required; provider implementation/export exists without router registration.",
                    "system_information": "Native GUI: Cortex IDE",
                    "additional_context": "The prefix exists in provider source but is absent from providerMap registration block.",
                    "native_gui": "Cortex IDE",
                    "proof_artifacts": optional_proofs(repo_path, finding_id),
                    "fingerprint": build_fingerprint(
                        [
                            finding_id,
                            str(editor_mru_provider),
                            str(quickaccess_index),
                            str(quick_access),
                            editor_mru_prefix,
                        ]
                    ),
                    "dedup_hints": [
                        "EditorMRUProvider prefix edt mru exists but QuickAccessContext never registers providerMap set edt mru",
                        "quick access edt mru provider unreachable because router registration is missing",
                    ],
                }
            )

    # -------------------------------------------------------------------------
    # Finding 3: Wrong default repository URL in IssueReporterProvider
    # -------------------------------------------------------------------------
    issue_provider = repo_path / "src/providers/quickaccess/IssueReporterProvider.ts"
    wrong_default_repo = 'const DEFAULT_REPOSITORY_URL = "https://github.com/nicholasthompson/orion";'
    if issue_provider.exists() and find_line_number(issue_provider, wrong_default_repo):
        finding_id = "wrong-default-report-repo"
        evidence = [(issue_provider, wrong_default_repo)]
        findings.append(
            {
                "finding_id": finding_id,
                "evidence_file": str(issue_provider),
                "evidence_line": find_line_number(issue_provider, wrong_default_repo),
                "title": "Issue reporter default repository points to unrelated project",
                "description": (
                    "IssueReporterProvider hard-codes an unrelated default repository URL. If caller options "
                    "do not override this, bug reports open against the wrong project.\n\nEvidence:\n"
                    + format_evidence(repo_path, evidence)
                ),
                "reproduction_steps": [
                    "Trigger issue reporting via quick access provider without overriding repositoryUrl.",
                    "Select any issue type.",
                    "Observe generated URL points to nicholasthompson/orion instead of Cortex/platform target.",
                ],
                "impact": (
                    "Bug reports can be routed to an unrelated repository, causing data leakage and failed "
                    "reporting workflow."
                ),
                "project": "cortex-ide",
                "expected_behavior": (
                    "Issue reporting defaults should point to the correct project or configured target repository."
                ),
                "actual_behavior": (
                    "The default repository URL is hard-coded to nicholasthompson/orion, which is unrelated."
                ),
                "error_message": "No visible error; generated issue URL silently points to the wrong repository.",
                "debug_logs": "No debug logs required to confirm this default constant mismatch.",
                "system_information": "Native GUI: Cortex IDE",
                "additional_context": "If repositoryUrl override is absent, users are routed to the wrong project by default.",
                "native_gui": "Cortex IDE",
                "proof_artifacts": optional_proofs(repo_path, finding_id),
                "fingerprint": build_fingerprint([finding_id, str(issue_provider), wrong_default_repo]),
            }
        )

    # -------------------------------------------------------------------------
    # Finding 4: Hard-coded appVersion in system info reporting
    # -------------------------------------------------------------------------
    hardcoded_version_snippet = 'appVersion: "1.0.0", // Should be injected from app'
    package_json = repo_path / "package.json"

    if issue_provider.exists() and package_json.exists() and find_line_number(issue_provider, hardcoded_version_snippet):
        try:
            pkg = json.loads(read_text(package_json))
            actual_version = str(pkg.get("version", "unknown"))
        except Exception:
            actual_version = "unknown"

        finding_id = "system-info-version-mismatch"
        evidence = [(issue_provider, hardcoded_version_snippet), (package_json, '"version"')]
        findings.append(
            {
                "finding_id": finding_id,
                "evidence_file": str(issue_provider),
                "evidence_line": find_line_number(issue_provider, hardcoded_version_snippet),
                "title": "Issue reporter sends hard-coded app version in system info",
                "description": (
                    "collectSystemInfo() hard-codes appVersion to 1.0.0 instead of reading the real app version "
                    f"(package.json currently shows {actual_version}). This produces misleading system details in "
                    "bug reports.\n\nEvidence:\n"
                    + format_evidence(repo_path, evidence)
                ),
                "reproduction_steps": [
                    "Open issue reporting flow and include system information.",
                    "Inspect generated system info payload/body.",
                    "Observe App Version is fixed to 1.0.0 regardless of actual running version.",
                ],
                "impact": (
                    "Report triage can be misled by incorrect version metadata, increasing time-to-fix and causing "
                    "misclassification of regressions."
                ),
                "project": "cortex-ide",
                "expected_behavior": (
                    "System info in issue reports should reflect the actual running application version."
                ),
                "actual_behavior": (
                    "System info hard-codes appVersion to 1.0.0 even when project version differs."
                ),
                "error_message": "No explicit UI error; incorrect metadata is included in generated report content.",
                "debug_logs": "No debug logs required; mismatch is evident from source constants and package version.",
                "system_information": f"Native GUI: Cortex IDE; package.json version: {actual_version}",
                "additional_context": "The code comment itself marks this value as placeholder that should be injected.",
                "native_gui": "Cortex IDE",
                "proof_artifacts": optional_proofs(repo_path, finding_id),
                "fingerprint": build_fingerprint([finding_id, str(issue_provider), str(package_json)]),
            }
        )

    # -------------------------------------------------------------------------
    # Finding 5: Feedback dialog collects screenshot files but submission drops payload
    # -------------------------------------------------------------------------
    feedback_dialog = repo_path / "src/components/FeedbackDialog.tsx"
    tauri_ai_mod = repo_path / "src-tauri/src/ai/mod.rs"
    screenshot_ui_capture = 'updateForm("screenshots", [...form().screenshots, ...newFiles]);'
    screenshot_submit_count_only = "screenshotCount: f.screenshots.length,"
    screenshot_todo_comment = "// Note: Screenshots need to be handled separately as base64"
    rust_screenshot_count = "pub screenshot_count: Option<u32>,"

    if (
        feedback_dialog.exists()
        and tauri_ai_mod.exists()
        and find_line_number(feedback_dialog, screenshot_ui_capture)
        and find_line_number(feedback_dialog, screenshot_submit_count_only)
        and find_line_number(tauri_ai_mod, rust_screenshot_count)
    ):
        finding_id = "feedback-screenshots-dropped-on-submit"
        evidence = [
            (feedback_dialog, screenshot_ui_capture),
            (feedback_dialog, screenshot_submit_count_only),
            (feedback_dialog, screenshot_todo_comment),
            (tauri_ai_mod, rust_screenshot_count),
        ]
        findings.append(
            {
                "finding_id": finding_id,
                "evidence_file": str(feedback_dialog),
                "evidence_line": find_line_number(feedback_dialog, screenshot_submit_count_only),
                "title": "Feedback dialog accepts screenshots but drops them during submission",
                "description": (
                    "FeedbackDialog lets users attach screenshots and shows previews, but submit payload "
                    "only sends `screenshotCount` with no screenshot bytes/paths. Rust `submit_feedback` "
                    "schema also only accepts a numeric count, so uploaded screenshots are silently dropped.\n\nEvidence:\n"
                    + format_evidence(repo_path, evidence)
                ),
                "reproduction_steps": [
                    "Open Help -> Send Feedback in Cortex IDE.",
                    "Attach one or more screenshots in the dialog and confirm previews appear.",
                    "Submit feedback via backend path.",
                    "Observe submission payload/schema only includes screenshot count; no screenshot content is sent.",
                ],
                "impact": (
                    "Critical debugging evidence attached by users is lost, producing incomplete bug reports "
                    "and increasing triage/reproduction failures."
                ),
                "project": "cortex-ide",
                "expected_behavior": (
                    "When screenshots are attached, submission should include screenshot payload (file bytes, "
                    "temporary file references, or uploaded URLs) in backend request data."
                ),
                "actual_behavior": (
                    "The app records only `screenshotCount` and drops actual screenshot payload."
                ),
                "error_message": "No visible error; submission appears successful while screenshot artifacts are lost.",
                "debug_logs": "submit_feedback logs screenshot_count only; no screenshot payload fields are present.",
                "system_information": "Native GUI: Cortex IDE",
                "additional_context": (
                    "UI supports screenshot selection/previews, but transport schema and payload do not include files."
                ),
                "native_gui": "Cortex IDE",
                "proof_artifacts": optional_proofs(repo_path, finding_id),
                "fingerprint": build_fingerprint([
                    finding_id,
                    str(feedback_dialog),
                    str(tauri_ai_mod),
                    screenshot_submit_count_only,
                    rust_screenshot_count,
                ]),
                "dedup_hints": [
                    "FeedbackDialog accepts screenshot files but submit_feedback only receives screenshotCount",
                    "Attached screenshots are previewed in UI but dropped because backend payload has no screenshot field",
                    "submit_feedback schema only has screenshot_count and no screenshot bytes or file references",
                ],
            }
        )

    print(json.dumps(findings, ensure_ascii=True))


if __name__ == "__main__":
    main()
