#!/usr/bin/env python3
"""Best-effort native GUI screenshot capture for Cortex IDE findings.

Platform support:
- macOS: AppleScript + `screencapture` (includes per-finding UI navigation hooks)
- Windows: PowerShell window APIs + .NET screen capture
- Linux: `xdotool` + one screenshot tool (`import`/`maim`/`grim`)

Outputs the generated artifact path on stdout when successful.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path


def run(cmd: list[str], *, check: bool = False) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(cmd, text=True, capture_output=True)
    if check and proc.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{proc.stderr.strip()}")
    return proc


def run_osascript(script: str, *args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return run(["osascript", "-e", script, *args], check=check)


def powershell_executable() -> str:
    for candidate in ("powershell", "pwsh"):
        if shutil.which(candidate):
            return candidate
    raise RuntimeError("PowerShell is required on Windows but was not found in PATH.")


def run_powershell(script: str, *args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    exe = powershell_executable()
    return run([exe, "-NoProfile", "-Command", script, *args], check=check)


def activate_app(app_name: str) -> None:
    script = r'''
on run argv
  set appName to item 1 of argv
  tell application "System Events"
    if exists process appName then
      tell process appName
        set frontmost to true
      end tell
      return "ok"
    end if
  end tell
  tell application appName to activate
  return "ok"
end run
'''
    run_osascript(script, app_name, check=True)


def open_workspace(app_name: str, repo_path: Path) -> None:
    run(["open", "-a", app_name, str(repo_path)], check=True)


def open_file(app_name: str, file_path: Path) -> None:
    run(["open", "-a", app_name, str(file_path)], check=True)


def best_effort_press_escape(app_name: str) -> None:
    applescript = r'''
on run argv
  set appName to item 1 of argv
  tell application "System Events"
    if exists process appName then
      tell process appName
        set frontmost to true
        key code 53
      end tell
    end if
  end tell
end run
'''
    run_osascript(applescript, app_name)


def get_focused_role(app_name: str) -> str:
    applescript = r'''
on run argv
  set appName to item 1 of argv
  tell application "System Events"
    if not (exists process appName) then return ""
    tell process appName
      set focusedRole to ""
      try
        set focusedElem to value of attribute "AXFocusedUIElement"
        set focusedRole to role of focusedElem as text
      end try
      return focusedRole
    end tell
  end tell
end run
'''
    proc = run_osascript(applescript, app_name)
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def best_effort_click_relative(app_name: str, x_ratio: float, y_ratio: float) -> bool:
    applescript = r'''
on run argv
  set appName to item 1 of argv
  set xRatio to (item 2 of argv) as real
  set yRatio to (item 3 of argv) as real
  tell application "System Events"
    if not (exists process appName) then return "missing"
    tell process appName
      if (count of windows) is 0 then return "missing-window"
      set frontmost to true
      set p to position of front window
      set s to size of front window
      set clickX to (item 1 of p) + ((item 1 of s) * xRatio)
      set clickY to (item 2 of p) + ((item 2 of s) * yRatio)
      click at {clickX, clickY}
      return "ok"
    end tell
  end tell
end run
'''
    proc = run_osascript(applescript, app_name, str(x_ratio), str(y_ratio))
    return proc.returncode == 0 and proc.stdout.strip().lower() == "ok"


def best_effort_goto_line(app_name: str, line: int) -> None:
    """Try Cmd+L then type line. If app does not support it, no-op."""
    applescript = f'''
    tell application "System Events"
      if exists process "{app_name}" then
        tell process "{app_name}"
          set frontmost to true
          keystroke "l" using {{command down}}
          delay 0.2
          keystroke "{line}"
          key code 36
        end tell
      end if
    end tell
    '''
    run_osascript(applescript)


def best_effort_open_command_palette_query(app_name: str, query: str, enter_count: int = 0) -> bool:
    applescript = r'''
on run argv
  set appName to item 1 of argv
  set q to item 2 of argv
  set enterCount to (item 3 of argv) as integer
  tell application "System Events"
    if not (exists process appName) then return "missing"
    tell process appName
      set frontmost to true
      keystroke "p" using {command down, shift down}
      delay 0.35
      keystroke "a" using {command down}
      key code 51
      delay 0.1
      if q is not "" then keystroke q
      delay 0.35
      repeat enterCount times
        key code 36
        delay 0.2
      end repeat
    end tell
  end tell
  set focusedRole to ""
  try
    set focusedElem to value of attribute "AXFocusedUIElement"
    set focusedRole to role of focusedElem as text
  end try
  return focusedRole
end run
'''
    proc = run_osascript(applescript, app_name, query, str(max(0, enter_count)))
    role = proc.stdout.strip()
    return proc.returncode == 0 and role in {"AXTextField", "AXTextArea"}


def best_effort_open_quick_access_query(app_name: str, query: str, enter_count: int = 0) -> bool:
    applescript = r'''
on run argv
  set appName to item 1 of argv
  set q to item 2 of argv
  set enterCount to (item 3 of argv) as integer
  tell application "System Events"
    if not (exists process appName) then return "missing"
    tell process appName
      set frontmost to true
      keystroke "p" using {command down}
      delay 0.35
      keystroke "a" using {command down}
      key code 51
      delay 0.1
      if q is not "" then keystroke q
      delay 0.35
      repeat enterCount times
        key code 36
        delay 0.2
      end repeat
    end tell
  end tell
  set focusedRole to ""
  try
    set focusedElem to value of attribute "AXFocusedUIElement"
    set focusedRole to role of focusedElem as text
  end try
  return focusedRole
end run
'''
    proc = run_osascript(applescript, app_name, query, str(max(0, enter_count)))
    role = proc.stdout.strip()
    return proc.returncode == 0 and role in {"AXTextField", "AXTextArea"}


def best_effort_activate_docs_from_help_menu(app_name: str) -> bool:
    applescript = r'''
on run argv
  set appName to item 1 of argv
  tell application "System Events"
    if not (exists process appName) then return "missing"
    tell process appName
      set frontmost to true
      if not (exists menu bar 1) then return "missing-menu"
      tell menu bar 1
        if not (exists menu bar item "Help") then return "missing-help"
        tell menu bar item "Help"
          click
          delay 0.15
          if exists menu item "Documentation" of menu 1 then
            click menu item "Documentation" of menu 1
            return "ok"
          end if
        end tell
      end tell
    end tell
  end tell
  return "missing-docs-item"
end run
'''
    proc = run_osascript(applescript, app_name)
    return proc.returncode == 0 and proc.stdout.strip().lower() == "ok"


def best_effort_activate_docs_from_titlebar_button(app_name: str) -> bool:
    applescript = r'''
on run argv
  set appName to item 1 of argv
  tell application "System Events"
    if not (exists process appName) then return "missing"
    tell process appName
      set frontmost to true
      if (count of windows) is 0 then return "missing-window"
      set targetButton to missing value
      try
        set targetButton to first button of front window whose name is "Help"
      end try
      if targetButton is missing value then
        try
          set targetButton to first button of entire contents of front window whose name is "Help"
        end try
      end if
      if targetButton is missing value then return "missing-help-button"
      click targetButton
      return "ok"
    end tell
  end tell
end run
'''
    proc = run_osascript(applescript, app_name)
    return proc.returncode == 0 and proc.stdout.strip().lower() == "ok"


def best_effort_activate_docs_from_sidebar_button(app_name: str) -> bool:
    applescript = r'''
on run argv
  set appName to item 1 of argv
  tell application "System Events"
    if not (exists process appName) then return "missing"
    tell process appName
      set frontmost to true
      if (count of windows) is 0 then return "missing-window"
      set targetButton to missing value
      try
        set targetButton to first button of entire contents of front window whose (name is "Documentation" or description is "Documentation")
      end try
      if targetButton is missing value then return "missing-docs-button"
      click targetButton
      return "ok"
    end tell
  end tell
end run
'''
    proc = run_osascript(applescript, app_name)
    return proc.returncode == 0 and proc.stdout.strip().lower() == "ok"


def best_effort_navigate_docs_panel(app_name: str) -> bool:
    best_effort_press_escape(app_name)
    # Click in-app Help button area in the custom title bar.
    clicked = False
    clicked = best_effort_activate_docs_from_titlebar_button(app_name) or clicked
    clicked = best_effort_click_relative(app_name, 0.49, 0.02) or clicked
    if clicked:
        time.sleep(0.8)
    # Without an accessibility tree, we cannot verify docs panel visibility reliably.
    # Keep this opt-in to avoid producing weak/generic proof on machines where click->event fails.
    if clicked and os.environ.get("CORTEX_ENABLE_UNVERIFIED_UI_NAV", "").strip() == "1":
        return True
    return False


def best_effort_navigate_issue_quick_access(app_name: str) -> bool:
    best_effort_press_escape(app_name)
    before = get_focused_role(app_name)
    if not best_effort_open_quick_access_query(app_name, "?issue", enter_count=0):
        return False
    after = get_focused_role(app_name)
    if after not in {"AXTextField", "AXTextArea"} or after == before:
        return False
    time.sleep(0.6)
    return True


def best_effort_navigate_finding_state(app_name: str, finding_id: str) -> bool:
    if finding_id == "wrong-report-target-doc-panel":
        return best_effort_navigate_docs_panel(app_name)
    if finding_id in {
        "issue-provider-unreachable",
        "wrong-default-report-repo",
        "system-info-version-mismatch",
    }:
        return best_effort_navigate_issue_quick_access(app_name)
    return False


def best_effort_open_file_via_quick_open(app_name: str, repo_path: Path, file_path: Path) -> bool:
    try:
        rel = file_path.resolve().relative_to(repo_path.resolve()).as_posix()
    except ValueError:
        rel = file_path.name
    # Use Quick Open (Cmd+P) to open file in Cortex when open -a cannot target the process.
    applescript = f'''
    tell application "System Events"
      if exists process "{app_name}" then
        tell process "{app_name}"
          set frontmost to true
          keystroke "p" using {{command down}}
          delay 0.2
          keystroke "{rel}"
          delay 0.2
          key code 36
        end tell
      end if
    end tell
    '''
    proc = run_osascript(applescript)
    if proc.returncode != 0:
        return False
    if os.environ.get("CORTEX_ENABLE_UNVERIFIED_UI_NAV", "").strip() == "1":
        return True
    # In strict mode, only treat quick-open as usable if keyboard focus moved into an input.
    return get_focused_role(app_name) in {"AXTextField", "AXTextArea"}


def get_frontmost_app_name() -> str:
    script = (
        'tell application "System Events" to get name of first application process '
        "whose frontmost is true"
    )
    proc = run_osascript(script, check=True)
    return proc.stdout.strip()


def get_front_window_region(app_name: str) -> str:
    script = r'''
on run argv
  set appName to item 1 of argv
  tell application "System Events"
    if not (exists process appName) then error "Process not found: " & appName
    tell process appName
      if (count of windows) is 0 then error "No windows for: " & appName
      set p to position of front window
      set s to size of front window
      set x to item 1 of p as integer
      set y to item 2 of p as integer
      set w to item 1 of s as integer
      set h to item 2 of s as integer
      return (x as text) & "," & (y as text) & "," & (w as text) & "," & (h as text)
    end tell
  end tell
end run
'''
    proc = run_osascript(script, app_name, check=True)
    region = proc.stdout.strip()
    parts = region.split(",")
    if len(parts) != 4:
        raise RuntimeError(f"Invalid region from AppleScript: {region}")
    return ",".join(str(int(x)) for x in parts)


def process_exists(app_name: str) -> bool:
    script = r'''
on run argv
  set appName to item 1 of argv
  tell application "System Events"
    return (exists process appName)
  end tell
end run
'''
    proc = run_osascript(script, app_name)
    return proc.returncode == 0 and proc.stdout.strip().lower() == "true"


def find_process_for_window_title(title_fragment: str) -> str:
    script = r'''
on run argv
  set needle to item 1 of argv
  tell application "System Events"
    repeat with p in application processes
      try
        repeat with w in windows of p
          set wname to name of w as text
          if wname contains needle then return name of p as text
        end repeat
      end try
    end repeat
  end tell
  return ""
end run
'''
    proc = run_osascript(script, title_fragment)
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def get_front_window_title(app_name: str) -> str:
    script = r'''
on run argv
  set appName to item 1 of argv
  tell application "System Events"
    tell process appName
      if (count of windows) is 0 then return ""
      return name of front window as text
    end tell
  end tell
end run
'''
    proc = run_osascript(script, app_name)
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def wait_for_window_title(app_name: str, title_fragment: str, timeout_seconds: float = 5.0) -> bool:
    if not title_fragment:
        return True
    deadline = time.time() + max(0.1, timeout_seconds)
    while time.time() < deadline:
        title = get_front_window_title(app_name)
        if title_fragment in title:
            return True
        time.sleep(0.4)
    return False


def default_launch_cmd(repo_path: Path) -> str:
    package_json = repo_path / "package.json"
    if not package_json.exists():
        return ""

    # Prefer lockfile-appropriate package manager, but keep install step idempotent.
    if (repo_path / "pnpm-lock.yaml").exists():
        install_cmd = "pnpm install --frozen-lockfile"
        run_cmd = "pnpm run tauri:dev"
    elif (repo_path / "yarn.lock").exists():
        install_cmd = "yarn install --frozen-lockfile"
        run_cmd = "yarn run tauri:dev"
    else:
        install_cmd = "npm install"
        run_cmd = "npm run tauri:dev"

    # Prefer Homebrew LTS Node when available (esbuild is unstable on bleeding-edge Node releases).
    lts_node_bins = [
        Path("/opt/homebrew/opt/node@22/bin"),
        Path("/opt/homebrew/opt/node@20/bin"),
    ]
    path_prefix = ""
    for bin_dir in lts_node_bins:
        if (bin_dir / "node").exists() and (bin_dir / "npm").exists():
            path_prefix = f'PATH="{bin_dir}:$PATH" '
            break

    if not (repo_path / "node_modules").exists():
        return f"{path_prefix}{install_cmd} && {path_prefix}{run_cmd}"
    return f"{path_prefix}{run_cmd}"


def start_launch_command(repo_path: Path, launch_cmd: str, output_dir: Path) -> tuple[subprocess.Popen[str], Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / f"cortex-launch-{int(time.time())}.log"
    log_handle = log_path.open("a", encoding="utf-8")
    proc = subprocess.Popen(
        launch_cmd,
        shell=True,
        cwd=str(repo_path),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    return proc, log_path


def terminate_process_group(proc: subprocess.Popen[str]) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except Exception:
        return


def wait_for_target_process(preferred_name: str, window_title: str, timeout_seconds: int) -> str:
    deadline = time.time() + max(1, timeout_seconds)
    while time.time() < deadline:
        by_title = find_process_for_window_title(window_title)
        if by_title:
            return by_title
        if preferred_name and process_exists(preferred_name):
            return preferred_name
        time.sleep(1.0)
    raise RuntimeError(
        f"Timed out waiting for target app/window (name='{preferred_name}', title contains '{window_title}')"
    )


def wait_for_named_process(process_name: str, timeout_seconds: int) -> str:
    deadline = time.time() + max(1, timeout_seconds)
    while time.time() < deadline:
        if process_exists(process_name):
            return process_name
        time.sleep(1.0)
    raise RuntimeError(f"Timed out waiting for process '{process_name}'.")


def is_tauri_dev_cmd(cmd: str) -> bool:
    value = cmd.strip().lower()
    return "tauri:dev" in value


def take_screenshot_region(region: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run(["screencapture", "-x", "-R", region, str(output_path)], check=True)


def get_front_window_info_windows() -> dict[str, object]:
    script = r'''
Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;
public class WinApi {
  [StructLayout(LayoutKind.Sequential)]
  public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll", SetLastError=true)] public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);
  [DllImport("user32.dll", SetLastError=true)] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
  [DllImport("user32.dll", SetLastError=true)] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
}
"@
$hwnd = [WinApi]::GetForegroundWindow()
if ($hwnd -eq [IntPtr]::Zero) { return "" }
$sb = New-Object System.Text.StringBuilder 2048
[void][WinApi]::GetWindowText($hwnd, $sb, $sb.Capacity)
$title = $sb.ToString()
[uint32]$pid = 0
[void][WinApi]::GetWindowThreadProcessId($hwnd, [ref]$pid)
$proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
if ($null -eq $proc) { return "" }
$rect = New-Object WinApi+RECT
[void][WinApi]::GetWindowRect($hwnd, [ref]$rect)
$obj = [PSCustomObject]@{
  process = $proc.ProcessName
  title = $title
  left = [int]$rect.Left
  top = [int]$rect.Top
  width = [int]($rect.Right - $rect.Left)
  height = [int]($rect.Bottom - $rect.Top)
}
$obj | ConvertTo-Json -Compress
'''
    proc = run_powershell(script, check=True)
    payload = proc.stdout.strip()
    if not payload:
        raise RuntimeError("Could not read foreground window info on Windows.")
    data = json.loads(payload)
    return {
        "process": str(data.get("process", "")),
        "title": str(data.get("title", "")),
        "left": int(data.get("left", 0)),
        "top": int(data.get("top", 0)),
        "width": int(data.get("width", 0)),
        "height": int(data.get("height", 0)),
    }


def activate_window_windows(title_fragment: str) -> bool:
    script = r'''
param([string]$TitleFragment)
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class WinApi {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);
}
"@
$p = Get-Process | Where-Object { $_.MainWindowTitle -and $_.MainWindowTitle -like ("*" + $TitleFragment + "*") } | Select-Object -First 1
if ($null -eq $p) { return "false" }
[void][WinApi]::ShowWindowAsync($p.MainWindowHandle, 9)
[void][WinApi]::SetForegroundWindow($p.MainWindowHandle)
"true"
'''
    proc = run_powershell(script, title_fragment)
    return proc.returncode == 0 and proc.stdout.strip().lower() == "true"


def find_window_by_title_windows(title_fragment: str) -> bool:
    script = r'''
param([string]$TitleFragment)
$p = Get-Process | Where-Object { $_.MainWindowTitle -and $_.MainWindowTitle -like ("*" + $TitleFragment + "*") } | Select-Object -First 1
if ($null -eq $p) { "false" } else { "true" }
'''
    proc = run_powershell(script, title_fragment)
    return proc.returncode == 0 and proc.stdout.strip().lower() == "true"


def take_screenshot_windows(left: int, top: int, width: int, height: int, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    script = r'''
param([int]$Left, [int]$Top, [int]$Width, [int]$Height, [string]$OutPath)
Add-Type -AssemblyName System.Drawing
$bmp = New-Object System.Drawing.Bitmap($Width, $Height)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($Left, $Top, 0, 0, $bmp.Size)
$bmp.Save($OutPath, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose()
$bmp.Dispose()
'''
    run_powershell(script, str(left), str(top), str(width), str(height), str(output_path), check=True)


def require_linux_tool(tool: str) -> None:
    if not shutil.which(tool):
        raise RuntimeError(f"Required Linux tool '{tool}' is not installed or not in PATH.")


def get_linux_active_window_id() -> str:
    require_linux_tool("xdotool")
    proc = run(["xdotool", "getactivewindow"], check=True)
    win_id = proc.stdout.strip()
    if not win_id:
        raise RuntimeError("Could not determine active window id on Linux.")
    return win_id


def get_window_info_linux(window_id: str) -> dict[str, object]:
    require_linux_tool("xdotool")
    name_proc = run(["xdotool", "getwindowname", window_id], check=True)
    title = name_proc.stdout.strip()

    pid_proc = run(["xdotool", "getwindowpid", window_id], check=True)
    pid = int(pid_proc.stdout.strip())
    proc_name = ""
    comm_path = Path(f"/proc/{pid}/comm")
    if comm_path.exists():
        proc_name = comm_path.read_text(encoding="utf-8").strip()

    geom_proc = run(["xdotool", "getwindowgeometry", "--shell", window_id], check=True)
    geom_values: dict[str, int] = {}
    for line in geom_proc.stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().upper()
        value = value.strip()
        if key in {"X", "Y", "WIDTH", "HEIGHT"}:
            geom_values[key] = int(value)

    if not all(k in geom_values for k in ("X", "Y", "WIDTH", "HEIGHT")):
        raise RuntimeError("Could not parse active window geometry on Linux.")

    return {
        "process": proc_name,
        "title": title,
        "left": geom_values["X"],
        "top": geom_values["Y"],
        "width": geom_values["WIDTH"],
        "height": geom_values["HEIGHT"],
    }


def get_front_window_info_linux() -> dict[str, object]:
    win_id = get_linux_active_window_id()
    return get_window_info_linux(win_id)


def activate_window_linux(title_fragment: str) -> bool:
    require_linux_tool("xdotool")
    proc = run(["xdotool", "search", "--name", "--limit", "1", title_fragment])
    if proc.returncode != 0:
        return False
    win_id = proc.stdout.strip().splitlines()[0].strip() if proc.stdout.strip() else ""
    if not win_id:
        return False
    activate = run(["xdotool", "windowactivate", "--sync", win_id])
    return activate.returncode == 0


def find_window_by_title_linux(title_fragment: str) -> bool:
    require_linux_tool("xdotool")
    proc = run(["xdotool", "search", "--name", "--limit", "1", title_fragment])
    return proc.returncode == 0 and bool(proc.stdout.strip())


def take_screenshot_linux(left: int, top: int, width: int, height: int, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if shutil.which("import"):
        run(
            [
                "import",
                "-silent",
                "-window",
                "root",
                "-crop",
                f"{width}x{height}+{left}+{top}",
                str(output_path),
            ],
            check=True,
        )
        return
    if shutil.which("maim"):
        run(["maim", "-g", f"{width}x{height}+{left}+{top}", str(output_path)], check=True)
        return
    if shutil.which("grim"):
        run(["grim", "-g", f"{left},{top} {width}x{height}", str(output_path)], check=True)
        return
    raise RuntimeError(
        "No supported Linux screenshot tool found. Install one of: import (ImageMagick), maim, grim."
    )


def get_front_window_info_non_macos() -> dict[str, object]:
    system = platform.system()
    if system == "Windows":
        return get_front_window_info_windows()
    if system == "Linux":
        return get_front_window_info_linux()
    raise RuntimeError(f"Unsupported OS for non-macOS capture path: {system}")


def activate_window_non_macos(title_fragment: str) -> bool:
    system = platform.system()
    if system == "Windows":
        return activate_window_windows(title_fragment)
    if system == "Linux":
        return activate_window_linux(title_fragment)
    return False


def find_window_by_title_non_macos(title_fragment: str) -> bool:
    system = platform.system()
    if system == "Windows":
        return find_window_by_title_windows(title_fragment)
    if system == "Linux":
        return find_window_by_title_linux(title_fragment)
    return False


def take_screenshot_non_macos(info: dict[str, object], output_path: Path) -> None:
    left = int(info.get("left", 0))
    top = int(info.get("top", 0))
    width = int(info.get("width", 0))
    height = int(info.get("height", 0))
    if width <= 0 or height <= 0:
        raise RuntimeError(f"Invalid window region {left},{top},{width},{height} for screenshot capture.")
    system = platform.system()
    if system == "Windows":
        take_screenshot_windows(left, top, width, height, output_path)
        return
    if system == "Linux":
        take_screenshot_linux(left, top, width, height, output_path)
        return
    raise RuntimeError(f"Unsupported OS for screenshot: {system}")


def wait_for_window_by_title_non_macos(title_fragment: str, timeout_seconds: int) -> dict[str, object]:
    deadline = time.time() + max(1, timeout_seconds)
    while time.time() < deadline:
        if find_window_by_title_non_macos(title_fragment):
            activate_window_non_macos(title_fragment)
            time.sleep(0.6)
            try:
                info = get_front_window_info_non_macos()
            except Exception:
                time.sleep(0.4)
                continue
            title = str(info.get("title", ""))
            if title_fragment in title:
                return info
        time.sleep(0.6)
    raise RuntimeError(f"Timed out waiting for active window title containing '{title_fragment}'.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture Cortex IDE proof screenshot")
    parser.add_argument("--repo-path", required=True, help="Path to cortex-ide workspace")
    parser.add_argument("--finding-id", required=True, help="Stable finding identifier")
    parser.add_argument("--file", default="", help="Evidence file path")
    parser.add_argument("--line", type=int, default=1, help="Evidence line number")
    parser.add_argument("--app-name", default=os.environ.get("CORTEX_APP_NAME", "Cortex IDE"))
    parser.add_argument(
        "--window-title",
        default=os.environ.get("CORTEX_WINDOW_TITLE", "Cortex IDE"),
        help="Expected title fragment in Cortex window",
    )
    parser.add_argument(
        "--launch-cmd",
        default=os.environ.get("CORTEX_LAUNCH_CMD", ""),
        help="Optional command to start Cortex from source when app bundle is unavailable",
    )
    parser.add_argument(
        "--launch-timeout",
        type=int,
        default=int(os.environ.get("CORTEX_LAUNCH_TIMEOUT", "240")),
        help="Seconds to wait for launched Cortex window",
    )
    parser.add_argument("--output-dir", default="", help="Output proof directory")
    parser.add_argument(
        "--reuse-existing",
        action="store_true",
        help="Reuse existing artifact if present (default is recapture).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    repo_path = Path(args.repo_path).expanduser().resolve()
    evidence_file = Path(args.file).expanduser().resolve() if args.file else None
    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else (repo_path / "proofs")
    )
    output_path = output_dir / f"{args.finding_id}.png"

    if args.reuse_existing and output_path.exists() and output_path.is_file():
        print(str(output_path))
        return 0

    launch_proc: subprocess.Popen[str] | None = None
    launch_log: Path | None = None
    target_process_name = args.app_name
    launch_cmd_candidate = args.launch_cmd.strip() or default_launch_cmd(repo_path)
    require_tauri_dev = os.environ.get("CORTEX_REQUIRE_TAURI_DEV", "").strip() == "1" or is_tauri_dev_cmd(
        launch_cmd_candidate
    )
    strict_process_name = os.environ.get("CORTEX_STRICT_PROCESS_NAME", "").strip()
    if not strict_process_name and require_tauri_dev and platform.system() == "Darwin":
        strict_process_name = "cortex-gui"

    try:
        if platform.system() != "Darwin":
            # Windows/Linux path: strict foreground-window capture with title validation.
            launch_cmd = args.launch_cmd.strip() or default_launch_cmd(repo_path)
            if not find_window_by_title_non_macos(args.window_title):
                if not launch_cmd:
                    raise RuntimeError(
                        f"Could not find a window with title containing '{args.window_title}' and no launch command is configured."
                    )
                launch_proc, launch_log = start_launch_command(repo_path, launch_cmd, output_dir)
            info = wait_for_window_by_title_non_macos(args.window_title, args.launch_timeout)
            title = str(info.get("title", ""))
            if args.window_title and args.window_title not in title:
                raise RuntimeError(
                    f"Front window title '{title}' does not include expected fragment '{args.window_title}'."
                )
            take_screenshot_non_macos(info, output_path)
            print(str(output_path))
            return 0

        try:
            if require_tauri_dev:
                if strict_process_name:
                    if process_exists(strict_process_name):
                        target_process_name = strict_process_name
                    else:
                        if not launch_cmd_candidate:
                            raise RuntimeError("tauri:dev strict mode requested but launch command is empty.")
                        if not is_tauri_dev_cmd(launch_cmd_candidate):
                            raise RuntimeError(
                                f"Strict tauri mode requires a tauri:dev launch command, got: {launch_cmd_candidate}"
                            )
                        launch_proc, launch_log = start_launch_command(repo_path, launch_cmd_candidate, output_dir)
                        target_process_name = wait_for_named_process(strict_process_name, args.launch_timeout)
                else:
                    if find_process_for_window_title(args.window_title):
                        target_process_name = wait_for_target_process(
                            preferred_name=args.app_name,
                            window_title=args.window_title,
                            timeout_seconds=5,
                        )
                    else:
                        if not launch_cmd_candidate:
                            raise RuntimeError("tauri:dev strict mode requested but launch command is empty.")
                        if not is_tauri_dev_cmd(launch_cmd_candidate):
                            raise RuntimeError(
                                f"Strict tauri mode requires a tauri:dev launch command, got: {launch_cmd_candidate}"
                            )
                        launch_proc, launch_log = start_launch_command(repo_path, launch_cmd_candidate, output_dir)
                        target_process_name = wait_for_target_process(
                            preferred_name=args.app_name,
                            window_title=args.window_title,
                            timeout_seconds=args.launch_timeout,
                        )
            else:
                open_workspace(args.app_name, repo_path)
                time.sleep(2.0)
                target_process_name = wait_for_target_process(
                    preferred_name=args.app_name,
                    window_title=args.window_title,
                    timeout_seconds=20,
                )
        except Exception:
            # If app bundle open fails, first try attaching to an already-running target window.
            try:
                if strict_process_name:
                    target_process_name = wait_for_named_process(strict_process_name, 3)
                else:
                    target_process_name = wait_for_target_process(
                        preferred_name=args.app_name,
                        window_title=args.window_title,
                        timeout_seconds=3,
                    )
            except Exception:
                launch_cmd = launch_cmd_candidate
                if not launch_cmd:
                    raise RuntimeError(
                        f"Unable to open app '{args.app_name}' and no launch command is available."
                    )
                if require_tauri_dev and not is_tauri_dev_cmd(launch_cmd):
                    raise RuntimeError(
                        f"Strict tauri mode requires a tauri:dev launch command, got: {launch_cmd}"
                    )
                launch_proc, launch_log = start_launch_command(repo_path, launch_cmd, output_dir)
                if strict_process_name:
                    target_process_name = wait_for_named_process(strict_process_name, args.launch_timeout)
                else:
                    target_process_name = wait_for_target_process(
                        preferred_name=args.app_name,
                        window_title=args.window_title,
                        timeout_seconds=args.launch_timeout,
                    )

        finding_state_ready = best_effort_navigate_finding_state(
            target_process_name,
            args.finding_id.strip(),
        )
        opened_evidence_file = False
        if not finding_state_ready and evidence_file and evidence_file.exists():
            try:
                open_file(target_process_name, evidence_file)
                time.sleep(1.2)
                opened_evidence_file = True
            except Exception:
                # Fallback for source-launched process names that are not resolvable by `open -a`.
                opened_evidence_file = best_effort_open_file_via_quick_open(
                    target_process_name,
                    repo_path,
                    evidence_file,
                )
                if opened_evidence_file:
                    time.sleep(0.9)

        if not finding_state_ready and evidence_file and evidence_file.exists() and not opened_evidence_file:
            raise RuntimeError(
                "Unable to reach finding-specific UI state and unable to open evidence file in Cortex GUI. "
                "Grant Input Monitoring/Accessibility permissions or set CORTEX_ENABLE_UNVERIFIED_UI_NAV=1 "
                "to allow unverified UI navigation capture."
            )

        activate_app(target_process_name)
        time.sleep(0.8)

        # Ensure the target app is truly frontmost before capture.
        frontmost = get_frontmost_app_name()
        if strict_process_name and frontmost != strict_process_name:
            raise RuntimeError(
                f"Frontmost app is '{frontmost}', expected strict process '{strict_process_name}'. "
                "Refusing to capture non-cortex-gui window."
            )
        if frontmost != target_process_name:
            if wait_for_window_title(frontmost, args.window_title, timeout_seconds=5.0):
                target_process_name = frontmost
            else:
                raise RuntimeError(
                    f"Frontmost app is '{frontmost}', expected '{target_process_name}'. "
                    "Refusing to capture non-target GUI."
                )

        # Enforce that the visible target window corresponds to Cortex IDE context.
        front_window_title = get_front_window_title(target_process_name)
        if args.window_title and args.window_title not in front_window_title:
            if not wait_for_window_title(target_process_name, args.window_title, timeout_seconds=5.0):
                front_window_title = get_front_window_title(target_process_name)
                raise RuntimeError(
                    f"Front window title '{front_window_title}' does not include expected fragment '{args.window_title}'."
                )
            front_window_title = get_front_window_title(target_process_name)
        if args.window_title and args.window_title not in front_window_title:
            raise RuntimeError(
                f"Front window title '{front_window_title}' does not include expected fragment '{args.window_title}'."
            )

        if args.line > 1 and opened_evidence_file:
            best_effort_goto_line(target_process_name, args.line)
            time.sleep(0.6)

        region = get_front_window_region(target_process_name)
        take_screenshot_region(region, output_path)
    except Exception as exc:  # noqa: BLE001
        # Keep stdout empty on failure so caller can fall back cleanly.
        if launch_proc is not None:
            terminate_process_group(launch_proc)
        if launch_log is not None and launch_log.exists():
            sys.stderr.write(f"capture failed: {exc}\nlauncher log: {launch_log}\n")
            return 1
        sys.stderr.write(f"capture failed: {exc}\n")
        return 1

    print(str(output_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
