"""Benchmark MuMu nemu_ipc screenshot throughput."""

from __future__ import annotations

import argparse
import os
import sys
import time

from bangdream_yolo.capture.nemu_ipc import NemuIpc
from bangdream_yolo.config import load_config


def main() -> int:
    """Capture frames continuously and print basic FPS statistics."""

    if os.name == "nt":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Benchmark nemu_ipc screenshot FPS.")
    parser.add_argument("--frames", type=int, default=300, help="Number of frames to capture.")
    args = parser.parse_args()

    config = load_config()
    frame_times: list[float] = []

    print("nemu_ipc 截图基准")
    print(f"MuMu 路径: {config.mumu_path}")
    print(f"实例: {config.instance_id}, display: {config.display_id}")

    with NemuIpc(config.mumu_path, config.instance_id, config.display_id) as ipc:
        width, height = ipc.get_resolution()
        print(f"分辨率: {width}x{height}")

        start = time.perf_counter()
        for index in range(args.frames):
            frame_start = time.perf_counter()
            image = ipc.screenshot()
            frame_times.append(time.perf_counter() - frame_start)
            if index == 0:
                print(f"首帧 shape: {image.shape}")
        total = time.perf_counter() - start

    fps = args.frames / total if total > 0 else 0.0
    avg_ms = (sum(frame_times) / len(frame_times)) * 1000
    max_ms = max(frame_times) * 1000

    print("")
    print(f"帧数: {args.frames}")
    print(f"总耗时: {total:.3f}s")
    print(f"平均 FPS: {fps:.2f}")
    print(f"平均单帧: {avg_ms:.2f}ms")
    print(f"最慢单帧: {max_ms:.2f}ms")

    if fps < 60:
        print("结果低于 60 fps，后续需要继续定位性能瓶颈。")
        return 1

    print("截图基准通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
