"""Launch the configured BangDream YOLO preview tool."""

from __future__ import annotations

import os
import sys

from bangdream_yolo.config import load_config


def main() -> int:
    """Dispatch to the configured preview entrypoint."""

    if os.name == "nt":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    config = load_config()
    mode = config.mode.strip().lower().replace("-", "_")
    if mode in {"policy", "policy_preview"}:
        from bangdream_yolo.tools.policy_preview import main as policy_main

        print("启动模式: policy_preview")
        return policy_main()
    if mode in {"live", "live_preview"}:
        from bangdream_yolo.tools.live_preview import main as live_main

        print("启动模式: live_preview")
        return live_main()

    print(f"不支持的 mode: {config.mode}")
    print("请在 config.yml 中设置 mode: policy_preview 或 mode: live_preview")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
