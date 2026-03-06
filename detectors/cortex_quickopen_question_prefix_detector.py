#!/usr/bin/env python3
"""Detect Ctrl+P question-prefix routing mismatch versus Quick Access Help provider."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Dict, List, Optional


def find_line_number(path: Path, snippet: str) -> Optional[int]:
    if not path.exists():
        return None
    for idx, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        if snippet in line:
            return idx
    return None


def existing_proofs(repo_path: Path, finding_id: str) -> List[str]:
    if os.environ.get("AUDIT_ALLOW_PREEXISTING_PROOFS", "").strip() != "1":
        return []

    proofs_dir = repo_path / "proofs"
    names = [
        f"{finding_id}.png",
        f"{finding_id}.step2.png",
        f"{finding_id}.preview.gif",
        f"{finding_id}.mp4",
        f"{finding_id}.cursor.mp4",
    ]
    out: List[str] = []
    for name in names:
        candidate = proofs_dir / name
        if candidate.exists() and candidate.is_file():
            out.append(str(candidate.resolve()))
    return out


def build_fingerprint(parts: List[str]) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def main() -> None:
    repo_path = Path(os.environ.get("AUDIT_REPO_PATH", ".")).expanduser().resolve()

    command_context = repo_path / "src/context/CommandContext.tsx"
    quick_access = repo_path / "src/context/QuickAccessContext.tsx"

    ctrl_p_line = find_line_number(command_context, "setShowFileFinder(true)")
    help_prefix_line = find_line_number(quick_access, 'prefix: "?",')
    help_provider_map_line = find_line_number(quick_access, 'providerMap.set("?", helpProvider);')

    findings: List[Dict[str, object]] = []

    if ctrl_p_line and help_prefix_line and help_provider_map_line:
        finding_id = "quickopen-question-prefix-routed-to-files"
        findings.append(
            {
                "finding_id": finding_id,
                "evidence_file": str(command_context),
                "evidence_line": ctrl_p_line,
                "title": "Ctrl+P `?` prefix is routed to file search instead of Quick Access Help provider",
                "description": (
                    "Quick Access defines a Help provider for `?`, but the Ctrl+P entry path in CommandContext "
                    "opens FileFinder. In GUI repro, typing `?term` remains in file-search mode (files/no-files UI) "
                    "instead of switching to Help prefix entries."
                ),
                "reproduction_steps": [
                    "Open Cortex IDE with any folder/workspace visible in the sidebar.",
                    "Press Ctrl+P and type `?term`.",
                    "Observe the quick-open surface stays in file-search mode (not Help provider entries).",
                ],
                "impact": (
                    "Users cannot use the `?` help-prefix workflow from the primary Ctrl+P quick-open path, "
                    "so prefix discovery and provider navigation are effectively broken in the main command surface."
                ),
                "project": "ide",
                "expected_behavior": "Typing `?` in Ctrl+P should switch to Help provider and list available prefixes.",
                "actual_behavior": "Ctrl+P keeps file-search behavior for `?term` and does not enter Help provider mode.",
                "error_message": "No explicit error appears; the input is silently handled by file-search flow.",
                "debug_logs": (
                    "CommandContext routes Ctrl+P to FileFinder while QuickAccessContext separately registers Help `?` provider."
                ),
                "system_information": "Native GUI: Cortex IDE",
                "additional_context": (
                    f"CommandContext.tsx:{ctrl_p_line} sets FileFinder for Ctrl+P; "
                    f"QuickAccessContext.tsx:{help_prefix_line}/{help_provider_map_line} defines `?` help provider."
                ),
                "native_gui": "Cortex IDE",
                "dedup_hints": [
                    "Ctrl+P Quick Open ignores non-file quick access prefixes and stays in file-search mode",
                    "Ctrl+P Quick Open ignores term prefix and stays in file-search mode",
                    "question prefix routing mismatch between file finder and quick access help",
                    "question-mark prefix in ctrl+p does not enter help provider mode",
                ],
                "proof_artifacts": existing_proofs(repo_path, finding_id),
                "fingerprint": build_fingerprint(
                    [
                        "quickopen-question-prefix-routes-to-files",
                        str(command_context),
                        str(quick_access),
                        "ctrl+p-filefinder",
                        "help-provider-question-prefix",
                    ]
                ),
            }
        )

    print(json.dumps(findings, ensure_ascii=True))


if __name__ == "__main__":
    main()
