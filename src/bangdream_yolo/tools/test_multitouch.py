"""Send a simple 5-finger touch pattern through minitouch."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from bangdream_yolo.config import load_config
from bangdream_yolo.input.minitouch import MinitouchClient, find_adb_executable


def project_root() -> Path:
    """Return repository root based on this source file location."""

    return Path(__file__).resolve().parents[3]


def read_wm_size(mumu_path: Path, adb_serial: str) -> tuple[int, int]:
    """Read logical screen size from ``adb shell wm size``."""

    adb_path = find_adb_executable(mumu_path)
    if adb_path is None:
        raise RuntimeError("未找到 adb，无法读取 wm size")

    completed = subprocess.run(
        [adb_path, "-s", adb_serial, "shell", "wm", "size"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = (completed.stdout + completed.stderr).strip()
    if completed.returncode != 0:
        raise RuntimeError(f"wm size 失败：{output}")

    # Typical lines: "Physical size: 1920x1080" and maybe "Override size: 1600x900"
    match = None
    for line in output.splitlines():
        if "Override size" in line:
            match = re.search(r"(\d+)\s*x\s*(\d+)", line)
            if match:
                return int(match.group(1)), int(match.group(2))
    for line in output.splitlines():
        if "Physical size" in line:
            match = re.search(r"(\d+)\s*x\s*(\d+)", line)
            if match:
                return int(match.group(1)), int(match.group(2))
    match = re.search(r"(\d+)\s*x\s*(\d+)", output)
    if match:
        return int(match.group(1)), int(match.group(2))
    raise RuntimeError(f"无法解析 wm size 输出：{output}")


def main() -> int:
    """Run a visible 5-finger down/up test near the lower half of the screen."""

    if os.name == "nt":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    config = load_config()
    parser = argparse.ArgumentParser(description="Test minitouch multi-touch input.")
    parser.add_argument("--hold", type=float, default=0.5, help="Seconds to hold fingers down.")
    args = parser.parse_args()

    try:
        width, height = read_wm_size(config.mumu_path, config.adb_serial)
    except RuntimeError as exc:
        print(exc)
        width, height = config.screen_width, config.screen_height
        print(f"回退使用配置分辨率：{width}x{height}")

    y = int(height * 0.72)
    xs = [
        int(width * ratio)
        for ratio in (0.22, 0.36, 0.50, 0.64, 0.78)
    ]

    print("minitouch 5 指测试")
    print(f"ADB serial: {config.adb_serial}")
    print(f"分辨率（wm size）: {width}x{height}")
    print(f"坐标: {[(x, y) for x in xs]}")
    print("请先在 MuMu/Android 开发者选项里打开“显示点按操作反馈”。")

    with MinitouchClient(
        mumu_path=config.mumu_path,
        adb_serial=config.adb_serial,
        project_root=project_root(),
        port=config.minitouch_port,
        remote_path=config.minitouch_remote_path,
    ) as client:
        for pointer_id, x in enumerate(xs):
            client.down(pointer_id, x, y)
        client.commit()

        time.sleep(args.hold)

        for pointer_id in range(len(xs)):
            client.up(pointer_id)
        client.commit()

    print("5 指测试完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
