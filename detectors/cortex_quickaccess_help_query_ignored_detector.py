#!/usr/bin/env python3
"""Detect Quick Access help provider query filtering regression."""

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
    quick_access = repo_path / "src/context/QuickAccessContext.tsx"

    findings: List[Dict[str, object]] = []

    help_prefix = 'prefix: "?",'
    provide_items_signature = "provideItems: async () => {"
    help_loop = "for (const [prefix, provider] of providerMap.entries()) {"

    if (
        quick_access.exists()
        and find_line_number(quick_access, help_prefix)
        and find_line_number(quick_access, provide_items_signature)
        and find_line_number(quick_access, help_loop)
    ):
        finding_id = "quickaccess-help-query-ignored-no-filtering"
        evidence = [
            (quick_access, help_prefix),
            (quick_access, provide_items_signature),
            (quick_access, help_loop),
        ]
        findings.append(
            {
                "finding_id": finding_id,
                "evidence_file": str(quick_access),
                "evidence_line": find_line_number(quick_access, provide_items_signature),
                "title": "Quick Access '?' help ignores typed query and always returns full prefix list",
                "description": (
                    "Help quick-access provider declares `provideItems: async () => {}` and never consumes "
                    "the user query text, so typing after `?` does not narrow results. Users cannot quickly "
                    "filter help entries by prefix or provider name.\n\n"
                    "Evidence:\n" + format_evidence(repo_path, evidence)
                ),
                "reproduction_steps": [
                    "Open Cortex IDE with a workspace folder.",
                    "Press `Ctrl+P` and type `?term`.",
                    "Observe help list still shows unrelated providers (for example `>`, `@`, `#`, `:`) instead of filtering to terminal-related entries.",
                ],
                "impact": (
                    "Quick Access help becomes noisy and harder to use for keyboard-driven discovery, "
                    "especially as provider count grows."
                ),
                "project": "ide",
                "expected_behavior": "Typing after `?` should filter help entries by prefix/name/description.",
                "actual_behavior": "Help provider ignores query input and always returns the full provider list.",
                "error_message": "No explicit error; the result list does not react to help query text.",
                "debug_logs": "No runtime logs required; behavior is visible in GUI and in provider implementation.",
                "system_information": "Native GUI: Cortex IDE",
                "additional_context": "Other providers consume query (`q`) and filter items; help provider does not.",
                "native_gui": "Cortex IDE",
                "dedup_hints": [
                    "Quick Access help provider ignores typed query and does not filter",
                    "question-prefix quick access always returns full list regardless of query",
                ],
                "proof_artifacts": optional_proofs(repo_path, finding_id),
                "fingerprint": build_fingerprint(
                    [
                        finding_id,
                        str(quick_access),
                        help_prefix,
                        provide_items_signature,
                        help_loop,
                    ]
                ),
            }
        )

    print(json.dumps(findings, ensure_ascii=True))


if __name__ == "__main__":
    main()
