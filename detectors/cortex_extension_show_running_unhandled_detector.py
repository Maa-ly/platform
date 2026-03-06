#!/usr/bin/env python3
"""Detect unhandled event routing for 'Show Running Extensions' command."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Dict, Iterable, List, Optional


def find_line_number(path: Path, needle: str) -> Optional[int]:
    if not path.exists():
        return None
    for idx, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        if needle in line:
            return idx
    return None


def iter_source_files(root: Path) -> Iterable[Path]:
    src = root / "src"
    if not src.exists():
        return []
    for path in src.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in {".ts", ".tsx", ".js", ".jsx"}:
            continue
        if "__tests__" in path.parts:
            continue
        yield path


def listener_count(repo_path: Path, event_name: str) -> int:
    token = f'addEventListener("{event_name}"'
    total = 0
    for path in iter_source_files(repo_path):
        text = path.read_text(encoding="utf-8", errors="replace")
        total += text.count(token)
    return total


def dispatch_count(repo_path: Path, event_name: str) -> int:
    token = f'new CustomEvent("{event_name}"'
    total = 0
    for path in iter_source_files(repo_path):
        text = path.read_text(encoding="utf-8", errors="replace")
        total += text.count(token)
    return total


def build_fingerprint(parts: List[str]) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def main() -> None:
    repo_path = Path(os.environ.get("AUDIT_REPO_PATH", ".")).expanduser().resolve()
    command_context = repo_path / "src/context/CommandContext.tsx"

    event_name = "extensions:show-running"
    dispatch_line = find_line_number(command_context, f'new CustomEvent("{event_name}")')
    if not dispatch_line:
        print("[]")
        return

    dispatches = dispatch_count(repo_path, event_name)
    listeners = listener_count(repo_path, event_name)
    if dispatches <= 0 or listeners > 0:
        print("[]")
        return

    finding_id = "extensions-show-running-event-unhandled"
    finding: Dict[str, object] = {
        "finding_id": finding_id,
        "evidence_file": str(command_context),
        "evidence_line": dispatch_line,
        "title": "Command Palette 'Show Running Extensions' action dispatches an unhandled event and no-ops",
        "description": (
            "CommandContext registers `Show Running Extensions` (`extension.showRunningExtensions`) and "
            "dispatches `extensions:show-running`, but there are no production listeners for that event. "
            "Executing the command from Command Palette results in no visible action."
        ),
        "reproduction_steps": [
            "Open Cortex IDE with any workspace folder visible in the sidebar.",
            "Open Command Palette (`Ctrl+Shift+P`) and run `Show Running Extensions`.",
            "Observe no running-extensions view/panel opens; UI state remains unchanged.",
        ],
        "impact": (
            "A discoverable command in the primary command surface silently fails, "
            "breaking extension diagnostics workflow and reducing trust in command routing."
        ),
        "project": "ide",
        "expected_behavior": (
            "`Show Running Extensions` should open the running-extensions diagnostics view/panel."
        ),
        "actual_behavior": (
            "The command emits `extensions:show-running` with zero listeners, so it no-ops."
        ),
        "error_message": "No explicit error; command closes and nothing opens.",
        "debug_logs": (
            f"`{event_name}` dispatch count: {dispatches}; listener count (excluding tests): {listeners}."
        ),
        "system_information": "Native GUI: Cortex IDE",
        "additional_context": (
            "This is an event-routing regression in command execution path "
            "(`extension.showRunningExtensions` -> `extensions:show-running`)."
        ),
        "native_gui": "Cortex IDE",
        "proof_artifacts": [],
        "dedup_hints": [
            "Show Running Extensions command silently does nothing",
            "extensions:show-running dispatched with no listener",
            "extension.showRunningExtensions no-op in command palette",
        ],
        "fingerprint": build_fingerprint(
            [
                finding_id,
                str(command_context),
                event_name,
                f"dispatches={dispatches}",
                f"listeners={listeners}",
            ]
        ),
    }
    print(json.dumps([finding], ensure_ascii=True))


if __name__ == "__main__":
    main()
