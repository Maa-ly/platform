#!/usr/bin/env python3
"""Terminate stale Cortex dev processes before strict GUI capture.

This avoids stale windows (or dead dev-server tabs) being captured as proof.
"""

from __future__ import annotations

import os
import signal
import time
from pathlib import Path


PATTERNS = (
    "target/debug/cortex-gui",
    "node_modules/.bin/tauri dev",
    "node_modules/.bin/vite",
    "cargo  run --no-default-features --features wasm-extensions,remote-ssh,image-processing",
)


def _read_cmdline(pid: int) -> str:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except Exception:
        return ""
    if not raw:
        return ""
    return raw.replace(b"\x00", b" ").decode("utf-8", errors="ignore").strip()


def _matches_target(cmdline: str) -> bool:
    if not cmdline:
        return False
    return any(pattern in cmdline for pattern in PATTERNS)


def _list_target_pids() -> list[int]:
    me = os.getpid()
    parent = os.getppid()
    pids: list[int] = []
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        pid = int(name)
        if pid in {me, parent}:
            continue
        cmdline = _read_cmdline(pid)
        if _matches_target(cmdline):
            pids.append(pid)
    return pids


def _kill_pids(pids: list[int], sig: int) -> None:
    for pid in pids:
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            pass
        except Exception:
            pass


def main() -> int:
    pids = _list_target_pids()
    if not pids:
        return 0

    _kill_pids(pids, signal.SIGTERM)
    time.sleep(1.2)

    survivors = [pid for pid in pids if Path(f"/proc/{pid}").exists()]
    if survivors:
        _kill_pids(survivors, signal.SIGKILL)
        time.sleep(0.4)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

