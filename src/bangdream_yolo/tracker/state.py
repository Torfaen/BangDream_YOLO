"""Data structures shared by note tracking and policy stages."""

from __future__ import annotations

from dataclasses import dataclass, field

from bangdream_yolo.detection.postprocess import NoteDetection


@dataclass
class TrackedNote:
    """A note detection associated across frames with ETA state."""

    track_id: int
    note_type: str
    lane: int
    latest: NoteDetection
    history: list[tuple[float, float]] = field(default_factory=list)
    missed_frames: int = 0
    velocity_y: float | None = None
    eta_seconds: float | None = None
    is_active: bool = True

