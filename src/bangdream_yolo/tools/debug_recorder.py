"""Structured debug recording for policy preview sessions."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any

import cv2

from bangdream_yolo.detection.postprocess import NoteDetection
from bangdream_yolo.policy.scheduler import PolicyDebugEvent, PolicyResult, TouchAction
from bangdream_yolo.tracker.state import TrackedNote


SCREENSHOT_MODES = {"event", "all", "none"}


class DebugRecorder:
    """Write per-frame JSONL and optional screenshots for one preview run."""

    def __init__(
        self,
        root_dir: Path,
        screenshot_mode: str = "event",
        screenshot_every: int = 1,
        session_name: str | None = None,
    ) -> None:
        if screenshot_mode not in SCREENSHOT_MODES:
            raise ValueError(f"unknown screenshot mode: {screenshot_mode}")

        self.root_dir = Path(root_dir)
        self.screenshot_mode = screenshot_mode
        self.screenshot_every = max(1, int(screenshot_every))
        self.session_dir = self._create_session_dir(session_name)
        self.raw_dir = self.session_dir / "raw"
        self.overlay_dir = self.session_dir / "overlay"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.overlay_dir.mkdir(parents=True, exist_ok=True)
        self.frames_file = (self.session_dir / "frames.jsonl").open("a", encoding="utf-8")
        self.events_file = (self.session_dir / "events.jsonl").open("a", encoding="utf-8")

    def close(self) -> None:
        """Close JSONL file handles."""

        self.frames_file.close()
        self.events_file.close()

    def write_meta(self, meta: dict[str, Any]) -> None:
        """Write session metadata once."""

        meta_record = {
            **meta,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "screenshot_mode": self.screenshot_mode,
            "screenshot_every": self.screenshot_every,
        }
        self._write_json(self.session_dir / "meta.json", meta_record)

    def record_frame(
        self,
        frame_index: int,
        timestamp: float,
        fps: float,
        touch_enabled: bool,
        detections: list[NoteDetection],
        tracks: list[TrackedNote],
        policy_result: PolicyResult,
        green_holds: list[dict[str, object]],
        raw_frame: Any | None = None,
        overlay_frame: Any | None = None,
        manual_snapshot: bool = False,
    ) -> None:
        """Record one policy preview frame."""

        events = self._frame_events(policy_result, manual_snapshot)
        screenshots = self._maybe_save_screenshots(frame_index, raw_frame, overlay_frame, bool(events), manual_snapshot)
        frame_record = {
            "frame_index": frame_index,
            "timestamp": timestamp,
            "fps": fps,
            "touch_enabled": touch_enabled,
            "detections": [_detection_record(detection) for detection in detections],
            "tracks": [_track_record(track) for track in tracks],
            "actions": [_action_record(action) for action in policy_result.actions],
            "warnings": list(policy_result.warnings),
            "green_holds": green_holds,
            "screenshots": screenshots,
        }
        self._write_jsonl(self.frames_file, frame_record)

        for event in events:
            event_record = {
                **event,
                "frame_index": frame_index,
                "timestamp": timestamp,
                "screenshots": screenshots,
            }
            self._write_jsonl(self.events_file, event_record)

    def _create_session_dir(self, session_name: str | None) -> Path:
        self.root_dir.mkdir(parents=True, exist_ok=True)
        base_name = session_name or f"policy_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        candidate = self.root_dir / base_name
        if not candidate.exists():
            candidate.mkdir()
            return candidate

        for index in range(1, 1000):
            candidate = self.root_dir / f"{base_name}_{index:02d}"
            if not candidate.exists():
                candidate.mkdir()
                return candidate
        raise RuntimeError(f"cannot create unique debug log dir under {self.root_dir}")

    def _frame_events(self, policy_result: PolicyResult, manual_snapshot: bool) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        if policy_result.actions:
            events.append(
                {
                    "kind": "policy_actions",
                    "reason": "action_output",
                    "actions": [_action_record(action) for action in policy_result.actions],
                }
            )
        if policy_result.warnings:
            events.append(
                {
                    "kind": "policy_warnings",
                    "reason": "warning_output",
                    "warnings": list(policy_result.warnings),
                }
            )
        events.extend(_debug_event_record(event) for event in policy_result.debug_events)
        if manual_snapshot:
            events.append({"kind": "manual_snapshot", "reason": "keyboard_s"})
        return events

    def _maybe_save_screenshots(
        self,
        frame_index: int,
        raw_frame: Any | None,
        overlay_frame: Any | None,
        has_events: bool,
        manual_snapshot: bool,
    ) -> dict[str, str]:
        should_save = manual_snapshot
        if self.screenshot_mode == "event":
            should_save = should_save or has_events
        elif self.screenshot_mode == "all":
            should_save = should_save or frame_index % self.screenshot_every == 0

        if not should_save:
            return {}

        screenshots: dict[str, str] = {}
        frame_name = f"frame_{frame_index:06d}.png"
        if raw_frame is not None:
            raw_path = self.raw_dir / frame_name
            _write_image(raw_path, raw_frame)
            screenshots["raw"] = raw_path.relative_to(self.session_dir).as_posix()
        if overlay_frame is not None:
            overlay_path = self.overlay_dir / frame_name
            _write_image(overlay_path, overlay_frame)
            screenshots["overlay"] = overlay_path.relative_to(self.session_dir).as_posix()
        return screenshots

    @staticmethod
    def _write_json(path: Path, record: dict[str, Any]) -> None:
        path.write_text(json.dumps(record, ensure_ascii=False, default=str, indent=2), encoding="utf-8")

    @staticmethod
    def _write_jsonl(handle, record: dict[str, Any]) -> None:
        handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        handle.flush()


def _write_image(path: Path, frame: Any) -> None:
    if not cv2.imwrite(str(path), frame):
        raise RuntimeError(f"failed to write debug screenshot: {path}")


def _detection_record(detection: NoteDetection) -> dict[str, Any]:
    return {
        "type": detection.note_type,
        "confidence": detection.confidence,
        "bbox": list(detection.bbox),
        "center": [detection.center_x, detection.center_y],
        "track_x": detection.track_x,
        "track_y": detection.track_y,
        "lane": detection.lane,
    }


def _track_record(track: TrackedNote) -> dict[str, Any]:
    return {
        "track_id": track.track_id,
        "type": track.note_type,
        "lane": track.lane,
        "track_y": track.latest.track_y,
        "track_x": track.latest.track_x,
        "eta_seconds": track.eta_seconds,
        "velocity_y": track.velocity_y,
        "missed_frames": track.missed_frames,
        "history_len": len(track.history),
        "is_active": track.is_active,
        "confidence": track.latest.confidence,
        "bbox": list(track.latest.bbox),
    }


def _action_record(action: TouchAction) -> dict[str, Any]:
    return {
        "kind": action.kind,
        "pointer_id": action.pointer_id,
        "x": action.x,
        "y": action.y,
        "track_id": action.track_id,
        "note_type": action.note_type,
        "lane": action.lane,
        "pressure": action.pressure,
    }


def _debug_event_record(event: PolicyDebugEvent) -> dict[str, Any]:
    return {
        "kind": event.kind,
        "reason": event.reason,
        "track_id": event.track_id,
        "note_type": event.note_type,
        "lane": event.lane,
        "pointer_id": event.pointer_id,
        "detail": event.detail,
    }
