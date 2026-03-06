#!/usr/bin/env python3
"""Detect event-routing regressions in Cortex IDE quick access/menu flows.

Outputs JSON list of findings to stdout (detector contract).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
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
    pattern = re.compile(
        rf"addEventListener\s*\(\s*['\"]{re.escape(event_name)}['\"]"
    )
    total = 0
    for path in iter_source_files(repo_path):
        text = path.read_text(encoding="utf-8", errors="replace")
        total += len(pattern.findall(text))
    return total


def dispatch_count(repo_path: Path, event_name: str) -> int:
    pattern = re.compile(
        rf"CustomEvent\s*\(\s*['\"]{re.escape(event_name)}['\"]"
    )
    total = 0
    for path in iter_source_files(repo_path):
        text = path.read_text(encoding="utf-8", errors="replace")
        total += len(pattern.findall(text))
    return total


def build_fingerprint(parts: List[str]) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def command_has_shortcut(source_text: str, command_id: str, shortcut: str) -> bool:
    pattern = re.compile(
        rf'id:\s*"{re.escape(command_id)}".*?shortcut:\s*"{re.escape(shortcut)}"',
        re.DOTALL,
    )
    return bool(pattern.search(source_text))


def finding_base(
    finding_id: str,
    title: str,
    description: str,
    impact: str,
    evidence_file: Path,
    evidence_line: int,
    repro_steps: List[str],
    expected: str,
    actual: str,
    additional_context: str,
) -> Dict[str, object]:
    return {
        "finding_id": finding_id,
        "title": title,
        "description": description,
        "impact": impact,
        "reproduction_steps": repro_steps,
        "project": "cortex-ide",
        "native_gui": "Cortex IDE",
        "system_information": "Native GUI: Cortex IDE",
        "expected_behavior": expected,
        "actual_behavior": actual,
        "additional_context": additional_context,
        "error_message": "No visible error; the UI action silently has no effect.",
        "debug_logs": "No runtime exception required to trigger this regression.",
        "evidence_file": str(evidence_file),
        "evidence_line": evidence_line,
        "proof_artifacts": [],
    }


def main() -> None:
    repo_path = Path(os.environ.get("AUDIT_REPO_PATH", ".")).expanduser().resolve()
    enable_shortcut_conflicts = os.environ.get(
        "CORTEX_ENABLE_SHORTCUT_CONFLICT_FINDINGS",
        "0",
    ).strip() in {"1", "true", "yes"}
    enable_ambiguous_shortcut_findings = os.environ.get(
        "CORTEX_ENABLE_AMBIGUOUS_SHORTCUT_FINDINGS",
        "0",
    ).strip() in {"1", "true", "yes"}
    findings: List[Dict[str, object]] = []

    quick_access = repo_path / "src/context/QuickAccessContext.tsx"
    view_quick_access = repo_path / "src/components/ViewQuickAccess.tsx"
    command_context = repo_path / "src/context/CommandContext.tsx"
    menu_bar = repo_path / "src/components/MenuBar.tsx"
    view_nav_handlers = repo_path / "src/components/cortex/handlers/ViewNavigationHandlers.tsx"
    command_context_text = (
        command_context.read_text(encoding="utf-8", errors="replace") if command_context.exists() else ""
    )

    # Finding 1: "view " quick access dispatches an unhandled event.
    layout_event = "layout:show-view"
    layout_dispatch_line = find_line_number(quick_access, layout_event)
    layout_listener_count = listener_count(repo_path, layout_event)
    view_focus_line = find_line_number(view_quick_access, 'new CustomEvent("view:focus"')
    if layout_dispatch_line and layout_listener_count == 0 and view_focus_line:
        finding_id = "quickaccess-view-event-unhandled"
        finding = finding_base(
            finding_id=finding_id,
            title="Quick Access 'view ' entries dispatch an event with no registered handler",
            description=(
                "The Quick Access Views provider emits `layout:show-view`, but no production file "
                "registers `addEventListener` for that event. Related view navigation paths use "
                "`view:focus`, creating an event-name mismatch that leaves `view ` selections inert."
            ),
            impact=(
                "Users selecting entries from `view ` quick access cannot navigate to the requested view, "
                "breaking a core keyboard navigation workflow."
            ),
            evidence_file=quick_access,
            evidence_line=layout_dispatch_line,
            repro_steps=[
                "Open Quick Access in Cortex IDE.",
                "Type `view ` and select any result such as Explorer or Search.",
                "Observe that no view focus/navigation change occurs.",
            ],
            expected=(
                "Selecting a `view ` item should focus/open the corresponding target view."
            ),
            actual=(
                "Selection emits `layout:show-view`, which has no listener, so the UI remains unchanged."
            ),
            additional_context=(
                f"`layout:show-view` listener count in src (excluding tests): {layout_listener_count}. "
                f"`view:focus` is actively dispatched in {view_quick_access}."
            ),
        )
        finding["fingerprint"] = build_fingerprint(
            [finding_id, str(quick_access), layout_event, "listener_count=0", str(view_quick_access)]
        )
        finding["dedup_hints"] = [
            "quick access view entries dispatch event with no registered handler",
        ]
        findings.append(finding)

    # Finding 2: debug actions exposed in menus/commands but no listeners.
    debug_events = [
        "debug:add-configuration",
        "debug:open-launch-json",
        "debug:continue",
        "debug:pause",
        "debug:step-over",
        "debug:step-into",
        "debug:step-out",
    ]
    missing_debug = [
        ev for ev in debug_events if dispatch_count(repo_path, ev) > 0 and listener_count(repo_path, ev) == 0
    ]
    debug_line = find_line_number(command_context, 'new CustomEvent("debug:add-configuration")')
    if debug_line and missing_debug:
        finding_id = "debug-actions-event-handlers-missing"
        finding = finding_base(
            finding_id=finding_id,
            title="Debug command actions are wired to events that are never handled",
            description=(
                "Debug commands dispatch events such as `debug:add-configuration` and "
                "`debug:open-launch-json`, but there are no corresponding `addEventListener` handlers in "
                "production code. Menu and command-palette entries therefore no-op."
            ),
            impact=(
                "Core debug workflows become unreachable from UI command surfaces, increasing time-to-debug "
                "and creating misleading affordances."
            ),
            evidence_file=command_context,
            evidence_line=debug_line,
            repro_steps=[
                "Open Cortex IDE Run/Debug menu or Command Palette.",
                "Trigger actions like `Add Configuration...`, `Open launch.json`, `Continue`, or `Step Over`.",
                "Observe no corresponding debug operation executes.",
            ],
            expected=(
                "Each debug action should be consumed by a registered handler that performs the intended operation."
            ),
            actual=(
                "The actions emit unhandled events, so the UI action silently does nothing."
            ),
            additional_context=(
                "Unhandled debug events detected: " + ", ".join(missing_debug)
            ),
        )
        finding["fingerprint"] = build_fingerprint(
            [finding_id, str(command_context), ",".join(sorted(missing_debug))]
        )
        finding["dedup_hints"] = [
            "debug add configuration command silently fails with no launch.json created",
            "debug commands dispatch unhandled events and do nothing",
        ]
        findings.append(finding)

    # Finding 3: multiple Git command events are dispatched but unhandled.
    git_events = [
        "git:clone-recursive",
        "git:merge",
        "git:merge-abort",
        "git:publish-branch",
        "git:set-upstream",
        "git:stash-show-diff",
    ]
    missing_git = [
        ev for ev in git_events if dispatch_count(repo_path, ev) > 0 and listener_count(repo_path, ev) == 0
    ]
    git_line = find_line_number(command_context, 'new CustomEvent("git:clone-recursive")')
    handled_git_line = find_line_number(view_nav_handlers, '"git:clone": (() => {')
    if git_line and missing_git and handled_git_line:
        finding_id = "git-command-events-handler-gap"
        finding = finding_base(
            finding_id=finding_id,
            title="Git menu/command actions expose events that are not wired to handlers",
            description=(
                "Git commands dispatch events for clone-recursive/merge/publish/stash flows, but these "
                "events are not handled anywhere in production listeners. In contrast, only a subset like "
                "`git:clone`, `git:push`, and `git:pull` are wired."
            ),
            impact=(
                "Users can select visible Git actions that silently do nothing, breaking source-control workflows "
                "and trust in menu/command discoverability."
            ),
            evidence_file=command_context,
            evidence_line=git_line,
            repro_steps=[
                "Open Git menu or Command Palette in Cortex IDE.",
                "Run actions such as `Clone Repository (with submodules)...`, `Merge Branch...`, or `Publish Branch...`.",
                "Observe there is no resulting dialog/operation for these actions.",
            ],
            expected=(
                "Each exposed Git action should trigger its corresponding operation or dialog."
            ),
            actual=(
                "Actions emit unhandled events and do not execute."
            ),
            additional_context=(
                "Handled Git events exist in ViewNavigationHandlers, but missing handlers were detected for: "
                + ", ".join(missing_git)
            ),
        )
        finding["fingerprint"] = build_fingerprint(
            [finding_id, str(command_context), str(view_nav_handlers), ",".join(sorted(missing_git))]
        )
        finding["dedup_hints"] = [
            "git publish branch command silently fails with no action",
            "git menu command actions are not wired to handlers",
        ]
        findings.append(finding)

    # Finding 4: Ctrl+T shortcut conflict makes transpose unreachable from keyboard.
    workspace_symbol_ctrl_t = command_has_shortcut(
        command_context_text, "workspace-symbol-picker", "Ctrl+T"
    )
    transpose_ctrl_t = command_has_shortcut(
        command_context_text, "transpose-characters", "Ctrl+T"
    )
    ctrl_t_keydown_line = find_line_number(command_context, 'e.key === "t")')
    transpose_command_line = find_line_number(command_context, 'id: "transpose-characters"')
    if (
        enable_shortcut_conflicts
        and workspace_symbol_ctrl_t
        and transpose_ctrl_t
        and ctrl_t_keydown_line
        and transpose_command_line
    ):
        finding_id = "shortcut-ctrl-t-transpose-unreachable"
        finding = finding_base(
            finding_id=finding_id,
            title="Ctrl+T always opens Workspace Symbols, making Transpose Characters unreachable",
            description=(
                "CommandContext binds `Ctrl+T` to both `workspace-symbol-picker` and "
                "`transpose-characters`, but the global keydown handler always intercepts "
                "`Ctrl+T` and opens the workspace symbol picker. The transpose shortcut "
                "cannot be triggered from the keyboard."
            ),
            impact=(
                "Users cannot execute `Transpose Characters` via its advertised shortcut, and "
                "keyboard behavior is inconsistent with command labels."
            ),
            evidence_file=command_context,
            evidence_line=ctrl_t_keydown_line,
            repro_steps=[
                "Open a text file and place the cursor in a word.",
                "Press `Ctrl+T`.",
                "Observe that Workspace Symbols opens instead of transposing adjacent characters.",
            ],
            expected=(
                "`Ctrl+T` should execute exactly one command or use non-conflicting bindings; "
                "if labeled for transpose, it should transpose text in-editor."
            ),
            actual=(
                "`Ctrl+T` is hardwired to open workspace symbols, so transpose is unreachable from keyboard."
            ),
            additional_context=(
                f"`transpose-characters` shortcut declaration line: {transpose_command_line}; "
                f"`Ctrl+T` keydown intercept line: {ctrl_t_keydown_line}."
            ),
        )
        finding["fingerprint"] = build_fingerprint(
            [finding_id, str(command_context), "workspace-symbol-picker:Ctrl+T", "transpose-characters:Ctrl+T"]
        )
        finding["dedup_hints"] = [
            "Ctrl+T shortcut conflict opens workspace symbols instead of transpose characters",
            "transpose characters shortcut unreachable because Ctrl+T is intercepted",
            "Transpose Characters Short Key doesn't work Ctrl+T Go to Symbol in Workspace",
            "Ctrl+T bound to two commands Transpose Characters unreachable",
        ]
        findings.append(finding)

    # Finding 5: Ctrl+K Ctrl+C is assigned to two unrelated commands.
    add_line_comment_ctrl_k_c = command_has_shortcut(
        command_context_text, "add-line-comment", "Ctrl+K Ctrl+C"
    )
    centered_layout_ctrl_k_c = command_has_shortcut(
        command_context_text, "workbench.action.toggleCenteredLayout", "Ctrl+K Ctrl+C"
    )
    add_line_comment_line = find_line_number(command_context, 'id: "add-line-comment"')
    centered_layout_line = find_line_number(command_context, 'id: "workbench.action.toggleCenteredLayout"')
    if (
        enable_shortcut_conflicts
        and add_line_comment_ctrl_k_c
        and centered_layout_ctrl_k_c
        and add_line_comment_line
        and centered_layout_line
    ):
        finding_id = "shortcut-ctrl-k-ctrl-c-centered-layout-conflict"
        finding = finding_base(
            finding_id=finding_id,
            title="Ctrl+K Ctrl+C is assigned to both Add Line Comment and Toggle Centered Layout",
            description=(
                "CommandContext declares the same chord (`Ctrl+K Ctrl+C`) for two unrelated commands: "
                "`add-line-comment` and `workbench.action.toggleCenteredLayout`. "
                "This creates an ambiguous binding where keyboard intent cannot be resolved reliably."
            ),
            impact=(
                "At least one of the two commands becomes unreachable or unpredictable from the keyboard, "
                "and users receive conflicting shortcut guidance in command surfaces."
            ),
            evidence_file=command_context,
            evidence_line=add_line_comment_line,
            repro_steps=[
                "Open Command Palette (`Ctrl+Shift+P`) in Cortex IDE.",
                "Search `Add Line Comment` and note shortcut `Ctrl+K Ctrl+C`.",
                "Search `Toggle Centered Layout` and note the same shortcut `Ctrl+K Ctrl+C`.",
                "Press `Ctrl+K Ctrl+C` and observe only one action can win for the same chord.",
            ],
            expected=(
                "Each keyboard chord should map to a single command or be disambiguated by explicit context."
            ),
            actual=(
                "`Ctrl+K Ctrl+C` is advertised for both commenting and centered layout toggling."
            ),
            additional_context=(
                f"`add-line-comment` declared at line {add_line_comment_line}; "
                f"`workbench.action.toggleCenteredLayout` declared at line {centered_layout_line}."
            ),
        )
        finding["fingerprint"] = build_fingerprint(
            [
                finding_id,
                str(command_context),
                "add-line-comment:Ctrl+K Ctrl+C",
                "workbench.action.toggleCenteredLayout:Ctrl+K Ctrl+C",
            ]
        )
        finding["dedup_hints"] = [
            "Ctrl+K Ctrl+C assigned to both Add Line Comment and Toggle Centered Layout",
            "centered layout command reuses add line comment chord Ctrl+K Ctrl+C",
        ]
        findings.append(finding)

    # Finding 6: Debug "New Breakpoint" submenu actions dispatch unhandled events.
    breakpoint_events = [
        "debug:add-conditional-breakpoint",
        "debug:add-logpoint",
        "debug:add-function-breakpoint",
        "debug:add-data-breakpoint",
    ]
    missing_breakpoint_events = [
        ev for ev in breakpoint_events if dispatch_count(repo_path, ev) > 0 and listener_count(repo_path, ev) == 0
    ]
    breakpoint_line = find_line_number(command_context, 'new CustomEvent("debug:add-conditional-breakpoint")')
    if breakpoint_line and missing_breakpoint_events:
        finding_id = "debug-breakpoint-submenu-unhandled-events"
        finding = finding_base(
            finding_id=finding_id,
            title="Run menu 'New Breakpoint' actions silently no-op due to unhandled debug events",
            description=(
                "Cortex exposes breakpoint submenu commands (Conditional/Logpoint/Function/Data), "
                "but these commands dispatch debug events with no production listeners, so invoking "
                "them from Command Palette or menus produces no dialog or breakpoint action."
            ),
            impact=(
                "Users cannot create advanced breakpoint types from visible debug controls, "
                "blocking debugging workflows and causing silent command failure."
            ),
            evidence_file=command_context,
            evidence_line=breakpoint_line,
            repro_steps=[
                "Open Command Palette in Cortex IDE.",
                "Run `Debug: Add Conditional Breakpoint...`.",
                "Observe that no breakpoint dialog or editor prompt appears.",
            ],
            expected=(
                "Selecting a New Breakpoint command should open the corresponding breakpoint "
                "UI flow (conditional/logpoint/function/data)."
            ),
            actual=(
                "Command executes silently with no visible result because dispatched events have no handlers."
            ),
            additional_context=(
                "Unhandled breakpoint events detected: " + ", ".join(missing_breakpoint_events)
            ),
        )
        finding["fingerprint"] = build_fingerprint(
            [finding_id, str(command_context), ",".join(sorted(missing_breakpoint_events))]
        )
        finding["dedup_hints"] = [
            "debug add conditional breakpoint command dispatches unhandled event",
            "new breakpoint submenu options logpoint function data breakpoint do nothing",
            "debug:add-conditional-breakpoint debug:add-logpoint debug:add-function-breakpoint debug:add-data-breakpoint no listener",
        ]
        findings.append(finding)

    # Finding 7: Alt+Down is assigned to two unrelated commands.
    move_line_down_alt_down = command_has_shortcut(
        command_context_text, "move-line-down", "Alt+Down"
    )
    terminal_split_down_alt_down = command_has_shortcut(
        command_context_text, "terminal.navigateSplitDown", "Alt+Down"
    )
    move_line_down_line = find_line_number(command_context, 'id: "move-line-down"')
    terminal_split_down_line = find_line_number(command_context, 'id: "terminal.navigateSplitDown"')
    if (
        enable_shortcut_conflicts
        and
        move_line_down_alt_down
        and terminal_split_down_alt_down
        and move_line_down_line
        and terminal_split_down_line
    ):
        finding_id = "shortcut-alt-down-move-line-vs-terminal-split-conflict"
        finding = finding_base(
            finding_id=finding_id,
            title="Alt+Down is bound to both Move Line Down and Terminal Navigate Split Down",
            description=(
                "CommandContext assigns `Alt+Down` to two unrelated commands: "
                "`move-line-down` and `terminal.navigateSplitDown`. This creates "
                "an ambiguous global keybinding where one of the actions is blocked."
            ),
            impact=(
                "Keyboard workflows become inconsistent: users cannot reliably trigger "
                "line movement versus terminal split navigation from the same shortcut."
            ),
            evidence_file=command_context,
            evidence_line=move_line_down_line,
            repro_steps=[
                "Open Command Palette in Cortex IDE (`Ctrl+Shift+P`).",
                "Search `down` and inspect results containing `Move Line Down` and `Navigate Split Down`.",
                "Observe both commands advertise shortcut `Alt+Down`.",
                "Press `Alt+Down` and observe only one action can execute for the shared chord.",
            ],
            expected=(
                "Each shortcut should map to one command, or bindings should be context-scoped without collision."
            ),
            actual=(
                "`Alt+Down` is advertised for both line move and terminal split navigation."
            ),
            additional_context=(
                f"`move-line-down` line: {move_line_down_line}; "
                f"`terminal.navigateSplitDown` line: {terminal_split_down_line}."
            ),
        )
        finding["fingerprint"] = build_fingerprint(
            [
                finding_id,
                str(command_context),
                "move-line-down:Alt+Down",
                "terminal.navigateSplitDown:Alt+Down",
            ]
        )
        finding["dedup_hints"] = [
            "Alt+Down bound to both Move Line Down and Terminal Navigate Split Down",
            "move-line-down and terminal.navigateSplitDown share Alt+Down shortcut conflict",
        ]
        findings.append(finding)

    # Finding 8: Ctrl+Shift+5 is assigned to two terminal split commands.
    split_terminal_ctrl_shift_5 = command_has_shortcut(
        command_context_text, "terminal.splitTerminal", "Ctrl+Shift+5"
    )
    split_vertical_ctrl_shift_5 = command_has_shortcut(
        command_context_text, "terminal.splitVertical", "Ctrl+Shift+5"
    )
    split_terminal_line = find_line_number(command_context, 'id: "terminal.splitTerminal"')
    split_vertical_line = find_line_number(command_context, 'id: "terminal.splitVertical"')
    if (
        enable_shortcut_conflicts
        and
        split_terminal_ctrl_shift_5
        and split_vertical_ctrl_shift_5
        and split_terminal_line
        and split_vertical_line
    ):
        finding_id = "shortcut-ctrl-shift-5-terminal-split-conflict"
        finding = finding_base(
            finding_id=finding_id,
            title="Ctrl+Shift+5 is bound to both Split Terminal and Split Terminal Vertically",
            description=(
                "CommandContext assigns `Ctrl+Shift+5` to two terminal commands: "
                "`terminal.splitTerminal` and `terminal.splitVertical`. This creates an "
                "ambiguous binding where keyboard intent cannot be resolved predictably."
            ),
            impact=(
                "One of the terminal split actions becomes unreachable or inconsistent from "
                "the advertised shortcut, reducing reliability of terminal pane workflows."
            ),
            evidence_file=command_context,
            evidence_line=split_terminal_line,
            repro_steps=[
                "Open Command Palette in Cortex IDE (`Ctrl+Shift+P`).",
                "Search `split terminal` and inspect results containing both split commands.",
                "Observe `Split Terminal` and `Split Terminal Vertically` both advertise `Ctrl+Shift+5`.",
                "Press `Ctrl+Shift+5` and observe only one action can execute for the same chord.",
            ],
            expected=(
                "Each shortcut should map to one command, or bindings should be scoped so terminal split "
                "actions are unambiguous."
            ),
            actual=(
                "`Ctrl+Shift+5` is advertised for both terminal split commands."
            ),
            additional_context=(
                f"`terminal.splitTerminal` line: {split_terminal_line}; "
                f"`terminal.splitVertical` line: {split_vertical_line}."
            ),
        )
        finding["fingerprint"] = build_fingerprint(
            [
                finding_id,
                str(command_context),
                "terminal.splitTerminal:Ctrl+Shift+5",
                "terminal.splitVertical:Ctrl+Shift+5",
            ]
        )
        finding["dedup_hints"] = [
            "Ctrl+Shift+5 bound to both Split Terminal and Split Terminal Vertically",
            "terminal.splitTerminal and terminal.splitVertical share Ctrl+Shift+5 shortcut conflict",
        ]
        findings.append(finding)

    # Finding 9: Alt+Up is assigned to both line movement and terminal split navigation.
    move_line_up_alt_up = command_has_shortcut(
        command_context_text, "move-line-up", "Alt+Up"
    )
    terminal_split_up_alt_up = command_has_shortcut(
        command_context_text, "terminal.navigateSplitUp", "Alt+Up"
    )
    move_line_up_line = find_line_number(command_context, 'id: "move-line-up"')
    terminal_split_up_line = find_line_number(command_context, 'id: "terminal.navigateSplitUp"')
    if (
        enable_shortcut_conflicts
        and
        move_line_up_alt_up
        and terminal_split_up_alt_up
        and move_line_up_line
        and terminal_split_up_line
    ):
        finding_id = "shortcut-alt-up-move-line-vs-terminal-split-up-conflict"
        finding = finding_base(
            finding_id=finding_id,
            title="Alt+Up is bound to both Move Line Up and Terminal Navigate Split Up",
            description=(
                "CommandContext assigns `Alt+Up` to both `move-line-up` and "
                "`terminal.navigateSplitUp`, producing a keyboard conflict between editor "
                "line editing and terminal split navigation."
            ),
            impact=(
                "At least one advertised Alt+Up action is blocked or context-dependent in ways "
                "not communicated to users."
            ),
            evidence_file=command_context,
            evidence_line=move_line_up_line,
            repro_steps=[
                "Open Command Palette in Cortex IDE (`Ctrl+Shift+P`).",
                "Search `up` and inspect results containing `Move Line Up` and `Navigate Split Up`.",
                "Observe both commands advertise shortcut `Alt+Up`.",
                "Press `Alt+Up` and observe only one action can execute for the shared chord.",
            ],
            expected=(
                "Each shortcut should map to one command, or bindings should be scoped to avoid overlap."
            ),
            actual=(
                "`Alt+Up` is advertised for both line movement and terminal split navigation."
            ),
            additional_context=(
                f"`move-line-up` line: {move_line_up_line}; "
                f"`terminal.navigateSplitUp` line: {terminal_split_up_line}."
            ),
        )
        finding["fingerprint"] = build_fingerprint(
            [
                finding_id,
                str(command_context),
                "move-line-up:Alt+Up",
                "terminal.navigateSplitUp:Alt+Up",
            ]
        )
        finding["dedup_hints"] = [
            "Alt+Up bound to both Move Line Up and Terminal Navigate Split Above",
            "move-line-up and terminal.navigateSplitUp share Alt+Up shortcut conflict",
        ]
        findings.append(finding)

    # Finding 10: Alt+F12 is assigned to both breadcrumbs toggle and type definition.
    breadcrumbs_toggle_alt_f12 = command_has_shortcut(
        command_context_text, "breadcrumbs.toggle", "Alt+F12"
    )
    goto_type_definition_alt_f12 = command_has_shortcut(
        command_context_text, "go-to-type-definition", "Alt+F12"
    )
    breadcrumbs_toggle_line = find_line_number(command_context, 'id: "breadcrumbs.toggle"')
    goto_type_definition_line = find_line_number(command_context, 'id: "go-to-type-definition"')
    if (
        enable_ambiguous_shortcut_findings
        and
        breadcrumbs_toggle_alt_f12
        and goto_type_definition_alt_f12
        and breadcrumbs_toggle_line
        and goto_type_definition_line
    ):
        finding_id = "shortcut-alt-f12-breadcrumbs-vs-type-definition-conflict"
        finding = finding_base(
            finding_id=finding_id,
            title="Alt+F12 is bound to both Breadcrumbs Toggle and Go to Type Definition",
            description=(
                "CommandContext assigns `Alt+F12` to two unrelated commands: "
                "`breadcrumbs.toggle` and `go-to-type-definition`. This creates a global "
                "shortcut collision where one action is unreachable or behavior becomes context-dependent."
            ),
            impact=(
                "Users cannot rely on `Alt+F12` for deterministic navigation/editing behavior, "
                "and at least one advertised command is blocked from keyboard access."
            ),
            evidence_file=command_context,
            evidence_line=breadcrumbs_toggle_line,
            repro_steps=[
                "Open Command Palette in Cortex IDE (`Ctrl+Shift+P`).",
                "Search `f12` and inspect results containing `Toggle Breadcrumbs` and `Go to Type Definition`.",
                "Observe both commands advertise shortcut `Alt+F12`.",
                "Press `Alt+F12` and observe only one action can execute for the shared chord.",
            ],
            expected=(
                "Each shortcut should map to a single command, or conflicting bindings should be removed/scoped."
            ),
            actual=(
                "`Alt+F12` is advertised for both breadcrumb toggling and type-definition navigation."
            ),
            additional_context=(
                f"`breadcrumbs.toggle` line: {breadcrumbs_toggle_line}; "
                f"`go-to-type-definition` line: {goto_type_definition_line}."
            ),
        )
        finding["fingerprint"] = build_fingerprint(
            [
                finding_id,
                str(command_context),
                "breadcrumbs.toggle:Alt+F12",
                "go-to-type-definition:Alt+F12",
            ]
        )
        finding["dedup_hints"] = [
            "Alt+F12 bound to both Toggle Breadcrumbs and Go to Type Definition",
            "breadcrumbs.toggle and go-to-type-definition share Alt+F12 shortcut conflict",
        ]
        findings.append(finding)

    # Finding 11: Ctrl+Alt+B is assigned to both Subagent Manager and Command Center.
    subagent_manager_ctrl_alt_b = command_has_shortcut(
        command_context_text, "subagent-manager", "Ctrl+Alt+B"
    )
    command_center_ctrl_alt_b = command_has_shortcut(
        command_context_text, "workbench.action.toggleCommandCenter", "Ctrl+Alt+B"
    )
    subagent_manager_line = find_line_number(command_context, 'id: "subagent-manager"')
    command_center_line = find_line_number(command_context, 'id: "workbench.action.toggleCommandCenter"')
    if (
        enable_ambiguous_shortcut_findings
        and
        subagent_manager_ctrl_alt_b
        and command_center_ctrl_alt_b
        and subagent_manager_line
        and command_center_line
    ):
        finding_id = "shortcut-ctrl-alt-b-subagent-vs-command-center-conflict"
        finding = finding_base(
            finding_id=finding_id,
            title="Ctrl+Alt+B is bound to both Subagent Manager and Toggle Command Center",
            description=(
                "CommandContext assigns `Ctrl+Alt+B` to two unrelated commands: "
                "`subagent-manager` and `workbench.action.toggleCommandCenter`. "
                "This introduces a global keybinding collision where one action cannot be invoked reliably."
            ),
            impact=(
                "Users lose deterministic keyboard access to either Subagent Manager or Command Center, "
                "and shortcut guidance in command surfaces becomes misleading."
            ),
            evidence_file=command_context,
            evidence_line=subagent_manager_line,
            repro_steps=[
                "Open Command Palette in Cortex IDE (`Ctrl+Shift+P`).",
                "Search `ctrl+alt+b` and inspect results for `Subagent Manager` and `Toggle Command Center`.",
                "Observe both commands advertise shortcut `Ctrl+Alt+B`.",
                "Press `Ctrl+Alt+B` and observe only one action can execute for the shared chord.",
            ],
            expected=(
                "Each shortcut should map to a single command, or conflicts should be resolved with explicit scoping."
            ),
            actual=(
                "`Ctrl+Alt+B` is advertised for both Subagent Manager and Command Center toggling."
            ),
            additional_context=(
                f"`subagent-manager` line: {subagent_manager_line}; "
                f"`workbench.action.toggleCommandCenter` line: {command_center_line}."
            ),
        )
        finding["fingerprint"] = build_fingerprint(
            [
                finding_id,
                str(command_context),
                "subagent-manager:Ctrl+Alt+B",
                "workbench.action.toggleCommandCenter:Ctrl+Alt+B",
            ]
        )
        finding["dedup_hints"] = [
            "Ctrl+Alt+B bound to both Subagent Manager and Toggle Command Center",
            "subagent-manager and workbench.action.toggleCommandCenter share Ctrl+Alt+B shortcut conflict",
        ]
        findings.append(finding)

    print(json.dumps(findings, ensure_ascii=True))


if __name__ == "__main__":
    main()
