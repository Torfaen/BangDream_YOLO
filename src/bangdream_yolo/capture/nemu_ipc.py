"""Minimal MuMu Player 12 nemu_ipc screenshot wrapper."""

from __future__ import annotations

import ctypes
from pathlib import Path

import cv2
import numpy as np


NEMU_IPC_DLL_CANDIDATES = (
    Path("shell/sdk/external_renderer_ipc.dll"),
    Path("nx_device/12.0/shell/sdk/external_renderer_ipc.dll"),
)


class NemuIpcError(RuntimeError):
    """Raised when MuMu IPC cannot connect or capture a frame."""


def find_nemu_ipc_dll(nemu_folder: Path) -> Path | None:
    """Return the first known external_renderer_ipc.dll path under MuMu root."""

    for relative_path in NEMU_IPC_DLL_CANDIDATES:
        dll_path = nemu_folder / relative_path
        if dll_path.exists():
            return dll_path
    return None


class NemuIpc:
    """Small wrapper around MuMu's external renderer IPC screenshot API.

    Args:
        nemu_folder: MuMu installation root, for example
            ``C:\\Program Files\\Netease\\MuMu``.
        instance_id: MuMu instance id. Port 16384 usually maps to instance 0.
        display_id: Display id, normally 0 when background keep-alive is off.
    """

    def __init__(self, nemu_folder: Path, instance_id: int = 0, display_id: int = 0):
        self.nemu_folder = Path(nemu_folder)
        self.instance_id = instance_id
        self.display_id = display_id
        self.connect_id = 0
        self.width = 0
        self.height = 0

        dll_path = find_nemu_ipc_dll(self.nemu_folder)
        if dll_path is None:
            checked = ", ".join(str(self.nemu_folder / path) for path in NEMU_IPC_DLL_CANDIDATES)
            raise NemuIpcError(f"未找到 external_renderer_ipc.dll；已检查：{checked}")

        self.dll_path = dll_path
        self.lib = ctypes.CDLL(str(dll_path))
        self.lib.nemu_connect.restype = ctypes.c_int
        self.lib.nemu_disconnect.restype = ctypes.c_int
        self.lib.nemu_capture_display.restype = ctypes.c_int

    def __enter__(self) -> "NemuIpc":
        self.connect()
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.disconnect()

    def connect(self) -> None:
        """Connect to the configured MuMu instance."""

        if self.connect_id:
            return

        connect_id = self.lib.nemu_connect(str(self.nemu_folder), self.instance_id)
        if connect_id == 0:
            raise NemuIpcError(
                "nemu_connect 失败；请确认 MuMu 已启动，且 nemu_folder 指向 MuMu 安装根目录"
            )
        self.connect_id = int(connect_id)

    def disconnect(self) -> None:
        """Disconnect from MuMu IPC if connected."""

        if not self.connect_id:
            return
        self.lib.nemu_disconnect(self.connect_id)
        self.connect_id = 0

    def get_resolution(self) -> tuple[int, int]:
        """Read emulator resolution and cache it as ``width`` / ``height``."""

        if not self.connect_id:
            self.connect()

        width_ptr = ctypes.pointer(ctypes.c_int(0))
        height_ptr = ctypes.pointer(ctypes.c_int(0))
        null_pixels = ctypes.POINTER(ctypes.c_int)()

        ret = self.lib.nemu_capture_display(
            self.connect_id,
            self.display_id,
            0,
            width_ptr,
            height_ptr,
            null_pixels,
        )
        if ret > 0:
            raise NemuIpcError(f"获取分辨率失败，nemu_capture_display 返回 {ret}")

        self.width = int(width_ptr.contents.value)
        self.height = int(height_ptr.contents.value)
        return self.width, self.height

    def screenshot(self) -> np.ndarray:
        """Capture one frame and return an OpenCV BGR image.

        MuMu IPC returns a 4-channel image that is upside down. The conversion
        here keeps downstream code in the normal OpenCV coordinate system.
        """

        if not self.connect_id:
            self.connect()
        if self.width == 0 or self.height == 0:
            self.get_resolution()

        width_ptr = ctypes.pointer(ctypes.c_int(self.width))
        height_ptr = ctypes.pointer(ctypes.c_int(self.height))
        length = self.width * self.height * 4
        pixel_buffer = (ctypes.c_ubyte * length)()
        pixels_ptr = ctypes.pointer(pixel_buffer)

        ret = self.lib.nemu_capture_display(
            self.connect_id,
            self.display_id,
            length,
            width_ptr,
            height_ptr,
            pixels_ptr,
        )
        if ret > 0:
            raise NemuIpcError(f"截图失败，nemu_capture_display 返回 {ret}")

        self.width = int(width_ptr.contents.value)
        self.height = int(height_ptr.contents.value)
        image = np.ctypeslib.as_array(pixel_buffer).reshape((self.height, self.width, 4))
        bgr = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        return cv2.flip(bgr, 0)
