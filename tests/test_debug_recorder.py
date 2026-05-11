"""Tests for policy preview debug logging."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from bangdream_yolo.detection.postprocess import NoteDetection
from bangdream_yolo.policy.scheduler import PolicyDebugEvent, PolicyResult, TouchAction
from bangdream_yolo.tools.debug_recorder import DebugRecorder
from bangdream_yolo.tracker.state import TrackedNote


def sample_detection() -> NoteDetection:
    """Build one serializable detection for debug recorder tests."""

    return NoteDetection(
        note_type="green_note",
        lane=2,
        bbox=(1.0, 2.0, 11.0, 12.0),
        center_x=6.0,
        center_y=7.0,
        track_x=0.35,
        track_y=0.95,
        confidence=0.9,
    )


def sample_track() -> TrackedNote:
    """Build one serializable track for debug recorder tests."""

    detection = sample_detection()
    return TrackedNote(
        track_id=5,
        note_type=detection.note_type,
        lane=detection.lane,
        latest=detection,
        history=[(1.0, 0.9), (1.1, 0.95)],
        velocity_y=0.5,
        eta_seconds=0.1,
    )


def read_jsonl(path: Path) -> list[dict]:
    """Read a JSONL file into dictionaries."""

    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    return [json.loads(line) for line in text.splitlines()]


class DebugRecorderTests(unittest.TestCase):
    def test_creates_session_structure_and_meta(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            recorder = DebugRecorder(Path(temp_dir), session_name="policy_test")
            try:
                recorder.write_meta({"tool": "policy_preview"})
            finally:
                recorder.close()

            session_dir = Path(temp_dir) / "policy_test"
            self.assertTrue((session_dir / "meta.json").exists())
            self.assertTrue((session_dir / "frames.jsonl").exists())
            self.assertTrue((session_dir / "events.jsonl").exists())
            self.assertTrue((session_dir / "raw").is_dir())
            self.assertTrue((session_dir / "overlay").is_dir())
            self.assertEqual(json.loads((session_dir / "meta.json").read_text(encoding="utf-8"))["tool"], "policy_preview")

    def test_event_mode_skips_screenshots_for_quiet_frame(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            recorder = DebugRecorder(Path(temp_dir), session_name="policy_test", screenshot_mode="event")
            try:
                recorder.record_frame(
                    frame_index=1,
                    timestamp=1.0,
                    fps=60.0,
                    touch_enabled=False,
                    detections=[sample_detection()],
                    tracks=[sample_track()],
                    policy_result=PolicyResult(actions=[], warnings=[]),
                    green_holds=[],
                    raw_frame=np.zeros((4, 4, 3), dtype=np.uint8),
                    overlay_frame=np.zeros((4, 4, 3), dtype=np.uint8),
                )
            finally:
                recorder.close()

            session_dir = Path(temp_dir) / "policy_test"
            frames = read_jsonl(session_dir / "frames.jsonl")
            events = read_jsonl(session_dir / "events.jsonl")
            self.assertEqual(len(frames), 1)
            self.assertEqual(events, [])
            self.assertEqual(frames[0]["screenshots"], {})
            self.assertEqual(list((session_dir / "raw").iterdir()), [])
            self.assertEqual(list((session_dir / "overlay").iterdir()), [])

    def test_event_mode_saves_raw_and_overlay_for_action_frame(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            recorder = DebugRecorder(Path(temp_dir), session_name="policy_test", screenshot_mode="event")
            try:
                recorder.record_frame(
                    frame_index=2,
                    timestamp=1.0,
                    fps=60.0,
                    touch_enabled=True,
                    detections=[sample_detection()],
                    tracks=[sample_track()],
                    policy_result=PolicyResult(
                        actions=[TouchAction(kind="down", pointer_id=0, x=100, y=200, track_id=5, note_type="tap", lane=2)],
                        warnings=[],
                        debug_events=[
                            PolicyDebugEvent(
                                kind="green_note_terminal_ignored",
                                reason="near_visible_unstable_echo",
                                track_id=5,
                                note_type="green_note",
                                lane=2,
                                pointer_id=0,
                            )
                        ],
                    ),
                    green_holds=[{"pointer_id": 0, "owner_track_id": 4}],
                    raw_frame=np.zeros((4, 4, 3), dtype=np.uint8),
                    overlay_frame=np.ones((4, 4, 3), dtype=np.uint8),
                )
            finally:
                recorder.close()

            session_dir = Path(temp_dir) / "policy_test"
            frames = read_jsonl(session_dir / "frames.jsonl")
            events = read_jsonl(session_dir / "events.jsonl")
            self.assertEqual(frames[0]["screenshots"], {"raw": "raw/frame_000002.png", "overlay": "overlay/frame_000002.png"})
            self.assertTrue((session_dir / "raw" / "frame_000002.png").exists())
            self.assertTrue((session_dir / "overlay" / "frame_000002.png").exists())
            self.assertEqual(events[0]["screenshots"], frames[0]["screenshots"])
            self.assertEqual({event["kind"] for event in events}, {"policy_actions", "green_note_terminal_ignored"})

    def test_manual_snapshot_saves_even_when_screenshots_none(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            recorder = DebugRecorder(Path(temp_dir), session_name="policy_test", screenshot_mode="none")
            try:
                recorder.record_frame(
                    frame_index=3,
                    timestamp=1.0,
                    fps=60.0,
                    touch_enabled=False,
                    detections=[],
                    tracks=[],
                    policy_result=PolicyResult(actions=[], warnings=[]),
                    green_holds=[],
                    raw_frame=np.zeros((4, 4, 3), dtype=np.uint8),
                    overlay_frame=np.zeros((4, 4, 3), dtype=np.uint8),
                    manual_snapshot=True,
                )
            finally:
                recorder.close()

            session_dir = Path(temp_dir) / "policy_test"
            events = read_jsonl(session_dir / "events.jsonl")
            self.assertEqual(events[0]["kind"], "manual_snapshot")
            self.assertTrue((session_dir / "raw" / "frame_000003.png").exists())
            self.assertTrue((session_dir / "overlay" / "frame_000003.png").exists())


if __name__ == "__main__":
    unittest.main()
