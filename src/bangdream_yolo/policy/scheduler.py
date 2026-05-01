"""Convert tracked notes into dry-run or minitouch-ready actions."""

from __future__ import annotations

from dataclasses import dataclass

from bangdream_yolo.geometry.calibration import Calibration
from bangdream_yolo.geometry.lane import lane_touch_points
from bangdream_yolo.input.pointer_pool import PointerPool, PointerSlot
from bangdream_yolo.policy.flick import flick_end_point
from bangdream_yolo.tracker.state import TrackedNote


@dataclass(frozen=True)
class SchedulerConfig:
    """Tunable m6 policy defaults."""

    latency_offset: float = 0.040
    tap_hold_seconds: float = 0.030
    flick_duration: float = 0.050
    flick_distance: int = 100
    flick_lead_seconds: float = 0.020
    trigger_window_before: float = 0.025
    trigger_window_after: float = 0.080
    green_release_grace: float = 0.120
    pressure: int = 100
    max_pointers: int = 10


@dataclass(frozen=True)
class TouchAction:
    """One low-level touch action or commit marker."""

    kind: str
    pointer_id: int | None = None
    x: int | None = None
    y: int | None = None
    track_id: int | None = None
    note_type: str | None = None
    lane: int | None = None
    pressure: int = 100


@dataclass(frozen=True)
class PolicyResult:
    """Scheduler output for one frame."""

    actions: list[TouchAction]
    warnings: list[str]


@dataclass
class PendingRelease:
    """Delayed tap/flick release state."""

    track_id: int
    note_type: str
    lane: int
    due_time: float
    start_time: float | None = None
    start_point: tuple[int, int] | None = None
    flick_end: tuple[int, int] | None = None


def lane_touch_map(calibration: Calibration) -> dict[int, tuple[int, int]]:
    """Return lane index to integer touch judgment coordinates."""

    return {
        lane: (int(round(touch_point.x)), int(round(touch_point.y)))
        for lane, _capture_point, touch_point in lane_touch_points(calibration)
    }


class PolicyScheduler:
    """Schedule tap, flick, and green hold actions from tracked notes."""

    def __init__(
        self,
        lane_touches: dict[int, tuple[int, int]],
        config: SchedulerConfig | None = None,
        pointer_pool: PointerPool | None = None,
    ) -> None:
        self.config = config or SchedulerConfig()
        self.lane_touches = lane_touches
        self.pointer_pool = pointer_pool or PointerPool(self.config.max_pointers)
        self.triggered_tracks: set[int] = set()
        self.expired_tracks: set[int] = set()
        self.pending_releases: list[PendingRelease] = []
        self.green_last_seen: dict[int, float] = {}

    def update(self, tracks: list[TrackedNote], now: float) -> PolicyResult:
        """Return touch actions for the current tracked notes."""

        actions: list[TouchAction] = []
        warnings: list[str] = []
        actions.extend(self._release_due(now, warnings))

        visible_green_lanes: set[int] = set()
        for track in sorted(tracks, key=self._track_sort_key):
            if track.note_type == "green_note":
                self._handle_green(track, now, actions, warnings, visible_green_lanes)
            else:
                self._handle_discrete(track, now, actions, warnings)

        actions.extend(self._release_stale_green(now, visible_green_lanes))
        return PolicyResult(actions=actions, warnings=warnings)

    def release_all(self) -> list[TouchAction]:
        """Release every active pointer for shutdown or panic-stop paths."""

        actions: list[TouchAction] = []
        for slot in list(self.pointer_pool.active_slots()):
            released = self.pointer_pool.release(slot.track_id) if slot.track_id is not None else None
            if released is not None:
                actions.append(self._up_action(released))
        if actions:
            actions.append(self._commit_action())
        self.pending_releases.clear()
        self.green_last_seen.clear()
        return actions

    def _track_sort_key(self, track: TrackedNote) -> tuple[float, int]:
        eta = track.eta_seconds if track.eta_seconds is not None else 999.0
        return eta, track.track_id

    def _handle_discrete(
        self,
        track: TrackedNote,
        now: float,
        actions: list[TouchAction],
        warnings: list[str],
    ) -> None:
        if track.track_id in self.triggered_tracks or track.track_id in self.expired_tracks:
            return
        if self._mark_expired_if_late(track):
            return

        if track.note_type in ("tap", "skill"):
            if not self._is_ready(track):
                return
            self._schedule_tap_like(track, now, actions, warnings)
        elif track.note_type == "flick":
            if not self._is_ready(track, self.config.flick_lead_seconds):
                return
            self._schedule_flick(track, now, actions, warnings)

    def _handle_green(
        self,
        track: TrackedNote,
        now: float,
        actions: list[TouchAction],
        warnings: list[str],
        visible_green_lanes: set[int],
    ) -> None:
        lane = track.lane
        active_slot = self.pointer_pool.get_by_lane(lane, "green_note")
        if active_slot is not None:
            visible_green_lanes.add(lane)
            self.green_last_seen[lane] = now
            x, y = self._lane_touch(lane)
            should_move = (active_slot.x, active_slot.y) != (x, y)
            moved = self.pointer_pool.move(active_slot.track_id, x, y) if should_move and active_slot.track_id is not None else None
            if moved is not None:
                actions.append(self._move_action(moved))
                actions.append(self._commit_action())
            return

        if track.track_id in self.expired_tracks:
            return
        if self._mark_expired_if_late(track) or not self._is_ready(track):
            return

        x, y = self._lane_touch(lane)
        slot = self.pointer_pool.acquire(track.track_id, lane, "green_note", x, y, now)
        if slot is None:
            warnings.append(f"no free pointer for green_note track={track.track_id} lane={lane}")
            return
        visible_green_lanes.add(lane)
        self.green_last_seen[lane] = now
        self.triggered_tracks.add(track.track_id)
        actions.append(self._down_action(slot))
        actions.append(self._commit_action())

    def _schedule_tap_like(
        self,
        track: TrackedNote,
        now: float,
        actions: list[TouchAction],
        warnings: list[str],
    ) -> None:
        x, y = self._lane_touch(track.lane)
        slot = self.pointer_pool.acquire(track.track_id, track.lane, track.note_type, x, y, now)
        if slot is None:
            warnings.append(f"no free pointer for {track.note_type} track={track.track_id} lane={track.lane}")
            return

        self.triggered_tracks.add(track.track_id)
        self.pending_releases.append(
            PendingRelease(
                track_id=track.track_id,
                note_type=track.note_type,
                lane=track.lane,
                due_time=now + self.config.tap_hold_seconds,
            )
        )
        actions.append(self._down_action(slot))
        actions.append(self._commit_action())

    def _schedule_flick(
        self,
        track: TrackedNote,
        now: float,
        actions: list[TouchAction],
        warnings: list[str],
    ) -> None:
        x, y = self._lane_touch(track.lane)
        slot = self.pointer_pool.acquire(track.track_id, track.lane, track.note_type, x, y, now)
        if slot is None:
            warnings.append(f"no free pointer for flick track={track.track_id} lane={track.lane}")
            return

        self.triggered_tracks.add(track.track_id)
        self.pending_releases.append(
            PendingRelease(
                track_id=track.track_id,
                note_type=track.note_type,
                lane=track.lane,
                due_time=now + self.config.flick_duration,
                start_time=now,
                start_point=(x, y),
                flick_end=flick_end_point(x, y, self.config.flick_distance),
            )
        )
        actions.append(self._down_action(slot))
        actions.append(self._commit_action())

    def _release_due(self, now: float, warnings: list[str]) -> list[TouchAction]:
        actions: list[TouchAction] = []
        remaining: list[PendingRelease] = []
        for pending in self.pending_releases:
            if pending.due_time > now:
                if pending.flick_end is not None:
                    actions.extend(self._move_flick_in_progress(pending, now))
                remaining.append(pending)
                continue

            slot = self.pointer_pool.get_by_track(pending.track_id)
            if slot is None:
                warnings.append(f"pending release has no pointer track={pending.track_id}")
                continue

            if pending.flick_end is not None:
                actions.extend(self._move_flick_to_end(pending))

            released = self.pointer_pool.release(pending.track_id)
            if released is not None:
                actions.append(self._up_action(released))
                actions.append(self._commit_action())

        self.pending_releases = remaining
        return actions

    def _move_flick_in_progress(self, pending: PendingRelease, now: float) -> list[TouchAction]:
        """Move one active flick pointer according to elapsed gesture progress."""

        x, y = self._interpolate_flick_point(pending, now)
        slot = self.pointer_pool.get_by_track(pending.track_id)
        if slot is None or (slot.x, slot.y) == (x, y):
            return []

        moved = self.pointer_pool.move(pending.track_id, x, y)
        if moved is None:
            return []
        return [self._move_action(moved), self._commit_action()]

    def _move_flick_to_end(self, pending: PendingRelease) -> list[TouchAction]:
        """Move one flick pointer to its final position before release."""

        if pending.flick_end is None:
            return []
        end_x, end_y = pending.flick_end
        moved = self.pointer_pool.move(pending.track_id, end_x, end_y)
        if moved is None:
            return []
        return [self._move_action(moved)]

    def _interpolate_flick_point(self, pending: PendingRelease, now: float) -> tuple[int, int]:
        """Return the current in-progress flick position."""

        if pending.start_time is None or pending.start_point is None or pending.flick_end is None:
            raise ValueError("pending flick is missing interpolation points")

        duration = max(0.001, pending.due_time - pending.start_time)
        progress = min(1.0, max(0.0, (now - pending.start_time) / duration))
        start_x, start_y = pending.start_point
        end_x, end_y = pending.flick_end
        x = start_x + (end_x - start_x) * progress
        y = start_y + (end_y - start_y) * progress
        return int(round(x)), int(round(y))

    def _release_stale_green(self, now: float, visible_green_lanes: set[int]) -> list[TouchAction]:
        actions: list[TouchAction] = []
        for lane, last_seen in list(self.green_last_seen.items()):
            if lane in visible_green_lanes:
                continue
            if now - last_seen <= self.config.green_release_grace:
                continue

            released = self.pointer_pool.release_by_lane(lane, "green_note")
            if released is not None:
                actions.append(self._up_action(released))
                actions.append(self._commit_action())
            self.green_last_seen.pop(lane, None)
        return actions

    def _mark_expired_if_late(self, track: TrackedNote) -> bool:
        if track.eta_seconds is None:
            return False
        if track.eta_seconds - self.config.latency_offset < -self.config.trigger_window_after:
            self.expired_tracks.add(track.track_id)
            return True
        return False

    def _is_ready(self, track: TrackedNote, lead_seconds: float = 0.0) -> bool:
        if track.eta_seconds is None:
            return False
        delta = track.eta_seconds - self.config.latency_offset - lead_seconds
        return -self.config.trigger_window_after <= delta <= self.config.trigger_window_before

    def _lane_touch(self, lane: int) -> tuple[int, int]:
        return self.lane_touches[lane]

    def _down_action(self, slot: PointerSlot) -> TouchAction:
        return TouchAction(
            kind="down",
            pointer_id=slot.pointer_id,
            x=slot.x,
            y=slot.y,
            track_id=slot.track_id,
            note_type=slot.note_type,
            lane=slot.lane,
            pressure=self.config.pressure,
        )

    def _move_action(self, slot: PointerSlot) -> TouchAction:
        return TouchAction(
            kind="move",
            pointer_id=slot.pointer_id,
            x=slot.x,
            y=slot.y,
            track_id=slot.track_id,
            note_type=slot.note_type,
            lane=slot.lane,
            pressure=self.config.pressure,
        )

    def _up_action(self, slot: PointerSlot) -> TouchAction:
        return TouchAction(
            kind="up",
            pointer_id=slot.pointer_id,
            x=slot.x,
            y=slot.y,
            track_id=slot.track_id,
            note_type=slot.note_type,
            lane=slot.lane,
            pressure=self.config.pressure,
        )

    def _commit_action(self) -> TouchAction:
        return TouchAction(kind="commit", pressure=self.config.pressure)
