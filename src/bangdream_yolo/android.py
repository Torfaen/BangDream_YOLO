"""Small ADB helpers shared by Android-facing tools."""

from __future__ import annotations

from dataclasses import dataclass
import re
import shutil
import subprocess
from pathlib import Path


MUMU_ADB_CANDIDATES = (
    Path("shell/adb.exe"),
    Path("shell/adb/adb.exe"),
    Path("nx_device/12.0/shell/adb.exe"),
    Path("nx_device/12.0/shell/adb/adb.exe"),
)


class AdbError(RuntimeError):
    """Raised when ADB is unavailable or returns unexpected output."""


@dataclass(frozen=True)
class AdbDevice:
    """One device row parsed from ``adb devices -l`` output."""

    serial: str
    status: str
    details: str = ""

    @property
    def is_online(self) -> bool:
        """Return True when adb reports the device as usable."""

        return self.status == "device"


def find_adb_executable(mumu_path: Path) -> str | None:
    """Find adb from PATH first, then from known MuMu install locations."""

    adb_path = shutil.which("adb")
    if adb_path is not None:
        return adb_path

    for relative_path in MUMU_ADB_CANDIDATES:
        candidate = Path(mumu_path) / relative_path
        if candidate.exists():
            return str(candidate)
    return None


def parse_adb_devices(output: str) -> list[AdbDevice]:
    """Parse ``adb devices -l`` output into device records."""

    devices: list[AdbDevice] = []
    for line in output.splitlines():
        line = line.strip()
        if not line or line.lower().startswith("list of devices"):
            continue

        parts = line.split()
        if len(parts) < 2:
            continue

        devices.append(
            AdbDevice(
                serial=parts[0],
                status=parts[1],
                details=" ".join(parts[2:]),
            )
        )
    return devices


def list_adb_devices(adb_path: str) -> tuple[list[AdbDevice], str]:
    """Return parsed adb devices plus the raw command output."""

    completed = subprocess.run(
        [adb_path, "devices", "-l"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = (completed.stdout + completed.stderr).strip()
    if completed.returncode != 0:
        raise AdbError(f"adb devices 执行失败：{output}")
    return parse_adb_devices(output), output


def resolve_adb_serial(
    mumu_path: Path,
    preferred_serial: str,
    *,
    adb_path: str | None = None,
    quiet: bool = False,
) -> str:
    """Use preferred serial if online, otherwise choose the only online adb device."""

    resolved_adb_path = adb_path or find_adb_executable(mumu_path)
    if resolved_adb_path is None:
        raise AdbError("未找到 adb；请确认 MuMu 自带 adb 存在或 adb 在 PATH 中")

    devices, raw_output = list_adb_devices(resolved_adb_path)
    online_devices = [device for device in devices if device.is_online]

    for device in online_devices:
        if device.serial == preferred_serial:
            return preferred_serial

    if len(online_devices) == 1:
        resolved_serial = online_devices[0].serial
        if not quiet and resolved_serial != preferred_serial:
            print(f"[adb] configured serial {preferred_serial} is offline; using {resolved_serial}")
        return resolved_serial

    if not online_devices:
        raise AdbError(
            f"ADB 未发现在线设备；配置 serial={preferred_serial}\nadb devices 输出：\n{raw_output}"
        )

    choices = ", ".join(device.serial for device in online_devices)
    raise AdbError(
        "ADB 检测到多个在线设备，无法自动选择；"
        f"请设置 BANGDREAM_ADB_SERIAL。在线设备：{choices}"
    )


def run_adb(mumu_path: Path, adb_serial: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Run adb for the configured or auto-resolved device."""

    adb_path = find_adb_executable(mumu_path)
    if adb_path is None:
        raise AdbError("未找到 adb；请确认 MuMu 自带 adb 存在或 adb 在 PATH 中")

    resolved_serial = resolve_adb_serial(
        mumu_path,
        adb_serial,
        adb_path=adb_path,
        quiet=True,
    )
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
