"""Interactively calibrate BangDream lane geometry from one MuMu screenshot."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import cv2

from bangdream_yolo.android import AdbError, read_wm_size
from bangdream_yolo.capture.nemu_ipc import NemuIpc
from bangdream_yolo.config import load_config
from bangdream_yolo.geometry.calibration import (
    DEFAULT_CALIBRATION_PATH,
    POINT_NAMES,
    Calibration,
    Point,
    infer_touch_rotation,
    save_calibration,
)
from bangdream_yolo.geometry.lane import lane_touch_points


POINT_LABELS = {
    "judge_left": "判定线左端",
    "judge_right": "判定线右端",
    "track_top_left": "远端轨道左边界",
    "track_top_right": "远端轨道右边界",
}


class ClickState:
    """Mouse-click state for collecting calibration points."""

    def __init__(self) -> None:
        self.points: dict[str, Point] = {}

    @property
    def next_name(self) -> str | None:
        if len(self.points) >= len(POINT_NAMES):
            return None
        return POINT_NAMES[len(self.points)]

    def add_point(self, x: int, y: int) -> None:
        name = self.next_name
        if name is not None:
            self.points[name] = Point(float(x), float(y))

    def reset(self) -> None:
        self.points.clear()


def draw_overlay(image, state: ClickState):
    """Draw collected points and the current instruction on a screenshot."""

    view = image.copy()
    for name, point in state.points.items():
        center = (int(point.x), int(point.y))
        cv2.circle(view, center, 6, (0, 0, 255), -1)
        cv2.putText(
            view,
            name,
            (center[0] + 8, center[1] - 8),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 0, 255),
            1,
            cv2.LINE_AA,
        )

    if len(state.points) >= 2:
        left = state.points.get("judge_left")
        right = state.points.get("judge_right")
        if left is not None and right is not None:
            cv2.line(
                view,
                (int(left.x), int(left.y)),
                (int(right.x), int(right.y)),
                (0, 255, 255),
                2,
            )

    next_name = state.next_name
    message = "已收集 4 点，按 s 保存；r 重置；q 退出"
    if next_name is not None:
        message = f"点击：{POINT_LABELS[next_name]} ({next_name})；r 重置；q 退出"

    cv2.rectangle(view, (0, 0), (view.shape[1], 32), (0, 0, 0), -1)
    cv2.putText(
        view,
        message,
        (10, 22),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    return view


def mouse_callback(event: int, x: int, y: int, flags: int, userdata: ClickState) -> None:
    """Handle left-click point collection."""

    if event == cv2.EVENT_LBUTTONDOWN:
        userdata.add_point(x, y)


def print_lane_points(calibration: Calibration) -> None:
    """Print lane judgment centers in capture and touch coordinates."""

    print("lane 判定线中心：")
    for lane, capture_point, touch_point in lane_touch_points(calibration):
        print(
            f"  lane {lane}: "
            f"capture=({capture_point.x:.1f}, {capture_point.y:.1f}) "
            f"touch=({touch_point.x:.1f}, {touch_point.y:.1f})"
        )


def main() -> int:
    """Run the OpenCV-based calibration flow."""

    if os.name == "nt":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Calibrate BangDream lane geometry.")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_CALIBRATION_PATH,
        help="Calibration YAML output path.",
    )
    parser.add_argument(
        "--rotation",
        choices=("auto", "none", "clockwise", "counterclockwise", "transpose"),
        default="auto",
        help="Touch coordinate rotation relative to capture coordinates.",
    )
    args = parser.parse_args()

    config = load_config()
    with NemuIpc(config.mumu_path, config.instance_id, config.display_id) as ipc:
        image = ipc.screenshot()

    capture_height, capture_width = image.shape[:2]
    try:
        touch_width, touch_height = read_wm_size(config.mumu_path, config.adb_serial)
    except AdbError as exc:
        print(f"读取 touch 分辨率失败：{exc}")
        touch_width, touch_height = config.screen_width, config.screen_height
        print(f"回退使用配置分辨率：{touch_width}x{touch_height}")

    rotation = args.rotation
    if rotation == "auto":
        rotation = infer_touch_rotation((capture_width, capture_height), (touch_width, touch_height))

    print(f"capture 分辨率: {capture_width}x{capture_height}")
    print(f"touch 分辨率: {touch_width}x{touch_height}")
    print(f"touch.rotation: {rotation}")
    print("点击顺序：judge_left -> judge_right -> track_top_left -> track_top_right")

    state = ClickState()
    window_name = "BangDream calibration"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(window_name, mouse_callback, state)

    saved = False
    while True:
        cv2.imshow(window_name, draw_overlay(image, state))
        key = cv2.waitKey(30) & 0xFF
        if key == ord("r"):
            state.reset()
        elif key == ord("q") or key == 27:
            break
        elif key == ord("s"):
            if len(state.points) < len(POINT_NAMES):
                print("还没有收集完 4 个点，不能保存。")
                continue
            calibration = Calibration(
                capture_width=capture_width,
                capture_height=capture_height,
                touch_width=touch_width,
                touch_height=touch_height,
                touch_rotation=rotation,
                points=state.points,
            )
            save_calibration(calibration, args.output)
            print(f"已保存标定文件：{args.output}")
            print_lane_points(calibration)
            saved = True
            break

    cv2.destroyAllWindows()
    return 0 if saved else 1


if __name__ == "__main__":
    raise SystemExit(main())
