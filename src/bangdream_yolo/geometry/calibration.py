"""Calibration file model for BangDream lane geometry."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


CALIBRATION_VERSION = 1
DEFAULT_CALIBRATION_PATH = Path("data/calibration.yml")
POINT_NAMES = ("judge_left", "judge_right", "track_top_left", "track_top_right")
TOUCH_ROTATIONS = ("none", "clockwise", "counterclockwise", "transpose")


@dataclass(frozen=True)
class Point:
    """2D point in image or touch coordinates."""

    x: float
    y: float

    @classmethod
    def from_list(cls, values: list[float] | tuple[float, float]) -> "Point":
        return cls(float(values[0]), float(values[1]))

    def to_list(self) -> list[float]:
        return [float(self.x), float(self.y)]


@dataclass(frozen=True)
class Calibration:
    """Saved lane geometry calibration."""

    capture_width: int
    capture_height: int
    touch_width: int
    touch_height: int
    touch_rotation: str
    points: dict[str, Point]
    lane_count: int = 7
    version: int = CALIBRATION_VERSION

    def __post_init__(self) -> None:
        missing = [name for name in POINT_NAMES if name not in self.points]
        if missing:
            raise ValueError(f"标定点缺失：{missing}")
        if self.touch_rotation not in TOUCH_ROTATIONS:
            raise ValueError(f"不支持的 touch_rotation：{self.touch_rotation}")

    def to_dict(self) -> dict[str, Any]:
        """Convert calibration to a YAML-friendly dictionary."""

        return {
            "version": self.version,
            "capture": {
                "width": self.capture_width,
                "height": self.capture_height,
            },
            "touch": {
                "width": self.touch_width,
                "height": self.touch_height,
                "rotation": self.touch_rotation,
            },
            "points": {name: self.points[name].to_list() for name in POINT_NAMES},
            "lanes": {"count": self.lane_count},
        }


def load_calibration(path: Path = DEFAULT_CALIBRATION_PATH) -> Calibration:
    """Load a calibration YAML file."""

    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)

    points = {name: Point.from_list(data["points"][name]) for name in POINT_NAMES}
    return Calibration(
        version=int(data.get("version", CALIBRATION_VERSION)),
        capture_width=int(data["capture"]["width"]),
        capture_height=int(data["capture"]["height"]),
        touch_width=int(data["touch"]["width"]),
        touch_height=int(data["touch"]["height"]),
        touch_rotation=str(data["touch"].get("rotation", "counterclockwise")),
        points=points,
        lane_count=int(data.get("lanes", {}).get("count", 7)),
    )


def save_calibration(calibration: Calibration, path: Path = DEFAULT_CALIBRATION_PATH) -> None:
    """Save calibration to YAML, creating parent directories if needed."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        yaml.safe_dump(
            calibration.to_dict(),
            file,
            allow_unicode=True,
            sort_keys=False,
        )


def infer_touch_rotation(
    capture_size: tuple[int, int],
    touch_size: tuple[int, int],
) -> str:
    """Infer a reasonable initial rotation between capture and minitouch sizes."""

    capture_width, capture_height = capture_size
    touch_width, touch_height = touch_size
    if (capture_width, capture_height) == (touch_width, touch_height):
        return "none"
    if (capture_width, capture_height) == (touch_height, touch_width):
        return "clockwise"
    return "none"
