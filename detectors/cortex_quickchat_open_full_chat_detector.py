#!/usr/bin/env python3
"""Detect unhandled Quick Chat 'Open in full chat' routing."""

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
    quick_chat = repo_path / "src/components/ai/QuickChat.tsx"

    event_name = "chat:open"
    dispatch_line = find_line_number(quick_chat, f'new CustomEvent("{event_name}"')
    action_line = find_line_number(quick_chat, "onClick={openInFullChat}")
    if not dispatch_line or not action_line:
        print("[]")
        return

    dispatches = dispatch_count(repo_path, event_name)
    listeners = listener_count(repo_path, event_name)
    if dispatches <= 0 or listeners > 0:
        print("[]")
        return

    finding_id = "quickchat-open-full-chat-event-unhandled"
    finding: Dict[str, object] = {
        "finding_id": finding_id,
        "evidence_file": str(quick_chat),
        "evidence_line": action_line,
        "title": "Quick Chat 'Open in full chat' control closes overlay but never opens full chat",
        "description": (
            "QuickChat's header maximize action (`Open in full chat`) calls `openInFullChat()`, "
            "which closes Quick Chat and dispatches `chat:open`. No production listener is registered "
            "for `chat:open`, so the full chat surface is never opened."
        ),
        "reproduction_steps": [
            "Open Cortex IDE with any workspace folder visible.",
            "Open Quick Chat with `Ctrl+I`.",
            "Click the maximize icon in the Quick Chat header (tooltip: `Open in full chat`).",
            "Observe Quick Chat closes, but no full chat panel/view opens.",
        ],
        "impact": (
            "The advertised transition from Quick Chat to full chat is non-functional, "
            "breaking conversation handoff and forcing users to manually reopen chat context."
        ),
        "project": "ide",
        "expected_behavior": (
            "Clicking `Open in full chat` should open the full chat panel with the active thread."
        ),
        "actual_behavior": (
            "The action only closes Quick Chat and emits an unhandled `chat:open` event."
        ),
        "error_message": "No UI error; control appears to work but target panel never opens.",
        "debug_logs": (
            f"`{event_name}` dispatch count: {dispatches}; listener count (excluding tests): {listeners}."
        ),
        "system_information": "Native GUI: Cortex IDE",
        "additional_context": (
            "Quick Chat itself listens to `quick-chat:open`, but `openInFullChat()` emits `chat:open` "
            "instead of a handled event path."
        ),
        "native_gui": "Cortex IDE",
        "proof_artifacts": [],
        "dedup_hints": [
            "Quick Chat Open in full chat closes popup but does not open full chat",
            "chat:open event dispatched from QuickChat has no listener",
            "QuickChat maximize button is a silent no-op for full chat routing",
        ],
        "fingerprint": build_fingerprint(
            [
                finding_id,
                str(quick_chat),
                event_name,
                f"dispatches={dispatches}",
                f"listeners={listeners}",
            ]
        ),
    }
    print(json.dumps([finding], ensure_ascii=True))


if __name__ == "__main__":
    main()
