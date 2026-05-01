"""Send a simple touch pattern through minitouch."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from bangdream_yolo.android import AdbError, read_wm_size
from bangdream_yolo.config import load_config
from bangdream_yolo.input.minitouch import MinitouchClient, MinitouchError, resolve_adb_serial


def project_root() -> Path:
    """Return repository root based on this source file location."""

    return Path(__file__).resolve().parents[3]


def main() -> int:
    """Run a visible single- or five-finger down/up test."""

    if os.name == "nt":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    config = load_config()
    parser = argparse.ArgumentParser(description="Test minitouch multi-touch input.")
    parser.add_argument("--hold", type=float, default=0.5, help="Seconds to hold fingers down.")
    parser.add_argument("--single", action="store_true", help="Send only one center touch for smoke testing.")
    args = parser.parse_args()

    try:
        adb_serial = resolve_adb_serial(config.mumu_path, config.adb_serial)
    except MinitouchError as exc:
        print(exc)
        adb_serial = config.adb_serial

    try:
        width, height = read_wm_size(config.mumu_path, adb_serial)
    except AdbError as exc:
        print(exc)
        width, height = config.screen_width, config.screen_height
        print(f"回退使用配置分辨率：{width}x{height}")

    print("minitouch 单点测试" if args.single else "minitouch 5 指测试")
    print(f"ADB serial: {adb_serial}")
    print(f"分辨率（wm size）: {width}x{height}")
    print("请先在 MuMu/Android 开发者选项里打开“显示点按操作反馈”。")

    with MinitouchClient(
        mumu_path=config.mumu_path,
        adb_serial=adb_serial,
        project_root=project_root(),
        port=config.minitouch_port,
        remote_path=config.minitouch_remote_path,
    ) as client:
        print(f"[minitouch] {client.banner.describe()}")
        touch_width = client.banner.max_x if client.banner.max_x is not None else width
        touch_height = client.banner.max_y if client.banner.max_y is not None else height
        ratios = (0.50,) if args.single else (0.22, 0.36, 0.50, 0.64, 0.78)
        y = int(touch_height * 0.72)
        xs = [int(touch_width * ratio) for ratio in ratios]
        print(f"坐标（minitouch）: {[(x, y) for x in xs]}")

        down_builder = client.command_builder()
        for pointer_id, x in enumerate(xs):
            down_builder.down(pointer_id, x, y)
        down_builder.commit()
        client.send_builder(down_builder)

        time.sleep(args.hold)

        up_builder = client.command_builder()
        for pointer_id in range(len(xs)):
            up_builder.up(pointer_id)
        up_builder.commit()
        client.send_builder(up_builder)

    print("minitouch 测试完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
