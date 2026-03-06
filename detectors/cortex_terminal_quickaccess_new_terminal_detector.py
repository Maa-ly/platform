#!/usr/bin/env python3
"""Detect unreachable terminal quick-access prefix in Ctrl+P quick-open flow."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


def find_line_number(path: Path, snippet: str) -> Optional[int]:
    if not path.exists():
        return None
    for idx, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if snippet in line:
            return idx
    return None


def display_path(repo_path: Path, file_path: Path) -> str:
    root = repo_path.resolve()
    current = file_path.resolve()
    try:
        rel = current.relative_to(root)
        return f"{root.name}/{rel.as_posix()}"
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


def build_fingerprint(parts: Sequence[str]) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def main() -> None:
    repo_path = Path(os.environ.get("AUDIT_REPO_PATH", ".")).expanduser().resolve()
    quick_access = repo_path / "src/context/QuickAccessContext.tsx"
    command_context = repo_path / "src/context/CommandContext.tsx"
    quick_open = repo_path / "src/components/palette/QuickOpen.tsx"

    findings: List[Dict[str, object]] = []

    term_prefix_snippet = 'prefix: "term "'
    term_provider_registered_snippet = 'providerMap.set("term ", terminalProvider);'
    ctrl_p_binding_snippet = 'shortcut: "Ctrl+P"'
    ctrl_p_action_snippet = "action: () => setShowFileFinder(true)"
    quick_open_mode_snippet = 'if (q.startsWith(">")) return "commands";'
    quick_open_default_snippet = 'return "files";'

    if (
        quick_access.exists()
        and find_line_number(quick_access, term_prefix_snippet)
        and find_line_number(quick_access, term_provider_registered_snippet)
        and find_line_number(command_context, ctrl_p_binding_snippet)
        and find_line_number(command_context, ctrl_p_action_snippet)
        and find_line_number(quick_open, quick_open_mode_snippet)
        and find_line_number(quick_open, quick_open_default_snippet)
    ):
        finding_id = "quickaccess-term-new-terminal-query-no-results"
        evidence = [
            (quick_access, term_prefix_snippet),
            (quick_access, term_provider_registered_snippet),
            (command_context, ctrl_p_binding_snippet),
            (command_context, ctrl_p_action_snippet),
            (quick_open, quick_open_mode_snippet),
            (quick_open, quick_open_default_snippet),
        ]

        findings.append(
            {
                "finding_id": finding_id,
                "evidence_file": str(quick_open),
                "evidence_line": find_line_number(quick_open, quick_open_default_snippet),
                "title": "Ctrl+P Quick Open ignores `term ` prefix, making terminal quick-access flow unreachable",
                "description": (
                    "The codebase defines and registers a `term ` quick-access provider, but `Ctrl+P` is bound to "
                    "the file-only Quick Open implementation. Quick Open mode detection recognizes only `>`, `@`, "
                    "`#`, and `:`, then falls back to file mode for all other prefixes. This makes terminal-prefixed "
                    "queries (for example `term new terminal`) unreachable from the active Ctrl+P entrypoint.\n\nEvidence:\n"
                    + format_evidence(repo_path, evidence)
                ),
                "reproduction_steps": [
                    "Open Cortex IDE with a workspace folder loaded.",
                    "Press Ctrl+P to open Quick Open.",
                    "Type `term new terminal`.",
                    "Observe the UI stays in file-search mode and does not route to terminal quick-access results.",
                ],
                "impact": (
                    "Terminal quick-access functionality is effectively unreachable from the primary quick-open shortcut, "
                    "so users cannot access terminal actions through the documented `term ` prefix flow."
                ),
                "project": "ide",
                "expected_behavior": (
                    "When a user types `term ...` in the quick-open input, routing should switch to terminal provider items."
                ),
                "actual_behavior": (
                    "Ctrl+P input remains file-mode and never invokes the registered `term ` provider."
                ),
                "error_message": "No explicit error dialog; prefix routing silently stays in file mode.",
                "debug_logs": "No runtime exception is required; this is deterministic routing behavior.",
                "system_information": "Native GUI: Cortex IDE",
                "additional_context": (
                    "Quick Access context advertises terminal prefix support, but the Ctrl+P surface is backed by "
                    "Palette Quick Open routing that does not include `term ` mode handling."
                ),
                "native_gui": "Cortex IDE",
                "dedup_hints": [
                    "Ctrl+P QuickOpen ignores term prefix and stays in files mode",
                    "terminal quick-access provider registered but unreachable from quick open",
                ],
                "proof_artifacts": [],
                "fingerprint": build_fingerprint(
                    [
                        finding_id,
                        str(quick_access),
                        str(command_context),
                        str(quick_open),
                        term_prefix_snippet,
                        term_provider_registered_snippet,
                        ctrl_p_action_snippet,
                        quick_open_default_snippet,
                    ]
                ),
            }
        )

    print(json.dumps(findings, ensure_ascii=True))


if __name__ == "__main__":
    main()
