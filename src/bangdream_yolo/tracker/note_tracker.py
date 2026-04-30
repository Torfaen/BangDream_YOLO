"""Lightweight lane-bucketed tracker for falling BangDream notes."""

from __future__ import annotations

from bangdream_yolo.detection.postprocess import NoteDetection
from bangdream_yolo.tracker.state import TrackedNote


class NoteTracker:
    """Track notes by lane/type continuity and estimate ETA by linear fit."""

    def __init__(
        self,
        history_size: int = 6,
        max_missed_frames: int = 2,
        max_track_y_distance: float = 0.12,
        min_velocity_y: float = 0.05,
        stale_track_y: float = 1.10,
        min_history_points: int = 3,
    ) -> None:
        self.history_size = history_size
        self.max_missed_frames = max_missed_frames
        self.max_track_y_distance = max_track_y_distance
        self.min_velocity_y = min_velocity_y
        self.stale_track_y = stale_track_y
        self.min_history_points = min_history_points
        self._next_track_id = 1
        self._tracks: list[TrackedNote] = []

    @property
    def tracks(self) -> list[TrackedNote]:
        """Return currently active tracks."""

        return [track for track in self._tracks if track.is_active]

    def update(self, detections: list[NoteDetection], timestamp: float) -> list[TrackedNote]:
        """Associate detections to tracks and return active tracks."""

        matched_track_ids: set[int] = set()

        for detection in self._sort_detections(detections):
            track = self._best_track_for(detection, timestamp, matched_track_ids)
            if track is None:
                track = self._create_track(detection, timestamp)
            else:
                self._update_track(track, detection, timestamp)
            matched_track_ids.add(track.track_id)

        for track in self._tracks:
            if not track.is_active or track.track_id in matched_track_ids:
                continue
            track.missed_frames += 1
            self._update_missed_eta(track, timestamp)
            if track.missed_frames > self.max_missed_frames:
                track.is_active = False

        for track in self._tracks:
            stale_y = self._predicted_track_y(track, timestamp)
            if track.is_active and stale_y > self.stale_track_y:
                track.is_active = False

        self._tracks = [track for track in self._tracks if track.is_active]
        return self.tracks

    def _sort_detections(self, detections: list[NoteDetection]) -> list[NoteDetection]:
        """Process lower notes first so near-judge tracks keep continuity."""

        return sorted(detections, key=lambda detection: (detection.lane, -detection.track_y))

    def _best_track_for(
        self,
        detection: NoteDetection,
        timestamp: float,
        matched_track_ids: set[int],
    ) -> TrackedNote | None:
        best_track: TrackedNote | None = None
        best_distance = self.max_track_y_distance

        for track in self._tracks:
            if not track.is_active or track.track_id in matched_track_ids:
                continue
            if track.lane != detection.lane or track.note_type != detection.note_type:
                continue

            predicted_y = self._predicted_track_y(track, timestamp)
            distance = abs(detection.track_y - predicted_y)
            if distance <= best_distance:
                best_distance = distance
                best_track = track

        return best_track

    def _create_track(self, detection: NoteDetection, timestamp: float) -> TrackedNote:
        track = TrackedNote(
            track_id=self._next_track_id,
            note_type=detection.note_type,
            lane=detection.lane,
            latest=detection,
            history=[(timestamp, detection.track_y)],
        )
        self._next_track_id += 1
        self._tracks.append(track)
        return track

    def _update_track(self, track: TrackedNote, detection: NoteDetection, timestamp: float) -> None:
        track.latest = detection
        track.missed_frames = 0
        track.history.append((timestamp, detection.track_y))
        if len(track.history) > self.history_size:
            del track.history[: len(track.history) - self.history_size]
        self._fit_eta(track, timestamp)

    def _predicted_track_y(self, track: TrackedNote, timestamp: float) -> float:
        last_timestamp, last_y = track.history[-1]
        if track.velocity_y is None:
            return last_y
        return last_y + track.velocity_y * (timestamp - last_timestamp)

    def _update_missed_eta(self, track: TrackedNote, timestamp: float) -> None:
        if track.velocity_y is None:
            return
        predicted_y = self._predicted_track_y(track, timestamp)
        track.eta_seconds = (1.0 - predicted_y) / track.velocity_y

    def _fit_eta(self, track: TrackedNote, timestamp: float) -> None:
        history = track.history[-self.history_size :]
        if len(history) < self.min_history_points:
            track.velocity_y = None
            track.eta_seconds = None
            return

        mean_t = sum(point[0] for point in history) / len(history)
        mean_y = sum(point[1] for point in history) / len(history)
        denominator = sum((point[0] - mean_t) ** 2 for point in history)
        if denominator <= 0:
            track.velocity_y = None
            track.eta_seconds = None
            return

        numerator = sum((point[0] - mean_t) * (point[1] - mean_y) for point in history)
        velocity_y = numerator / denominator
        if velocity_y <= self.min_velocity_y:
            track.velocity_y = None
            track.eta_seconds = None
            return

        fitted_y_now = mean_y + velocity_y * (timestamp - mean_t)
        track.velocity_y = velocity_y
        track.eta_seconds = (1.0 - fitted_y_now) / velocity_y
