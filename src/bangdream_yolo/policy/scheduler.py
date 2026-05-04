"""Convert tracked notes into dry-run or minitouch-ready actions."""

from __future__ import annotations

from dataclasses import dataclass, field
import math

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
    green_release_grace: float = 0.350
    green_bar_min_track_y: float = 0.82
    green_bar_max_track_y: float = 1.10
    green_slot_match_lanes: float = 0.75
    green_bar_follow_lanes: float = 1.35
    green_terminal_arm_seconds: float = 0.080
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


@dataclass
class GreenHoldState:
    """State for one held green slide chain."""

    pointer_id: int
    owner_track_id: int
    follow_track_id: int
    started_at: float
    last_seen: float
    has_followed_green_bar: bool = False
    ignored_terminal_track_ids: set[int] = field(default_factory=set)


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
        self.green_holds: dict[int, GreenHoldState] = {}

    def update(self, tracks: list[TrackedNote], now: float) -> PolicyResult:
        """Return touch actions for the current tracked notes."""

        actions: list[TouchAction] = []
        warnings: list[str] = []
        actions.extend(self._release_due(now, warnings))

        visible_green_pointers: set[int] = set()
        green_bars = [track for track in tracks if track.note_type == "green_bar"]
        followable_green_bars = [track for track in green_bars if self._is_followable_green_bar(track)]
        used_green_bars: set[int] = set()
        self._follow_green_holds_by_id(followable_green_bars, now, actions, visible_green_pointers, used_green_bars)
        self._follow_green_holds_by_distance(followable_green_bars, now, actions, visible_green_pointers, used_green_bars)

        flick_tracks = [track for track in tracks if track.note_type == "flick"]
        self._handle_green_terminal_flicks(flick_tracks, now, actions)
        green_notes = [track for track in tracks if track.note_type == "green_note"]
        self._release_green_note_terminals(green_notes, now, actions, visible_green_pointers)

        playable_tracks = [track for track in tracks if track.note_type not in ("green_bar", "green_note")]
        for track in sorted(playable_tracks, key=self._track_sort_key):
            self._handle_discrete(track, now, actions, warnings)

        self._start_green_holds(followable_green_bars, green_notes, now, actions, warnings, used_green_bars)
        actions.extend(self._release_stale_green(now))
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
        self.green_holds.clear()
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

    def _follow_green_holds_by_id(
        self,
        tracks: list[TrackedNote],
        now: float,
        actions: list[TouchAction],
        visible_green_pointers: set[int],
        used_tracks: set[int],
    ) -> None:
        """Refresh green holds whose current bottom green_bar kept the same track id."""

        tracks_by_id = {track.track_id: track for track in tracks}
        for state, slot in self._active_green_hold_slots():
            track = tracks_by_id.get(state.follow_track_id)
            if track is None:
                continue
            self._move_green_hold_to_bar(state, slot, track, now, actions, visible_green_pointers)
            used_tracks.add(track.track_id)

    def _follow_green_holds_by_distance(
        self,
        tracks: list[TrackedNote],
        now: float,
        actions: list[TouchAction],
        visible_green_pointers: set[int],
        used_tracks: set[int],
    ) -> None:
        """Reconnect active green holds when tracker briefly changes the bottom bar id."""

        pairs: list[tuple[float, GreenHoldState, PointerSlot, TrackedNote]] = []
        distance_limit = self._green_follow_distance_limit()
        for state, slot in self._active_green_hold_slots():
            if state.pointer_id in visible_green_pointers or slot.x is None or slot.y is None:
                continue
            for track in tracks:
                if track.track_id in used_tracks:
                    continue
                target_x, target_y = self._track_touch(track)
                distance = math.hypot(slot.x - target_x, slot.y - target_y)
                if distance <= distance_limit:
                    pairs.append((distance, state, slot, track))

        used_pointers: set[int] = set()
        for _distance, state, slot, track in sorted(pairs, key=lambda item: item[0]):
            if state.pointer_id in used_pointers or state.pointer_id in visible_green_pointers:
                continue
            if track.track_id in used_tracks:
                continue
            self._move_green_hold_to_bar(state, slot, track, now, actions, visible_green_pointers)
            used_pointers.add(state.pointer_id)
            used_tracks.add(track.track_id)

    def _start_green_holds(
        self,
        tracks: list[TrackedNote],
        green_notes: list[TrackedNote],
        now: float,
        actions: list[TouchAction],
        warnings: list[str],
        used_tracks: set[int],
    ) -> None:
        """Create new green holds from unused bottom green_bar tracks."""

        for track in sorted(tracks, key=self._track_sort_key):
            if track.track_id in used_tracks or track.track_id in self.triggered_tracks:
                continue
            if self._nearest_green_hold(track) is not None:
                continue

            x, y = self._track_touch(track)
            slot = self.pointer_pool.acquire(track.track_id, track.lane, "green_bar", x, y, now)
            if slot is None:
                warnings.append(f"no free pointer for green_bar track={track.track_id} lane={track.lane}")
                continue

            self.green_holds[slot.pointer_id] = GreenHoldState(
                pointer_id=slot.pointer_id,
                owner_track_id=track.track_id,
                follow_track_id=track.track_id,
                started_at=now,
                last_seen=now,
                ignored_terminal_track_ids=self._green_notes_near_track(track, green_notes),
            )
            self.triggered_tracks.add(track.track_id)
            used_tracks.add(track.track_id)
            actions.append(self._down_action(slot))
            actions.append(self._commit_action())

    def _move_green_hold_to_bar(
        self,
        state: GreenHoldState,
        slot: PointerSlot,
        track: TrackedNote,
        now: float,
        actions: list[TouchAction],
        visible_green_pointers: set[int],
    ) -> None:
        """Move one held green pointer to the current bottom green_bar center."""

        if slot.track_id is None:
            return

        x, y = self._track_touch(track)
        old_point = (slot.x, slot.y)
        moved = self.pointer_pool.move(slot.track_id, x, y, lane=track.lane, note_type="green_bar")
        if moved is None:
            return

        state.follow_track_id = track.track_id
        state.last_seen = now
        if now > state.started_at:
            state.has_followed_green_bar = True
        visible_green_pointers.add(state.pointer_id)
        if old_point != (x, y):
            actions.append(self._move_action(moved))
            actions.append(self._commit_action())

    def _is_followable_green_bar(self, track: TrackedNote) -> bool:
        """Return True for currently visible green bars close to the judgment line."""

        if track.note_type != "green_bar" or track.missed_frames != 0:
            return False
        track_y = track.latest.track_y
        return self.config.green_bar_min_track_y <= track_y <= self.config.green_bar_max_track_y

    def _release_green_note_terminals(
        self,
        tracks: list[TrackedNote],
        now: float,
        actions: list[TouchAction],
        visible_green_pointers: set[int],
    ) -> None:
        """Release green holds when a green_note endpoint reaches the line."""

        for track in sorted(tracks, key=self._track_sort_key):
            if track.missed_frames != 0 or track.track_id in self.triggered_tracks:
                continue
            match = self._nearest_armed_green_hold(track, now)
            if match is None:
                continue
            state, slot = match
            if self._should_ignore_green_note_terminal(track, state, slot, visible_green_pointers):
                state.last_seen = now
                continue
            if not self._is_green_terminal_ready(track):
                continue

            self.triggered_tracks.add(track.track_id)
            self._release_green_hold(state, actions)

    def _should_ignore_green_note_terminal(
        self,
        track: TrackedNote,
        state: GreenHoldState,
        slot: PointerSlot,
        visible_green_pointers: set[int],
    ) -> bool:
        """Return True when a green_note is probably the active hold itself."""

        if track.track_id in state.ignored_terminal_track_ids:
            return True
        if not state.has_followed_green_bar:
            return True
        if state.pointer_id not in visible_green_pointers:
            return False
        if slot.x is None or slot.y is None:
            return False

        track_x, track_y = self._track_touch(track)
        distance = math.hypot(slot.x - track_x, slot.y - track_y)
        if distance > self._green_slot_match_distance_limit():
            return False
        return not self._is_stable_green_note_terminal(track)

    def _is_stable_green_note_terminal(self, track: TrackedNote) -> bool:
        """Return True when a green_note has enough tracking history to be a real endpoint."""

        return track.eta_seconds is not None and len(track.history) >= 2

    def _is_green_terminal_ready(self, track: TrackedNote) -> bool:
        """Return True when a green_note is close enough to end a held green chain."""

        if track.eta_seconds is not None:
            return self._is_ready(track)
        return self.config.green_bar_min_track_y <= track.latest.track_y <= self.config.green_bar_max_track_y

    def _green_notes_near_track(self, track: TrackedNote, green_notes: list[TrackedNote]) -> set[int]:
        """Return same-frame green_note ids that overlap the green_bar start."""

        start_x, start_y = self._track_touch(track)
        ignored_ids: set[int] = set()
        distance_limit = self._green_slot_match_distance_limit()
        for note in green_notes:
            if note.missed_frames != 0:
                continue
            note_x, note_y = self._track_touch(note)
            if math.hypot(start_x - note_x, start_y - note_y) <= distance_limit:
                ignored_ids.add(note.track_id)
        return ignored_ids

    def _handle_green_terminal_flicks(
        self,
        tracks: list[TrackedNote],
        now: float,
        actions: list[TouchAction],
    ) -> None:
        """Reuse held green pointers for flick endpoints."""

        for track in sorted(tracks, key=self._track_sort_key):
            if track.missed_frames != 0 or track.track_id in self.triggered_tracks:
                continue
            if not self._is_ready(track, self.config.flick_lead_seconds):
                continue

            match = self._nearest_green_hold(track)
            if match is None:
                continue
            state, slot = match
            self._schedule_green_terminal_flick(state, slot, track, now, actions)

    def _schedule_green_terminal_flick(
        self,
        state: GreenHoldState,
        slot: PointerSlot,
        track: TrackedNote,
        now: float,
        actions: list[TouchAction],
    ) -> None:
        """Reuse an already held green pointer for a flick endpoint."""

        start_x, start_y = self._track_touch(track)
        old_point = (slot.x, slot.y)
        moved = self.pointer_pool.move(state.owner_track_id, start_x, start_y, lane=track.lane, note_type="flick")
        if moved is not None and old_point != (start_x, start_y):
            actions.append(self._move_action(moved))
            actions.append(self._commit_action())

        self.green_holds.pop(state.pointer_id, None)
        self.triggered_tracks.add(track.track_id)
        self.pending_releases.append(
            PendingRelease(
                track_id=state.owner_track_id,
                note_type="flick",
                lane=track.lane,
                due_time=now + self.config.flick_duration,
                start_time=now,
                start_point=(start_x, start_y),
                flick_end=flick_end_point(start_x, start_y, self.config.flick_distance),
            )
        )

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

    def _release_stale_green(self, now: float) -> list[TouchAction]:
        actions: list[TouchAction] = []
        for state, _slot in self._active_green_hold_slots():
            if now - state.last_seen <= self.config.green_release_grace:
                continue

            self._release_green_hold(state, actions)
        return actions

    def _release_green_hold(
        self,
        state: GreenHoldState,
        actions: list[TouchAction],
    ) -> None:
        """Release one active green hold and clear its state."""

        released = self.pointer_pool.release(state.owner_track_id)
        self.green_holds.pop(state.pointer_id, None)
        if released is not None:
            actions.append(self._up_action(released))
            actions.append(self._commit_action())

    def _active_green_hold_slots(self) -> list[tuple[GreenHoldState, PointerSlot]]:
        """Return active green hold states with their pointer slots."""

        active: list[tuple[GreenHoldState, PointerSlot]] = []
        for pointer_id, state in list(self.green_holds.items()):
            slot = self._slot_for_green_hold(state)
            if slot is None:
                self.green_holds.pop(pointer_id, None)
                continue
            active.append((state, slot))
        return active

    def _slot_for_green_hold(self, state: GreenHoldState) -> PointerSlot | None:
        """Return the pointer slot owned by one green hold."""

        if state.pointer_id < 0 or state.pointer_id >= len(self.pointer_pool.slots):
            return None
        slot = self.pointer_pool.slots[state.pointer_id]
        if not slot.is_down or slot.track_id != state.owner_track_id:
            return None
        return slot

    def _nearest_green_hold(
        self,
        track: TrackedNote,
        distance_limit: float | None = None,
    ) -> tuple[GreenHoldState, PointerSlot] | None:
        """Return the closest active green hold to a tracked object."""

        target_x, target_y = self._track_touch(track)
        best_match: tuple[GreenHoldState, PointerSlot] | None = None
        best_distance = distance_limit if distance_limit is not None else self._green_slot_match_distance_limit()
        for state, slot in self._active_green_hold_slots():
            if slot.x is None or slot.y is None:
                continue
            distance = math.hypot(slot.x - target_x, slot.y - target_y)
            if distance <= best_distance:
                best_distance = distance
                best_match = (state, slot)
        return best_match

    def _nearest_armed_green_hold(self, track: TrackedNote, now: float) -> tuple[GreenHoldState, PointerSlot] | None:
        """Return the closest green hold that is old enough to accept an endpoint."""

        match = self._nearest_green_hold(track)
        if match is None:
            return None
        state, _slot = match
        if now - state.started_at < self.config.green_terminal_arm_seconds:
            return None
        return match

    def _green_slot_match_distance_limit(self) -> float:
        """Return the maximum distance for flick or a new bar ID to reuse one held pointer."""

        return self._average_lane_distance() * self.config.green_slot_match_lanes

    def _green_follow_distance_limit(self) -> float:
        """Return the maximum per-frame distance for green_bar follow matching."""

        return self._average_lane_distance() * self.config.green_bar_follow_lanes

    def _average_lane_distance(self) -> float:
        """Return average touch distance between neighboring lanes."""

        lane_points = [self.lane_touches[lane] for lane in sorted(self.lane_touches)]
        if len(lane_points) < 2:
            return float("inf")

        distances = [
            math.hypot(right[0] - left[0], right[1] - left[1])
            for left, right in zip(lane_points, lane_points[1:])
        ]
        return sum(distances) / len(distances)

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

    def _track_touch(self, track: TrackedNote) -> tuple[int, int]:
        """Map a tracked note's continuous track_x to the judgment-line touch point."""

        lane_keys = sorted(self.lane_touches)
        if len(lane_keys) < 2:
            return self._lane_touch(track.lane)

        lane_count = len(lane_keys)
        left_lane = lane_keys[0]
        right_lane = lane_keys[-1]
        left_x, left_y = self.lane_touches[left_lane]
        right_x, right_y = self.lane_touches[right_lane]

        left_center = 0.5 / lane_count
        right_center = (lane_count - 0.5) / lane_count
        denominator = max(0.001, right_center - left_center)
        fraction = (track.latest.track_x - left_center) / denominator
        fraction = min(1.0, max(0.0, fraction))

        x = left_x + (right_x - left_x) * fraction
        y = left_y + (right_y - left_y) * fraction
        return int(round(x)), int(round(y))

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
