#!/usr/bin/env python3
"""Detect malformed terminal context-menu shortcut labels in Cortex IDE."""

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
    for ext in (".png", ".jpg", ".jpeg", ".mp4", ".mov", ".webm"):
        candidate = local_proof_dir / f"{finding_id}{ext}"
        if candidate.exists() and candidate.is_file():
            out.append(str(candidate.resolve()))
    return out


def build_fingerprint(parts: Sequence[str]) -> str:
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def main() -> None:
    repo_path = Path(os.environ.get("AUDIT_REPO_PATH", ".")).expanduser().resolve()
    terminal_tabs = repo_path / "src/components/TerminalGroupTabs.tsx"

    findings: List[Dict[str, object]] = []

    malformed_shortcut = 'Ctrl+Shift+"'
    split_down_label = "Split Down"
    split_vertical_action = 'handleContextMenuAction("split-vertical")'

    if (
        terminal_tabs.exists()
        and find_line_number(terminal_tabs, malformed_shortcut)
        and find_line_number(terminal_tabs, split_down_label)
        and find_line_number(terminal_tabs, split_vertical_action)
    ):
        finding_id = "terminal-split-down-shortcut-label-malformed-ctrl-shift-quote"
        evidence = [
            (terminal_tabs, split_vertical_action),
            (terminal_tabs, split_down_label),
            (terminal_tabs, malformed_shortcut),
        ]
        findings.append(
            {
                "finding_id": finding_id,
                "evidence_file": str(terminal_tabs),
                "evidence_line": find_line_number(terminal_tabs, malformed_shortcut),
                "title": 'Terminal context menu shows malformed shortcut label `Ctrl+Shift+"` for Split Down',
                "description": (
                    "The Terminal context menu entry for `Split Down` renders shortcut text as "
                    "`Ctrl+Shift+\"`, which is a malformed/non-actionable accelerator label and does not "
                    "match expected keybinding notation.\n\nEvidence:\n"
                    + format_evidence(repo_path, evidence)
                ),
                "reproduction_steps": [
                    "Open Cortex IDE with a workspace folder loaded.",
                    "Open the terminal panel and right-click a terminal tab.",
                    "Observe the `Split Down` item in the context menu.",
                    "Note the shortcut label is shown as `Ctrl+Shift+\"`.",
                ],
                "impact": (
                    "Terminal context menu displays misleading keyboard guidance for a primary split action, "
                    "causing failed shortcut attempts and lower command discoverability."
                ),
                "project": "ide",
                "expected_behavior": (
                    "Split Down should show a valid, human-readable shortcut label that matches the actual keybinding."
                ),
                "actual_behavior": (
                    "Split Down displays malformed shortcut text `Ctrl+Shift+\"`."
                ),
                "error_message": "No explicit error dialog; malformed accelerator text is visible in GUI.",
                "debug_logs": "No logs required; issue is visible in the terminal context menu rendering.",
                "system_information": "Native GUI: Cortex IDE",
                "additional_context": (
                    "The malformed label is hard-coded next to the split-vertical context-menu action."
                ),
                "native_gui": "Cortex IDE",
                "dedup_hints": [
                    'TerminalGroupTabs Split Down shortcut label is rendered as Ctrl+Shift+"',
                    "terminal context menu displays malformed accelerator text for split down",
                ],
                "proof_artifacts": optional_proofs(repo_path, finding_id),
                "fingerprint": build_fingerprint(
                    [
                        finding_id,
                        str(terminal_tabs),
                        malformed_shortcut,
                        split_vertical_action,
                    ]
                ),
            }
        )

    print(json.dumps(findings, ensure_ascii=True))


if __name__ == "__main__":
    main()
