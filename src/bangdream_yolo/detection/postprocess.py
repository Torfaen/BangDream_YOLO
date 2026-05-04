"""Convert YOLO boxes into lane-aware note detections."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from bangdream_yolo.geometry.calibration import Calibration, Point
from bangdream_yolo.geometry.lane import normalize_capture_point


CLASS_NAMES = {
    0: "tap",
    1: "skill",
    2: "flick",
    3: "green_note",
    4: "green_bar",
}


@dataclass(frozen=True)
class NoteDetection:
    """One YOLO note box mapped into capture, track, and lane coordinates."""

    note_type: str
    lane: int
    bbox: tuple[float, float, float, float]
    center_x: float
    center_y: float
    track_x: float
    track_y: float
    confidence: float


def track_x_to_lane(track_x: float, lane_count: int) -> int:
    """Map normalized track X to a clamped lane index."""

    lane = math.floor(track_x * lane_count)
    return max(0, min(lane_count - 1, lane))


def _first_scalar(value: Any) -> Any:
    """Extract a scalar from tensor/list-like Ultralytics fields."""

    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, (list, tuple)):
        return _first_scalar(value[0])
    return value


def _xyxy_tuple(value: Any) -> tuple[float, float, float, float]:
    """Extract x1, y1, x2, y2 from a tensor/list-like YOLO xyxy field."""

    if hasattr(value, "tolist"):
        value = value.tolist()
    if value and isinstance(value[0], (list, tuple)):
        value = value[0]
    x1, y1, x2, y2 = value
    return float(x1), float(y1), float(x2), float(y2)


def postprocess_detections(
    result: Any,
    calibration: Calibration,
    conf_threshold: float = 0.25,
) -> list[NoteDetection]:
    """Convert one Ultralytics result into project note detections."""

    detections: list[NoteDetection] = []
    boxes = getattr(result, "boxes", None)
    if boxes is None:
        return detections

    for box in boxes:
        class_id = int(_first_scalar(box.cls))
        note_type = CLASS_NAMES.get(class_id)
        if note_type is None:
            continue

        confidence = float(_first_scalar(box.conf))
        if confidence < conf_threshold:
            continue

        bbox = _xyxy_tuple(box.xyxy)
        x1, y1, x2, y2 = bbox
        center_x = (x1 + x2) / 2.0
        center_y = (y1 + y2) / 2.0
        track_point = normalize_capture_point(calibration, Point(center_x, center_y))
        lane = track_x_to_lane(track_point.x, calibration.lane_count)
        detections.append(
            NoteDetection(
                note_type=note_type,
                lane=lane,
                bbox=bbox,
                center_x=center_x,
                center_y=center_y,
                track_x=track_point.x,
                track_y=track_point.y,
                confidence=confidence,
            )
        )

    return detections
