"""Preview ETA policy actions with optional minitouch execution."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import cv2

from bangdream_yolo.capture.nemu_ipc import NemuIpc, NemuIpcError
from bangdream_yolo.config import load_config
from bangdream_yolo.detection.postprocess import postprocess_detections
from bangdream_yolo.geometry.calibration import DEFAULT_CALIBRATION_PATH, load_calibration
from bangdream_yolo.input.minitouch import MinitouchClient, MinitouchError
from bangdream_yolo.policy.scheduler import (
    PolicyScheduler,
    SchedulerConfig,
    TouchAction,
    lane_touch_map,
)
from bangdream_yolo.tools.debug_recorder import DebugRecorder
from bangdream_yolo.tools.live_preview import (
    create_window,
    current_window_image_size,
    draw_detections,
    draw_tracks,
    fit_window_size,
    import_yolo,
    letterbox_to_size,
)
from bangdream_yolo.tracker.note_tracker import NoteTracker


def action_text(action: TouchAction) -> str:
    """Return a compact console/overlay description for one action."""

    if action.kind == "commit":
        return "commit"
    return (
        f"{action.kind} p={action.pointer_id} "
        f"lane={action.lane} track={action.track_id} "
        f"{action.note_type} ({action.x},{action.y})"
    )


def apply_actions(client: MinitouchClient | None, actions: list[TouchAction]) -> None:
    """Send actions to minitouch when a client is present."""

    if client is None:
        return

    builder = client.command_builder()
    for action in actions:
        if action.kind == "down" and action.pointer_id is not None and action.x is not None and action.y is not None:
            builder.down(action.pointer_id, action.x, action.y, action.pressure)
        elif action.kind == "move" and action.pointer_id is not None and action.x is not None and action.y is not None:
            builder.move(action.pointer_id, action.x, action.y, action.pressure)
        elif action.kind == "up" and action.pointer_id is not None:
            builder.up(action.pointer_id)
        elif action.kind == "commit":
            builder.commit()
    client.send_builder(builder)


def apply_release_actions(client: MinitouchClient | None, actions: list[TouchAction]) -> None:
    """Best-effort release during shutdown without masking the real failure."""

    if client is None or not actions:
        return
    if client.sock is None:
        print("[policy warning] minitouch socket 已断开，跳过退出释放动作")
        return
    try:
        apply_actions(client, actions)
    except MinitouchError as exc:
        print(f"[policy warning] 退出释放动作发送失败：{exc}")


def draw_policy_actions(frame, actions: list[TouchAction], warnings: list[str], touch_enabled: bool) -> None:
    """Draw recent policy actions in the preview window."""

    mode = "TOUCH ON" if touch_enabled else "DRY RUN"
    lines = [mode, *[action_text(action) for action in actions[-4:]], *warnings[-2:]]
    y = 58
    for line in lines:
        cv2.putText(
            frame,
            line,
            (12, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        y += 22


def print_actions(actions: list[TouchAction], warnings: list[str], touch_enabled: bool) -> None:
    """Print dry-run or sent actions to the console."""

    prefix = "touch" if touch_enabled else "dry-run"
    for action in actions:
        print(f"[{prefix}] {action_text(action)}")
    for warning in warnings:
        print(f"[policy warning] {warning}")


def build_scheduler_config(args: argparse.Namespace) -> SchedulerConfig:
    """Build scheduler config from CLI flags."""

    return SchedulerConfig(
        latency_offset=args.latency_offset,
        tap_hold_seconds=args.tap_hold_seconds,
        flick_duration=args.flick_duration,
        flick_distance=args.flick_distance,
        flick_lead_seconds=args.flick_lead_seconds,
        trigger_window_before=args.trigger_window_before,
        trigger_window_after=args.trigger_window_after,
        green_release_grace=args.green_release_grace,
        green_bar_min_track_y=args.green_bar_min_track_y,
        green_bar_max_track_y=args.green_bar_max_track_y,
        green_slot_match_lanes=args.green_slot_match_lanes,
        green_bar_follow_lanes=args.green_bar_follow_lanes,
        green_terminal_arm_seconds=args.green_terminal_arm_seconds,
        green_start_echo_track_y=args.green_start_echo_track_y,
        pressure=args.pressure,
        max_pointers=args.max_pointers,
    )


def main() -> int:
    """CLI entry for m6 policy preview."""

    if os.name == "nt":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Live BangDream ETA policy preview.")
    parser.add_argument("--model", type=Path, default=Path("models/bangdream_yolo_m4_green_bar.pt"))
    parser.add_argument("--calibration", type=Path, default=DEFAULT_CALIBRATION_PATH)
    parser.add_argument("--conf", type=float, default=0.25, help="YOLO confidence threshold.")
    parser.add_argument("--imgsz", type=int, default=640, help="YOLO inference image size.")
    parser.add_argument("--device", default="auto", help="Ultralytics device value.")
    parser.add_argument("--duration", type=float, default=0.0, help="Seconds to run; 0 means until quit.")
    parser.add_argument("--max-fps", type=float, default=0.0, help="Optional preview FPS cap.")
    parser.add_argument("--window-name", default="BangDream YOLO policy preview")
    parser.add_argument("--window-width", type=int, default=1280)
    parser.add_argument("--window-height", type=int, default=720)
    parser.add_argument("--topmost", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Explicit no-touch mode; this is the default.")
    parser.add_argument("--enable-touch", action="store_true", help="Actually send minitouch actions.")
    parser.add_argument("--latency-offset", type=float, default=0.040)
    parser.add_argument("--tap-hold-seconds", type=float, default=0.030)
    parser.add_argument("--flick-duration", type=float, default=0.050)
    parser.add_argument("--flick-distance", type=int, default=100)
    parser.add_argument("--flick-lead-seconds", type=float, default=0.020)
    parser.add_argument("--trigger-window-before", type=float, default=0.025)
    parser.add_argument("--trigger-window-after", type=float, default=0.080)
    parser.add_argument("--green-release-grace", type=float, default=0.350)
    parser.add_argument("--green-bar-min-track-y", type=float, default=0.82)
    parser.add_argument("--green-bar-max-track-y", type=float, default=1.10)
    parser.add_argument("--green-slot-match-lanes", type=float, default=0.75)
    parser.add_argument("--green-bar-follow-lanes", type=float, default=1.35)
    parser.add_argument("--green-terminal-arm-seconds", type=float, default=0.080)
    parser.add_argument("--green-start-echo-track-y", type=float, default=0.080)
    parser.add_argument("--pressure", type=int, default=100)
    parser.add_argument("--max-pointers", type=int, default=10)
    parser.add_argument("--debug-log", action="store_true", help="Write structured debug logs under --debug-log-dir.")
    parser.add_argument("--debug-log-dir", type=Path, default=Path("logs"), help="Debug log root directory.")
    parser.add_argument(
        "--debug-log-screenshots",
        choices=("event", "all", "none"),
        default="event",
        help="Save debug screenshots for event frames, all sampled frames, or none.",
    )
    parser.add_argument("--debug-log-every", type=int, default=1, help="Screenshot interval when using --debug-log-screenshots all.")
    args = parser.parse_args()

    if not args.model.exists():
        raise SystemExit(f"模型不存在：{args.model}")
    if not args.calibration.exists():
        raise SystemExit(f"标定文件不存在：{args.calibration}；请先运行 `python -m bangdream_yolo.tools.calibrate`")
    if args.conf <= 0 or args.conf > 1:
        raise SystemExit("--conf must be in (0, 1]")
    if args.imgsz <= 0:
        raise SystemExit("--imgsz must be > 0")

    YOLO = import_yolo()
    model = YOLO(str(args.model))
    config = load_config()
    calibration = load_calibration(args.calibration)
    tracker = NoteTracker()
    scheduler = PolicyScheduler(lane_touch_map(calibration), build_scheduler_config(args))
    touch_enabled = args.enable_touch

    predict_kwargs = {
        "imgsz": args.imgsz,
        "conf": args.conf,
        "verbose": False,
    }
    if args.device != "auto":
        predict_kwargs["device"] = args.device

    frame_count = 0
    start = time.perf_counter()
    last_fps_update = start
    fps = 0.0
    min_interval = 1.0 / args.max_fps if args.max_fps > 0 else 0.0
    fallback_window_width = 320
    fallback_window_height = 180
    client: MinitouchClient | None = None
    debug_recorder: DebugRecorder | None = None

    if args.debug_log:
        debug_recorder = DebugRecorder(
            args.debug_log_dir,
            screenshot_mode=args.debug_log_screenshots,
            screenshot_every=args.debug_log_every,
        )
        debug_recorder.write_meta(
            {
                "tool": "policy_preview",
                "model": str(args.model),
                "calibration": str(args.calibration),
                "conf": args.conf,
                "imgsz": args.imgsz,
                "device": args.device,
                "touch_enabled": touch_enabled,
                "duration": args.duration,
                "max_fps": args.max_fps,
            }
        )
        print(f"[debug] logging to {debug_recorder.session_dir}")

    create_window(args.window_name, fallback_window_width, fallback_window_height, args.topmost)
    mode_text = "TOUCH ON (--enable-touch)" if touch_enabled else "dry-run"
    print(f"policy preview 已启动。模式：{mode_text}；按 q 或 Esc 退出。")

    try:
        if touch_enabled:
            client = MinitouchClient(
                mumu_path=config.mumu_path,
                adb_serial=config.adb_serial,
                project_root=Path(".").resolve(),
                port=config.minitouch_port,
                remote_path=config.minitouch_remote_path,
            )
            client.start()
            print(f"[minitouch] local port={client.port}, {client.banner.describe()}")

        with NemuIpc(config.mumu_path, config.instance_id, config.display_id) as ipc:
            resized_window = False
            while True:
                loop_start = time.perf_counter()
                if args.duration > 0 and loop_start - start >= args.duration:
                    break

                frame = ipc.screenshot()
                if not resized_window:
                    frame_height, frame_width = frame.shape[:2]
                    window_width, window_height = fit_window_size(
                        frame_width,
                        frame_height,
                        args.window_width,
                        args.window_height,
                    )
                    cv2.resizeWindow(args.window_name, window_width, window_height)
                    fallback_window_width = window_width
                    fallback_window_height = window_height
                    resized_window = True

                raw_frame = frame.copy() if debug_recorder is not None else None
                result = model.predict(frame, **predict_kwargs)[0]
                detections = postprocess_detections(result, calibration, args.conf)
                tracks = tracker.update(detections, loop_start)
                policy_result = scheduler.update(tracks, loop_start)
                print_actions(policy_result.actions, policy_result.warnings, touch_enabled)
                apply_actions(client, policy_result.actions)

                draw_detections(frame, result, model.names, fps)
                draw_tracks(frame, tracks)
                draw_policy_actions(frame, policy_result.actions, policy_result.warnings, touch_enabled)
                window_width, window_height = current_window_image_size(
                    args.window_name,
                    fallback_window_width,
                    fallback_window_height,
                )
                display_frame = letterbox_to_size(frame, window_width, window_height)
                cv2.imshow(args.window_name, display_frame)
                fallback_window_width = window_width
                fallback_window_height = window_height

                frame_count += 1
                now = time.perf_counter()
                if now - last_fps_update >= 0.5:
                    fps = frame_count / max(0.001, now - start)
                    last_fps_update = now

                key = cv2.waitKey(1) & 0xFF
                manual_snapshot = key == ord("s")
                if debug_recorder is not None:
                    debug_recorder.record_frame(
                        frame_index=frame_count,
                        timestamp=loop_start,
                        fps=fps,
                        touch_enabled=touch_enabled,
                        detections=detections,
                        tracks=tracks,
                        policy_result=policy_result,
                        green_holds=scheduler.debug_green_holds(),
                        raw_frame=raw_frame,
                        overlay_frame=frame,
                        manual_snapshot=manual_snapshot,
                    )
                if key in (27, ord("q")):
                    break

                if min_interval > 0:
                    elapsed = time.perf_counter() - loop_start
                    if elapsed < min_interval:
                        time.sleep(min_interval - elapsed)
    except (NemuIpcError, MinitouchError) as exc:
        print(f"policy preview 连接失败：{exc}")
        return 2
    finally:
        release_actions = scheduler.release_all()
        print_actions(release_actions, [], touch_enabled)
        apply_release_actions(client, release_actions)
        if client is not None:
            client.close()
        if debug_recorder is not None:
            debug_recorder.close()
        cv2.destroyAllWindows()

    elapsed = time.perf_counter() - start
    avg_fps = frame_count / elapsed if elapsed > 0 else 0.0
    print(f"policy preview 已退出：frames={frame_count}, avg_fps={avg_fps:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
