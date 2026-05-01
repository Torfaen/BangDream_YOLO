"""Check local prerequisites before running capture, training, and input tools."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from bangdream_yolo.config import load_config
from bangdream_yolo.input.minitouch import MinitouchError, resolve_adb_serial


REQUIRED_MODULES = {
    "ultralytics": "ultralytics",
    "cv2": "opencv-python",
    "numpy": "numpy",
    "adbutils": "adbutils",
    "yaml": "pyyaml",
    "loguru": "loguru",
}

NEMU_IPC_DLL_CANDIDATES = (
    Path("shell/sdk/external_renderer_ipc.dll"),
    Path("nx_device/12.0/shell/sdk/external_renderer_ipc.dll"),
)

MUMU_ADB_CANDIDATES = (
    Path("shell/adb.exe"),
    Path("shell/adb/adb.exe"),
    Path("nx_device/12.0/shell/adb.exe"),
    Path("nx_device/12.0/shell/adb/adb.exe"),
)


@dataclass(frozen=True)
class CheckResult:
    """Single environment check result for human-readable reporting."""

    name: str
    ok: bool
    detail: str


def _format_result(result: CheckResult) -> str:
    status = "OK" if result.ok else "FAIL"
    return f"[{status}] {result.name}: {result.detail}"


def _run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def check_python_version() -> CheckResult:
    """Verify the interpreter is new enough for this project."""

    version = sys.version_info
    ok = version >= (3, 11)
    detail = f"{version.major}.{version.minor}.{version.micro}"
    if not ok:
        detail += "，建议使用 Python 3.11 或更新版本"
    return CheckResult("Python 版本", ok, detail)


def check_python_modules() -> list[CheckResult]:
    """Check whether the dependency set can be imported."""

    results: list[CheckResult] = []
    for module_name, package_name in REQUIRED_MODULES.items():
        spec = importlib.util.find_spec(module_name)
        if spec is None:
            results.append(
                CheckResult(
                    f"Python 依赖 {package_name}",
                    False,
                    "缺失；请运行 pip install -r requirements.txt",
                )
            )
        else:
            results.append(CheckResult(f"Python 依赖 {package_name}", True, "可导入"))
    return results


def check_mumu_path(mumu_path: Path) -> CheckResult:
    """Verify the configured MuMu installation root exists."""

    if mumu_path.exists() and mumu_path.is_dir():
        return CheckResult("MuMu 安装根目录", True, str(mumu_path))
    return CheckResult("MuMu 安装根目录", False, f"不存在：{mumu_path}")


def find_nemu_ipc_dll(mumu_path: Path) -> Path | None:
    """Return the first known Nemu IPC DLL path under the MuMu root."""

    for relative_path in NEMU_IPC_DLL_CANDIDATES:
        dll_path = mumu_path / relative_path
        if dll_path.exists():
            return dll_path
    return None


def check_nemu_ipc_dll(mumu_path: Path) -> CheckResult:
    """Verify external_renderer_ipc.dll exists in a supported location."""

    dll_path = find_nemu_ipc_dll(mumu_path)
    if dll_path is not None:
        return CheckResult("external_renderer_ipc.dll", True, str(dll_path))

    candidates = ", ".join(str(mumu_path / path) for path in NEMU_IPC_DLL_CANDIDATES)
    return CheckResult("external_renderer_ipc.dll", False, f"未找到；已检查：{candidates}")


def find_adb_executable(mumu_path: Path) -> str | None:
    """Find adb from PATH first, then from known MuMu install locations."""

    adb_path = shutil.which("adb")
    if adb_path is not None:
        return adb_path

    for relative_path in MUMU_ADB_CANDIDATES:
        candidate = mumu_path / relative_path
        if candidate.exists():
            return str(candidate)
    return None


def check_adb(mumu_path: Path, adb_serial: str) -> list[CheckResult]:
    """Check adb executable and resolve the target MuMu serial."""

    adb_path = find_adb_executable(mumu_path)
    if adb_path is None:
        return [
            CheckResult(
                "ADB 可执行文件",
                False,
                "未在 PATH 中找到 adb；请安装 Android platform-tools 或使用 MuMu 自带 adb",
            )
        ]

    results = [CheckResult("ADB 可执行文件", True, adb_path)]
    completed = _run_command([adb_path, "devices", "-l"])
    output = (completed.stdout + completed.stderr).strip()
    if completed.returncode != 0:
        results.append(CheckResult("ADB 设备列表", False, output or "adb devices 执行失败"))
        return results

    try:
        resolved_serial = resolve_adb_serial(
            mumu_path,
            adb_serial,
            adb_path=adb_path,
            quiet=True,
        )
    except MinitouchError as exc:
        results.append(CheckResult("ADB serial", False, str(exc)))
        return results

    if resolved_serial == adb_serial:
        detail = f"已找到 {adb_serial}"
    else:
        detail = f"配置 {adb_serial} 不在线；自动使用 {resolved_serial}"
    results.append(CheckResult("ADB serial", True, detail))
    return results


def main() -> int:
    """Run all environment checks and return a shell-friendly exit code."""

    if os.name == "nt":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    config = load_config()
    results: list[CheckResult] = [
        check_python_version(),
        check_mumu_path(config.mumu_path),
        check_nemu_ipc_dll(config.mumu_path),
    ]
    results.extend(check_python_modules())
    results.extend(check_adb(config.mumu_path, config.adb_serial))

    print("BangDream YOLO 环境检查")
    print(f"MuMu 路径: {config.mumu_path}")
    print(f"配置 ADB serial: {config.adb_serial}")
    print("")
    for result in results:
        print(_format_result(result))

    failed = [result for result in results if not result.ok]
    if failed:
        print("")
        print(f"环境检查未通过：{len(failed)} 项需要处理")
        return 1

    print("")
    print("环境检查通过，可以进入下一阶段。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
