"""Small ADB helpers shared by tools."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from bangdream_yolo.input.minitouch import MinitouchError, find_adb_executable, resolve_adb_serial


class AdbError(RuntimeError):
    """Raised when ADB is unavailable or returns unexpected output."""


def run_adb(mumu_path: Path, adb_serial: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Run adb for the configured or auto-resolved device."""

    adb_path = find_adb_executable(mumu_path)
    if adb_path is None:
        raise AdbError("未找到 adb；请确认 MuMu 自带 adb 存在或 adb 在 PATH 中")

    try:
        resolved_serial = resolve_adb_serial(
            mumu_path,
            adb_serial,
            adb_path=adb_path,
            quiet=True,
        )
    except MinitouchError as exc:
        raise AdbError(str(exc)) from exc

    completed = subprocess.run(
        [adb_path, "-s", resolved_serial, *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        output = (completed.stdout + completed.stderr).strip()
        raise AdbError(f"adb 命令失败：{output}")
    return completed


def read_wm_size(mumu_path: Path, adb_serial: str) -> tuple[int, int]:
    """Read logical screen size from ``adb shell wm size``."""

    completed = run_adb(mumu_path, adb_serial, "shell", "wm", "size")
    output = (completed.stdout + completed.stderr).strip()

    for label in ("Override size", "Physical size"):
        for line in output.splitlines():
            if label in line:
                match = re.search(r"(\d+)\s*x\s*(\d+)", line)
                if match:
                    return int(match.group(1)), int(match.group(2))

    match = re.search(r"(\d+)\s*x\s*(\d+)", output)
    if match:
        return int(match.group(1)), int(match.group(2))
    raise AdbError(f"无法解析 wm size 输出：{output}")
