"""Synthetic checks for m6 pointer pool and ETA policy scheduling."""

from __future__ import annotations

import contextlib
import io
import unittest

from bangdream_yolo.android import parse_adb_devices
from bangdream_yolo.detection.postprocess import NoteDetection
from bangdream_yolo.geometry.calibration import Calibration, Point
from bangdream_yolo.geometry.lane import capture_to_touch
from bangdream_yolo.input.minitouch import (
    MinitouchBanner,
    MinitouchClient,
    MinitouchError,
    parse_minitouch_banner,
)
from bangdream_yolo.input.pointer_pool import PointerPool
from bangdream_yolo.policy.scheduler import PolicyScheduler, SchedulerConfig
from bangdream_yolo.policy.scheduler import TouchAction
from bangdream_yolo.tools.policy_preview import apply_release_actions
from bangdream_yolo.tracker.state import TrackedNote


LANE_TOUCHES = {lane: (100 + lane * 10, 500) for lane in range(7)}


def tracked_note(
    track_id: int,
    note_type: str = "tap",
    lane: int = 3,
    eta_seconds: float | None = 0.040,
    track_y: float = 0.90,
    history_len: int = 1,
) -> TrackedNote:
    """Build one tracked note ready for scheduler tests."""

    detection = NoteDetection(
        note_type=note_type,
        lane=lane,
        bbox=(0.0, 0.0, 10.0, 10.0),
        center_x=5.0,
        center_y=5.0,
        track_x=(lane + 0.5) / 7,
        track_y=track_y,
        confidence=0.9,
    )
    return TrackedNote(
        track_id=track_id,
        note_type=note_type,
        lane=lane,
        latest=detection,
        history=[(float(index), track_y) for index in range(history_len)],
        velocity_y=1.0,
        eta_seconds=eta_seconds,
    )


def action_kinds(result) -> list[str]:
    """Return action kind names from a PolicyResult."""

    return [action.kind for action in result.actions]


class PointerPoolTests(unittest.TestCase):
    def test_acquire_and_release_pointer(self) -> None:
        pool = PointerPool(max_pointers=1)

        slot = pool.acquire(10, 3, "tap", 100, 500, now=1.0)

        self.assertIsNotNone(slot)
        self.assertEqual(slot.pointer_id, 0)
        self.assertIsNone(pool.acquire(11, 4, "tap", 110, 500, now=1.0))
        released = pool.release(10)
        self.assertIsNotNone(released)
        self.assertEqual(pool.active_slots(), [])


class TouchGeometryTests(unittest.TestCase):
    def test_transpose_rotation_maps_capture_xy_to_touch_yx(self) -> None:
        calibration = Calibration(
            capture_width=1280,
            capture_height=720,
            touch_width=720,
            touch_height=1280,
            touch_rotation="transpose",
            points={
                "judge_left": Point(122.0, 590.0),
                "judge_right": Point(1156.0, 590.0),
                "track_top_left": Point(531.0, 149.0),
                "track_top_right": Point(763.0, 160.0),
            },
        )

        touch = capture_to_touch(calibration, Point(920.0, 360.0))

        self.assertEqual((touch.x, touch.y), (360.0, 920.0))

    def test_clockwise_rotation_maps_game_down_to_touch_x_down(self) -> None:
        calibration = Calibration(
            capture_width=1280,
            capture_height=720,
            touch_width=720,
            touch_height=1280,
            touch_rotation="clockwise",
            points={
                "judge_left": Point(122.0, 590.0),
                "judge_right": Point(1156.0, 590.0),
                "track_top_left": Point(531.0, 149.0),
                "track_top_right": Point(763.0, 160.0),
            },
        )

        start = capture_to_touch(calibration, Point(640.0, 590.0))
        end = capture_to_touch(calibration, Point(640.0, 600.0))

        self.assertEqual((start.x, start.y), (130.0, 640.0))
        self.assertEqual((end.x, end.y), (120.0, 640.0))


class BrokenSocket:
    """Socket stand-in that fails on write."""

    def __init__(self) -> None:
        self.closed = False

    def sendall(self, _data: bytes) -> None:
        raise ConnectionAbortedError(10053, "connection aborted")

    def close(self) -> None:
        self.closed = True


class RecordingSocket:
    """Socket stand-in that records raw minitouch payloads."""

    def __init__(self) -> None:
        self.payloads: list[bytes] = []

    def sendall(self, data: bytes) -> None:
        self.payloads.append(data)


class BrokenClient:
    """Minimal policy_preview client stand-in with a disconnected socket."""

    sock = None

    def up(self, _pointer_id: int) -> None:
        raise AssertionError("release should not write to a disconnected socket")

    def commit(self) -> None:
        raise AssertionError("release should not commit to a disconnected socket")


class MinitouchDisconnectTests(unittest.TestCase):
    def test_parse_adb_devices_marks_only_device_online(self) -> None:
        devices = parse_adb_devices(
            "List of devices attached\n"
            "127.0.0.1:16384 offline transport_id:1\n"
            "emulator-5554 device product:r11q model:SM_S7110\n"
            "phone unauthorized\n"
        )

        self.assertEqual([device.serial for device in devices], ["127.0.0.1:16384", "emulator-5554", "phone"])
        self.assertEqual([device.is_online for device in devices], [False, True, False])

    def test_parse_minitouch_banner_limits(self) -> None:
        banner = parse_minitouch_banner("v 1\n^ 10 720 1280 255\n$ 1234\n")

        self.assertEqual(banner.version, 1)
        self.assertEqual(banner.max_contacts, 10)
        self.assertEqual(banner.max_x, 720)
        self.assertEqual(banner.max_y, 1280)
        self.assertEqual(banner.max_pressure, 255)
        self.assertEqual(banner.pid, 1234)

    def test_format_down_rejects_out_of_bounds_values(self) -> None:
        client = object.__new__(MinitouchClient)
        client.banner = MinitouchBanner(max_contacts=2, max_x=720, max_y=1280, max_pressure=255)

        self.assertEqual(client.format_down(1, 720, 1280, 255), "d 1 720 1280 255\n")
        with self.assertRaises(MinitouchError):
            client.format_down(2, 100, 100, 50)
        with self.assertRaises(MinitouchError):
            client.format_down(0, 721, 100, 50)
        with self.assertRaises(MinitouchError):
            client.format_down(0, 100, 1281, 50)
        with self.assertRaises(MinitouchError):
            client.format_down(0, 100, 100, 256)

    def test_format_down_zero_pressure_device_keeps_pressure(self) -> None:
        client = object.__new__(MinitouchClient)
        client.banner = MinitouchBanner(max_contacts=10, max_x=720, max_y=1280, max_pressure=0)

        self.assertEqual(client.format_down(0, 100, 200, 100), "d 0 100 200 100\n")

    def test_command_builder_sends_one_payload(self) -> None:
        socket = RecordingSocket()
        client = object.__new__(MinitouchClient)
        client.sock = socket
        client.process = None
        client.banner = MinitouchBanner(max_contacts=10, max_x=720, max_y=1280, max_pressure=255)

        builder = client.command_builder().down(0, 100, 200, 50).commit().up(0).commit()
        client.send_builder(builder)

        self.assertEqual(socket.payloads, [b"d 0 100 200 50\nc\nu 0\nc\n"])

    def test_send_wraps_socket_abort_as_minitouch_error(self) -> None:
        client = object.__new__(MinitouchClient)
        client.sock = BrokenSocket()

        with self.assertRaises(MinitouchError):
            client.send("c\n")

        self.assertIsNone(client.sock)

    def test_release_actions_skip_disconnected_socket(self) -> None:
        actions = [TouchAction(kind="up", pointer_id=0), TouchAction(kind="commit")]

        with contextlib.redirect_stdout(io.StringIO()):
            apply_release_actions(BrokenClient(), actions)


class PolicySchedulerTests(unittest.TestCase):
    def test_tap_triggers_once_and_releases(self) -> None:
        scheduler = PolicyScheduler(LANE_TOUCHES, SchedulerConfig())
        note = tracked_note(1, "tap")

        first = scheduler.update([note], now=0.0)
        second = scheduler.update([note], now=0.010)
        release = scheduler.update([note], now=0.031)

        self.assertEqual(action_kinds(first), ["down", "commit"])
        self.assertEqual(second.actions, [])
        self.assertEqual(action_kinds(release), ["up", "commit"])

    def test_skill_uses_tap_like_sequence(self) -> None:
        scheduler = PolicyScheduler(LANE_TOUCHES, SchedulerConfig())
        note = tracked_note(2, "skill")

        result = scheduler.update([note], now=0.0)

        self.assertEqual(action_kinds(result), ["down", "commit"])
        self.assertEqual(result.actions[0].note_type, "skill")

    def test_flick_produces_down_move_up(self) -> None:
        scheduler = PolicyScheduler(LANE_TOUCHES, SchedulerConfig(flick_distance=100, flick_duration=0.100))
        note = tracked_note(3, "flick", eta_seconds=0.080)

        first = scheduler.update([note], now=0.0)
        middle = scheduler.update([note], now=0.050)
        release = scheduler.update([note], now=0.101)

        self.assertEqual(action_kinds(first), ["down", "commit"])
        self.assertEqual(action_kinds(middle), ["move", "commit"])
        self.assertEqual(action_kinds(release), ["move", "up", "commit"])
        self.assertEqual((middle.actions[0].x, middle.actions[0].y), (80, 500))
        self.assertEqual((release.actions[0].x, release.actions[0].y), (30, 500))

    def test_flick_can_trigger_before_tap_window(self) -> None:
        scheduler = PolicyScheduler(LANE_TOUCHES, SchedulerConfig(flick_lead_seconds=0.100))

        tap_result = scheduler.update([tracked_note(13, "tap", eta_seconds=0.140)], now=0.0)
        flick_result = scheduler.update([tracked_note(14, "flick", eta_seconds=0.140)], now=0.0)

        self.assertEqual(tap_result.actions, [])
        self.assertEqual(action_kinds(flick_result), ["down", "commit"])

    def test_green_bar_holds_and_releases_after_grace(self) -> None:
        scheduler = PolicyScheduler(LANE_TOUCHES, SchedulerConfig(green_release_grace=0.120))

        first = scheduler.update([tracked_note(50, "green_bar", lane=2, eta_seconds=None, track_y=1.0)], now=0.0)
        hold = scheduler.update([tracked_note(50, "green_bar", lane=2, eta_seconds=None, track_y=1.0)], now=0.05)
        still_held = scheduler.update([], now=0.16)
        released = scheduler.update([], now=0.171)

        self.assertEqual(action_kinds(first), ["down", "commit"])
        self.assertEqual(hold.actions, [])
        self.assertEqual(still_held.actions, [])
        self.assertEqual(action_kinds(released), ["up", "commit"])

    def test_green_note_alone_is_ignored(self) -> None:
        scheduler = PolicyScheduler(LANE_TOUCHES, SchedulerConfig())

        result = scheduler.update([tracked_note(4, "green_note", lane=2)], now=0.0)

        self.assertEqual(result.actions, [])

    def test_green_bar_moves_held_pointer(self) -> None:
        scheduler = PolicyScheduler(LANE_TOUCHES, SchedulerConfig())

        first = scheduler.update([tracked_note(50, "green_bar", lane=2, eta_seconds=None, track_y=1.0)], now=0.0)
        follow = scheduler.update([tracked_note(50, "green_bar", lane=3, eta_seconds=None, track_y=1.0)], now=0.050)

        self.assertEqual(action_kinds(first), ["down", "commit"])
        self.assertEqual(action_kinds(follow), ["move", "commit"])
        self.assertEqual((follow.actions[0].x, follow.actions[0].y), (130, 500))

    def test_green_bar_track_id_change_reuses_nearby_pointer(self) -> None:
        scheduler = PolicyScheduler(LANE_TOUCHES, SchedulerConfig())

        first = scheduler.update([tracked_note(50, "green_bar", lane=2, eta_seconds=None, track_y=1.0)], now=0.0)
        follow = scheduler.update([tracked_note(51, "green_bar", lane=2, eta_seconds=None, track_y=1.0)], now=0.050)

        self.assertEqual(action_kinds(first), ["down", "commit"])
        self.assertEqual(follow.actions, [])
        self.assertEqual(len(scheduler.pointer_pool.active_slots()), 1)

    def test_adjacent_green_bars_acquire_two_pointers(self) -> None:
        scheduler = PolicyScheduler(LANE_TOUCHES, SchedulerConfig())

        result = scheduler.update(
            [
                tracked_note(50, "green_bar", lane=2, eta_seconds=None, track_y=1.0),
                tracked_note(51, "green_bar", lane=3, eta_seconds=None, track_y=1.0),
            ],
            now=0.0,
        )

        self.assertEqual(action_kinds(result), ["down", "commit", "down", "commit"])
        self.assertEqual((result.actions[0].pointer_id, result.actions[0].lane), (0, 2))
        self.assertEqual((result.actions[2].pointer_id, result.actions[2].lane), (1, 3))

    def test_parallel_green_bars_keep_two_pointers_visible(self) -> None:
        scheduler = PolicyScheduler(LANE_TOUCHES, SchedulerConfig())

        scheduler.update(
            [
                tracked_note(50, "green_bar", lane=2, eta_seconds=None, track_y=1.0),
                tracked_note(51, "green_bar", lane=4, eta_seconds=None, track_y=1.0),
            ],
            now=0.0,
        )
        held = scheduler.update(
            [
                tracked_note(50, "green_bar", lane=2, eta_seconds=None, track_y=1.0),
                tracked_note(51, "green_bar", lane=4, eta_seconds=None, track_y=1.0),
            ],
            now=0.050,
        )

        self.assertEqual(held.actions, [])
        self.assertEqual(len(scheduler.pointer_pool.active_slots()), 2)

    def test_one_missing_parallel_bar_does_not_steal_other_bar(self) -> None:
        scheduler = PolicyScheduler(LANE_TOUCHES, SchedulerConfig())

        scheduler.update(
            [
                tracked_note(50, "green_bar", lane=2, eta_seconds=None, track_y=1.0),
                tracked_note(51, "green_bar", lane=4, eta_seconds=None, track_y=1.0),
            ],
            now=0.0,
        )
        held = scheduler.update([tracked_note(51, "green_bar", lane=4, eta_seconds=None, track_y=1.0)], now=0.050)

        self.assertEqual(held.actions, [])
        slots = sorted(scheduler.pointer_pool.active_slots(), key=lambda slot: slot.pointer_id)
        self.assertEqual([(slot.pointer_id, slot.lane, slot.x) for slot in slots], [(0, 2, 120), (1, 4, 140)])

    def test_green_bar_alone_triggers_touch(self) -> None:
        scheduler = PolicyScheduler(LANE_TOUCHES, SchedulerConfig())

        result = scheduler.update([tracked_note(50, "green_bar", lane=4, eta_seconds=None, track_y=1.0)], now=0.0)

        self.assertEqual(action_kinds(result), ["down", "commit"])

    def test_green_bar_ignored_when_far_from_judgment_line(self) -> None:
        scheduler = PolicyScheduler(LANE_TOUCHES, SchedulerConfig())

        follow = scheduler.update([tracked_note(50, "green_bar", lane=4, eta_seconds=None, track_y=0.50)], now=0.050)

        self.assertEqual(follow.actions, [])

    def test_missed_green_bar_does_not_move_pointer(self) -> None:
        scheduler = PolicyScheduler(LANE_TOUCHES, SchedulerConfig())
        missed_bar = tracked_note(50, "green_bar", lane=4, eta_seconds=None, track_y=1.0)
        missed_bar.missed_frames = 1

        scheduler.update([tracked_note(49, "green_bar", lane=2, eta_seconds=None, track_y=1.0)], now=0.0)
        follow = scheduler.update([missed_bar], now=0.050)

        self.assertEqual(follow.actions, [])

    def test_green_note_endpoint_releases_green_hold_after_arm(self) -> None:
        scheduler = PolicyScheduler(LANE_TOUCHES, SchedulerConfig())

        scheduler.update([tracked_note(50, "green_bar", lane=2, eta_seconds=None, track_y=1.0)], now=0.0)
        scheduler.update([tracked_note(50, "green_bar", lane=2, eta_seconds=None, track_y=1.0)], now=0.050)
        release = scheduler.update(
            [tracked_note(5, "green_note", lane=2, eta_seconds=0.040)],
            now=0.100,
        )

        self.assertEqual(action_kinds(release), ["up", "commit"])
        self.assertEqual(len(scheduler.pointer_pool.active_slots()), 0)

    def test_green_note_endpoint_waits_until_ready(self) -> None:
        scheduler = PolicyScheduler(LANE_TOUCHES, SchedulerConfig())

        scheduler.update([tracked_note(50, "green_bar", lane=2, eta_seconds=None, track_y=1.0)], now=0.0)
        scheduler.update([tracked_note(50, "green_bar", lane=2, eta_seconds=None, track_y=1.0)], now=0.050)
        held = scheduler.update([tracked_note(5, "green_note", lane=2, eta_seconds=0.200)], now=0.100)

        self.assertEqual(held.actions, [])

    def test_green_note_endpoint_without_eta_releases_by_track_y(self) -> None:
        scheduler = PolicyScheduler(LANE_TOUCHES, SchedulerConfig())

        scheduler.update([tracked_note(50, "green_bar", lane=2, eta_seconds=None, track_y=1.0)], now=0.0)
        scheduler.update([tracked_note(50, "green_bar", lane=2, eta_seconds=None, track_y=1.0)], now=0.050)
        release = scheduler.update([tracked_note(5, "green_note", lane=2, eta_seconds=None, track_y=1.0)], now=0.100)

        self.assertEqual(action_kinds(release), ["up", "commit"])

    def test_pre_bar_green_note_transition_does_not_release_hold(self) -> None:
        scheduler = PolicyScheduler(LANE_TOUCHES, SchedulerConfig(green_release_grace=0.120))

        scheduler.update([tracked_note(50, "green_bar", lane=2, eta_seconds=None, track_y=1.0)], now=0.0)
        held = scheduler.update([tracked_note(5, "green_note", lane=2, eta_seconds=0.040)], now=0.100)
        still_held = scheduler.update([], now=0.210)

        self.assertEqual(held.actions, [])
        self.assertEqual(still_held.actions, [])
        self.assertEqual(len(scheduler.pointer_pool.active_slots()), 1)

    def test_visible_green_bar_blocks_nearby_green_note_echo_release(self) -> None:
        scheduler = PolicyScheduler(LANE_TOUCHES, SchedulerConfig())

        scheduler.update([tracked_note(50, "green_bar", lane=2, eta_seconds=None, track_y=1.0)], now=0.0)
        held = scheduler.update(
            [
                tracked_note(50, "green_bar", lane=2, eta_seconds=None, track_y=1.0),
                tracked_note(5, "green_note", lane=2, eta_seconds=0.040),
            ],
            now=0.100,
        )

        self.assertEqual(held.actions, [])
        self.assertEqual(len(scheduler.pointer_pool.active_slots()), 1)

    def test_stable_green_note_terminal_can_release_while_green_bar_visible(self) -> None:
        scheduler = PolicyScheduler(LANE_TOUCHES, SchedulerConfig())

        scheduler.update([tracked_note(50, "green_bar", lane=2, eta_seconds=None, track_y=1.0)], now=0.0)
        scheduler.update([tracked_note(50, "green_bar", lane=2, eta_seconds=None, track_y=1.0)], now=0.050)
        release = scheduler.update(
            [
                tracked_note(50, "green_bar", lane=2, eta_seconds=None, track_y=1.0),
                tracked_note(5, "green_note", lane=2, eta_seconds=0.040, history_len=3),
            ],
            now=0.100,
        )

        self.assertEqual(action_kinds(release), ["up", "commit"])
        self.assertEqual(len(scheduler.pointer_pool.active_slots()), 0)

    def test_green_note_does_not_release_new_green_bar_same_frame(self) -> None:
        scheduler = PolicyScheduler(LANE_TOUCHES, SchedulerConfig())

        result = scheduler.update(
            [
                tracked_note(50, "green_bar", lane=2, eta_seconds=None, track_y=1.0),
                tracked_note(5, "green_note", lane=2, eta_seconds=0.040),
            ],
            now=0.0,
        )

        self.assertEqual(action_kinds(result), ["down", "commit"])

    def test_start_green_note_echo_does_not_release_after_arm(self) -> None:
        scheduler = PolicyScheduler(LANE_TOUCHES, SchedulerConfig())

        start = scheduler.update(
            [
                tracked_note(50, "green_bar", lane=2, eta_seconds=None, track_y=1.0),
                tracked_note(5, "green_note", lane=2, eta_seconds=0.040),
            ],
            now=0.0,
        )
        scheduler.update([tracked_note(50, "green_bar", lane=2, eta_seconds=None, track_y=1.0)], now=0.050)
        held = scheduler.update([tracked_note(5, "green_note", lane=2, eta_seconds=0.040)], now=0.100)
        release = scheduler.update([tracked_note(6, "green_note", lane=2, eta_seconds=0.040)], now=0.120)

        self.assertEqual(action_kinds(start), ["down", "commit"])
        self.assertEqual(held.actions, [])
        self.assertEqual(action_kinds(release), ["up", "commit"])

    def test_missed_green_note_endpoint_does_not_release(self) -> None:
        scheduler = PolicyScheduler(LANE_TOUCHES, SchedulerConfig())
        missed_endpoint = tracked_note(5, "green_note", lane=2, eta_seconds=0.040)
        missed_endpoint.missed_frames = 1

        scheduler.update([tracked_note(50, "green_bar", lane=2, eta_seconds=None, track_y=1.0)], now=0.0)
        scheduler.update([tracked_note(50, "green_bar", lane=2, eta_seconds=None, track_y=1.0)], now=0.050)
        held = scheduler.update([missed_endpoint], now=0.100)

        self.assertEqual(held.actions, [])

    def test_green_bar_releases_after_grace_after_follow(self) -> None:
        scheduler = PolicyScheduler(LANE_TOUCHES, SchedulerConfig(green_release_grace=0.120))

        scheduler.update([tracked_note(50, "green_bar", lane=2, eta_seconds=None, track_y=1.0)], now=0.0)
        scheduler.update([tracked_note(50, "green_bar", lane=3, eta_seconds=None, track_y=1.0)], now=0.030)
        release = scheduler.update([], now=0.151)

        self.assertEqual(action_kinds(release), ["up", "commit"])
        self.assertEqual((release.actions[0].x, release.actions[0].y), (130, 500))

    def test_recent_green_bar_survives_one_frame_missing_bar(self) -> None:
        scheduler = PolicyScheduler(LANE_TOUCHES, SchedulerConfig(green_release_grace=0.120))

        scheduler.update([tracked_note(50, "green_bar", lane=2, eta_seconds=None, track_y=1.0)], now=0.030)
        held = scheduler.update([], now=0.060)

        self.assertEqual(held.actions, [])

    def test_next_green_bar_does_not_release_held_pointer(self) -> None:
        scheduler = PolicyScheduler(LANE_TOUCHES, SchedulerConfig())

        scheduler.update([tracked_note(50, "green_bar", lane=2, eta_seconds=None, track_y=1.0)], now=0.0)
        held = scheduler.update(
            [
                tracked_note(50, "green_bar", lane=2, eta_seconds=None, track_y=1.0),
                tracked_note(51, "green_bar", lane=2, eta_seconds=0.040, track_y=1.0),
            ],
            now=0.100,
        )

        self.assertEqual(held.actions, [])
        self.assertEqual(len(scheduler.pointer_pool.active_slots()), 1)

    def test_ready_green_bar_keeps_holding_when_current_bar_missing(self) -> None:
        scheduler = PolicyScheduler(LANE_TOUCHES, SchedulerConfig())

        scheduler.update([tracked_note(50, "green_bar", lane=2, eta_seconds=None, track_y=1.0)], now=0.0)
        held = scheduler.update([tracked_note(51, "green_bar", lane=2, eta_seconds=0.040, track_y=1.0)], now=0.100)

        self.assertEqual(held.actions, [])
        self.assertEqual(len(scheduler.pointer_pool.active_slots()), 1)

    def test_unready_green_bar_id_change_keeps_holding(self) -> None:
        scheduler = PolicyScheduler(LANE_TOUCHES, SchedulerConfig())

        scheduler.update([tracked_note(50, "green_bar", lane=2, eta_seconds=None, track_y=1.0)], now=0.0)
        held = scheduler.update([tracked_note(51, "green_bar", lane=2, eta_seconds=None, track_y=1.0)], now=0.100)

        self.assertEqual(held.actions, [])
        self.assertEqual(len(scheduler.pointer_pool.active_slots()), 1)

    def test_green_endpoint_flick_reuses_held_pointer_without_down(self) -> None:
        scheduler = PolicyScheduler(LANE_TOUCHES, SchedulerConfig(flick_distance=100, flick_duration=0.100))

        scheduler.update([tracked_note(50, "green_bar", lane=3, eta_seconds=None, track_y=1.0)], now=0.0)
        start_flick = scheduler.update([tracked_note(5, "flick", lane=3, eta_seconds=0.060)], now=0.010)
        middle = scheduler.update([], now=0.060)
        release = scheduler.update([], now=0.111)

        self.assertEqual(start_flick.actions, [])
        self.assertEqual(action_kinds(middle), ["move", "commit"])
        self.assertEqual(action_kinds(release), ["move", "up", "commit"])
        self.assertEqual((middle.actions[0].x, middle.actions[0].y), (80, 500))
        self.assertEqual((release.actions[0].x, release.actions[0].y), (30, 500))

    def test_flick_endpoint_takes_priority_over_green_note_release(self) -> None:
        scheduler = PolicyScheduler(LANE_TOUCHES, SchedulerConfig(flick_distance=100, flick_duration=0.100))

        scheduler.update([tracked_note(50, "green_bar", lane=3, eta_seconds=None, track_y=1.0)], now=0.0)
        start_flick = scheduler.update(
            [
                tracked_note(5, "green_note", lane=3, eta_seconds=0.040),
                tracked_note(6, "flick", lane=3, eta_seconds=0.060),
            ],
            now=0.100,
        )
        middle = scheduler.update([], now=0.150)

        self.assertEqual(start_flick.actions, [])
        self.assertEqual(action_kinds(middle), ["move", "commit"])

    def test_late_note_is_not_backfilled(self) -> None:
        scheduler = PolicyScheduler(LANE_TOUCHES, SchedulerConfig())
        note = tracked_note(6, "tap", eta_seconds=-0.200)

        result = scheduler.update([note], now=0.0)
        retry = scheduler.update([tracked_note(6, "tap", eta_seconds=0.040)], now=0.01)

        self.assertEqual(result.actions, [])
        self.assertEqual(retry.actions, [])

    def test_no_free_pointer_warns_and_continues(self) -> None:
        scheduler = PolicyScheduler(LANE_TOUCHES, SchedulerConfig(max_pointers=1))

        result = scheduler.update([tracked_note(7, "tap", lane=1), tracked_note(8, "tap", lane=2)], now=0.0)

        self.assertEqual(action_kinds(result), ["down", "commit"])
        self.assertEqual(len(result.warnings), 1)


if __name__ == "__main__":
    unittest.main()
