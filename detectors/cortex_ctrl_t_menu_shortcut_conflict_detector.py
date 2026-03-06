#!/usr/bin/env python3
"""Detect Ctrl+T shortcut conflict in Cortex menu bar."""

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
    menu_bar = repo_path / "src/components/MenuBar.tsx"

    findings: List[Dict[str, object]] = []

    transpose_item = '{ label: "Transpose Characters", shortcut: "Ctrl+T", action: menuActions.transposeCharacters },'
    go_symbol_item = '{ label: "Go to Symbol in Workspace...", shortcut: "Ctrl+T", action: menuActions.showWorkspaceSymbolPicker },'

    if (
        menu_bar.exists()
        and find_line_number(menu_bar, transpose_item)
        and find_line_number(menu_bar, go_symbol_item)
    ):
        finding_id = "menubar-ctrl-t-shortcut-conflict-transpose-vs-go-symbol"
        evidence = [
            (menu_bar, transpose_item),
            (menu_bar, go_symbol_item),
        ]
        findings.append(
            {
                "finding_id": finding_id,
                "evidence_file": str(menu_bar),
                "evidence_line": find_line_number(menu_bar, transpose_item),
                "title": "Menu bar assigns `Ctrl+T` to two different commands (Transpose vs Go to Symbol in Workspace)",
                "description": (
                    "The Menu Bar defines `Ctrl+T` for both `Edit -> Transpose Characters` and "
                    "`Go -> Go to Symbol in Workspace`, creating a global accelerator collision.\n\n"
                    "Evidence:\n" + format_evidence(repo_path, evidence)
                ),
                "reproduction_steps": [
                    "Open Cortex IDE with a workspace folder.",
                    "Open the `Edit` menu and note `Transpose Characters` shows `Ctrl+T`.",
                    "Open the `Go` menu and note `Go to Symbol in Workspace...` also shows `Ctrl+T`.",
                    "Use `Ctrl+T` and observe only one behavior can be triggered in practice for a shared accelerator.",
                ],
                "impact": (
                    "One of the two user-facing actions becomes effectively unreachable or context-dependent in an unpredictable way."
                ),
                "project": "ide",
                "expected_behavior": "Each command should have a unique accelerator or explicit context scoping visible to users.",
                "actual_behavior": "Two unrelated menu items advertise the same `Ctrl+T` shortcut.",
                "error_message": "No explicit error dialog; shortcut collision is visible in the GUI menu and keybinding behavior.",
                "debug_logs": "No logs required; issue is visible in menu labels and command dispatch behavior.",
                "system_information": "Native GUI: Cortex IDE",
                "additional_context": "The conflict is declared in the same MenuBar menu configuration source.",
                "native_gui": "Cortex IDE",
                "dedup_hints": [
                    "Ctrl+T assigned to Transpose Characters and Go to Symbol in Workspace in MenuBar",
                    "duplicate Ctrl+T accelerator between Edit and Go menus",
                ],
                "proof_artifacts": optional_proofs(repo_path, finding_id),
                "fingerprint": build_fingerprint(
                    [
                        finding_id,
                        str(menu_bar),
                        transpose_item,
                        go_symbol_item,
                    ]
                ),
            }
        )

    print(json.dumps(findings, ensure_ascii=True))


if __name__ == "__main__":
    main()
