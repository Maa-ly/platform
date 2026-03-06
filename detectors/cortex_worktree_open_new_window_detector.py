#!/usr/bin/env python3
"""Detect unhandled worktree open-in-new-window command dispatch."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional


def find_line_number(path: Path, needle: str) -> Optional[int]:
    if not path.exists():
        return None
    for idx, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        if needle in line:
            return idx
    return None


def iter_source_files(root: Path):
    src = root / "src"
    if not src.exists():
        return
    for path in src.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in {".ts", ".tsx", ".js", ".jsx"}:
            continue
        if "__tests__" in path.parts:
            continue
        yield path


def listener_count(repo_path: Path, event_name: str) -> int:
    pattern = re.compile(rf"addEventListener\s*\(\s*['\"]{re.escape(event_name)}['\"]")
    total = 0
    for path in iter_source_files(repo_path):
        text = path.read_text(encoding="utf-8", errors="replace")
        total += len(pattern.findall(text))
    return total


def build_fingerprint(parts: List[str]) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def optional_existing_proofs(repo_path: Path, finding_id: str) -> List[str]:
    if os.environ.get("AUDIT_ALLOW_PREEXISTING_PROOFS", "").strip() != "1":
        return []

    proofs_dir = repo_path / "proofs"
    candidates = [
        proofs_dir / f"{finding_id}.png",
        proofs_dir / f"{finding_id}.step2.png",
        proofs_dir / f"{finding_id}.preview.gif",
        proofs_dir / f"{finding_id}.cursor.mp4",
        proofs_dir / f"{finding_id}.mp4",
    ]
    out: List[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate.exists() or not candidate.is_file():
            continue
        resolved = str(candidate.resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        out.append(resolved)
    return out


def main() -> None:
    repo_path = Path(os.environ.get("AUDIT_REPO_PATH", ".")).expanduser().resolve()

    worktree_manager = repo_path / "src/components/git/WorktreeManager.tsx"
    git_panel = repo_path / "src/components/git/GitPanel.tsx"
    event_name = "command:workbench.openWorktree"

    findings: List[Dict[str, object]] = []

    dispatch_line_worktree = find_line_number(worktree_manager, f'new CustomEvent("{event_name}"')
    dispatch_line_panel = find_line_number(git_panel, f'new CustomEvent("{event_name}"')
    tooltip_line = find_line_number(worktree_manager, 'tooltip="Open in New Window"')
    open_action_line = find_line_number(worktree_manager, 'onClick={() => openInNewWindow(worktree)}')
    listeners = listener_count(repo_path, event_name)

    if (
        dispatch_line_worktree
        and dispatch_line_panel
        and tooltip_line
        and open_action_line
        and listeners == 0
    ):
        finding_id = "worktree-open-new-window-event-unhandled"
        findings.append(
            {
                "finding_id": finding_id,
                "evidence_file": str(worktree_manager),
                "evidence_line": dispatch_line_worktree,
                "title": "Worktree 'Open in New Window' action is a no-op because its command event is never handled",
                "description": (
                    "WorktreeManager exposes an `Open in New Window` action (icon tooltip and expanded `Open` button), "
                    "and both WorktreeManager and GitPanel dispatch `command:workbench.openWorktree`. "
                    "No production listener consumes that event, so clicking the action does nothing."
                ),
                "reproduction_steps": [
                    "Open Source Control in Cortex IDE and switch to the Worktrees view.",
                    "Click `Open in New Window` on any worktree row (or expand a row and click `Open`).",
                    "Observe no new window opens and the current UI remains unchanged.",
                ],
                "impact": (
                    "Users cannot open worktrees in separate windows from the advertised UI action, "
                    "breaking a core multi-worktree workflow."
                ),
                "project": "ide",
                "expected_behavior": (
                    "`Open in New Window` should open the selected worktree in a new IDE window."
                ),
                "actual_behavior": (
                    "Clicking the action dispatches `command:workbench.openWorktree`, but no listener handles it."
                ),
                "error_message": "No explicit error toast appears; the UI action silently no-ops.",
                "debug_logs": (
                    f"`{event_name}` listener count in production src (excluding tests): {listeners}."
                ),
                "system_information": "Native GUI: Cortex IDE",
                "additional_context": (
                    f"Dispatch sites: WorktreeManager.tsx:{dispatch_line_worktree} and "
                    f"GitPanel.tsx:{dispatch_line_panel}. "
                    f"UI affordances: tooltip line {tooltip_line}, Open action line {open_action_line}."
                ),
                "native_gui": "Cortex IDE",
                "dedup_hints": [
                    "worktree open in new window button does nothing",
                    "command:workbench.openWorktree is dispatched but has no listener",
                ],
                "proof_artifacts": optional_existing_proofs(repo_path, finding_id),
                "fingerprint": build_fingerprint(
                    [
                        finding_id,
                        str(worktree_manager),
                        str(git_panel),
                        event_name,
                        "listener_count=0",
                    ]
                ),
            }
        )

    print(json.dumps(findings, ensure_ascii=True))


if __name__ == "__main__":
    main()
