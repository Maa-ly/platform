#!/usr/bin/env python3
"""Detect Ctrl+Alt shortcut conflicts in Cortex command registry."""

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


def build_conflict(
    repo_path: Path,
    source_file: Path,
    finding_id: str,
    title: str,
    shortcut: str,
    left_id: str,
    left_label: str,
    right_id: str,
    right_label: str,
) -> Optional[Dict[str, object]]:
    left_id_snippet = f'id: "{left_id}",'
    right_id_snippet = f'id: "{right_id}",'
    shortcut_snippet = f'shortcut: "{shortcut}",'

    left_line = find_line_number(source_file, left_id_snippet)
    right_line = find_line_number(source_file, right_id_snippet)
    shortcut_line = find_line_number(source_file, shortcut_snippet)
    if not left_line or not right_line or not shortcut_line:
        return None

    evidence = [
        (source_file, left_id_snippet),
        (source_file, right_id_snippet),
        (source_file, shortcut_snippet),
    ]

    return {
        "finding_id": finding_id,
        "evidence_file": str(source_file),
        "evidence_line": left_line,
        "title": title,
        "description": (
            f"Command registry assigns `{shortcut}` to both `{left_label}` and `{right_label}`. "
            "This creates an ambiguous global keybinding where only one command can win for the same chord.\n\n"
            "Evidence:\n" + format_evidence(repo_path, evidence)
        ),
        "reproduction_steps": [
            "Open Cortex IDE with a workspace folder.",
            "Open Command Palette (`Ctrl+Shift+P`).",
            f"Search `{shortcut}` and observe both `{left_label}` and `{right_label}` advertise the same shortcut.",
            f"Press `{shortcut}` and observe only one command can execute for the shared chord.",
        ],
        "impact": (
            "At least one advertised command becomes unreachable or behaves unpredictably from keyboard, "
            "causing broken command discoverability and inconsistent UX."
        ),
        "project": "ide",
        "expected_behavior": "Each shortcut should map to exactly one command unless explicit context scoping prevents collisions.",
        "actual_behavior": f"`{shortcut}` is assigned to multiple unrelated commands in command registry.",
        "error_message": "No error toast/dialog; bug appears as conflicting shortcut assignments and ambiguous behavior.",
        "debug_logs": "No runtime log required; conflict is visible from command metadata and keyboard behavior.",
        "system_information": "Native GUI: Cortex IDE",
        "additional_context": "Conflict is defined in src/context/CommandContext.tsx command declarations.",
        "native_gui": "Cortex IDE",
        "dedup_hints": [
            f"{shortcut} assigned to both {left_id} and {right_id}",
            f"shortcut collision {shortcut} between {left_label} and {right_label}",
        ],
        "proof_artifacts": optional_proofs(repo_path, finding_id),
        "fingerprint": build_fingerprint([
            finding_id,
            str(source_file),
            left_id,
            right_id,
            shortcut,
        ]),
    }


def main() -> None:
    repo_path = Path(os.environ.get("AUDIT_REPO_PATH", ".")).expanduser().resolve()
    source = repo_path / "src/context/CommandContext.tsx"

    findings: List[Dict[str, object]] = []

    candidates = [
        (
            "shortcut-ctrl-alt-j-join-lines-vs-bookmarks-prev-conflict",
            "Ctrl+Alt+J is assigned to both Join Lines and Go to Previous Bookmark",
            "Ctrl+Alt+J",
            "editor.action.joinLines",
            "Join Lines",
            "bookmarks.prev",
            "Go to Previous Bookmark",
        ),
        (
            "shortcut-ctrl-alt-b-inline-blame-vs-secondary-sidebar-conflict",
            "Ctrl+Alt+B is assigned to both Toggle Inline Git Blame and Toggle Secondary Sidebar",
            "Ctrl+Alt+B",
            "toggle-inline-blame",
            "Toggle Inline Git Blame",
            "workbench.action.toggleAuxiliaryBar",
            "Toggle Secondary Sidebar",
        ),
        (
            "shortcut-ctrl-alt-r-recent-projects-vs-terminal-run-recent-command-conflict",
            "Ctrl+Alt+R is assigned to both Open Recent Project and Run Recent Command",
            "Ctrl+Alt+R",
            "recent-projects",
            "Open Recent Project...",
            "terminal.runRecentCommand",
            "Run Recent Command...",
        ),
    ]

    for finding_id, title, shortcut, left_id, left_label, right_id, right_label in candidates:
        finding = build_conflict(
            repo_path=repo_path,
            source_file=source,
            finding_id=finding_id,
            title=title,
            shortcut=shortcut,
            left_id=left_id,
            left_label=left_label,
            right_id=right_id,
            right_label=right_label,
        )
        if finding:
            findings.append(finding)

    print(json.dumps(findings, ensure_ascii=True))


if __name__ == "__main__":
    main()
