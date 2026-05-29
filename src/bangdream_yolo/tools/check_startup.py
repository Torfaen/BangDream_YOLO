"""Validate configured startup files before opening preview windows."""

from __future__ import annotations

import os
import sys

from bangdream_yolo.config import load_config


def main() -> int:
    """Check files that the configured startup mode needs."""

    if os.name == "nt":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    config = load_config()
    failed = False
    mode = config.mode.strip().lower().replace("-", "_")

    print("BangDream YOLO 启动配置")
    print(f"mode: {config.mode}")
    print(f"model_path: {config.model_path}")
    print(f"calibration_path: {config.calibration_path}")
    print(f"enable_touch: {config.enable_touch}")
    print("")

    if not config.model_path.exists():
        print(f"[FAIL] 模型不存在：{config.model_path}")
        failed = True
    else:
        print(f"[OK] 模型：{config.model_path}")

    if mode in {"policy", "policy_preview"}:
        if not config.calibration_path.exists():
            print(f"[FAIL] 标定文件不存在：{config.calibration_path}")
            print("请先运行：python -m bangdream_yolo.tools.calibrate")
            failed = True
        else:
            print(f"[OK] 标定：{config.calibration_path}")
    elif mode not in {"live", "live_preview"}:
        print(f"[FAIL] 不支持的 mode：{config.mode}")
        print("请设置 mode: policy_preview 或 mode: live_preview")
        failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
