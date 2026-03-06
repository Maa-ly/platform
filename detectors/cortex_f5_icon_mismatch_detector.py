#!/usr/bin/env python3
"""Detect F5 title-bar icon semantics mismatch in Cortex IDE."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Dict, List, Optional


def find_line_number(path: Path, snippet: str) -> Optional[int]:
    if not path.exists():
        return None
    for idx, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if snippet in line:
            return idx
    return None


def build_fingerprint(parts: List[str]) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def is_menu_bar_runtime_reachable(repo_path: Path, menu_bar: Path) -> bool:
    src_root = repo_path / "src"
    if not src_root.exists():
        return False

    for file_path in src_root.rglob("*"):
        if file_path.suffix not in {".ts", ".tsx"}:
            continue
        rel = file_path.relative_to(src_root).as_posix()
        if "__tests__" in rel:
            continue
        if file_path.resolve() == menu_bar.resolve():
            continue
        if rel == "components/index.ts":
            continue

        text = file_path.read_text(encoding="utf-8")
        if 'from "@/components/MenuBar"' in text:
            return True
        if 'from "./components/MenuBar"' in text or 'from "../components/MenuBar"' in text:
            return True
        if "<MenuBar" in text:
            return True
    return False


def main() -> None:
    repo_path = Path(os.environ.get("AUDIT_REPO_PATH", ".")).expanduser().resolve()
    menu_bar = repo_path / "src/components/MenuBar.tsx"
    findings: List[Dict[str, object]] = []

    tooltip_snippet = 'title="Start Debugging (F5)"'
    pause_icon_snippet = '<Icon name="pause" size={16} />'

    tooltip_line = find_line_number(menu_bar, tooltip_snippet)
    pause_icon_line = find_line_number(menu_bar, pause_icon_snippet)

    if menu_bar.exists() and is_menu_bar_runtime_reachable(repo_path, menu_bar) and tooltip_line and pause_icon_line:
        finding_id = "titlebar-f5-pause-glyph-mismatch"
        findings.append(
            {
                "finding_id": finding_id,
                "evidence_file": str(menu_bar),
                "evidence_line": pause_icon_line,
                "title": "F5 title-bar control uses a pause glyph despite start tooltip semantics",
                "description": (
                    "The right-side F5 control tooltip indicates a start action, but the rendered icon is `pause`. "
                    "The visual cue conflicts with the tooltip semantics shown on the same control."
                ),
                "reproduction_steps": [
                    "Launch Cortex IDE with the custom title bar visible.",
                    "Hover the F5 control in the top-right area and read tooltip `Start Debugging (F5)`.",
                    "Observe the same control uses a pause icon instead of a start/play icon.",
                ],
                "impact": (
                    "Conflicting icon semantics can mislead users about control intent and reduce trust in "
                    "top-level navigation affordances."
                ),
                "project": "ide",
                "expected_behavior": "A control labeled Start Debugging should use start/play iconography.",
                "actual_behavior": "The control is labeled as Start Debugging but displays a pause glyph.",
                "error_message": "No explicit error; the mismatch is visible in the native GUI control itself.",
                "debug_logs": "No logs required; mismatch is deterministic from title and icon markup.",
                "system_information": "Native GUI: Cortex IDE",
                "additional_context": "Tooltip text and icon glyph diverge in the same MenuBar control.",
                "native_gui": "Cortex IDE",
                "dedup_hints": [
                    "F5 title-bar control uses pause glyph despite start tooltip semantics",
                    "title-bar iconography mismatch pause glyph on F5 control",
                    "MenuBar Start Debugging (F5) visual glyph is pause",
                ],
                "proof_artifacts": [],
                "fingerprint": build_fingerprint(
                    [finding_id, str(menu_bar), tooltip_snippet, pause_icon_snippet]
                ),
            }
        )

    print(json.dumps(findings, ensure_ascii=True))


if __name__ == "__main__":
    main()
