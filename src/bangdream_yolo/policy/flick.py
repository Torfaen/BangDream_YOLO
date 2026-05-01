"""Flick gesture helpers."""

from __future__ import annotations


def flick_end_point(start_x: int, start_y: int, distance: int) -> tuple[int, int]:
    """Return a short downward-in-game flick endpoint for clockwise touch mapping."""

    return max(0, int(start_x) - int(distance)), int(start_y)
