#!/usr/bin/env python3
"""Detect Alt+F12 shortcut collision for navigation commands."""

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
    command_context = repo_path / "src/context/CommandContext.tsx"

    findings: List[Dict[str, object]] = []

    peek_def_id = 'id: "editor.action.peekDefinition",'
    peek_def_shortcut = 'shortcut: "Alt+F12",'
    refs_id = 'id: "find-all-references",'

    if (
        command_context.exists()
        and find_line_number(command_context, peek_def_id)
        and find_line_number(command_context, refs_id)
        and find_line_number(command_context, peek_def_shortcut)
    ):
        finding_id = "shortcut-alt-f12-peek-definition-vs-find-all-references-conflict"
        evidence = [
            (command_context, peek_def_id),
            (command_context, refs_id),
            (command_context, peek_def_shortcut),
        ]
        findings.append(
            {
                "finding_id": finding_id,
                "evidence_file": str(command_context),
                "evidence_line": find_line_number(command_context, peek_def_id),
                "title": "Alt+F12 is assigned to both Peek Definition and Find All References",
                "description": (
                    "Command registry assigns `Alt+F12` to two unrelated navigation actions: "
                    "`Peek Definition` and `Find All References`. With no visible context gating in "
                    "the command declarations, this creates an ambiguous global shortcut.\n\n"
                    "Evidence:\n" + format_evidence(repo_path, evidence)
                ),
                "reproduction_steps": [
                    "Open Cortex IDE with a workspace folder.",
                    "Open Command Palette (`Ctrl+Shift+P`).",
                    "Search `Alt+F12` and observe both `Peek Definition` and `Find All References` advertise the same shortcut.",
                    "Press `Alt+F12` and observe only one of the two actions can execute for the shared keybinding.",
                ],
                "impact": (
                    "One of the advertised navigation flows becomes unreachable or unpredictable from keyboard, "
                    "degrading code navigation reliability."
                ),
                "project": "ide",
                "expected_behavior": "Each keybinding should map to one command unless explicit context isolation is defined and user-visible.",
                "actual_behavior": "`Alt+F12` is shared by two unrelated commands in the same command registry.",
                "error_message": "No explicit error dialog; conflict is visible via command metadata and keyboard behavior.",
                "debug_logs": "No logs required; conflict is directly visible in command declarations and palette shortcuts.",
                "system_information": "Native GUI: Cortex IDE",
                "additional_context": "Both commands are declared in src/context/CommandContext.tsx default command list.",
                "native_gui": "Cortex IDE",
                "dedup_hints": [
                    "Alt+F12 assigned to editor.action.peekDefinition and find-all-references",
                    "shortcut conflict between Peek Definition and Find All References",
                ],
                "proof_artifacts": optional_proofs(repo_path, finding_id),
                "fingerprint": build_fingerprint(
                    [
                        finding_id,
                        str(command_context),
                        peek_def_id,
                        refs_id,
                        peek_def_shortcut,
                    ]
                ),
            }
        )

    print(json.dumps(findings, ensure_ascii=True))


if __name__ == "__main__":
    main()
