#!/usr/bin/env python3
"""Detect nested terminal tab buttons that produce malformed HTML markup."""

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
    tabs_file = repo_path / "src/components/TerminalGroupTabs.tsx"

    findings: List[Dict[str, object]] = []

    outer_button_snippet = "onClick={() => handleSelectTerminal(terminal.id)}"
    inner_close_button_snippet = "onClick={(e) => handleCloseTerminal(e, terminal.id)}"
    close_icon_snippet = "<Icon name=\"xmark\" style={{ width: \"10px\", height: \"10px\" }} />"

    outer_line = find_line_number(tabs_file, outer_button_snippet)
    inner_line = find_line_number(tabs_file, inner_close_button_snippet)

    if tabs_file.exists() and outer_line and inner_line and inner_line > outer_line:
        finding_id = "terminal-tabs-close-button-nested-button-markup"
        evidence = [
            (tabs_file, outer_button_snippet),
            (tabs_file, inner_close_button_snippet),
            (tabs_file, close_icon_snippet),
        ]
        findings.append(
            {
                "finding_id": finding_id,
                "evidence_file": str(tabs_file),
                "evidence_line": inner_line,
                "title": "Terminal tabs render nested button markup for the close control",
                "description": (
                    "Terminal tab rows are rendered as `<button>` elements, and each row embeds a second "
                    "close `<button>` inside the parent button. This is invalid interactive HTML and browsers "
                    "re-parent the DOM, which can produce malformed-render warnings and inconsistent click/focus "
                    "behavior.\n\n"
                    "Evidence:\n"
                    + format_evidence(repo_path, evidence)
                ),
                "reproduction_steps": [
                    "Open Cortex IDE with any workspace folder loaded.",
                    "Open the terminal panel so terminal tabs are visible.",
                    "Observe each tab row contains an `x` close button inside the tab button itself.",
                    "Interact with the close control and note this relies on invalid nested-button markup.",
                ],
                "impact": (
                    "Invalid nested interactive markup can cause accessibility regressions, inconsistent event "
                    "propagation/focus behavior, and browser DOM autocorrection warnings in production GUI flows."
                ),
                "project": "ide",
                "expected_behavior": (
                    "Terminal tab rows should avoid nesting interactive controls (for example, use a non-button "
                    "container for the row, or separate sibling controls)."
                ),
                "actual_behavior": (
                    "A close `<button>` is rendered inside a parent tab `<button>` in TerminalGroupTabs."
                ),
                "error_message": (
                    "Malformed HTML warning may be emitted by the renderer due to nested button markup."
                ),
                "debug_logs": (
                    "No backend log required; invalid markup is visible in source and reproducible in native GUI."
                ),
                "system_information": "Native GUI: Cortex IDE",
                "additional_context": (
                    "This pattern appears in terminal tab rendering where tab selection and close actions share "
                    "nested button elements."
                ),
                "native_gui": "Cortex IDE",
                "dedup_hints": [
                    "TerminalGroupTabs renders close button inside terminal tab button",
                    "terminal tab close control uses nested interactive button markup",
                ],
                "proof_artifacts": optional_proofs(repo_path, finding_id),
                "fingerprint": build_fingerprint(
                    [
                        finding_id,
                        str(tabs_file),
                        outer_button_snippet,
                        inner_close_button_snippet,
                    ]
                ),
            }
        )

    print(json.dumps(findings, ensure_ascii=True))


if __name__ == "__main__":
    main()
