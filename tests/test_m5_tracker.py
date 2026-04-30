"""Synthetic checks for m5 postprocess and note tracking."""

from __future__ import annotations

import unittest

from bangdream_yolo.detection.postprocess import NoteDetection, postprocess_detections, track_x_to_lane
from bangdream_yolo.geometry.calibration import Calibration, Point
from bangdream_yolo.tracker.note_tracker import NoteTracker


class TensorLike(list):
    """Tiny list wrapper with the tolist method used by YOLO tensors."""

    def tolist(self) -> list[float]:
        return list(self)


class FakeBox:
    """Minimal Ultralytics box stand-in for postprocess tests."""

    def __init__(self, xyxy: list[float], class_id: int, confidence: float) -> None:
        self.xyxy = [TensorLike(xyxy)]
        self.cls = [class_id]
        self.conf = [confidence]


class FakeResult:
    """Minimal Ultralytics result stand-in for postprocess tests."""

    def __init__(self, boxes: list[FakeBox]) -> None:
        self.boxes = boxes


def rectangle_calibration() -> Calibration:
    """Return an identity-like 100x100 track calibration."""

    return Calibration(
        capture_width=100,
        capture_height=100,
        touch_width=100,
        touch_height=100,
        touch_rotation="none",
        points={
            "track_top_left": Point(0, 0),
            "track_top_right": Point(100, 0),
            "judge_right": Point(100, 100),
            "judge_left": Point(0, 100),
        },
        lane_count=7,
    )


def detection(track_y: float, lane: int = 3, note_type: str = "tap") -> NoteDetection:
    """Build a synthetic detection at one normalized Y position."""

    center_x = (lane + 0.5) / 7.0
    return NoteDetection(
        note_type=note_type,
        lane=lane,
        bbox=(center_x * 100 - 3, track_y * 100 - 3, center_x * 100 + 3, track_y * 100 + 3),
        center_x=center_x * 100,
        center_y=track_y * 100,
        track_x=center_x,
        track_y=track_y,
        confidence=0.9,
    )


class PostprocessTests(unittest.TestCase):
    def test_postprocess_maps_class_center_and_lane(self) -> None:
        result = FakeResult([FakeBox([45, 45, 55, 55], class_id=2, confidence=0.8)])

        detections = postprocess_detections(result, rectangle_calibration(), conf_threshold=0.25)

        self.assertEqual(len(detections), 1)
        self.assertEqual(detections[0].note_type, "flick")
        self.assertEqual(detections[0].lane, 3)
        self.assertAlmostEqual(detections[0].track_x, 0.5, places=5)
        self.assertAlmostEqual(detections[0].track_y, 0.5, places=5)

    def test_postprocess_ignores_low_confidence_and_unknown_classes(self) -> None:
        result = FakeResult(
            [
                FakeBox([10, 10, 20, 20], class_id=0, confidence=0.1),
                FakeBox([30, 30, 40, 40], class_id=99, confidence=0.9),
            ]
        )

        detections = postprocess_detections(result, rectangle_calibration(), conf_threshold=0.25)

        self.assertEqual(detections, [])

    def test_track_x_to_lane_clamps_bounds(self) -> None:
        self.assertEqual(track_x_to_lane(-0.1, 7), 0)
        self.assertEqual(track_x_to_lane(0.5, 7), 3)
        self.assertEqual(track_x_to_lane(1.2, 7), 6)


class NoteTrackerTests(unittest.TestCase):
    def test_tracker_keeps_track_id_and_eta_decreases(self) -> None:
        tracker = NoteTracker()

        first = tracker.update([detection(0.50)], timestamp=0.00)[0]
        second = tracker.update([detection(0.55)], timestamp=0.05)[0]
        third = tracker.update([detection(0.60)], timestamp=0.10)[0]
        third_eta = third.eta_seconds
        fourth = tracker.update([detection(0.65)], timestamp=0.15)[0]

        self.assertEqual(first.track_id, second.track_id)
        self.assertEqual(first.track_id, third.track_id)
        self.assertIsNotNone(third.velocity_y)
        self.assertIsNotNone(third_eta)
        self.assertIsNotNone(fourth.eta_seconds)
        self.assertLess(fourth.eta_seconds, third_eta)

    def test_tracker_keeps_short_missed_tracks_alive(self) -> None:
        tracker = NoteTracker(max_missed_frames=2)

        first = tracker.update([detection(0.50)], timestamp=0.00)[0]
        self.assertEqual(tracker.update([], timestamp=0.05)[0].track_id, first.track_id)
        self.assertEqual(tracker.update([], timestamp=0.10)[0].track_id, first.track_id)
        self.assertEqual(tracker.update([], timestamp=0.15), [])


if __name__ == "__main__":
    unittest.main()
