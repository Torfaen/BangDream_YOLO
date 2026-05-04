"""Convert X-AnyLabeling/LabelMe JSON annotations into YOLO dataset files."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


LABEL_TO_ID = {
    "tap": 0,
    "skill": 1,
    "flick": 2,
    "green_note": 3,
    "green_bar": 4,
}
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".webp")


@dataclass(frozen=True)
class ConvertedBox:
    """One normalized YOLO bbox line and its source label."""

    label: str
    line: str


@dataclass(frozen=True)
class ConvertedSample:
    """One converted image/label pair."""

    source_json: Path
    source_image: Path
    output_image: Path
    output_label: Path
    boxes: list[ConvertedBox]


def slugify(value: str) -> str:
    """Return a short ASCII slug for output filenames."""

    slug = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()
    return slug[:48] if slug else "src"


def iter_json_files(sources: list[Path]) -> list[tuple[Path, Path]]:
    """Return ``(source_root, json_path)`` pairs for all source annotations."""

    pairs: list[tuple[Path, Path]] = []
    for source in sources:
        if source.is_file():
            if source.suffix.lower() == ".json":
                pairs.append((source.parent, source))
            continue
        if not source.exists():
            raise FileNotFoundError(f"源路径不存在：{source}")
        for json_path in sorted(source.rglob("*.json")):
            pairs.append((source, json_path))
    return pairs


def image_for_json(json_path: Path, data: dict[str, Any]) -> Path:
    """Find the image referenced by a JSON annotation file."""

    image_path = data.get("imagePath")
    if isinstance(image_path, str) and image_path:
        candidate = json_path.parent / image_path
        if candidate.exists():
            return candidate

    for extension in IMAGE_EXTENSIONS:
        candidate = json_path.with_suffix(extension)
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"找不到对应图片：{json_path}")


def output_stem(source_root: Path, json_path: Path) -> str:
    """Build a deterministic unique output stem for a source annotation."""

    try:
        relative_parent = json_path.parent.relative_to(source_root)
    except ValueError:
        relative_parent = Path(source_root.name)
    if str(relative_parent) == ".":
        relative_parent = Path(source_root.name)

    relative_key = relative_parent.as_posix()
    digest = hashlib.sha1(relative_key.encode("utf-8")).hexdigest()[:8]
    return f"{slugify(relative_key)}_{digest}_{json_path.stem}"


def bbox_from_points(
    points: list[list[float]],
    image_width: int,
    image_height: int,
) -> tuple[float, float, float, float] | None:
    """Convert arbitrary shape points into a clipped pixel-space bbox."""

    if not points:
        return None

    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    x_min = max(0.0, min(xs))
    y_min = max(0.0, min(ys))
    x_max = min(float(image_width), max(xs))
    y_max = min(float(image_height), max(ys))
    if x_max <= x_min or y_max <= y_min:
        return None
    return x_min, y_min, x_max, y_max


def yolo_line(
    class_id: int,
    bbox: tuple[float, float, float, float],
    image_width: int,
    image_height: int,
) -> str:
    """Format one bbox as a normalized YOLO label line."""

    x_min, y_min, x_max, y_max = bbox
    x_center = ((x_min + x_max) / 2.0) / image_width
    y_center = ((y_min + y_max) / 2.0) / image_height
    width = (x_max - x_min) / image_width
    height = (y_max - y_min) / image_height
    return f"{class_id} {x_center:.6f} {y_center:.6f} {width:.6f} {height:.6f}"


def convert_boxes(data: dict[str, Any], json_path: Path) -> tuple[list[ConvertedBox], int]:
    """Convert all valid shapes in one JSON annotation."""

    image_width = int(data["imageWidth"])
    image_height = int(data["imageHeight"])
    boxes: list[ConvertedBox] = []
    skipped = 0

    for shape in data.get("shapes", []):
        label = str(shape.get("label", ""))
        if label not in LABEL_TO_ID:
            raise ValueError(f"未知标签 {label!r}：{json_path}")

        points = shape.get("points", [])
        bbox = bbox_from_points(points, image_width, image_height)
        if bbox is None:
            skipped += 1
            continue

        boxes.append(
            ConvertedBox(
                label=label,
                line=yolo_line(LABEL_TO_ID[label], bbox, image_width, image_height),
            )
        )

    return boxes, skipped


def prepare_output(output_dir: Path, force: bool) -> tuple[Path, Path]:
    """Create image and label output directories."""

    if output_dir.exists():
        if not force:
            raise FileExistsError(f"输出目录已存在；如需覆盖请加 --force：{output_dir}")
        shutil.rmtree(output_dir)

    images_dir = output_dir / "images"
    labels_dir = output_dir / "labels"
    images_dir.mkdir(parents=True, exist_ok=True)
    labels_dir.mkdir(parents=True, exist_ok=True)
    return images_dir, labels_dir


def convert_annotations(
    sources: list[Path],
    output_dir: Path,
    force: bool = False,
) -> tuple[list[ConvertedSample], dict[str, int], int]:
    """Convert annotation JSON files and copy their images."""

    json_pairs = iter_json_files(sources)
    if not json_pairs:
        raise FileNotFoundError("没有找到 JSON 标注文件")

    images_dir, labels_dir = prepare_output(output_dir, force)
    samples: list[ConvertedSample] = []
    counts = {label: 0 for label in LABEL_TO_ID}
    skipped_boxes = 0
    used_stems: set[str] = set()

    for source_root, json_path in json_pairs:
        with json_path.open("r", encoding="utf-8-sig") as file:
            data = json.load(file)

        image_path = image_for_json(json_path, data)
        stem = output_stem(source_root, json_path)
        if stem in used_stems:
            raise ValueError(f"输出文件名冲突：{stem}")
        used_stems.add(stem)

        boxes, skipped = convert_boxes(data, json_path)
        skipped_boxes += skipped
        for box in boxes:
            counts[box.label] += 1

        output_image = images_dir / f"{stem}{image_path.suffix.lower()}"
        output_label = labels_dir / f"{stem}.txt"
        shutil.copy2(image_path, output_image)
        output_label.write_text(
            "\n".join(box.line for box in boxes) + ("\n" if boxes else ""),
            encoding="utf-8",
        )
        samples.append(
            ConvertedSample(
                source_json=json_path,
                source_image=image_path,
                output_image=output_image,
                output_label=output_label,
                boxes=boxes,
            )
        )

    return samples, counts, skipped_boxes


def main() -> int:
    """CLI entry for JSON annotation conversion."""

    if os.name == "nt":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Convert JSON annotations to YOLO txt labels.")
    parser.add_argument(
        "--source",
        type=Path,
        action="append",
        required=True,
        help="Source JSON file or directory. Can be passed multiple times.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/annotated"),
        help="Output root with images/ and labels/ subdirectories.",
    )
    parser.add_argument("--force", action="store_true", help="Delete and recreate output root.")
    args = parser.parse_args()

    samples, counts, skipped_boxes = convert_annotations(args.source, args.output, args.force)

    print("标注转换完成")
    print(f"output: {args.output}")
    print(f"samples: {len(samples)}")
    print(f"skipped boxes: {skipped_boxes}")
    for label, class_id in sorted(LABEL_TO_ID.items(), key=lambda item: item[1]):
        print(f"{class_id} {label}: {counts[label]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
