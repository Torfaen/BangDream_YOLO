"""Record sampled MuMu screenshots for manual YOLO labeling."""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2

from bangdream_yolo.capture.nemu_ipc import NemuIpc
from bangdream_yolo.config import load_config


def default_output_dir() -> Path:
    """Return a timestamped raw-data session directory."""

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("data") / "raw" / f"session_{timestamp}"


def main() -> int:
    """Capture frames at a fixed interval and save them as PNG files."""

    if os.name == "nt":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Record sampled screenshots through nemu_ipc.")
    parser.add_argument("--seconds", type=float, default=60.0, help="Recording duration.")
    parser.add_argument("--interval", type=float, default=0.1, help="Seconds between saved frames.")
    parser.add_argument("--warmup", type=float, default=1.0, help="Delay before recording starts.")
    parser.add_argument("--output", type=Path, default=None, help="Output directory.")
    args = parser.parse_args()

    if args.seconds <= 0:
        raise SystemExit("--seconds must be > 0")
    if args.interval <= 0:
        raise SystemExit("--interval must be > 0")

    config = load_config()
    output_dir = args.output or default_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)

    print("BangDream YOLO 录制工具")
    print(f"output: {output_dir}")
    print(f"seconds: {args.seconds}")
    print(f"interval: {args.interval}")
    print(f"warmup: {args.warmup}")
    if args.warmup > 0:
        time.sleep(args.warmup)

    saved = 0
    start = time.perf_counter()
    next_save = start
    end_time = start + args.seconds

    with NemuIpc(config.mumu_path, config.instance_id, config.display_id) as ipc:
        while time.perf_counter() < end_time:
            now = time.perf_counter()
            if now < next_save:
                time.sleep(min(0.005, next_save - now))
                continue

            image = ipc.screenshot()
            height, width = image.shape[:2]
            if saved == 0 and (width, height) != (config.screen_width, config.screen_height):
                print(
                    "警告：截图分辨率与配置不同，"
                    f"capture={width}x{height}, config={config.screen_width}x{config.screen_height}"
                )

            saved += 1
            filename = output_dir / f"frame_{saved:06d}.png"
            if not cv2.imwrite(str(filename), image):
                raise RuntimeError(f"保存失败：{filename}")

            next_save += args.interval

    elapsed = time.perf_counter() - start
    fps = saved / elapsed if elapsed > 0 else 0.0
    print("")
    print(f"saved: {saved}")
    print(f"elapsed: {elapsed:.3f}s")
    print(f"saved fps: {fps:.2f}")
    print(f"output: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
