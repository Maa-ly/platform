#!/usr/bin/env python3
"""Best-effort native GUI screenshot capture for Cortex IDE findings.

Platform support:
- macOS: AppleScript + `screencapture` (includes per-finding UI navigation hooks)
- Windows: PowerShell window APIs + .NET screen capture
- Linux: native X11 backend (`python-xlib` + `mss`) or `xdotool` + screenshot tool (`import`/`maim`/`grim`)

Outputs the generated artifact path on stdout when successful.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Local vendored deps for strict Linux capture in environments without apt tools.
VENDORED_PYDEPS = Path(__file__).resolve().parent / "_pydeps"
if VENDORED_PYDEPS.exists():
    sys.path.insert(0, str(VENDORED_PYDEPS))

try:
    from mss import mss
    from mss.tools import to_png as mss_to_png
except Exception:
    mss = None
    mss_to_png = None

try:
    from Xlib import X as xlib_X
    from Xlib import display as xlib_display
    from Xlib import protocol as xlib_protocol
    from Xlib.error import BadWindow as xlib_BadWindow
except Exception:
    xlib_X = None
    xlib_display = None
    xlib_protocol = None
    xlib_BadWindow = Exception


def run(
    cmd: list[str],
    *,
    check: bool = False,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        proc = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Command timed out: {' '.join(cmd)}") from exc
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


def is_wsl() -> bool:
    if platform.system() != "Linux":
        return False
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    rel = platform.release().lower()
    return "microsoft" in rel or "wsl" in rel


def wsl_powershell_executable() -> str:
    if not is_wsl():
        raise RuntimeError("WSL PowerShell is only available when running inside WSL.")
    for candidate in ("powershell.exe", "pwsh.exe"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    raise RuntimeError("powershell.exe was not found in PATH from WSL.")


def run_wsl_powershell(script: str, *args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    exe = wsl_powershell_executable()
    temp_path = Path()
    try:
        temp_dir_arg: str | None = None
        try:
            # Prefer writing the transient .ps1 into Windows TEMP so powershell.exe
            # can open it via a native drive path instead of WSL UNC.
            temp_probe = run([exe, "-NoProfile", "-NoLogo", "-Command", "$env:TEMP"])
            win_temp_lines = [line.strip() for line in temp_probe.stdout.splitlines() if line.strip()]
            if win_temp_lines:
                win_temp = win_temp_lines[-1]
                wsl_temp = run(["wslpath", "-u", win_temp], check=True).stdout.strip()
                if wsl_temp:
                    temp_dir = Path(wsl_temp)
                    if temp_dir.exists():
                        temp_dir_arg = str(temp_dir)
        except Exception:
            temp_dir_arg = None

        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            suffix=".ps1",
            delete=False,
            dir=temp_dir_arg,
        ) as tmp:
            tmp.write(script)
            temp_path = Path(tmp.name)

        script_arg = str(temp_path)
        try:
            converted = run(["wslpath", "-w", str(temp_path)], check=True).stdout.strip()
            if converted:
                script_arg = converted
        except Exception:
            script_arg = str(temp_path)

        return run(
            [exe, "-NoProfile", "-NoLogo", "-ExecutionPolicy", "Bypass", "-File", script_arg, *args],
            check=check,
        )
    finally:
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass


def to_windows_path(path: Path) -> str:
    if not is_wsl():
        return str(path)
    source = path if path.exists() else path.parent
    proc = run(["wslpath", "-w", str(source)], check=True)
    value = proc.stdout.strip()
    if not value:
        raise RuntimeError(f"Could not convert WSL path to Windows path: {path}")
    if source != path:
        value = value.rstrip("\\/")
        value = f"{value}\\{path.name}"
    return value


def linux_x11_backend_available() -> bool:
    return xlib_display is not None and mss is not None and mss_to_png is not None


def linux_x11_backend_usable() -> bool:
    if not linux_x11_backend_available():
        return False
    try:
        info = get_front_window_info_linux_python()
        return int(info.get("width", 0)) > 0 and int(info.get("height", 0)) > 0
    except Exception:
        return False


def has_linux_tool_backend() -> bool:
    if not shutil.which("xdotool"):
        return False
    return bool(shutil.which("import") or shutil.which("maim") or shutil.which("grim"))


def allow_wsl_host_capture() -> bool:
    return os.environ.get("CORTEX_ALLOW_WSL_HOST_CAPTURE", "").strip() == "1"


def allow_blank_capture() -> bool:
    return os.environ.get("CORTEX_ALLOW_BLANK_CAPTURE", "").strip() == "1"


def strict_full_gui_required() -> bool:
    # Hard requirement: keep full Cortex GUI visible in every generated artifact.
    # Set CORTEX_STRICT_FULL_GUI=0 only for local troubleshooting.
    return os.environ.get("CORTEX_STRICT_FULL_GUI", "1").strip() != "0"


def linux_capture_backend_name() -> str:
    # In WSL, host-window capture is the most reliable strict path for Cortex GUI.
    if is_wsl() and allow_wsl_host_capture():
        return "wsl-host-fallback"
    if has_linux_tool_backend():
        return "linux-tools"
    if linux_x11_backend_usable():
        return "linux-x11-python"
    return ""


FINDING_STATE_OVERRIDES_NON_MACOS: dict[str, dict[str, str]] = {
    "titlebar-menu-missing-run": {
        "figma_layout_mode": "ide",
        "figma_layout_sidebar_collapsed": "false",
        "figma_layout_sidebar_tab": "files",
    },
    "titlebar-menu-missing-git": {
        "figma_layout_mode": "ide",
        "figma_layout_sidebar_collapsed": "false",
        "figma_layout_sidebar_tab": "files",
    },
    "titlebar-menu-missing-developer": {
        "figma_layout_mode": "ide",
        "figma_layout_sidebar_collapsed": "false",
        "figma_layout_sidebar_tab": "files",
    },
    "open-file-label-mismatch-folder-action": {
        "figma_layout_mode": "ide",
        "figma_layout_sidebar_collapsed": "false",
        "figma_layout_sidebar_tab": "files",
    },
    "titlebar-f5-pause-glyph-mismatch": {
        "figma_layout_mode": "ide",
        "figma_layout_sidebar_collapsed": "false",
        "figma_layout_sidebar_tab": "files",
    },
    "activitybar-exposes-unimplemented-dashboard-and-roadmap": {
        "figma_layout_mode": "ide",
        "figma_layout_sidebar_collapsed": "false",
        "figma_layout_sidebar_tab": "files",
    },
    "dashboard-activity-tab-renders-empty-sidebar": {
        "figma_layout_mode": "ide",
        "figma_layout_sidebar_collapsed": "false",
        "figma_layout_sidebar_tab": "files",
    },
    "roadmap-activity-tab-renders-empty-sidebar": {
        "figma_layout_mode": "ide",
        "figma_layout_sidebar_collapsed": "false",
        "figma_layout_sidebar_tab": "files",
    },
    "plugins-marketplace-search-placeholder-mismatch": {
        "figma_layout_mode": "ide",
        "figma_layout_sidebar_collapsed": "false",
        "figma_layout_sidebar_tab": "plugins",
        "cortex_current_project": "",
        "cortex_current_project_main": "",
        "cortex_workspace_state": '{"folders":[],"workspaceFilePath":null,"activeFolder":null,"settings":{}}',
    },
}


def _crop_box_for_finding(finding_id: str, width: int, height: int) -> tuple[int, int, int, int] | None:
    fid = finding_id.strip()
    if fid == "titlebar-menu-missing-run":
        return (
            int(width * 0.36),
            int(height * 0.0),
            int(width * 0.72),
            int(height * 0.13),
        )
    if fid == "titlebar-menu-missing-git":
        return (
            int(width * 0.44),
            int(height * 0.0),
            int(width * 0.82),
            int(height * 0.13),
        )
    if fid == "titlebar-menu-missing-developer":
        return (
            int(width * 0.54),
            int(height * 0.0),
            int(width * 0.95),
            int(height * 0.13),
        )
    if fid == "open-file-label-mismatch-folder-action":
        return (
            int(width * 0.055),
            int(height * 0.0),
            int(width * 0.34),
            int(height * 0.13),
        )
    if fid == "titlebar-f5-pause-glyph-mismatch":
        return (
            int(width * 0.82),
            int(height * 0.0),
            int(width * 0.93),
            int(height * 0.13),
        )
    if fid == "activitybar-exposes-unimplemented-dashboard-and-roadmap":
        return (
            int(width * 0.055),
            int(height * 0.08),
            int(width * 0.13),
            int(height * 0.80),
        )
    if fid == "quickaccess-editor-mru-provider-unreachable":
        return (
            int(width * 0.24),
            int(height * 0.09),
            int(width * 0.78),
            int(height * 0.42),
        )
    return None


def _env_int(name: str, default: int = 0) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(0, value)


def requested_extra_shots() -> int:
    return _env_int("CORTEX_CAPTURE_EXTRA_SHOTS", 0)


def requested_video_seconds() -> int:
    return _env_int("CORTEX_CAPTURE_VIDEO_SECONDS", 0)


def requested_post_action_settle_ms() -> int:
    return _env_int("CORTEX_POST_ACTION_SETTLE_MS", 900)


def require_preclick_capture() -> bool:
    return os.environ.get("CORTEX_REQUIRE_PRECLICK", "1").strip() != "0"


def require_video_artifact() -> bool:
    return os.environ.get("CORTEX_REQUIRE_VIDEO", "").strip() == "1"


def _quoted_for_ffmpeg_concat(path: Path) -> str:
    return str(path).replace("'", "'\\''")


def create_video_artifact_from_images(image_paths: list[Path], output_path: Path, seconds: int) -> bool:
    if seconds <= 0 or not image_paths:
        return False
    if not shutil.which("ffmpeg"):
        return False

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if len(image_paths) == 1:
        cmd = [
            "ffmpeg",
            "-y",
            "-loop",
            "1",
            "-i",
            str(image_paths[0]),
            "-t",
            str(seconds),
            "-vf",
            "fps=24,format=yuv420p",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        proc = run(cmd)
        return proc.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0

    per_slide = max(0.2, float(seconds) / float(len(image_paths)))
    concat_file = Path()
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False) as tmp:
            concat_file = Path(tmp.name)
            for path in image_paths:
                tmp.write(f"file '{_quoted_for_ffmpeg_concat(path)}'\n")
                tmp.write(f"duration {per_slide:.3f}\n")
            # Repeat last frame so concat demuxer applies final duration.
            tmp.write(f"file '{_quoted_for_ffmpeg_concat(image_paths[-1])}'\n")

        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-vsync",
            "vfr",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        proc = run(cmd)
        return proc.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0
    finally:
        if concat_file and concat_file.exists():
            try:
                concat_file.unlink()
            except Exception:
                pass


def should_use_wsl_host_video_capture(capture_info: dict[str, object] | None) -> bool:
    if platform.system() != "Linux" or not is_wsl():
        return False
    if os.environ.get("CORTEX_DISABLE_WSL_HOST_VIDEO", "").strip() == "1":
        return False
    # In WSL, prefer host-side recording whenever host capture is enabled.
    # This preserves visible cursor movement in proof videos.
    if allow_wsl_host_capture():
        return True
    backend = str((capture_info or {}).get("_capture_backend", "")).strip()
    if backend in {"wsl-host", "wsl-host-fallback"}:
        return True
    return os.environ.get("CORTEX_FORCE_WSL_HOST_VIDEO", "").strip() == "1"


def create_video_artifact_wsl_host(
    output_path: Path,
    finding_id: str,
    seconds: int,
    window_title: str,
) -> bool:
    script_path = Path(__file__).resolve().with_name("cortex_wsl_record.sh")
    if not script_path.exists():
        return False

    output_path.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.setdefault("FPS", str(max(5, _env_int("CORTEX_CAPTURE_VIDEO_FPS", 20))))

    normalized_finding_id = finding_id.strip()
    if normalized_finding_id:
        env["FINDING_ID"] = normalized_finding_id

    actions_file = os.environ.get("CORTEX_WSL_VIDEO_ACTIONS_FILE", "").strip()
    if actions_file:
        env["ACTIONS_FILE"] = actions_file
    else:
        default_actions_file = script_path.with_name("cortex_wsl_video_actions.json")
        if default_actions_file.exists():
            env.setdefault("ACTIONS_FILE", str(default_actions_file))

    cmd = [
        "bash",
        str(script_path),
        window_title or "Cortex IDE",
        str(max(1, seconds)),
        str(output_path),
    ]
    if normalized_finding_id:
        cmd.append(normalized_finding_id)
    proc = subprocess.run(cmd, text=True, capture_output=True, env=env)
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip()
        if detail:
            sys.stderr.write(f"wsl-host video capture failed: {detail}\n")
        return False
    return output_path.exists() and output_path.stat().st_size > 0


def _actions_profile_path() -> Path:
    configured = os.environ.get("CORTEX_WSL_VIDEO_ACTIONS_FILE", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().with_name("cortex_wsl_video_actions.json")


def _load_actions_payload() -> dict[str, object]:
    profile_path = _actions_profile_path()
    if not profile_path.exists():
        return {}
    try:
        payload = json.loads(profile_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def has_explicit_finding_actions_profile(finding_id: str) -> bool:
    payload = _load_actions_payload()
    value = payload.get(finding_id)
    return isinstance(value, list) and len(value) > 0


def require_finding_actions_replay() -> bool:
    return os.environ.get("CORTEX_REQUIRE_FINDING_ACTIONS", "1").strip() != "0"


def require_action_click() -> bool:
    # Enforce at least one click action in replay profiles so bug proof
    # demonstrates a real GUI interaction.
    return os.environ.get("CORTEX_REQUIRE_ACTION_CLICK", "1").strip() != "0"


def ensure_clickable_actions(actions: list[dict[str, object]]) -> list[dict[str, object]]:
    if not actions or not require_action_click():
        return actions
    has_click = any(bool(action.get("click", False)) for action in actions)
    if has_click:
        return actions

    # Preserve sequence while forcing one deterministic interaction click.
    updated: list[dict[str, object]] = [dict(action) for action in actions]
    idx = min(len(updated) - 1, max(0, len(updated) // 2))
    updated[idx]["click"] = True
    updated[idx].setdefault("button", "left")
    return updated


def load_finding_actions_profile(finding_id: str) -> list[dict[str, object]]:
    payload = _load_actions_payload()
    selected = payload.get(finding_id)
    if selected is None:
        selected = payload.get("_default")
    if not isinstance(selected, list):
        return []

    actions: list[dict[str, object]] = []
    for item in selected:
        if isinstance(item, dict):
            actions.append(item)
    return ensure_clickable_actions(actions)


def _xdotool_button(button: str) -> str:
    value = button.strip().lower()
    if value == "right":
        return "3"
    if value == "middle":
        return "2"
    return "1"


def run_finding_actions_linux_xdotool(
    actions: list[dict[str, object]],
    capture_info: dict[str, object] | None,
    window_title: str,
) -> bool:
    if not actions or not shutil.which("xdotool"):
        return False

    # Keep actions anchored to the Cortex window geometry used for capture.
    left = int((capture_info or {}).get("left", 0))
    top = int((capture_info or {}).get("top", 0))
    width = int((capture_info or {}).get("width", 0))
    height = int((capture_info or {}).get("height", 0))
    if width <= 0 or height <= 0:
        return False

    try:
        for action in actions:
            delay_ms = int(action.get("delayMs", 0) or 0)
            if delay_ms > 0:
                time.sleep(float(delay_ms) / 1000.0)

            x_ratio = float(action.get("xRatio", 0.5) or 0.5)
            y_ratio = float(action.get("yRatio", 0.5) or 0.5)
            x = int(round(left + (width * x_ratio)))
            y = int(round(top + (height * y_ratio)))
            run(["xdotool", "mousemove", "--sync", str(x), str(y)], timeout=2.0)

            if bool(action.get("click", False)):
                button = _xdotool_button(str(action.get("button", "left")))
                run(["xdotool", "click", button], timeout=2.0)

            hotkey = str(action.get("hotkey", "") or "").strip()
            if hotkey:
                run(["xdotool", "key", "--clearmodifiers", hotkey], timeout=2.0)

            send_keys = str(action.get("sendKeys", "") or "").strip()
            if send_keys:
                run(["xdotool", "key", "--clearmodifiers", send_keys], timeout=2.0)

            text = str(action.get("text", "") or "")
            if text:
                run(["xdotool", "type", "--delay", "1", text], timeout=2.0)

            if bool(action.get("pressEnter", False)):
                run(["xdotool", "key", "Return"], timeout=2.0)
    except Exception:
        return False
    return True


def _resolve_replay_file_query(repo_path: Path, evidence_file: Path | None) -> str:
    if evidence_file and evidence_file.exists():
        try:
            return evidence_file.resolve().relative_to(repo_path.resolve()).as_posix()
        except Exception:
            return evidence_file.name

    fallback_candidates = [
        repo_path / "src/context/CommandContext.tsx",
        repo_path / "src/context/QuickAccessContext.tsx",
        repo_path / "README.md",
        repo_path / "package.json",
    ]
    for candidate in fallback_candidates:
        if candidate.exists():
            try:
                return candidate.resolve().relative_to(repo_path.resolve()).as_posix()
            except Exception:
                return candidate.name
    return "README.md"


def _workspace_bootstrap_actions(repo_path: Path, evidence_file: Path | None) -> list[dict[str, object]]:
    query = _resolve_replay_file_query(repo_path, evidence_file)
    return [
        {"delayMs": 240, "xRatio": 0.52, "yRatio": 0.40, "click": True, "button": "left"},
        {"delayMs": 260, "hotkey": "ctrl+p"},
        {"delayMs": 200, "hotkey": "ctrl+a"},
        {"delayMs": 120, "sendKeys": "{BACKSPACE}"},
        {"delayMs": 180, "text": query},
        {"delayMs": 240, "pressEnter": True},
        {"delayMs": 650, "xRatio": 0.08, "yRatio": 0.16, "click": True, "button": "left"},
    ]


def run_finding_actions_wsl_host(
    finding_id: str,
    window_title: str,
    repo_path: Path,
    evidence_file: Path | None,
) -> bool:
    script_path = Path(__file__).resolve().with_name("cortex_wsl_record.sh")
    if not script_path.exists():
        return False

    finding_actions = load_finding_actions_profile(finding_id.strip())
    if not finding_actions:
        return False
    replay_actions = _workspace_bootstrap_actions(repo_path, evidence_file) + finding_actions
    replay_actions = ensure_clickable_actions(replay_actions)

    with tempfile.TemporaryDirectory(prefix="cortex-actions-") as temp_dir:
        temp_mp4 = Path(temp_dir) / "actions-only.mp4"
        env = os.environ.copy()
        env["ACTIONS_ONLY"] = "1"
        env["FINDING_ID"] = finding_id.strip()
        env["ACTIONS_JSON"] = json.dumps(replay_actions, ensure_ascii=True, separators=(",", ":"))
        env.setdefault("FPS", str(max(5, _env_int("CORTEX_CAPTURE_VIDEO_FPS", 12))))

        cmd = [
            "bash",
            str(script_path),
            window_title or "Cortex IDE",
            "1",
            str(temp_mp4),
            finding_id.strip(),
        ]
        proc = subprocess.run(cmd, text=True, capture_output=True, env=env)
        if proc.returncode != 0:
            detail = proc.stderr.strip() or proc.stdout.strip()
            if detail:
                sys.stderr.write(f"wsl-host action replay failed: {detail}\n")
            return False
    return True


def perform_finding_actions_non_macos(
    finding_id: str,
    window_title: str,
    capture_info: dict[str, object] | None,
    repo_path: Path,
    evidence_file: Path | None,
) -> bool:
    actions = load_finding_actions_profile(finding_id.strip())
    if not actions or platform.system() != "Linux":
        return False

    if is_wsl() and allow_wsl_host_capture():
        return run_finding_actions_wsl_host(finding_id, window_title, repo_path, evidence_file)
    backend = str((capture_info or {}).get("_capture_backend", "")).strip()
    if backend in {"wsl-host", "wsl-host-fallback"} and is_wsl():
        return run_finding_actions_wsl_host(finding_id, window_title, repo_path, evidence_file)

    return run_finding_actions_linux_xdotool(actions, capture_info, window_title)


def create_focus_artifact_for_finding(output_path: Path, finding_id: str) -> Path | None:
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return None

    try:
        with Image.open(output_path) as img:
            width, height = img.size
            box = _crop_box_for_finding(finding_id, width, height)
            if not box:
                return None
            left, top, right, bottom = box
            left = max(0, min(left, width - 1))
            top = max(0, min(top, height - 1))
            right = max(left + 1, min(right, width))
            bottom = max(top + 1, min(bottom, height))

            # Keep the full Cortex GUI visible and add only a ring marker.
            # No blur, redaction, or interior crop is applied.
            marked = img.convert("RGBA")
            draw = ImageDraw.Draw(marked, "RGBA")
            pad_x = max(8, int((right - left) * 0.10))
            pad_y = max(8, int((bottom - top) * 0.20))
            ring = (
                int(max(6, left - pad_x)),
                int(max(6, top - pad_y)),
                int(min(width - 7, right + pad_x)),
                int(min(height - 7, bottom + pad_y)),
            )
            draw.ellipse(ring, outline=(255, 80, 80, 255), width=7)
            inset = (
                min(ring[0] + 3, ring[2]),
                min(ring[1] + 3, ring[3]),
                max(ring[0], ring[2] - 3),
                max(ring[1], ring[3] - 3),
            )
            draw.ellipse(inset, outline=(255, 255, 255, 235), width=2)
            focus_path = output_path.with_name(f"{output_path.stem}.focus{output_path.suffix}")
            marked.convert("RGB").save(focus_path)
            return focus_path
    except Exception:
        return None


def assert_same_image_dimensions(reference_path: Path, candidate_path: Path) -> None:
    if not strict_full_gui_required():
        return
    try:
        from PIL import Image
    except Exception:
        return

    with Image.open(reference_path) as reference:
        with Image.open(candidate_path) as candidate:
            if reference.size != candidate.size:
                raise RuntimeError(
                    "Strict full-GUI capture failed: generated artifact changed frame size "
                    f"from {reference.size[0]}x{reference.size[1]} to {candidate.size[0]}x{candidate.size[1]} "
                    f"({candidate_path.name})."
                )


def collect_multi_artifacts(
    primary_path: Path,
    capture_once,
    finding_id: str,
    *,
    window_title: str = "Cortex IDE",
    capture_info: dict[str, object] | None = None,
) -> list[Path]:
    artifacts: list[Path] = []

    capture_once(primary_path)
    validate_captured_image_strict(primary_path)
    artifacts.append(primary_path)

    focus_path = create_focus_artifact_for_finding(primary_path, finding_id)
    if focus_path and focus_path.exists():
        validate_captured_image_strict(focus_path)
        assert_same_image_dimensions(primary_path, focus_path)
        artifacts.append(focus_path)

    extra_count = requested_extra_shots()
    if has_explicit_finding_actions_profile(finding_id):
        extra_count = max(1, extra_count)
    delay = max(0.1, float(_env_int("CORTEX_CAPTURE_EXTRA_SHOT_DELAY_MS", 450)) / 1000.0)
    for idx in range(extra_count):
        step_path = primary_path.with_name(f"{primary_path.stem}.step{idx + 2}{primary_path.suffix}")
        time.sleep(delay)
        capture_once(step_path)
        validate_captured_image_strict(step_path)
        assert_same_image_dimensions(primary_path, step_path)
        artifacts.append(step_path)

    video_seconds = requested_video_seconds()
    if video_seconds > 0:
        video_path = primary_path.with_name(f"{primary_path.stem}.mp4")
        video_created = False
        if should_use_wsl_host_video_capture(capture_info):
            video_created = create_video_artifact_wsl_host(
                video_path,
                finding_id=finding_id,
                seconds=video_seconds,
                window_title=window_title,
            )

        if not video_created:
            image_paths = [p for p in artifacts if p.suffix.lower() in {".png", ".jpg", ".jpeg"}]
            video_created = create_video_artifact_from_images(image_paths, video_path, video_seconds)

        if video_created:
            artifacts.append(video_path)
            cursor_video = video_path.with_name(f"{video_path.stem}.cursor.mp4")
            if cursor_video.exists() and cursor_video.stat().st_size > 0:
                artifacts.append(cursor_video)
            gif_preview = video_path.with_name(f"{video_path.stem}.preview.gif")
            if gif_preview.exists() and gif_preview.stat().st_size > 0:
                artifacts.append(gif_preview)
        elif require_video_artifact():
            raise RuntimeError(
                "Video evidence was requested but could not be generated. "
                "Install ffmpeg or unset CORTEX_REQUIRE_VIDEO."
            )

    return artifacts


def _localstorage_db_candidates_linux() -> list[Path]:
    home = Path.home()
    roots = [
        home / ".local/share/com.cortexlm.cortex-ide/localstorage",
        home / ".local/share/Cortex/localstorage",
        home / ".local/share/Cortex-desktop/localstorage",
    ]
    out: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for candidate in sorted(root.glob("*.localstorage")):
            if candidate.is_file():
                out.append(candidate)
    return out


def _encode_localstorage_value(value: str) -> bytes:
    # WebKitGTK localStorage values are UTF-16LE blobs in ItemTable.
    return value.encode("utf-16le")


def _apply_localstorage_overrides_linux(overrides: dict[str, str]) -> bool:
    candidates = _localstorage_db_candidates_linux()
    if not candidates:
        return False

    updated = False
    for db_path in candidates:
        try:
            with sqlite3.connect(str(db_path), timeout=5) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                for key, value in overrides.items():
                    conn.execute(
                        """
                        INSERT INTO ItemTable(key, value)
                        VALUES (?, ?)
                        ON CONFLICT(key) DO UPDATE SET value = excluded.value
                        """,
                        (key, _encode_localstorage_value(str(value))),
                    )
                conn.commit()
                updated = True
        except Exception:
            continue
    return updated


def prepare_finding_state_non_macos(finding_id: str) -> bool:
    finding = finding_id.strip()
    overrides = FINDING_STATE_OVERRIDES_NON_MACOS.get(finding)
    if not overrides:
        return False
    if platform.system() != "Linux":
        return False
    return _apply_localstorage_overrides_linux(overrides)


def require_workspace_open_for_proof() -> bool:
    # Keep a real project folder open in Cortex so capture validators see
    # authenticated workspace context in every proof artifact.
    return os.environ.get("CORTEX_REQUIRE_OPEN_WORKSPACE", "1").strip() != "0"


def _workspace_state_overrides(repo_path: Path, *, preserve_layout: bool = False) -> dict[str, str]:
    folder_path = str(repo_path.resolve())
    folder_name = repo_path.name or "workspace"
    workspace_state = {
        "folders": [{"path": folder_path, "name": folder_name}],
        "workspaceFilePath": None,
        "activeFolder": folder_path,
        "settings": {},
    }
    encoded_state = json.dumps(workspace_state, ensure_ascii=True, separators=(",", ":"))
    overrides: dict[str, str] = {
        "projectPath": folder_path,
        "cortex_current_project": folder_path,
        "cortex_current_project_main": folder_path,
        "cortex_workspace_state": encoded_state,
        "cortex_workspace_state_main": encoded_state,
    }
    if not preserve_layout:
        overrides.update(
            {
                "figma_layout_mode": "ide",
                "figma_layout_sidebar_collapsed": "false",
                "figma_layout_sidebar_tab": "files",
            }
        )
    return overrides


def prepare_workspace_state_non_macos(repo_path: Path, *, preserve_layout: bool = False) -> bool:
    if platform.system() != "Linux" or not require_workspace_open_for_proof():
        return False
    return _apply_localstorage_overrides_linux(
        _workspace_state_overrides(repo_path, preserve_layout=preserve_layout)
    )


def _kill_pids(pids: list[int]) -> bool:
    killed = False
    self_pid = os.getpid()
    for pid in pids:
        if pid <= 1 or pid == self_pid:
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            killed = True
        except Exception:
            continue
    return killed


def restart_cortex_for_state_non_macos(strict_process_name: str = "") -> bool:
    if platform.system() != "Linux":
        return False

    names: list[str] = []
    for item in [strict_process_name.strip(), "cortex-gui"]:
        if item and item not in names:
            names.append(item)

    killed = False
    for name in names:
        proc = run(["pgrep", "-x", name])
        if proc.returncode != 0:
            continue
        pids: list[int] = []
        for line in proc.stdout.splitlines():
            raw = line.strip()
            if not raw:
                continue
            try:
                pids.append(int(raw))
            except ValueError:
                continue
        if _kill_pids(pids):
            killed = True

    # Fallback for process trees where the command name is not exactly cortex-gui.
    if not killed:
        proc = run(["pgrep", "-f", "target/debug/cortex-gui"])
        if proc.returncode == 0:
            pids: list[int] = []
            for line in proc.stdout.splitlines():
                raw = line.strip()
                if not raw:
                    continue
                try:
                    pids.append(int(raw))
                except ValueError:
                    continue
            if _kill_pids(pids):
                killed = True

    if killed:
        time.sleep(1.0)
    return killed


def _x11_open_display():
    if xlib_display is None:
        raise RuntimeError("python-xlib is not available.")
    try:
        return xlib_display.Display()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Unable to open X11 display '{os.environ.get('DISPLAY', '')}': {exc}") from exc


def _x11_atom(disp, name: str) -> int:
    return int(disp.intern_atom(name, only_if_exists=False))


def _x11_window_title(disp, window) -> str:
    # Prefer UTF-8 EWMH title when available.
    try:
        net_wm_name = _x11_atom(disp, "_NET_WM_NAME")
        utf8 = _x11_atom(disp, "UTF8_STRING")
        prop = window.get_full_property(net_wm_name, utf8)
        if prop and prop.value is not None:
            raw = bytes(prop.value)
            text = raw.decode("utf-8", errors="replace").strip("\x00").strip()
            if text:
                return text
    except Exception:
        pass
    try:
        title = window.get_wm_name()
        if isinstance(title, str):
            return title
    except Exception:
        pass
    return ""


def _x11_window_pid(disp, window) -> int:
    try:
        pid_atom = _x11_atom(disp, "_NET_WM_PID")
        prop = window.get_full_property(pid_atom, xlib_X.AnyPropertyType)
        if prop and getattr(prop, "value", None) is not None and len(prop.value) > 0:
            return int(prop.value[0])
    except Exception:
        pass
    return 0


def _x11_window_info(disp, window) -> dict[str, object]:
    try:
        geom = window.get_geometry()
        root = disp.screen().root
        coords = window.translate_coords(root, 0, 0)
    except xlib_BadWindow as exc:
        raise RuntimeError(f"X11 window no longer exists: {exc}") from exc
    title = _x11_window_title(disp, window)
    pid = _x11_window_pid(disp, window)
    process = ""
    if pid > 0:
        comm = Path(f"/proc/{pid}/comm")
        if comm.exists():
            try:
                process = comm.read_text(encoding="utf-8").strip()
            except Exception:
                process = ""
    return {
        "process": process,
        "title": title,
        "left": int(coords.x),
        "top": int(coords.y),
        "width": int(geom.width),
        "height": int(geom.height),
        "pid": int(pid) if pid > 0 else 0,
    }


def _x11_active_window(disp):
    root = disp.screen().root
    atom = _x11_atom(disp, "_NET_ACTIVE_WINDOW")
    prop = root.get_full_property(atom, xlib_X.AnyPropertyType)
    if (not prop) or (getattr(prop, "value", None) is None) or (len(prop.value) == 0):
        raise RuntimeError("Could not determine active X11 window.")
    win_id = int(prop.value[0])
    if win_id <= 0:
        raise RuntimeError("Active X11 window id is invalid.")
    return disp.create_resource_object("window", win_id)


def _x11_find_window_by_title(disp, title_fragment: str):
    fragment = title_fragment.casefold()
    root = disp.screen().root
    try:
        candidates = list(root.query_tree().children)
    except Exception:
        candidates = []
    # Iterate from top-most likely window first.
    for window in reversed(candidates):
        title = _x11_window_title(disp, window)
        if title and fragment in title.casefold():
            return window
    return None


def get_front_window_info_linux_python() -> dict[str, object]:
    disp = _x11_open_display()
    try:
        win = _x11_active_window(disp)
        return _x11_window_info(disp, win)
    finally:
        try:
            disp.close()
        except Exception:
            pass


def activate_window_linux_python(title_fragment: str) -> bool:
    disp = _x11_open_display()
    try:
        target = _x11_find_window_by_title(disp, title_fragment)
        if target is None:
            return False
        root = disp.screen().root
        active_atom = _x11_atom(disp, "_NET_ACTIVE_WINDOW")
        event = xlib_protocol.event.ClientMessage(
            window=target,
            client_type=active_atom,
            data=(32, [1, xlib_X.CurrentTime, 0, 0, 0]),
        )
        root.send_event(
            event,
            event_mask=xlib_X.SubstructureRedirectMask | xlib_X.SubstructureNotifyMask,
        )
        try:
            target.set_input_focus(xlib_X.RevertToPointerRoot, xlib_X.CurrentTime)
        except Exception:
            pass
        disp.flush()
        return True
    except Exception:
        return False
    finally:
        try:
            disp.close()
        except Exception:
            pass


def find_window_by_title_linux_python(title_fragment: str) -> bool:
    disp = _x11_open_display()
    try:
        return _x11_find_window_by_title(disp, title_fragment) is not None
    finally:
        try:
            disp.close()
        except Exception:
            pass


def take_screenshot_linux_python(left: int, top: int, width: int, height: int, output_path: Path) -> None:
    if mss is None or mss_to_png is None:
        raise RuntimeError("Python screenshot backend is unavailable (missing mss).")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    monitor = {
        "left": int(left),
        "top": int(top),
        "width": int(width),
        "height": int(height),
    }
    with mss() as sct:
        shot = sct.grab(monitor)
        mss_to_png(shot.rgb, shot.size, output=str(output_path))


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
    if proc.poll() is not None:
        return
    try:
        pgid = os.getpgid(proc.pid)
    except Exception:
        pgid = None

    if pgid is None:
        try:
            proc.terminate()
        except Exception:
            return
        try:
            proc.wait(timeout=2.0)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        return

    try:
        os.killpg(pgid, signal.SIGTERM)
    except Exception:
        pass

    deadline = time.time() + 2.0
    while time.time() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.1)

    try:
        os.killpg(pgid, signal.SIGKILL)
    except Exception:
        pass


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
[uint32]$procId = 0
[void][WinApi]::GetWindowThreadProcessId($hwnd, [ref]$procId)
$proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
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
    payload = ""
    for line in reversed(proc.stdout.splitlines()):
        candidate = line.strip()
        if candidate.startswith("{") and candidate.endswith("}"):
            payload = candidate
            break
    if not payload:
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
Add-Type -AssemblyName System.Windows.Forms
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


def get_front_window_info_wsl() -> dict[str, object]:
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
[uint32]$procId = 0
[void][WinApi]::GetWindowThreadProcessId($hwnd, [ref]$procId)
$proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
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
    proc = run_wsl_powershell(script, check=True)
    payload = ""
    for line in reversed(proc.stdout.splitlines()):
        candidate = line.strip()
        if candidate.startswith("{") and candidate.endswith("}"):
            payload = candidate
            break
    if not payload:
        payload = proc.stdout.strip()
    if not payload:
        raise RuntimeError("Could not read foreground window info via WSL PowerShell.")
    data = json.loads(payload)
    return {
        "process": str(data.get("process", "")),
        "title": str(data.get("title", "")),
        "left": int(data.get("left", 0)),
        "top": int(data.get("top", 0)),
        "width": int(data.get("width", 0)),
        "height": int(data.get("height", 0)),
    }


def activate_window_wsl(title_fragment: str) -> bool:
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
$p = Get-Process | Where-Object {
  $_.MainWindowHandle -ne 0 -and $_.MainWindowTitle -and $_.MainWindowTitle -like ("*" + $TitleFragment + "*")
} | Select-Object -First 1
if ($null -eq $p) {
  $p = Get-Process | Where-Object { $_.MainWindowHandle -ne 0 -and $_.ProcessName -eq "mstsc" } | Sort-Object StartTime -Descending | Select-Object -First 1
}
if ($null -eq $p) { return "false" }
[void][WinApi]::ShowWindowAsync($p.MainWindowHandle, 9)
[void][WinApi]::SetForegroundWindow($p.MainWindowHandle)
"true"
'''
    proc = run_wsl_powershell(script, title_fragment)
    return proc.returncode == 0 and proc.stdout.strip().lower() == "true"


def find_window_by_title_wsl(title_fragment: str) -> bool:
    script = r'''
param([string]$TitleFragment)
$p = Get-Process | Where-Object {
  $_.MainWindowHandle -ne 0 -and $_.MainWindowTitle -and $_.MainWindowTitle -like ("*" + $TitleFragment + "*")
} | Select-Object -First 1
if ($null -eq $p) {
  $p = Get-Process | Where-Object { $_.MainWindowHandle -ne 0 -and $_.ProcessName -eq "mstsc" } | Sort-Object StartTime -Descending | Select-Object -First 1
}
if ($null -eq $p) { "false" } else { "true" }
'''
    proc = run_wsl_powershell(script, title_fragment)
    return proc.returncode == 0 and proc.stdout.strip().lower() == "true"


def get_window_info_by_title_wsl(title_fragment: str) -> dict[str, object]:
    script = r'''
param([string]$TitleFragment)
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class WinApi {
  [StructLayout(LayoutKind.Sequential)]
  public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
  [DllImport("user32.dll", SetLastError=true)] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
}
"@
$p = Get-Process | Where-Object { $_.MainWindowTitle -and $_.MainWindowTitle -like ("*" + $TitleFragment + "*") } | Select-Object -First 1
if ($null -eq $p) {
  $p = Get-Process | Where-Object { $_.MainWindowHandle -ne 0 -and $_.ProcessName -eq "mstsc" } | Sort-Object StartTime -Descending | Select-Object -First 1
}
if ($null -eq $p) { return "" }
if ($p.MainWindowHandle -eq [IntPtr]::Zero) { return "" }
$rect = New-Object WinApi+RECT
if (-not [WinApi]::GetWindowRect($p.MainWindowHandle, [ref]$rect)) { return "" }
$width = [int]($rect.Right - $rect.Left)
$height = [int]($rect.Bottom - $rect.Top)
if ($p.ProcessName -eq "mstsc" -and ($width -lt 800 -or $height -lt 500)) {
  $bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
  $rect.Left = [int]$bounds.Left
  $rect.Top = [int]$bounds.Top
  $rect.Right = [int]$bounds.Right
  $rect.Bottom = [int]$bounds.Bottom
}
$title = $p.MainWindowTitle
if ([string]::IsNullOrWhiteSpace($title) -and $p.ProcessName -eq "mstsc") {
  $title = "Cortex IDE (Ubuntu)"
}
$obj = [PSCustomObject]@{
  process = $p.ProcessName
  title = $title
  left = [int]$rect.Left
  top = [int]$rect.Top
  width = [int]($rect.Right - $rect.Left)
  height = [int]($rect.Bottom - $rect.Top)
}
$obj | ConvertTo-Json -Compress
'''
    proc = run_wsl_powershell(script, title_fragment, check=True)
    payload = ""
    for line in reversed(proc.stdout.splitlines()):
        candidate = line.strip()
        if candidate.startswith("{") and candidate.endswith("}"):
            payload = candidate
            break
    if not payload:
        payload = proc.stdout.strip()
    if not payload:
        raise RuntimeError(f"Could not resolve WSL host window info for title fragment '{title_fragment}'.")
    data = json.loads(payload)
    return {
        "process": str(data.get("process", "")),
        "title": str(data.get("title", "")),
        "left": int(data.get("left", 0)),
        "top": int(data.get("top", 0)),
        "width": int(data.get("width", 0)),
        "height": int(data.get("height", 0)),
    }


def take_screenshot_wsl(left: int, top: int, width: int, height: int, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    windows_out = to_windows_path(output_path)
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
    run_wsl_powershell(
        script,
        str(left),
        str(top),
        str(width),
        str(height),
        windows_out,
        check=True,
    )
    if not output_path.exists():
        raise RuntimeError(f"WSL screenshot capture did not produce file: {output_path}")


def require_linux_tool(tool: str) -> None:
    if not shutil.which(tool):
        raise RuntimeError(f"Required Linux tool '{tool}' is not installed or not in PATH.")


def get_linux_active_window_id() -> str:
    require_linux_tool("xdotool")
    proc = run(["xdotool", "getactivewindow"], check=True, timeout=3.0)
    win_id = proc.stdout.strip()
    if not win_id:
        raise RuntimeError("Could not determine active window id on Linux.")
    return win_id


def get_window_info_linux(window_id: str) -> dict[str, object]:
    require_linux_tool("xdotool")
    name_proc = run(["xdotool", "getwindowname", window_id], check=True, timeout=3.0)
    title = name_proc.stdout.strip()

    pid_proc = run(["xdotool", "getwindowpid", window_id], check=True, timeout=3.0)
    pid = int(pid_proc.stdout.strip())
    proc_name = ""
    comm_path = Path(f"/proc/{pid}/comm")
    if comm_path.exists():
        proc_name = comm_path.read_text(encoding="utf-8").strip()

    geom_proc = run(["xdotool", "getwindowgeometry", "--shell", window_id], check=True, timeout=3.0)
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
    if has_linux_tool_backend():
        win_id = get_linux_active_window_id()
        return get_window_info_linux(win_id)
    if linux_x11_backend_available():
        return get_front_window_info_linux_python()
    raise RuntimeError(
        "No strict Linux window backend available. Install xdotool+import/maim/grim, "
        "or vendor python deps (mss + python-xlib)."
    )


def activate_window_linux(title_fragment: str) -> bool:
    if has_linux_tool_backend():
        require_linux_tool("xdotool")
        proc = run(["xdotool", "search", "--name", "--limit", "1", title_fragment], timeout=3.0)
        if proc.returncode != 0:
            return False
        win_id = proc.stdout.strip().splitlines()[0].strip() if proc.stdout.strip() else ""
        if not win_id:
            return False
        activate = run(["xdotool", "windowactivate", "--sync", win_id], timeout=3.0)
        return activate.returncode == 0
    if linux_x11_backend_available():
        return activate_window_linux_python(title_fragment)
    return False


def find_window_by_title_linux(title_fragment: str) -> bool:
    if has_linux_tool_backend():
        require_linux_tool("xdotool")
        proc = run(["xdotool", "search", "--name", "--limit", "1", title_fragment], timeout=3.0)
        return proc.returncode == 0 and bool(proc.stdout.strip())
    if linux_x11_backend_available():
        return find_window_by_title_linux_python(title_fragment)
    return False


def take_screenshot_linux(left: int, top: int, width: int, height: int, output_path: Path) -> None:
    if linux_x11_backend_available():
        take_screenshot_linux_python(left, top, width, height, output_path)
        return
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
        "No strict Linux screenshot backend available. Install one of: import/maim/grim, "
        "or vendor python deps (mss + python-xlib)."
    )


def get_front_window_info_non_macos() -> dict[str, object]:
    system = platform.system()
    if system == "Windows":
        return get_front_window_info_windows()
    if system == "Linux":
        backend = linux_capture_backend_name()
        if backend in {"linux-tools", "linux-x11-python"}:
            return get_front_window_info_linux()
        if backend == "wsl-host-fallback":
            return get_front_window_info_wsl()
        raise RuntimeError(
            "Strict Cortex capture on Linux requires a native Linux window backend. "
            "Install xdotool+import/maim/grim or ensure vendored python deps are available. "
            "Set CORTEX_ALLOW_WSL_HOST_CAPTURE=1 only for non-strict troubleshooting."
        )
    raise RuntimeError(f"Unsupported OS for non-macOS capture path: {system}")


def activate_window_non_macos(title_fragment: str) -> bool:
    system = platform.system()
    if system == "Windows":
        return activate_window_windows(title_fragment)
    if system == "Linux":
        backend = linux_capture_backend_name()
        if backend in {"linux-tools", "linux-x11-python"}:
            return activate_window_linux(title_fragment)
        if backend == "wsl-host-fallback":
            return activate_window_wsl(title_fragment)
        return False
    return False


def find_window_by_title_non_macos(title_fragment: str) -> bool:
    system = platform.system()
    if system == "Windows":
        return find_window_by_title_windows(title_fragment)
    if system == "Linux":
        backend = linux_capture_backend_name()
        if backend in {"linux-tools", "linux-x11-python"}:
            return find_window_by_title_linux(title_fragment)
        if backend == "wsl-host-fallback":
            return find_window_by_title_wsl(title_fragment)
        raise RuntimeError(
            "Strict Cortex capture is enabled but no native Linux window backend is available. "
            "Install xdotool+import/maim/grim or run with CORTEX_ALLOW_WSL_HOST_CAPTURE=1 for non-strict fallback."
        )
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
        forced_backend = str(info.get("_capture_backend", "")).strip()
        if forced_backend == "wsl-host":
            take_screenshot_wsl(left, top, width, height, output_path)
            return
        if forced_backend == "linux-native":
            take_screenshot_linux(left, top, width, height, output_path)
            return
        backend = linux_capture_backend_name()
        if backend in {"linux-tools", "linux-x11-python"}:
            take_screenshot_linux(left, top, width, height, output_path)
            return
        if backend == "wsl-host-fallback":
            take_screenshot_wsl(left, top, width, height, output_path)
            return
        raise RuntimeError(
            "Strict Cortex capture on Linux requires a native Linux screenshot backend. "
            "Set CORTEX_ALLOW_WSL_HOST_CAPTURE=1 only for non-strict troubleshooting."
        )
    raise RuntimeError(f"Unsupported OS for screenshot: {system}")


def best_effort_open_file_via_quick_open_linux(repo_path: Path, file_path: Path) -> bool:
    if not shutil.which("xdotool"):
        return False
    try:
        rel = file_path.resolve().relative_to(repo_path.resolve()).as_posix()
    except ValueError:
        rel = file_path.name
    try:
        run(["xdotool", "key", "--clearmodifiers", "ctrl+p"], check=True)
        time.sleep(0.25)
        run(["xdotool", "key", "--clearmodifiers", "ctrl+a"])
        run(["xdotool", "key", "BackSpace"])
        run(["xdotool", "type", "--delay", "1", rel], check=True)
        time.sleep(0.1)
        run(["xdotool", "key", "Return"], check=True)
        time.sleep(0.8)
        return True
    except Exception:
        return False


def best_effort_goto_line_linux(line: int) -> bool:
    if line <= 1 or not shutil.which("xdotool"):
        return False
    # Try common "Go to line" shortcuts used by code editors.
    for shortcut in ("ctrl+g", "ctrl+l"):
        try:
            run(["xdotool", "key", "--clearmodifiers", shortcut], check=True)
            time.sleep(0.15)
            run(["xdotool", "key", "--clearmodifiers", "ctrl+a"])
            run(["xdotool", "key", "BackSpace"])
            run(["xdotool", "type", "--delay", "1", str(int(line))], check=True)
            run(["xdotool", "key", "Return"], check=True)
            time.sleep(0.35)
            return True
        except Exception:
            continue
    return False


def best_effort_open_file_via_quick_open_non_macos(repo_path: Path, file_path: Path) -> bool:
    system = platform.system()
    if system == "Linux":
        return best_effort_open_file_via_quick_open_linux(repo_path, file_path)
    return False


def best_effort_goto_line_non_macos(line: int) -> bool:
    system = platform.system()
    if system == "Linux":
        return best_effort_goto_line_linux(line)
    return False


def validate_captured_image_strict(output_path: Path) -> None:
    if allow_blank_capture():
        return
    try:
        from PIL import Image, ImageStat
    except Exception:
        # If Pillow is unavailable, keep behavior backward-compatible.
        return

    if not output_path.exists() or output_path.stat().st_size <= 0:
        raise RuntimeError(f"Capture output is missing or empty: {output_path}")

    with Image.open(output_path) as img_raw:
        img = img_raw.convert("RGB")
        width, height = img.size
        if width < 80 or height < 60:
            raise RuntimeError(f"Captured image is unexpectedly small: {width}x{height}")

        # Sample down for stable heuristics across DPI/scaling.
        sample_w = min(240, width)
        sample_h = min(240, height)
        sample = img.resize((sample_w, sample_h))
        colors = sample.getcolors(maxcolors=sample_w * sample_h)
        if not colors:
            return
        total = sample_w * sample_h
        dominant = max(count for count, _ in colors) / float(total)
        unique = len(colors)
        variance = sum(ImageStat.Stat(sample).var)

        # Reject near-flat captures that are usually bad/blank screenshots.
        if (unique <= 6 and dominant >= 0.97) or variance < 12.0:
            raise RuntimeError(
                "Captured image appears blank or near-uniform. "
                "Strict mode refuses to submit non-informative GUI proof. "
                "Set CORTEX_ALLOW_BLANK_CAPTURE=1 only when blank screen is the intended bug proof."
            )


def wait_for_window_by_title_non_macos(title_fragment: str, timeout_seconds: int) -> dict[str, object]:
    if platform.system() == "Linux" and is_wsl():
        prefer_host = allow_wsl_host_capture()
        deadline = time.time() + max(1, timeout_seconds)
        while time.time() < deadline:
            if prefer_host:
                host_found = False
                try:
                    host_found = find_window_by_title_wsl(title_fragment)
                except Exception:
                    host_found = False
                if host_found:
                    try:
                        activate_window_wsl(title_fragment)
                        time.sleep(0.6)
                        info = get_front_window_info_wsl()
                        title = str(info.get("title", ""))
                        width = int(info.get("width", 0) or 0)
                        height = int(info.get("height", 0) or 0)
                        if title_fragment in title and width > 50 and height > 50:
                            info["_capture_backend"] = "wsl-host"
                            return info
                    except Exception:
                        pass
                    try:
                        info = get_window_info_by_title_wsl(title_fragment)
                        title = str(info.get("title", ""))
                        if title_fragment in title:
                            info["_capture_backend"] = "wsl-host"
                            return info
                    except Exception:
                        pass

            native_found = False
            try:
                native_found = find_window_by_title_linux(title_fragment)
            except Exception:
                native_found = False
            if native_found:
                try:
                    activate_window_linux(title_fragment)
                    time.sleep(0.6)
                    info = get_front_window_info_linux()
                    title = str(info.get("title", ""))
                    if title_fragment in title:
                        info["_capture_backend"] = "linux-native"
                        return info
                except Exception:
                    pass

            if not prefer_host:
                host_found = False
                try:
                    host_found = find_window_by_title_wsl(title_fragment)
                except Exception:
                    host_found = False
                if host_found:
                    try:
                        activate_window_wsl(title_fragment)
                        time.sleep(0.6)
                        info = get_front_window_info_wsl()
                        title = str(info.get("title", ""))
                        width = int(info.get("width", 0) or 0)
                        height = int(info.get("height", 0) or 0)
                        if title_fragment in title and width > 50 and height > 50:
                            info["_capture_backend"] = "wsl-host"
                            return info
                    except Exception:
                        pass
                    try:
                        info = get_window_info_by_title_wsl(title_fragment)
                        title = str(info.get("title", ""))
                        if title_fragment in title:
                            info["_capture_backend"] = "wsl-host"
                            return info
                    except Exception:
                        pass
            time.sleep(0.6)
        raise RuntimeError(f"Timed out waiting for active window title containing '{title_fragment}'.")

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
    artifacts: list[Path] = []

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
            has_state_override = args.finding_id.strip() in FINDING_STATE_OVERRIDES_NON_MACOS
            finding_state_prepared = False
            use_wsl_host_mode = is_wsl() and allow_wsl_host_capture()
            if has_state_override and os.environ.get("CORTEX_RESTART_FOR_STATE", "").strip() == "1":
                restart_cortex_for_state_non_macos(strict_process_name)
            if has_state_override:
                # Re-apply overrides after restart to avoid app shutdown hooks
                # writing stale state over the requested finding-specific state.
                finding_state_prepared = prepare_finding_state_non_macos(args.finding_id)
            prepare_workspace_state_non_macos(
                repo_path,
                preserve_layout=finding_state_prepared,
            )

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

            # For strict per-finding proof on non-macOS, attempt to open the evidence file
            # in Cortex before capture so each screenshot reflects the targeted bug context.
            if (not finding_state_prepared) and evidence_file and evidence_file.exists() and (not use_wsl_host_mode):
                opened = best_effort_open_file_via_quick_open_non_macos(repo_path, evidence_file)
                if not opened:
                    raise RuntimeError(
                        "Unable to open evidence file in Cortex GUI on non-macOS strict capture path."
                    )
                if args.line > 1:
                    best_effort_goto_line_non_macos(args.line)

            finding_id = args.finding_id.strip()
            artifacts: list[Path] = []

            # Interactive findings always capture a pre-action frame so issue bodies
            # can show strict before/after GUI proof.
            capture_preclick = require_preclick_capture() and has_explicit_finding_actions_profile(finding_id)
            if capture_preclick:
                if finding_id in {
                    "dashboard-activity-tab-renders-empty-sidebar",
                    "roadmap-activity-tab-renders-empty-sidebar",
                }:
                    delay_ms = _env_int("CORTEX_PRECLICK_DELAY_MS", 1200)
                    time.sleep(max(0.2, float(delay_ms) / 1000.0))
                preclick_path = output_path.with_name(f"{output_path.stem}.preclick{output_path.suffix}")
                take_screenshot_non_macos(info, preclick_path)
                validate_captured_image_strict(preclick_path)
                artifacts.append(preclick_path)

            # Reproduce finding-specific GUI behavior before proof capture.
            actions_ok = perform_finding_actions_non_macos(
                finding_id,
                args.window_title,
                info,
                repo_path,
                evidence_file,
            )
            if (
                require_finding_actions_replay()
                and has_explicit_finding_actions_profile(finding_id)
                and not actions_ok
            ):
                raise RuntimeError(
                    f"Unable to replay finding-specific GUI actions for '{finding_id}'."
                )
            settle_ms = requested_post_action_settle_ms()
            time.sleep(max(0.35, float(settle_ms) / 1000.0))

            artifacts.extend(
                collect_multi_artifacts(
                output_path,
                lambda p: take_screenshot_non_macos(info, p),
                args.finding_id,
                window_title=args.window_title,
                capture_info=info,
                )
            )
            if launch_proc is not None:
                terminate_process_group(launch_proc)
            for artifact in artifacts:
                print(str(artifact))
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
        artifacts = collect_multi_artifacts(
            output_path,
            lambda p: take_screenshot_region(region, p),
            args.finding_id,
            window_title=args.window_title,
        )
    except Exception as exc:  # noqa: BLE001
        # Keep stdout empty on failure so caller can fall back cleanly.
        if launch_proc is not None:
            terminate_process_group(launch_proc)
        if launch_log is not None and launch_log.exists():
            sys.stderr.write(f"capture failed: {exc}\nlauncher log: {launch_log}\n")
            return 1
        sys.stderr.write(f"capture failed: {exc}\n")
        return 1

    if launch_proc is not None:
        terminate_process_group(launch_proc)
    for artifact in artifacts:
        print(str(artifact))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
