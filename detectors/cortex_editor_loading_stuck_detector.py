#!/usr/bin/env python3
"""Detect potential stuck editor loading state in Cortex IDE."""

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
    if os.environ.get("AUDIT_ALLOW_PREEXISTING_PROOFS", "").strip() != "1":
        return []

    local_proof_dir = repo_path / "proofs"
    out: List[str] = []
    for ext in (".png", ".jpg", ".jpeg", ".gif", ".mp4", ".mov", ".webm"):
        candidate = local_proof_dir / f"{finding_id}{ext}"
        if candidate.exists() and candidate.is_file():
            out.append(str(candidate.resolve()))
    return out


def build_fingerprint(parts: Sequence[str]) -> str:
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def main() -> None:
    repo_path = Path(os.environ.get("AUDIT_REPO_PATH", ".")).expanduser().resolve()

    code_editor = repo_path / "src/components/editor/CodeEditor.tsx"
    editor_skeleton = repo_path / "src/components/editor/EditorSkeleton.tsx"
    editor_instance = repo_path / "src/components/editor/core/EditorInstance.tsx"

    findings: List[Dict[str, object]] = []

    skeleton_gate = "<Show when={instance.isLoading() && instance.activeFile()}>"
    loading_copy = "Loading editor..."
    loading_start = "setIsLoading(true);"
    loading_call = "monacoManager.ensureLoaded()"

    if (
        code_editor.exists()
        and editor_skeleton.exists()
        and editor_instance.exists()
        and find_line_number(code_editor, skeleton_gate)
        and find_line_number(editor_skeleton, loading_copy)
        and find_line_number(editor_instance, loading_start)
        and find_line_number(editor_instance, loading_call)
    ):
        finding_id = "editor-loading-skeleton-stuck-after-open-file"
        evidence = [
            (code_editor, skeleton_gate),
            (editor_skeleton, loading_copy),
            (editor_instance, loading_start),
            (editor_instance, loading_call),
        ]
        findings.append(
            {
                "finding_id": finding_id,
                "evidence_file": str(code_editor),
                "evidence_line": find_line_number(code_editor, skeleton_gate),
                "title": "Opening a file can leave the editor stuck on `Loading editor...` with no recovery",
                "description": (
                    "When a file is opened, the editor can remain in the loading skeleton state "
                    "(`Loading editor...`) and never transition to a rendered Monaco editor.\n\n"
                    "Evidence:\n" + format_evidence(repo_path, evidence)
                ),
                "reproduction_steps": [
                    "Open Cortex IDE with a workspace folder.",
                    "Use Quick Open (`Ctrl+P`) and open a source file (for example `src/components/TerminalGroupTabs.tsx`).",
                    "Wait for the editor panel to render.",
                    "Observe the editor can remain on `Loading editor...` instead of showing file contents.",
                ],
                "impact": (
                    "Users can be blocked from reading or editing files because the editor surface "
                    "never exits the loading state."
                ),
                "project": "ide",
                "expected_behavior": "Editor should render file contents after open, or surface a recoverable error state.",
                "actual_behavior": "Editor skeleton stays visible with `Loading editor...` and no in-UI recovery.",
                "error_message": "Loading editor...",
                "debug_logs": "No explicit frontend error required; stuck loading state is visible in the native GUI.",
                "system_information": "Native GUI: Cortex IDE",
                "additional_context": (
                    "Loading UI is gated on `instance.isLoading()` and can block the editor panel display "
                    "for the active file."
                ),
                "native_gui": "Cortex IDE",
                "dedup_hints": [
                    "editor stuck on Loading editor after opening file via quick open",
                    "CodeEditor isLoading skeleton persists and Monaco view does not render",
                ],
                "proof_artifacts": optional_proofs(repo_path, finding_id),
                "fingerprint": build_fingerprint(
                    [
                        finding_id,
                        str(code_editor),
                        skeleton_gate,
                        str(editor_instance),
                        loading_call,
                    ]
                ),
            }
        )

    print(json.dumps(findings, ensure_ascii=True))


if __name__ == "__main__":
    main()
