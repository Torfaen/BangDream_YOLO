"""Split manually labeled YOLO samples into train/val/test folders."""

from __future__ import annotations

import argparse
import os
import random
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
SPLITS = ("train", "val", "test")


@dataclass(frozen=True)
class Sample:
    """One image and its same-stem YOLO label file."""

    image: Path
    label: Path


def collect_samples(images_dir: Path, labels_dir: Path) -> list[Sample]:
    """Collect samples that have both image and same-stem .txt label."""

    samples: list[Sample] = []
    for image in sorted(images_dir.iterdir()):
        if not image.is_file() or image.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        label = labels_dir / f"{image.stem}.txt"
        if label.exists():
            samples.append(Sample(image=image, label=label))
    return samples


def split_counts(total: int, train_ratio: float, val_ratio: float) -> tuple[int, int, int]:
    """Return integer train/val/test counts that sum to total."""

    train_count = int(total * train_ratio)
    val_count = int(total * val_ratio)
    test_count = total - train_count - val_count
    return train_count, val_count, test_count


def prepare_output(output_dir: Path, force: bool) -> None:
    """Create a clean YOLO output tree."""

    if output_dir.exists():
        if not force:
            raise FileExistsError(f"输出目录已存在；如需覆盖请加 --force：{output_dir}")
        shutil.rmtree(output_dir)

    for split in SPLITS:
        (output_dir / "images" / split).mkdir(parents=True, exist_ok=True)
        (output_dir / "labels" / split).mkdir(parents=True, exist_ok=True)


def copy_samples(samples: list[Sample], output_dir: Path, split: str) -> None:
    """Copy image/label sample pairs into one split."""

    for sample in samples:
        shutil.copy2(sample.image, output_dir / "images" / split / sample.image.name)
        shutil.copy2(sample.label, output_dir / "labels" / split / sample.label.name)


def main() -> int:
    """CLI entry for reproducible YOLO train/val/test splitting."""

    if os.name == "nt":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Split YOLO-labeled images into train/val/test.")
    parser.add_argument("--images", type=Path, required=True, help="Source image directory.")
    parser.add_argument("--labels", type=Path, required=True, help="Source YOLO label directory.")
    parser.add_argument("--output", type=Path, default=Path("data/labeled"), help="Output dataset root.")
    parser.add_argument("--train", type=float, default=0.8, help="Train split ratio.")
    parser.add_argument("--val", type=float, default=0.1, help="Validation split ratio.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed.")
    parser.add_argument("--force", action="store_true", help="Delete and recreate output directory.")
    args = parser.parse_args()

    if args.train <= 0 or args.val < 0 or args.train + args.val >= 1:
        raise SystemExit("比例错误：需要 0 < train，0 <= val，且 train + val < 1")
    if not args.images.exists():
        raise SystemExit(f"图片目录不存在：{args.images}")
    if not args.labels.exists():
        raise SystemExit(f"标签目录不存在：{args.labels}")

    samples = collect_samples(args.images, args.labels)
    if not samples:
        raise SystemExit("没有找到同时存在图片和同名 .txt 标签的样本")

    rng = random.Random(args.seed)
    rng.shuffle(samples)

    train_count, val_count, test_count = split_counts(len(samples), args.train, args.val)
    train_samples = samples[:train_count]
    val_samples = samples[train_count : train_count + val_count]
    test_samples = samples[train_count + val_count :]

    prepare_output(args.output, args.force)
    copy_samples(train_samples, args.output, "train")
    copy_samples(val_samples, args.output, "val")
    copy_samples(test_samples, args.output, "test")

    print("数据集划分完成")
    print(f"source images: {args.images}")
    print(f"source labels: {args.labels}")
    print(f"output: {args.output}")
    print(f"total: {len(samples)}")
    print(f"train: {len(train_samples)}")
    print(f"val: {len(val_samples)}")
    print(f"test: {len(test_samples)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
