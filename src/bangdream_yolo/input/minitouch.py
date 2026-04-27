"""Minimal minitouch client for multi-touch validation on MuMu."""

from __future__ import annotations

import shutil
import socket
import subprocess
import time
from pathlib import Path


MUMU_ADB_CANDIDATES = (
    Path("shell/adb.exe"),
    Path("shell/adb/adb.exe"),
    Path("nx_device/12.0/shell/adb.exe"),
    Path("nx_device/12.0/shell/adb/adb.exe"),
)

MINITOUCH_LOCAL_CANDIDATES = (
    Path("third_party/minitouch/minitouch"),
    Path("third_party/minitouch/minitouch.exe"),
    Path("third_party/minitouch/arm64-v8a/minitouch"),
    Path("third_party/minitouch/x86_64/minitouch"),
    Path("third_party/minitouch/x86/minitouch"),
)


class MinitouchError(RuntimeError):
    """Raised when minitouch cannot start or send touch commands."""


def find_adb_executable(mumu_path: Path) -> str | None:
    """Find adb from PATH first, then from known MuMu install locations."""

    adb_path = shutil.which("adb")
    if adb_path is not None:
        return adb_path

    for relative_path in MUMU_ADB_CANDIDATES:
        candidate = Path(mumu_path) / relative_path
        if candidate.exists():
            return str(candidate)
    return None


def find_minitouch_binary(project_root: Path) -> Path | None:
    """Return a local minitouch binary if one has been placed under third_party."""

    for relative_path in MINITOUCH_LOCAL_CANDIDATES:
        candidate = project_root / relative_path
        if candidate.exists():
            return candidate
    return None


class MinitouchClient:
    """Start minitouch through adb and send the plain text touch protocol."""

    def __init__(
        self,
        *,
        mumu_path: Path,
        adb_serial: str,
        project_root: Path,
        port: int = 1111,
        remote_path: str = "/data/local/tmp/minitouch",
    ):
        self.mumu_path = Path(mumu_path)
        self.adb_serial = adb_serial
        self.project_root = Path(project_root)
        self.port = port
        self.remote_path = remote_path
        self.process: subprocess.Popen[str] | None = None
        self.sock: socket.socket | None = None

        adb_path = find_adb_executable(self.mumu_path)
        if adb_path is None:
            raise MinitouchError("未找到 adb；请确认 MuMu 自带 adb 存在或 adb 在 PATH 中")
        self.adb_path = adb_path

    def __enter__(self) -> "MinitouchClient":
        self.start()
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()

    def adb(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        """Run adb with the configured serial."""

        command = [self.adb_path, "-s", self.adb_serial, *args]
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if check and completed.returncode != 0:
            output = (completed.stdout + completed.stderr).strip()
            raise MinitouchError(f"adb 命令失败：{' '.join(command)}\n{output}")
        return completed

    def push_binary(self) -> Path:
        """Push local minitouch binary to Android temporary directory."""

        binary = find_minitouch_binary(self.project_root)
        if binary is None:
            raise MinitouchError(
                "未找到 minitouch 二进制；请先运行 "
                "`python -m bangdream_yolo.tools.fetch_assets`"
            )

        self.adb("push", str(binary), self.remote_path)
        self.adb("shell", "chmod", "755", self.remote_path)
        return binary

    def start(self) -> None:
        """Start minitouch service, forward its socket, and connect locally."""

        if self.sock is not None:
            return

        self.push_binary()
        self.adb("forward", f"tcp:{self.port}", "localabstract:minitouch")

        self.process = subprocess.Popen(
            [self.adb_path, "-s", self.adb_serial, "shell", self.remote_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        # minitouch needs a short moment to create localabstract:minitouch.
        last_error: OSError | None = None
        for _ in range(30):
            try:
                self.sock = socket.create_connection(("127.0.0.1", self.port), timeout=0.2)
                self.sock.settimeout(1.0)
                self._read_banner()
                return
            except OSError as exc:
                last_error = exc
                time.sleep(0.1)

        self.close()
        raise MinitouchError(f"连接 minitouch socket 失败：{last_error}")

    def _read_banner(self) -> None:
        """Consume the initial minitouch banner so later writes are predictable."""

        if self.sock is None:
            raise MinitouchError("minitouch socket 尚未连接")
        try:
            self.sock.recv(1024)
        except socket.timeout:
            # Some builds do not send the banner promptly; commands can still work.
            pass

    def send(self, command: str) -> None:
        """Send one raw minitouch protocol line."""

        if self.sock is None:
            raise MinitouchError("minitouch socket 尚未连接")
        self.sock.sendall(command.encode("ascii"))

    def down(self, pointer_id: int, x: int, y: int, pressure: int = 50) -> None:
        """Press one pointer without committing the frame."""

        self.send(f"d {pointer_id} {int(x)} {int(y)} {int(pressure)}\n")

    def move(self, pointer_id: int, x: int, y: int, pressure: int = 50) -> None:
        """Move one pointer without committing the frame."""

        self.send(f"m {pointer_id} {int(x)} {int(y)} {int(pressure)}\n")

    def up(self, pointer_id: int) -> None:
        """Release one pointer without committing the frame."""

        self.send(f"u {pointer_id}\n")

    def commit(self) -> None:
        """Commit all queued pointer changes as one input frame."""

        self.send("c\n")

    def tap(self, pointer_id: int, x: int, y: int, duration: float = 0.03) -> None:
        """Tap with one pointer using two committed frames."""

        self.down(pointer_id, x, y)
        self.commit()
        time.sleep(duration)
        self.up(pointer_id)
        self.commit()

    def close(self) -> None:
        """Release socket, adb forward, and the minitouch shell process."""

        if self.sock is not None:
            self.sock.close()
            self.sock = None

        self.adb("forward", "--remove", f"tcp:{self.port}", check=False)

        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None
