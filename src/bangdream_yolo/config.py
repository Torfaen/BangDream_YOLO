"""Project configuration defaults for local MuMu Player 12 checks."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_MUMU_PATH = Path(r"C:\Program Files\Netease\MuMu")
DEFAULT_ADB_SERIAL = "127.0.0.1:16384"


@dataclass(frozen=True)
class AppConfig:
    """Runtime settings used by early environment checks.

    Values can be overridden with environment variables so local paths do not
    need to be hardcoded elsewhere.
    """

    mumu_path: Path = DEFAULT_MUMU_PATH
    instance_id: int = 0
    display_id: int = 0
    adb_serial: str = DEFAULT_ADB_SERIAL
    screen_width: int = 1280
    screen_height: int = 720
    minitouch_port: int = 1111
    minitouch_remote_path: str = "/data/local/tmp/minitouch"
    log_level: str = "INFO"


def load_config() -> AppConfig:
    """Load config from environment variables with project defaults."""

    return AppConfig(
        mumu_path=Path(os.getenv("BANGDREAM_MUMU_PATH", str(DEFAULT_MUMU_PATH))),
        instance_id=int(os.getenv("BANGDREAM_MUMU_INSTANCE_ID", "0")),
        display_id=int(os.getenv("BANGDREAM_MUMU_DISPLAY_ID", "0")),
        adb_serial=os.getenv("BANGDREAM_ADB_SERIAL", DEFAULT_ADB_SERIAL),
        screen_width=int(os.getenv("BANGDREAM_SCREEN_WIDTH", "1280")),
        screen_height=int(os.getenv("BANGDREAM_SCREEN_HEIGHT", "720")),
        minitouch_port=int(os.getenv("BANGDREAM_MINITOUCH_PORT", "1111")),
        minitouch_remote_path=os.getenv(
            "BANGDREAM_MINITOUCH_REMOTE_PATH", "/data/local/tmp/minitouch"
        ),
        log_level=os.getenv("BANGDREAM_LOG_LEVEL", "INFO"),
    )
