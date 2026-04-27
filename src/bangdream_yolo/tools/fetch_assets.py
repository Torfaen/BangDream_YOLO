"""Download external assets that are intentionally kept out of Git."""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from bangdream_yolo.config import load_config
from bangdream_yolo.input.minitouch import find_adb_executable


MINITOUCH_VERSION = "1.2.0"
MINITOUCH_PACKAGE = "minitouch-prebuilt"
MINITOUCH_BASE_URLS = (
    f"https://cdn.jsdelivr.net/npm/{MINITOUCH_PACKAGE}@{MINITOUCH_VERSION}/prebuilt",
    f"https://unpkg.com/{MINITOUCH_PACKAGE}@{MINITOUCH_VERSION}/prebuilt",
)

MINITOUCH_SHA256 = {
    "x86_64": "31aa8eb22f78f3ee4ce47ac7315847009f0e8eefa0f694c6a96d9bcced219013",
}


@dataclass(frozen=True)
class AssetResult:
    """Downloaded or skipped asset metadata for console reporting."""

    name: str
    path: Path
    size: int
    sha256: str
    status: str


def project_root() -> Path:
    """Return repository root based on this source file location."""

    return Path(__file__).resolve().parents[3]


def sha256_file(path: Path) -> str:
    """Calculate SHA256 without loading the whole file into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_device_abi(mumu_path: Path, adb_serial: str) -> str | None:
    """Read Android ABI through adb, returning None if adb is unavailable."""

    adb_path = find_adb_executable(mumu_path)
    if adb_path is None:
        return None

    completed = subprocess.run(
        [adb_path, "-s", adb_serial, "shell", "getprop", "ro.product.cpu.abi"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        return None

    abi = completed.stdout.strip()
    return abi or None


def minitouch_url(abi: str, filename: str = "minitouch", mirror_index: int = 0) -> str:
    """Build the minitouch-prebuilt URL for one ABI."""

    base_url = MINITOUCH_BASE_URLS[mirror_index]
    return f"{base_url}/{abi}/bin/{filename}"


def minitouch_target(root: Path, abi: str, filename: str = "minitouch") -> Path:
    """Return the local target path used by MinitouchClient lookup."""

    return root / "third_party" / "minitouch" / abi / filename


def download_file(urls: list[str], target: Path) -> None:
    """Download from the first reachable URL into target."""

    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target.with_suffix(target.suffix + ".tmp")
    errors: list[str] = []

    for url in urls:
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                temp_path.write_bytes(response.read())
            temp_path.replace(target)
            return
        except (OSError, urllib.error.URLError) as exc:
            errors.append(f"{url}: {exc}")

    raise RuntimeError("下载失败：\n" + "\n".join(errors))


def fetch_minitouch(root: Path, abi: str, force: bool = False) -> AssetResult:
    """Download the minitouch binary for one Android ABI."""

    target = minitouch_target(root, abi)
    if target.exists() and not force:
        file_hash = sha256_file(target)
        return AssetResult("minitouch", target, target.stat().st_size, file_hash, "skipped")

    urls = [minitouch_url(abi, mirror_index=index) for index in range(len(MINITOUCH_BASE_URLS))]
    download_file(urls, target)
    file_hash = sha256_file(target)

    expected_hash = MINITOUCH_SHA256.get(abi)
    if expected_hash is not None and file_hash.lower() != expected_hash.lower():
        target.unlink(missing_ok=True)
        raise RuntimeError(
            f"minitouch SHA256 校验失败：expected={expected_hash}, actual={file_hash}"
        )

    return AssetResult("minitouch", target, target.stat().st_size, file_hash, "downloaded")


def print_result(result: AssetResult) -> None:
    """Print one asset result in a stable, copyable format."""

    print(f"[{result.status}] {result.name}")
    print(f"  path: {result.path}")
    print(f"  size: {result.size} bytes")
    print(f"  sha256: {result.sha256}")


def main() -> int:
    """CLI entry for downloading project external assets."""

    if os.name == "nt":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Download BangDream YOLO external assets.")
    parser.add_argument(
        "--asset",
        choices=("all", "minitouch"),
        default="all",
        help="Asset to download. Defaults to all currently required assets.",
    )
    parser.add_argument("--abi", help="Android ABI, e.g. x86_64 or arm64-v8a.")
    parser.add_argument("--force", action="store_true", help="Redownload even if file exists.")
    args = parser.parse_args()

    config = load_config()
    root = project_root()
    abi = args.abi or read_device_abi(config.mumu_path, config.adb_serial)
    if abi is None:
        print("无法自动读取设备 ABI，请手动指定，例如：--abi x86_64")
        return 1

    print("BangDream YOLO 外置资源下载")
    print(f"project: {root}")
    print(f"abi: {abi}")
    print("")

    results: list[AssetResult] = []
    if args.asset in ("all", "minitouch"):
        results.append(fetch_minitouch(root, abi, force=args.force))

    for result in results:
        print_result(result)

    print("")
    print("外置资源准备完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
