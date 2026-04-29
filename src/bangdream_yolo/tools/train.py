"""Train the first BangDream YOLO model with Ultralytics."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path


def configure_ultralytics_cache() -> Path:
    """Keep Ultralytics settings/cache writes inside the local workspace."""

    cache_dir = Path(".cache") / "ultralytics"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("YOLO_CONFIG_DIR", str(cache_dir.resolve()))
    return cache_dir


def import_yolo():
    """Import Ultralytics YOLO with a clear dependency error."""

    configure_ultralytics_cache()
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise SystemExit("未安装 ultralytics；请先运行 `pip install -r requirements.txt`") from exc
    return YOLO


def best_weight_path(train_result: object, model: object) -> Path | None:
    """Find best.pt from Ultralytics result/trainer objects."""

    save_dir = getattr(train_result, "save_dir", None)
    if save_dir is None:
        trainer = getattr(model, "trainer", None)
        save_dir = getattr(trainer, "save_dir", None)
    if save_dir is None:
        return None

    best_path = Path(save_dir) / "weights" / "best.pt"
    return best_path if best_path.exists() else None


def main() -> int:
    """CLI entry for m4 training."""

    if os.name == "nt":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Train BangDream YOLO with Ultralytics.")
    parser.add_argument("--data", type=Path, default=Path("data/dataset.yaml"), help="Dataset yaml.")
    parser.add_argument("--model", default="yolov8n.pt", help="Base YOLO model or local weight path.")
    parser.add_argument("--epochs", type=int, default=5, help="Training epochs.")
    parser.add_argument("--imgsz", type=int, default=640, help="Training image size.")
    parser.add_argument("--batch", type=int, default=8, help="Batch size.")
    parser.add_argument("--project", type=Path, default=Path("runs/train"), help="Output project dir.")
    parser.add_argument("--name", default="m4_smoke", help="Run name under project dir.")
    parser.add_argument(
        "--device",
        default="auto",
        help="Ultralytics device value. Use auto to let Ultralytics choose.",
    )
    parser.add_argument("--workers", type=int, default=0, help="DataLoader workers.")
    parser.add_argument("--copy-best", type=Path, default=None, help="Optional destination for best.pt.")
    parser.add_argument("--exist-ok", action="store_true", help="Allow reusing an existing run name.")
    args = parser.parse_args()

    if not args.data.exists():
        raise SystemExit(f"数据集配置不存在：{args.data}")
    if args.epochs <= 0:
        raise SystemExit("--epochs must be > 0")
    if args.batch <= 0:
        raise SystemExit("--batch must be > 0")

    YOLO = import_yolo()
    model = YOLO(args.model)

    train_kwargs = {
        "data": str(args.data),
        "epochs": args.epochs,
        "imgsz": args.imgsz,
        "batch": args.batch,
        "project": str(args.project.resolve()),
        "name": args.name,
        "workers": args.workers,
        "exist_ok": args.exist_ok,
    }
    if args.device != "auto":
        train_kwargs["device"] = args.device

    print("BangDream YOLO m4 training")
    print(f"data: {args.data}")
    print(f"model: {args.model}")
    print(f"epochs: {args.epochs}")
    print(f"imgsz: {args.imgsz}")
    print(f"batch: {args.batch}")
    print(f"device: {args.device}")

    result = model.train(**train_kwargs)
    best_path = best_weight_path(result, model)

    if best_path is None:
        print("未找到 best.pt；请检查 Ultralytics 输出目录。")
    else:
        print(f"best.pt: {best_path}")
        if args.copy_best is not None:
            args.copy_best.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(best_path, args.copy_best)
            print(f"copied best.pt -> {args.copy_best}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
