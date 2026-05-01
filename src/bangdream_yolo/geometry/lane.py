"""Map capture-space points to BangDream lanes and touch coordinates."""

from __future__ import annotations

import math

import cv2
import numpy as np

from bangdream_yolo.geometry.calibration import Calibration, Point


def lerp_point(a: Point, b: Point, ratio: float) -> Point:
    """Linearly interpolate between two points."""

    return Point(a.x + (b.x - a.x) * ratio, a.y + (b.y - a.y) * ratio)


def judge_lane_centers(calibration: Calibration) -> list[Point]:
    """Return capture-space lane centers on the judgment line."""

    left = calibration.points["judge_left"]
    right = calibration.points["judge_right"]
    return [
        lerp_point(left, right, (index + 0.5) / calibration.lane_count)
        for index in range(calibration.lane_count)
    ]


def perspective_matrix(calibration: Calibration) -> np.ndarray:
    """Build a perspective transform from track quadrilateral to unit square.

    The output X coordinate is used for lane assignment. Y is kept for future
    ETA/track-space work but is not used by m2 yet.
    """

    points = calibration.points
    source = np.array(
        [
            points["track_top_left"].to_list(),
            points["track_top_right"].to_list(),
            points["judge_right"].to_list(),
            points["judge_left"].to_list(),
        ],
        dtype=np.float32,
    )
    destination = np.array(
        [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
        dtype=np.float32,
    )
    return cv2.getPerspectiveTransform(source, destination)


def normalize_capture_point(calibration: Calibration, point: Point) -> Point:
    """Convert one capture-space point into normalized track coordinates."""

    matrix = perspective_matrix(calibration)
    source = np.array([[[point.x, point.y]]], dtype=np.float32)
    transformed = cv2.perspectiveTransform(source, matrix)[0][0]
    return Point(float(transformed[0]), float(transformed[1]))


def point_to_lane(calibration: Calibration, point: Point) -> int:
    """Map a capture-space point to a clamped lane index 0..lane_count-1."""

    normalized = normalize_capture_point(calibration, point)
    lane = math.floor(normalized.x * calibration.lane_count)
    return max(0, min(calibration.lane_count - 1, lane))


def capture_to_touch(calibration: Calibration, point: Point) -> Point:
    """Convert capture-space coordinates to minitouch coordinates."""

    rotation = calibration.touch_rotation
    if rotation == "none":
        scale_x = calibration.touch_width / calibration.capture_width
        scale_y = calibration.touch_height / calibration.capture_height
        return Point(point.x * scale_x, point.y * scale_y)
    if rotation == "counterclockwise":
        scale_x = calibration.touch_width / calibration.capture_height
        scale_y = calibration.touch_height / calibration.capture_width
        return Point(point.y * scale_x, (calibration.capture_width - point.x) * scale_y)
    if rotation == "clockwise":
        scale_x = calibration.touch_width / calibration.capture_height
        scale_y = calibration.touch_height / calibration.capture_width
        return Point((calibration.capture_height - point.y) * scale_x, point.x * scale_y)
    if rotation == "transpose":
        scale_x = calibration.touch_width / calibration.capture_height
        scale_y = calibration.touch_height / calibration.capture_width
        return Point(point.y * scale_x, point.x * scale_y)
    raise ValueError(f"不支持的 touch_rotation：{rotation}")


def lane_touch_points(calibration: Calibration) -> list[tuple[int, Point, Point]]:
    """Return lane index with capture and touch judgment centers."""

    rows: list[tuple[int, Point, Point]] = []
    for index, capture_point in enumerate(judge_lane_centers(calibration)):
        rows.append((index, capture_point, capture_to_touch(calibration, capture_point)))
    return rows
