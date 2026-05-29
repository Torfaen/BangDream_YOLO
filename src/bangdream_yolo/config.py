"""Project configuration defaults and local config file loading."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yml"
DEFAULT_MUMU_PATH = Path(r"C:\Program Files\Netease\MuMu")
DEFAULT_ADB_SERIAL = "emulator-5554"
DEFAULT_MODEL_PATH = Path("models/bangdream_yolo_m4_green_bar.pt")
DEFAULT_CALIBRATION_PATH = Path("data/calibration.yml")


class ConfigError(RuntimeError):
    """Raised when the local YAML config cannot be parsed."""


@dataclass(frozen=True)
class AppConfig:
    """Runtime settings used by environment checks and preview tools.

    Values are loaded from config.yml when present. Environment variables keep
    their old behavior and override the file.
    """

    mumu_path: Path = DEFAULT_MUMU_PATH
    instance_id: int = 0
    display_id: int = 0
    adb_serial: str = DEFAULT_ADB_SERIAL
    screen_width: int = 1280
    screen_height: int = 720
    model_path: Path = DEFAULT_MODEL_PATH
    calibration_path: Path = DEFAULT_CALIBRATION_PATH
    minitouch_port: int | None = None
    minitouch_remote_path: str = "/data/local/tmp/minitouch"
    log_level: str = "INFO"
    mode: str = "policy_preview"
    enable_touch: bool = False
    device: str = "auto"
    conf: float = 0.25
    imgsz: int = 640
    window_width: int = 1280
    window_height: int = 720
    topmost: bool = False
    asset_abi: str | None = None


def project_root() -> Path:
    """Return the repository root."""

    return PROJECT_ROOT


def _load_config_file(path: Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Load config.yml if it exists."""

    if not path.exists():
        return {}

    try:
        import yaml
    except ImportError as exc:
        raise ConfigError("存在 config.yml，但未安装 pyyaml；请先运行 pip install -r requirements.txt") from exc

    with path.open("r", encoding="utf-8") as file:
        loaded = yaml.safe_load(file)

    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ConfigError("config.yml 顶层必须是 YAML 对象")
    return loaded


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name, {})
    return value if isinstance(value, dict) else {}


def _config_value(data: dict[str, Any], key: str, section: str | None = None) -> Any:
    if key in data:
        return data[key]
    if section is not None:
        return _section(data, section).get(key)
    return None


def _env_or_config(data: dict[str, Any], env_name: str, key: str, default: Any, section: str | None = None) -> Any:
    value = os.getenv(env_name)
    if value is not None:
        return value
    config_value = _config_value(data, key, section)
    return default if config_value is None else config_value


def _as_path(value: Any, base_dir: Path = PROJECT_ROOT) -> Path:
    path = Path(str(value)).expanduser()
    if path.is_absolute():
        return path
    return base_dir / path


def _as_optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "y"}:
        return True
    if text in {"0", "false", "no", "off", "n"}:
        return False
    raise ConfigError(f"无法解析布尔值：{value!r}")


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> AppConfig:
    """Load config.yml and environment overrides with project defaults."""

    data = _load_config_file(path)
    return AppConfig(
        mumu_path=_as_path(_env_or_config(data, "BANGDREAM_MUMU_PATH", "mumu_path", DEFAULT_MUMU_PATH)),
        instance_id=int(_env_or_config(data, "BANGDREAM_MUMU_INSTANCE_ID", "instance_id", 0)),
        display_id=int(_env_or_config(data, "BANGDREAM_MUMU_DISPLAY_ID", "display_id", 0)),
        adb_serial=str(_env_or_config(data, "BANGDREAM_ADB_SERIAL", "adb_serial", DEFAULT_ADB_SERIAL)),
        screen_width=int(_env_or_config(data, "BANGDREAM_SCREEN_WIDTH", "screen_width", 1280)),
        screen_height=int(_env_or_config(data, "BANGDREAM_SCREEN_HEIGHT", "screen_height", 720)),
        model_path=_as_path(_env_or_config(data, "BANGDREAM_MODEL_PATH", "model_path", DEFAULT_MODEL_PATH)),
        calibration_path=_as_path(
            _env_or_config(data, "BANGDREAM_CALIBRATION_PATH", "calibration_path", DEFAULT_CALIBRATION_PATH)
        ),
        minitouch_port=_as_optional_int(
            _env_or_config(data, "BANGDREAM_MINITOUCH_PORT", "minitouch_port", None)
        ),
        minitouch_remote_path=str(
            _env_or_config(data, "BANGDREAM_MINITOUCH_REMOTE_PATH", "minitouch_remote_path", "/data/local/tmp/minitouch")
        ),
        log_level=str(_env_or_config(data, "BANGDREAM_LOG_LEVEL", "log_level", "INFO")),
        mode=str(_env_or_config(data, "BANGDREAM_MODE", "mode", "policy_preview", section="launch")),
        enable_touch=_as_bool(
            _env_or_config(data, "BANGDREAM_ENABLE_TOUCH", "enable_touch", False, section="launch")
        ),
        device=str(_env_or_config(data, "BANGDREAM_DEVICE", "device", "auto", section="launch")),
        conf=float(_env_or_config(data, "BANGDREAM_CONF", "conf", 0.25, section="launch")),
        imgsz=int(_env_or_config(data, "BANGDREAM_IMGSZ", "imgsz", 640, section="launch")),
        window_width=int(_env_or_config(data, "BANGDREAM_WINDOW_WIDTH", "window_width", 1280, section="launch")),
        window_height=int(_env_or_config(data, "BANGDREAM_WINDOW_HEIGHT", "window_height", 720, section="launch")),
        topmost=_as_bool(_env_or_config(data, "BANGDREAM_TOPMOST", "topmost", False, section="launch")),
        asset_abi=_as_optional_str(_env_or_config(data, "BANGDREAM_ASSET_ABI", "asset_abi", None, section="assets")),
    )
