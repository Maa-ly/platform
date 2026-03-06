#!/usr/bin/env python3
"""Detect Ctrl+Shift+R shortcut conflict in Cortex menu bar."""

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

    refactor_item = '{ label: "Refactor...", shortcut: "Ctrl+Shift+R", action: menuActions.refactor },'
    repl_item = '{ label: "Toggle REPL", shortcut: "Ctrl+Shift+R", action: toggleREPL },'

    if (
        menu_bar.exists()
        and find_line_number(menu_bar, refactor_item)
        and find_line_number(menu_bar, repl_item)
    ):
        finding_id = "menubar-ctrl-shift-r-shortcut-conflict-refactor-vs-toggle-repl"
        evidence = [
            (menu_bar, refactor_item),
            (menu_bar, repl_item),
        ]
        findings.append(
            {
                "finding_id": finding_id,
                "evidence_file": str(menu_bar),
                "evidence_line": find_line_number(menu_bar, refactor_item),
                "title": "Menu bar assigns `Ctrl+Shift+R` to both `Refactor...` and `Toggle REPL`",
                "description": (
                    "The Menu Bar maps `Ctrl+Shift+R` to two unrelated commands in different menus: "
                    "`Edit -> Refactor...` and `View -> Toggle REPL`.\n\n"
                    "Evidence:\n" + format_evidence(repo_path, evidence)
                ),
                "reproduction_steps": [
                    "Open Cortex IDE with a workspace folder.",
                    "Open the `Edit` menu and note `Refactor...` uses `Ctrl+Shift+R`.",
                    "Open the `View` menu and note `Toggle REPL` also uses `Ctrl+Shift+R`.",
                    "Press `Ctrl+Shift+R` and observe only one behavior can fire for the shared keybinding.",
                ],
                "impact": (
                    "A global shortcut collision makes one of the advertised commands unavailable "
                    "or context-ambiguous, reducing feature reachability."
                ),
                "project": "ide",
                "expected_behavior": "Each command should have a unique visible accelerator or explicit context scoping.",
                "actual_behavior": "Two unrelated commands expose the same `Ctrl+Shift+R` accelerator.",
                "error_message": "No explicit error dialog; collision is visible in menu labels and shortcut behavior.",
                "debug_logs": "No logs required; issue is visible in native GUI menu entries.",
                "system_information": "Native GUI: Cortex IDE",
                "additional_context": "Both bindings are declared in the same menu configuration source.",
                "native_gui": "Cortex IDE",
                "dedup_hints": [
                    "Ctrl+Shift+R assigned to Refactor and Toggle REPL in MenuBar",
                    "duplicate Ctrl+Shift+R accelerator across Edit and View menus",
                ],
                "proof_artifacts": optional_proofs(repo_path, finding_id),
                "fingerprint": build_fingerprint(
                    [
                        finding_id,
                        str(menu_bar),
                        refactor_item,
                        repl_item,
                    ]
                ),
            }
        )

    print(json.dumps(findings, ensure_ascii=True))


if __name__ == "__main__":
    main()
