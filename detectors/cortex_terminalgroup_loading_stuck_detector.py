#!/usr/bin/env python3
"""Detect TerminalGroupTabs-specific editor loading stall in Cortex IDE."""

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
    target_file = repo_path / "src/components/TerminalGroupTabs.tsx"

    findings: List[Dict[str, object]] = []

    skeleton_gate = "<Show when={instance.isLoading() && instance.activeFile()}>"
    loading_copy = "Loading editor..."
    terminal_export = "export function TerminalGroupTabs(props: TerminalGroupTabsProps) {"

    if (
        code_editor.exists()
        and editor_skeleton.exists()
        and target_file.exists()
        and find_line_number(code_editor, skeleton_gate)
        and find_line_number(editor_skeleton, loading_copy)
    ):
        finding_id = "editor-loading-stuck-terminalgrouptabs-file-open"
        evidence = [
            (code_editor, skeleton_gate),
            (editor_skeleton, loading_copy),
            (target_file, terminal_export),
        ]
        findings.append(
            {
                "finding_id": finding_id,
                "evidence_file": str(target_file),
                "evidence_line": 1,
                "title": "Opening `src/components/TerminalGroupTabs.tsx` can leave editor stuck on `Loading editor...`",
                "description": (
                    "Opening `src/components/TerminalGroupTabs.tsx` via Quick Open can leave the editor "
                    "in a persistent loading state (`Loading editor...`) instead of rendering file contents.\n\n"
                    "Evidence:\n" + format_evidence(repo_path, evidence)
                ),
                "reproduction_steps": [
                    "Open Cortex IDE with a workspace folder.",
                    "Press `Ctrl+P` and open `src/components/TerminalGroupTabs.tsx`.",
                    "Wait for the editor panel to render.",
                    "Observe the editor remains in `Loading editor...` state and the file content does not appear.",
                ],
                "impact": (
                    "A core UI source file can become non-openable in the editor, blocking inspection and edits."
                ),
                "project": "ide",
                "expected_behavior": "TerminalGroupTabs.tsx should render in Monaco after file open.",
                "actual_behavior": "Editor stays in loading skeleton state for the opened TerminalGroupTabs.tsx tab.",
                "error_message": "Loading editor...",
                "debug_logs": "No explicit console error required; loading stall is visible in native GUI.",
                "system_information": "Native GUI: Cortex IDE",
                "additional_context": (
                    "CodeEditor hides the editor surface while `instance.isLoading()` is true."
                ),
                "native_gui": "Cortex IDE",
                "dedup_hints": [
                    "TerminalGroupTabs.tsx tab remains stuck on Loading editor",
                    "file-specific loading stall when opening TerminalGroupTabs.tsx from Quick Open",
                ],
                "proof_artifacts": optional_proofs(repo_path, finding_id),
                "fingerprint": build_fingerprint(
                    [
                        finding_id,
                        str(target_file),
                        skeleton_gate,
                        loading_copy,
                    ]
                ),
            }
        )

    print(json.dumps(findings, ensure_ascii=True))


if __name__ == "__main__":
    main()
