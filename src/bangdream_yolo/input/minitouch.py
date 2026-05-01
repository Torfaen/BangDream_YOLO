"""Minimal minitouch client for multi-touch validation on MuMu."""

from __future__ import annotations

from dataclasses import dataclass
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
DEFAULT_TOUCH_PRESSURE = 100


class MinitouchError(RuntimeError):
    """Raised when minitouch cannot start or send touch commands."""


@dataclass(frozen=True)
class AdbDevice:
    """One device row parsed from ``adb devices -l`` output."""

    serial: str
    status: str
    details: str = ""

    @property
    def is_online(self) -> bool:
        """Return True when adb reports the device as usable."""

        return self.status == "device"


@dataclass(frozen=True)
class MinitouchBanner:
    """Parsed minitouch startup banner and device limits."""

    version: int | None = None
    max_contacts: int | None = None
    max_x: int | None = None
    max_y: int | None = None
    max_pressure: int | None = None
    pid: int | None = None
    raw_text: str = ""

    @property
    def has_limits(self) -> bool:
        """Return True when touch bounds were parsed from the banner."""

        return (
            self.max_contacts is not None
            and self.max_x is not None
            and self.max_y is not None
            and self.max_pressure is not None
        )

    def describe(self) -> str:
        """Return one readable line for startup diagnostics."""

        if not self.raw_text.strip():
            return "未读取到 banner，无法校验 minitouch 坐标上限"

        fields = [
            f"version={self.version if self.version is not None else '?'}",
            f"max_contacts={self.max_contacts if self.max_contacts is not None else '?'}",
            f"max_x={self.max_x if self.max_x is not None else '?'}",
            f"max_y={self.max_y if self.max_y is not None else '?'}",
            f"max_pressure={self.max_pressure if self.max_pressure is not None else '?'}",
            f"pid={self.pid if self.pid is not None else '?'}",
        ]
        return "minitouch " + ", ".join(fields)


def parse_minitouch_banner(raw_text: str) -> MinitouchBanner:
    """Parse minitouch banner lines into device limits."""

    version: int | None = None
    max_contacts: int | None = None
    max_x: int | None = None
    max_y: int | None = None
    max_pressure: int | None = None
    pid: int | None = None

    for line in raw_text.splitlines():
        parts = line.strip().split()
        if not parts:
            continue
        try:
            if parts[0] == "v" and len(parts) >= 2:
                version = int(parts[1])
            elif parts[0] == "^" and len(parts) >= 5:
                max_contacts = int(parts[1])
                max_x = int(parts[2])
                max_y = int(parts[3])
                max_pressure = int(parts[4])
            elif parts[0] == "$" and len(parts) >= 2:
                pid = int(parts[1])
        except ValueError:
            continue

    return MinitouchBanner(
        version=version,
        max_contacts=max_contacts,
        max_x=max_x,
        max_y=max_y,
        max_pressure=max_pressure,
        pid=pid,
        raw_text=raw_text,
    )


class MinitouchCommandBuilder:
    """Build one minitouch payload before sending it to the socket."""

    def __init__(self, client: "MinitouchClient"):
        self.client = client
        self.lines: list[str] = []

    def down(
        self,
        pointer_id: int,
        x: int,
        y: int,
        pressure: int = DEFAULT_TOUCH_PRESSURE,
    ) -> "MinitouchCommandBuilder":
        """Add one pointer down command."""

        self.lines.append(self.client.format_down(pointer_id, x, y, pressure))
        return self

    def move(
        self,
        pointer_id: int,
        x: int,
        y: int,
        pressure: int = DEFAULT_TOUCH_PRESSURE,
    ) -> "MinitouchCommandBuilder":
        """Add one pointer move command."""

        self.lines.append(self.client.format_move(pointer_id, x, y, pressure))
        return self

    def up(self, pointer_id: int) -> "MinitouchCommandBuilder":
        """Add one pointer release command."""

        self.lines.append(self.client.format_up(pointer_id))
        return self

    def commit(self) -> "MinitouchCommandBuilder":
        """Add one frame commit command."""

        self.lines.append(self.client.format_commit())
        return self

    def wait(self, milliseconds: int) -> "MinitouchCommandBuilder":
        """Add a minitouch wait command in milliseconds."""

        if milliseconds < 0:
            raise MinitouchError(f"wait 毫秒数不能为负：{milliseconds}")
        self.lines.append(f"w {int(milliseconds)}\n")
        return self

    def build(self) -> str:
        """Return all queued minitouch commands."""

        return "".join(self.lines)

    def __bool__(self) -> bool:
        return bool(self.lines)


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


def parse_adb_devices(output: str) -> list[AdbDevice]:
    """Parse ``adb devices -l`` output into device records."""

    devices: list[AdbDevice] = []
    for line in output.splitlines():
        line = line.strip()
        if not line or line.lower().startswith("list of devices"):
            continue

        parts = line.split()
        if len(parts) < 2:
            continue

        devices.append(
            AdbDevice(
                serial=parts[0],
                status=parts[1],
                details=" ".join(parts[2:]),
            )
        )
    return devices


def list_adb_devices(adb_path: str) -> tuple[list[AdbDevice], str]:
    """Return parsed adb devices plus the raw command output."""

    completed = subprocess.run(
        [adb_path, "devices", "-l"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = (completed.stdout + completed.stderr).strip()
    if completed.returncode != 0:
        raise MinitouchError(f"adb devices 执行失败：{output}")
    return parse_adb_devices(output), output


def resolve_adb_serial(
    mumu_path: Path,
    preferred_serial: str,
    *,
    adb_path: str | None = None,
    quiet: bool = False,
) -> str:
    """Use preferred serial if online, otherwise choose the only online adb device."""

    resolved_adb_path = adb_path or find_adb_executable(mumu_path)
    if resolved_adb_path is None:
        raise MinitouchError("未找到 adb；请确认 MuMu 自带 adb 存在或 adb 在 PATH 中")

    devices, raw_output = list_adb_devices(resolved_adb_path)
    online_devices = [device for device in devices if device.is_online]

    for device in online_devices:
        if device.serial == preferred_serial:
            return preferred_serial

    if len(online_devices) == 1:
        resolved_serial = online_devices[0].serial
        if not quiet and resolved_serial != preferred_serial:
            print(f"[adb] configured serial {preferred_serial} is offline; using {resolved_serial}")
        return resolved_serial

    if not online_devices:
        raise MinitouchError(
            f"ADB 未发现在线设备；配置 serial={preferred_serial}\nadb devices 输出：\n{raw_output}"
        )

    choices = ", ".join(device.serial for device in online_devices)
    raise MinitouchError(
        "ADB 检测到多个在线设备，无法自动选择；"
        f"请设置 BANGDREAM_ADB_SERIAL。在线设备：{choices}"
    )


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
        self.configured_adb_serial = adb_serial
        self.project_root = Path(project_root)
        self.port = port
        self.remote_path = remote_path
        self.process: subprocess.Popen[str] | None = None
        self.sock: socket.socket | None = None
        self.banner = MinitouchBanner()

        adb_path = find_adb_executable(self.mumu_path)
        if adb_path is None:
            raise MinitouchError("未找到 adb；请确认 MuMu 自带 adb 存在或 adb 在 PATH 中")
        self.adb_path = adb_path
        self.adb_serial = resolve_adb_serial(
            self.mumu_path,
            adb_serial,
            adb_path=self.adb_path,
        )

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

    def stop_remote_process(self) -> None:
        """Best-effort cleanup for stale remote minitouch processes."""

        self.adb("shell", "pkill", "-f", self.remote_path, check=False)
        self.adb("shell", "pkill", "-f", "minitouch", check=False)
        time.sleep(0.1)

    def start(self) -> None:
        """Start minitouch service, forward its socket, and connect locally."""

        if self.sock is not None:
            return

        self.stop_remote_process()
        self.push_binary()
        self.adb("forward", "--remove", f"tcp:{self.port}", check=False)
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
        last_error: Exception | None = None
        for _ in range(50):
            try:
                self.sock = socket.create_connection(("127.0.0.1", self.port), timeout=0.2)
                self.sock.settimeout(1.0)
                self._read_banner()
                return
            except MinitouchError as exc:
                last_error = exc
                if self.sock is not None:
                    self.sock.close()
                    self.sock = None
                if self.process is not None and self.process.poll() is not None:
                    self.close()
                    raise
                time.sleep(0.1)
            except OSError as exc:
                last_error = exc
                if self.sock is not None:
                    self.sock.close()
                    self.sock = None
                time.sleep(0.1)

        self.close()
        raise MinitouchError(f"连接 minitouch socket 失败：{last_error}")

    def _read_banner(self) -> None:
        """Read and parse the initial minitouch banner."""

        if self.sock is None:
            raise MinitouchError("minitouch socket 尚未连接")

        chunks: list[bytes] = []
        previous_timeout = self.sock.gettimeout()
        deadline = time.monotonic() + 1.0
        try:
            self.sock.settimeout(0.2)
            while time.monotonic() < deadline:
                try:
                    chunk = self.sock.recv(4096)
                except socket.timeout:
                    if chunks:
                        break
                    continue

                if not chunk:
                    detail = self._finished_process_output()
                    message = "minitouch socket 在 banner 阶段关闭"
                    if detail:
                        message = f"{message}\nminitouch 进程输出：\n{detail}"
                    raise MinitouchError(message)

                chunks.append(chunk)
                raw_text = b"".join(chunks).decode("utf-8", errors="replace")
                banner = parse_minitouch_banner(raw_text)
                if banner.has_limits and banner.pid is not None:
                    self.banner = banner
                    return
        finally:
            self.sock.settimeout(previous_timeout)

        raw_text = b"".join(chunks).decode("utf-8", errors="replace")
        self.banner = parse_minitouch_banner(raw_text)

    def send(self, command: str) -> None:
        """Send one raw minitouch protocol line."""

        if self.sock is None:
            raise MinitouchError("minitouch socket 尚未连接")
        try:
            self.sock.sendall(command.encode("ascii"))
        except OSError as exc:
            self.sock.close()
            self.sock = None
            detail = self._finished_process_output()
            message = f"minitouch socket 写入失败：{exc}"
            preview = command.replace("\n", "\\n")
            if len(preview) > 300:
                preview = preview[:300] + "..."
            message = f"{message}\n发送命令：{preview}"
            if detail:
                message = f"{message}\nminitouch 进程输出：\n{detail}"
            raise MinitouchError(message) from exc

    def command_builder(self) -> MinitouchCommandBuilder:
        """Create a builder for one batched minitouch payload."""

        return MinitouchCommandBuilder(self)

    def send_builder(self, builder: MinitouchCommandBuilder) -> None:
        """Send all commands queued in a builder."""

        if builder:
            self.send(builder.build())

    def _validate_pointer(self, pointer_id: int) -> int:
        """Validate and normalize a minitouch pointer id."""

        pointer_id = int(pointer_id)
        if pointer_id < 0:
            raise MinitouchError(f"pointer_id 不能为负：{pointer_id}")
        if self.banner.max_contacts is not None and pointer_id >= self.banner.max_contacts:
            raise MinitouchError(
                f"pointer_id 越界：{pointer_id}，minitouch max_contacts={self.banner.max_contacts}"
            )
        return pointer_id

    def _validate_touch(self, pointer_id: int, x: int, y: int, pressure: int) -> tuple[int, int, int, int]:
        """Validate one pointer command against minitouch banner limits."""

        pointer_id = self._validate_pointer(pointer_id)
        x = int(x)
        y = int(y)
        pressure = int(pressure)

        if x < 0:
            raise MinitouchError(f"touch x 不能为负：{x}")
        if y < 0:
            raise MinitouchError(f"touch y 不能为负：{y}")
        if pressure < 0:
            raise MinitouchError(f"touch pressure 不能为负：{pressure}")

        if self.banner.max_x is not None and x > self.banner.max_x:
            raise MinitouchError(f"touch x 越界：{x}，minitouch max_x={self.banner.max_x}")
        if self.banner.max_y is not None and y > self.banner.max_y:
            raise MinitouchError(f"touch y 越界：{y}，minitouch max_y={self.banner.max_y}")
        if (
            self.banner.max_pressure is not None
            and self.banner.max_pressure > 0
            and pressure > self.banner.max_pressure
        ):
            raise MinitouchError(
                f"touch pressure 越界：{pressure}，minitouch max_pressure={self.banner.max_pressure}"
            )

        return pointer_id, x, y, pressure

    def format_down(self, pointer_id: int, x: int, y: int, pressure: int = DEFAULT_TOUCH_PRESSURE) -> str:
        """Return one validated minitouch down command."""

        pointer_id, x, y, pressure = self._validate_touch(pointer_id, x, y, pressure)
        return f"d {pointer_id} {x} {y} {pressure}\n"

    def format_move(self, pointer_id: int, x: int, y: int, pressure: int = DEFAULT_TOUCH_PRESSURE) -> str:
        """Return one validated minitouch move command."""

        pointer_id, x, y, pressure = self._validate_touch(pointer_id, x, y, pressure)
        return f"m {pointer_id} {x} {y} {pressure}\n"

    def format_up(self, pointer_id: int) -> str:
        """Return one validated minitouch up command."""

        pointer_id = self._validate_pointer(pointer_id)
        return f"u {pointer_id}\n"

    def format_commit(self) -> str:
        """Return one minitouch commit command."""

        return "c\n"

    def _finished_process_output(self) -> str:
        """Return adb shell output if the minitouch process has already exited."""

        process = getattr(self, "process", None)
        if process is None or process.poll() is None:
            return ""
        try:
            stdout, stderr = process.communicate(timeout=0.2)
        except subprocess.TimeoutExpired:
            return ""
        output = "\n".join(part.strip() for part in (stdout, stderr) if part and part.strip())
        if len(output) > 1200:
            return output[-1200:]
        return output

    def down(self, pointer_id: int, x: int, y: int, pressure: int = DEFAULT_TOUCH_PRESSURE) -> None:
        """Press one pointer without committing the frame."""

        self.send(self.format_down(pointer_id, x, y, pressure))

    def move(self, pointer_id: int, x: int, y: int, pressure: int = DEFAULT_TOUCH_PRESSURE) -> None:
        """Move one pointer without committing the frame."""

        self.send(self.format_move(pointer_id, x, y, pressure))

    def up(self, pointer_id: int) -> None:
        """Release one pointer without committing the frame."""

        self.send(self.format_up(pointer_id))

    def commit(self) -> None:
        """Commit all queued pointer changes as one input frame."""

        self.send(self.format_commit())

    def tap(
        self,
        pointer_id: int,
        x: int,
        y: int,
        duration: float = 0.05,
        pressure: int = DEFAULT_TOUCH_PRESSURE,
    ) -> None:
        """Tap with one ALAS-style batched minitouch payload."""

        builder = self.command_builder().down(pointer_id, x, y, pressure).commit()
        wait_ms = max(0, int(round(duration * 1000)))
        if wait_ms > 0:
            builder.wait(wait_ms)
        builder.up(pointer_id).commit()
        self.send_builder(builder)
        time.sleep(0.05)

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

        self.stop_remote_process()
