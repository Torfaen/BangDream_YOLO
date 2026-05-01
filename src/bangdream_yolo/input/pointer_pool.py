"""Manage minitouch pointer ownership for scheduled note actions."""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass
class PointerSlot:
    """One reusable minitouch pointer slot."""

    pointer_id: int
    track_id: int | None = None
    lane: int | None = None
    note_type: str | None = None
    is_down: bool = False
    down_time: float | None = None
    x: int | None = None
    y: int | None = None

    def clear(self) -> None:
        """Mark this pointer as free."""

        self.track_id = None
        self.lane = None
        self.note_type = None
        self.is_down = False
        self.down_time = None
        self.x = None
        self.y = None


class PointerPool:
    """Small fixed-size pool for active minitouch pointers."""

    def __init__(self, max_pointers: int = 10) -> None:
        self.slots = [PointerSlot(pointer_id=index) for index in range(max_pointers)]

    def acquire(
        self,
        track_id: int,
        lane: int,
        note_type: str,
        x: int,
        y: int,
        now: float,
    ) -> PointerSlot | None:
        """Reserve one pointer for a track, returning None when full."""

        existing = self.get_by_track(track_id)
        if existing is not None:
            return existing

        for slot in self.slots:
            if not slot.is_down:
                slot.track_id = track_id
                slot.lane = lane
                slot.note_type = note_type
                slot.is_down = True
                slot.down_time = now
                slot.x = int(x)
                slot.y = int(y)
                return slot
        return None

    def release(self, track_id: int) -> PointerSlot | None:
        """Free the pointer owned by a track and return its previous state."""

        slot = self.get_by_track(track_id)
        if slot is None:
            return None
        released = replace(slot)
        slot.clear()
        return released

    def release_by_lane(self, lane: int, note_type: str | None = None) -> PointerSlot | None:
        """Free the first active pointer for a lane, optionally matching type."""

        slot = self.get_by_lane(lane, note_type)
        if slot is None or slot.track_id is None:
            return None
        return self.release(slot.track_id)

    def move(self, track_id: int, x: int, y: int) -> PointerSlot | None:
        """Update the remembered coordinates for an active pointer."""

        slot = self.get_by_track(track_id)
        if slot is None:
            return None
        slot.x = int(x)
        slot.y = int(y)
        return slot

    def get_by_track(self, track_id: int) -> PointerSlot | None:
        """Return the active pointer assigned to a track."""

        for slot in self.slots:
            if slot.is_down and slot.track_id == track_id:
                return slot
        return None

    def get_by_lane(self, lane: int, note_type: str | None = None) -> PointerSlot | None:
        """Return the first active pointer on a lane."""

        for slot in self.slots:
            if not slot.is_down or slot.lane != lane:
                continue
            if note_type is not None and slot.note_type != note_type:
                continue
            return slot
        return None

    def active_slots(self) -> list[PointerSlot]:
        """Return all currently held pointers."""

        return [slot for slot in self.slots if slot.is_down]

