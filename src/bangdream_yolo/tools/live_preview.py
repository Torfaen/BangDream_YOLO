"""Show a live MuMu screenshot window with YOLO note detections."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from bangdream_yolo.capture.nemu_ipc import NemuIpc, NemuIpcError
from bangdream_yolo.config import load_config


DEFAULT_COLORS = {
    0: (80, 220, 255),
    1: (0, 215, 255),
    2: (255, 80, 220),
    3: (80, 255, 80),
}


def configure_ultralytics_cache() -> None:
    """Keep Ultralytics settings/cache writes inside the local workspace."""

    cache_dir = Path(".cache") / "ultralytics"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("YOLO_CONFIG_DIR", str(cache_dir.resolve()))


def import_yolo():
    """Import Ultralytics YOLO after configuring its writable settings path."""

    configure_ultralytics_cache()
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise SystemExit("未安装 ultralytics；请先运行 `pip install -r requirements.txt`") from exc
    return YOLO


def class_name(names: object, class_id: int) -> str:
    """Return a display name from Ultralytics names metadata."""

    if isinstance(names, dict):
        return str(names.get(class_id, class_id))
    if isinstance(names, list) and 0 <= class_id < len(names):
        return str(names[class_id])
    return str(class_id)


def draw_detections(frame, result, names: object, fps: float) -> None:
    """Draw boxes, labels, and FPS directly onto a BGR frame."""

    for box in result.boxes:
        x1, y1, x2, y2 = [int(value) for value in box.xyxy[0].tolist()]
        class_id = int(box.cls[0])
        confidence = float(box.conf[0])
        color = DEFAULT_COLORS.get(class_id, (255, 255, 255))
        label = f"{class_name(names, class_id)} {confidence:.2f}"

        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        cv2.putText(
            frame,
            label,
            (x1, max(18, y1 - 6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            2,
            cv2.LINE_AA,
        )

    cv2.putText(
        frame,
        f"FPS {fps:.1f} | q/Esc to stop",
        (12, 28),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )


def fit_window_size(
    image_width: int,
    image_height: int,
    max_width: int,
    max_height: int,
) -> tuple[int, int]:
    """Fit an image into a bounding box while preserving aspect ratio."""

    if max_width <= 0 and max_height <= 0:
        return image_width, image_height
    if max_width <= 0:
        scale = max_height / image_height
    elif max_height <= 0:
        scale = max_width / image_width
    else:
        scale = min(max_width / image_width, max_height / image_height)
    scale = max(0.1, scale)
    return max(1, int(image_width * scale)), max(1, int(image_height * scale))


def current_window_image_size(name: str, fallback_width: int, fallback_height: int) -> tuple[int, int]:
    """Return the current OpenCV image area size, with a safe fallback."""

    try:
        _x, _y, width, height = cv2.getWindowImageRect(name)
    except cv2.error:
        return fallback_width, fallback_height

    if width <= 0 or height <= 0:
        return fallback_width, fallback_height
    return width, height


def letterbox_to_size(image: np.ndarray, target_width: int, target_height: int) -> np.ndarray:
    """Center an image in a black canvas without changing its aspect ratio."""

    source_height, source_width = image.shape[:2]
    if target_width <= 0 or target_height <= 0 or source_width <= 0 or source_height <= 0:
        return image

    scale = min(target_width / source_width, target_height / source_height)
    scaled_width = max(1, int(round(source_width * scale)))
    scaled_height = max(1, int(round(source_height * scale)))
    interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
    resized = cv2.resize(image, (scaled_width, scaled_height), interpolation=interpolation)

    if image.ndim == 2:
        canvas = np.zeros((target_height, target_width), dtype=image.dtype)
    else:
        canvas = np.zeros((target_height, target_width, image.shape[2]), dtype=image.dtype)

    x_offset = (target_width - scaled_width) // 2
    y_offset = (target_height - scaled_height) // 2
    canvas[y_offset : y_offset + scaled_height, x_offset : x_offset + scaled_width] = resized
    return canvas


def create_window(name: str, width: int, height: int, topmost: bool) -> None:
    """Create and size the OpenCV preview window."""

    cv2.namedWindow(name, cv2.WINDOW_NORMAL | cv2.WINDOW_FREERATIO)
    try:
        cv2.setWindowProperty(name, cv2.WND_PROP_ASPECT_RATIO, cv2.WINDOW_FREERATIO)
    except cv2.error:
        pass
    cv2.resizeWindow(name, width, height)
    if topmost:
        try:
            cv2.setWindowProperty(name, cv2.WND_PROP_TOPMOST, 1)
        except cv2.error:
            pass


def main() -> int:
    """CLI entry for live detection preview."""

    if os.name == "nt":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Live MuMu YOLO detection preview.")
    parser.add_argument("--model", type=Path, default=Path("models/bangdream_yolo_m4.pt"))
    parser.add_argument("--conf", type=float, default=0.25, help="YOLO confidence threshold.")
    parser.add_argument("--imgsz", type=int, default=640, help="YOLO inference image size.")
    parser.add_argument(
        "--device",
        default="auto",
        help="Ultralytics device value. Use auto to let Ultralytics choose.",
    )
    parser.add_argument("--duration", type=float, default=0.0, help="Seconds to run; 0 means until quit.")
    parser.add_argument("--max-fps", type=float, default=0.0, help="Optional preview FPS cap.")
    parser.add_argument("--window-name", default="BangDream YOLO live preview")
    parser.add_argument("--window-width", type=int, default=1280, help="Preview max width; 0 uses source width.")
    parser.add_argument("--window-height", type=int, default=720, help="Preview max height; 0 uses source height.")
    parser.add_argument("--topmost", action="store_true", help="Keep the OpenCV window on top.")
    args = parser.parse_args()

    if not args.model.exists():
        raise SystemExit(f"模型不存在：{args.model}")
    if args.conf <= 0 or args.conf > 1:
        raise SystemExit("--conf must be in (0, 1]")
    if args.imgsz <= 0:
        raise SystemExit("--imgsz must be > 0")

    YOLO = import_yolo()
    model = YOLO(str(args.model))
    config = load_config()

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

    create_window(args.window_name, fallback_window_width, fallback_window_height, args.topmost)
    print("实时预览已启动。按 q 或 Esc 退出；本工具不会触发任何触控输入。")

    try:
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

                result = model.predict(frame, **predict_kwargs)[0]
                draw_detections(frame, result, model.names, fps)
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
                if key in (27, ord("q")):
                    break

                if min_interval > 0:
                    elapsed = time.perf_counter() - loop_start
                    if elapsed < min_interval:
                        time.sleep(min_interval - elapsed)
    except NemuIpcError as exc:
        print(f"nemu_ipc 连接失败：{exc}")
        print("请确认：MuMu 实例已启动、游戏画面已打开、instance_id/display_id 配置正确。")
        print("如 ADB 未连接，可先运行 `python -m bangdream_yolo.tools.check_env` 查看详情。")
        return 2
    finally:
        cv2.destroyAllWindows()

    elapsed = time.perf_counter() - start
    avg_fps = frame_count / elapsed if elapsed > 0 else 0.0
    print(f"实时预览已退出：frames={frame_count}, avg_fps={avg_fps:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
