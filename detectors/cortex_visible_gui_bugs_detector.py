#!/usr/bin/env python3
"""Detect visibly reproducible Cortex GUI bugs suitable for screenshot proof."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


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
            # Re-export only; not a runtime mount signal.
            continue

        text = file_path.read_text(encoding="utf-8")
        if 'from "@/components/MenuBar"' in text:
            return True
        if 'from "./components/MenuBar"' in text or 'from "../components/MenuBar"' in text:
            return True
        if "<MenuBar" in text:
            return True
    return False


def build_fingerprint(parts: Sequence[str]) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def optional_proofs(repo_path: Path, finding_id: str) -> List[str]:
    """Attach existing native GUI artifacts when explicitly enabled."""
    if os.environ.get("AUDIT_ALLOW_PREEXISTING_PROOFS", "").strip() != "1":
        return []

    candidates: List[Path] = []
    local_proof_dir = repo_path / "proofs"
    env_proof_dir = (
        Path(os.environ.get("AUDIT_PROOF_DIR", "")).expanduser()
        if os.environ.get("AUDIT_PROOF_DIR")
        else None
    )

    base_names = [finding_id, f"{finding_id}.focus"]
    for base in base_names:
        for ext in (".png", ".jpg", ".jpeg", ".mp4", ".mov", ".webm"):
            candidates.append(local_proof_dir / f"{base}{ext}")
            if env_proof_dir:
                candidates.append(env_proof_dir / f"{base}{ext}")

    out: List[str] = []
    seen = set()
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            resolved = str(candidate.resolve())
            if resolved in seen:
                continue
            seen.add(resolved)
            out.append(resolved)
    return out


def parse_menu_labels(default_menus_path: Path) -> List[str]:
    text = read_text(default_menus_path)
    match = re.search(r"export const MENU_LABELS = \[(.*?)\];", text, re.DOTALL)
    if not match:
        return []
    labels_block = match.group(1)
    return re.findall(r'"([^"]+)"', labels_block)


def main() -> None:
    repo_path = Path(os.environ.get("AUDIT_REPO_PATH", ".")).expanduser().resolve()
    findings: List[Dict[str, object]] = []

    default_menus = repo_path / "src/components/cortex/titlebar/defaultMenus.ts"
    title_bar = repo_path / "src/components/cortex/CortexTitleBar.tsx"
    menu_bar = repo_path / "src/components/MenuBar.tsx"
    activity_bar = repo_path / "src/components/cortex/CortexActivityBar.tsx"
    sidebar_container = repo_path / "src/components/cortex/layout/CortexSidebarContainer.tsx"
    desktop_layout = repo_path / "src/components/cortex/CortexDesktopLayout.tsx"
    open_project_dropdown = repo_path / "src/components/cortex/primitives/CortexOpenProjectDropdown.tsx"
    menu_bar_reachable = is_menu_bar_runtime_reachable(repo_path, menu_bar) if menu_bar.exists() else False

    # Finding 1-3: Run/Git/Developer menus are defined but never rendered.
    if default_menus.exists() and title_bar.exists():
        labels = parse_menu_labels(default_menus)
        rendered_from_labels_line = find_line_number(title_bar, "<For each={MENU_LABELS}>")
        menu_defs = {
            "Run": "  Run: [",
            "Git": "  Git: [",
            "Developer": "  Developer: [",
        }
        if rendered_from_labels_line:
            for menu_label, menu_def_snippet in menu_defs.items():
                if menu_label in labels:
                    continue
                menu_def_line = find_line_number(default_menus, menu_def_snippet)
                if not menu_def_line:
                    continue
                finding_id = f"titlebar-menu-missing-{menu_label.lower()}"
                evidence = [
                    (default_menus, 'export const MENU_LABELS = ['),
                    (default_menus, menu_def_snippet),
                    (title_bar, "<For each={MENU_LABELS}>"),
                ]
                findings.append(
                    {
                        "finding_id": finding_id,
                        "evidence_file": str(default_menus),
                        "evidence_line": menu_def_line,
                        "title": f"Title bar hides '{menu_label}' menu even though actions are defined",
                        "description": (
                            f"The `{menu_label}` menu exists in DEFAULT_MENUS but is omitted from MENU_LABELS, "
                            "and the title bar renders from MENU_LABELS only. The menu is unreachable from visible "
                            "GUI navigation.\n\nEvidence:\n"
                            + format_evidence(repo_path, evidence)
                        ),
                        "reproduction_steps": [
                            "Launch Cortex IDE in IDE mode.",
                            "Inspect the top menu labels in the custom title bar.",
                            f"Observe the '{menu_label}' menu is not present.",
                        ],
                        "impact": (
                            f"Users lose direct access to the '{menu_label}' command group from the title bar, "
                            "reducing discoverability and keyboardless workflows."
                        ),
                        "project": "cortex-ide",
                        "expected_behavior": f"The '{menu_label}' top-level menu should be visible in the title bar.",
                        "actual_behavior": f"'{menu_label}' actions are defined but the '{menu_label}' menu is not rendered.",
                        "error_message": "No explicit error; menu omission is silent in GUI.",
                        "debug_logs": "No logs required; menu definitions and rendered labels are out of sync.",
                        "system_information": "Native GUI: Cortex IDE",
                        "additional_context": f"MENU_LABELS does not include '{menu_label}'.",
                        "native_gui": "Cortex IDE",
                        "dedup_hints": [
                            "title bar DEFAULT_MENUS defines run git developer but MENU_LABELS omits them",
                            "title bar missing top-level menus run git developer even though menu items exist",
                        ],
                        "proof_artifacts": optional_proofs(repo_path, finding_id),
                    "fingerprint": build_fingerprint([finding_id, menu_label, str(default_menus), str(title_bar)]),
                    }
                )

    # Finding 1b: F5 start-debug action uses a pause glyph in title bar.
    if menu_bar.exists() and menu_bar_reachable:
        start_debug_title_line = find_line_number(menu_bar, 'title="Start Debugging (F5)"')
        start_debug_pause_icon_line = find_line_number(menu_bar, '<Icon name="pause" size={16} />')
        if start_debug_title_line and start_debug_pause_icon_line:
            finding_id = "titlebar-f5-pause-glyph-mismatch"
            evidence = [
                (menu_bar, 'title="Start Debugging (F5)"'),
                (menu_bar, '<Icon name="pause" size={16} />'),
            ]
            findings.append(
                {
                    "finding_id": finding_id,
                    "evidence_file": str(menu_bar),
                    "evidence_line": start_debug_pause_icon_line,
                    "title": "F5 title-bar control uses a pause glyph despite start tooltip semantics",
                    "description": (
                        "The right-side F5 control tooltip indicates a start action, but the rendered icon is "
                        "`pause`. The visual cue conflicts with the tooltip semantics shown on the same control.\n\nEvidence:\n"
                        + format_evidence(repo_path, evidence)
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
                    "expected_behavior": (
                        "A control labeled Start Debugging should use start/play iconography."
                    ),
                    "actual_behavior": (
                        "The control is labeled as Start Debugging but displays a pause glyph."
                    ),
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
                    "proof_artifacts": optional_proofs(repo_path, finding_id),
                    "fingerprint": build_fingerprint([finding_id, str(menu_bar), "start-debugging", "pause-icon"]),
                }
            )

    # Finding 2: "Open File" title-bar action routes to folder/project opener.
    if open_project_dropdown.exists() and desktop_layout.exists():
        label_line = find_line_number(open_project_dropdown, 'const displayLabel = () => local.label ?? "Open File";')
        action_line = find_line_number(desktop_layout, 'onProjectDropdownClick={() => window.dispatchEvent(new CustomEvent("folder:open"))}')
        if label_line and action_line:
            finding_id = "open-file-label-mismatch-folder-action"
            evidence = [
                (open_project_dropdown, 'const displayLabel = () => local.label ?? "Open File";'),
                (desktop_layout, 'onProjectDropdownClick={() => window.dispatchEvent(new CustomEvent("folder:open"))}'),
            ]
            findings.append(
                {
                    "finding_id": finding_id,
                    "evidence_file": str(open_project_dropdown),
                    "evidence_line": label_line,
                    "title": "Title-bar button says 'Open File' but triggers folder/project open flow",
                    "description": (
                        "The primary title-bar dropdown defaults to label 'Open File', but its click handler dispatches "
                        "`folder:open`, which opens project/folder selection rather than file-open flow.\n\nEvidence:\n"
                        + format_evidence(repo_path, evidence)
                    ),
                    "reproduction_steps": [
                        "Launch Cortex IDE and inspect the top-left action button label.",
                        "Click 'Open File' in the title bar.",
                        "Observe it opens folder/project selection flow instead of a file picker.",
                    ],
                    "impact": (
                        "Mislabeled primary action misleads users about what operation will execute, causing "
                        "navigation errors and UX trust issues."
                    ),
                    "project": "cortex-ide",
                    "expected_behavior": "Label and action should match (either 'Open Project' or true file-open behavior).",
                    "actual_behavior": "Label says 'Open File' while action routes to folder/project open event.",
                    "error_message": "No explicit error; behavior mismatch occurs silently.",
                    "debug_logs": "No logs required; mismatch is deterministic from label/action wiring.",
                    "system_information": "Native GUI: Cortex IDE",
                    "additional_context": "Mismatch is visible in title bar and reproducible from first click.",
                    "native_gui": "Cortex IDE",
                    "dedup_hints": [
                        "title bar open project open file mislabeled",
                    ],
                    "proof_artifacts": optional_proofs(repo_path, finding_id),
                    "fingerprint": build_fingerprint([finding_id, str(open_project_dropdown), str(desktop_layout)]),
                }
            )

    # Keep these loaded for quick extension of visible-nav findings.
    _ = (activity_bar, sidebar_container)

    # Finding 3: Dashboard activity icon routes to an unrendered sidebar tab.
    if activity_bar.exists() and desktop_layout.exists() and sidebar_container.exists():
        dashboard_item_line = find_line_number(activity_bar, '{ id: "dashboard", icon: "dashboard", label: "Dashboard" }')
        valid_dashboard_tab_line = find_line_number(desktop_layout, '"dashboard"')
        dashboard_render_line = find_line_number(sidebar_container, 'props.sidebarTab === "dashboard"')
        if dashboard_item_line and valid_dashboard_tab_line and dashboard_render_line is None:
            finding_id = "dashboard-activity-tab-renders-empty-sidebar"
            evidence = [
                (activity_bar, '{ id: "dashboard", icon: "dashboard", label: "Dashboard" }'),
                (desktop_layout, "const VALID_SIDEBAR_TABS: SidebarTab[] = ["),
                (desktop_layout, '"dashboard"'),
            ]
            findings.append(
                {
                    "finding_id": finding_id,
                    "evidence_file": str(activity_bar),
                    "evidence_line": dashboard_item_line,
                    "title": "Dashboard activity icon opens a sidebar tab with no rendered panel",
                    "description": (
                        "The activity bar exposes a Dashboard icon and layout state accepts `dashboard` as a valid "
                        "sidebar tab, but CortexSidebarContainer has no `Show` branch for `props.sidebarTab === \"dashboard\"`. "
                        "Clicking Dashboard therefore opens an empty sidebar frame.\n\nEvidence:\n"
                        + format_evidence(repo_path, evidence)
                    ),
                    "reproduction_steps": [
                        "Launch Cortex IDE with a folder opened.",
                        "Click the `Dashboard` icon in the activity bar.",
                        "Observe the sidebar remains as an empty container with no dashboard content.",
                    ],
                    "impact": (
                        "Users are presented with a visible navigation target that leads to a dead-end panel, "
                        "breaking trust in primary sidebar navigation."
                    ),
                    "project": "cortex-ide",
                    "expected_behavior": "Dashboard should render panel content, or the Dashboard icon/tab should not be exposed.",
                    "actual_behavior": "Dashboard tab is selectable, but no panel renderer exists so the sidebar is empty.",
                    "error_message": "No explicit error; navigation silently lands on an unrendered tab.",
                    "debug_logs": "No logs required; dashboard tab is valid in layout state but absent in sidebar render branches.",
                    "system_information": "Native GUI: Cortex IDE",
                    "additional_context": "CortexSidebarContainer has no dashboard branch while ActivityBar/DesktopLayout expose it.",
                    "native_gui": "Cortex IDE",
                    "dedup_hints": [
                        "dashboard activity icon opens empty sidebar because dashboard tab has no renderer",
                        "dashboard sidebar tab is exposed but not implemented in CortexSidebarContainer",
                    ],
                    "proof_artifacts": optional_proofs(repo_path, finding_id),
                    "fingerprint": build_fingerprint([finding_id, str(activity_bar), str(desktop_layout), str(sidebar_container)]),
                }
            )

    # Finding 4: Roadmap activity icon routes to an unrendered sidebar tab.
    if activity_bar.exists() and desktop_layout.exists() and sidebar_container.exists():
        roadmap_item_line = find_line_number(activity_bar, '{ id: "map", icon: "map", label: "Roadmap" }')
        valid_map_tab_line = find_line_number(desktop_layout, '"map"')
        map_render_line = find_line_number(sidebar_container, 'props.sidebarTab === "map"')
        if roadmap_item_line and valid_map_tab_line and map_render_line is None:
            finding_id = "roadmap-activity-tab-renders-empty-sidebar"
            evidence = [
                (activity_bar, '{ id: "map", icon: "map", label: "Roadmap" }'),
                (desktop_layout, "const VALID_SIDEBAR_TABS: SidebarTab[] = ["),
                (desktop_layout, '"map"'),
            ]
            findings.append(
                {
                    "finding_id": finding_id,
                    "evidence_file": str(activity_bar),
                    "evidence_line": roadmap_item_line,
                    "title": "Roadmap activity icon opens a sidebar tab with no rendered panel",
                    "description": (
                        "The activity bar exposes a Roadmap icon (`id: \"map\"`) and layout state accepts `map` as a "
                        "valid sidebar tab, but CortexSidebarContainer has no `Show` branch for `props.sidebarTab === \"map\"`. "
                        "Clicking Roadmap therefore opens an empty sidebar frame.\n\nEvidence:\n"
                        + format_evidence(repo_path, evidence)
                    ),
                    "reproduction_steps": [
                        "Launch Cortex IDE with a folder opened.",
                        "Click the `Roadmap` icon in the activity bar.",
                        "Observe the sidebar remains as an empty container with no roadmap content.",
                    ],
                    "impact": (
                        "Users are presented with a visible navigation target that leads to an empty panel, "
                        "creating dead-end navigation in the primary activity bar."
                    ),
                    "project": "cortex-ide",
                    "expected_behavior": "Roadmap should render panel content, or the Roadmap icon/tab should be removed.",
                    "actual_behavior": "Roadmap tab is selectable, but no panel renderer exists so the sidebar is empty.",
                    "error_message": "No explicit error; navigation silently lands on an unrendered tab.",
                    "debug_logs": "No logs required; map tab is valid in layout state but absent in sidebar render branches.",
                    "system_information": "Native GUI: Cortex IDE",
                    "additional_context": "CortexSidebarContainer has no map branch while ActivityBar/DesktopLayout expose it.",
                    "native_gui": "Cortex IDE",
                    "dedup_hints": [
                        "roadmap activity icon opens empty sidebar because map tab has no renderer",
                        "map sidebar tab is exposed but not implemented in CortexSidebarContainer",
                    ],
                    "proof_artifacts": optional_proofs(repo_path, finding_id),
                    "fingerprint": build_fingerprint([finding_id, str(activity_bar), str(desktop_layout), str(sidebar_container)]),
                }
            )

    print(json.dumps(findings, ensure_ascii=True))


if __name__ == "__main__":
    main()
