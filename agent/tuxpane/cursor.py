"""Polls the X cursor image (XFixes) so the Mac can draw the pointer locally, with zero lag."""
from __future__ import annotations

import ctypes

from . import x11


class XFixesCursorImage(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_short), ("y", ctypes.c_short),
        ("width", ctypes.c_ushort), ("height", ctypes.c_ushort),
        ("xhot", ctypes.c_ushort), ("yhot", ctypes.c_ushort),
        ("cursor_serial", ctypes.c_ulong),
        ("pixels", ctypes.POINTER(ctypes.c_ulong)),
        ("atom", ctypes.c_ulong),
        ("name", ctypes.c_char_p),
    ]


def argb_to_rgba(pixels: list[int]) -> bytes:
    """XFixes gives premultiplied ARGB in the low 32 bits of each long; AppKit wants RGBA bytes."""
    out = bytearray(len(pixels) * 4)
    for i, p in enumerate(pixels):
        out[i * 4:i * 4 + 4] = ((p >> 16) & 255, (p >> 8) & 255, p & 255, (p >> 24) & 255)
    return bytes(out)


class CursorWatcher:
    """Opens X lazily; with no desktop session yet, polls simply report nothing."""

    def __init__(self, display: str = ":0", opener=None) -> None:
        self._opener = opener or (lambda: x11.open_display(display))
        self._x11 = None
        self._dpy = None
        self._xf = None
        self._serial: int | None = None

    def _ready(self) -> bool:
        if self._dpy is not None:
            return True
        try:
            lib, dpy = self._opener()
        except RuntimeError:
            return False
        xf = x11.load("Xfixes", "libXfixes.so.3")
        xf.XFixesQueryVersion.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
        xf.XFixesGetCursorImage.argtypes = [ctypes.c_void_p]
        xf.XFixesGetCursorImage.restype = ctypes.POINTER(XFixesCursorImage)
        major, minor = ctypes.c_int(4), ctypes.c_int(0)
        if not xf.XFixesQueryVersion(dpy, ctypes.byref(major), ctypes.byref(minor)):
            return False
        self._x11, self._dpy, self._xf = lib, dpy, xf
        return True

    def reset(self) -> None:
        """Forget the last cursor so the next poll reports it (a new client needs it)."""
        self._serial = None

    def poll(self) -> tuple[int, int, int, int, bytes] | None:
        if not self._ready():
            return None
        image_ptr = self._xf.XFixesGetCursorImage(self._dpy)
        if not image_ptr:
            return None
        try:
            image = image_ptr.contents
            if image.cursor_serial == self._serial:
                return None
            self._serial = image.cursor_serial
            rgba = argb_to_rgba(image.pixels[:image.width * image.height])
            return image.xhot, image.yhot, image.width, image.height, rgba
        finally:
            self._x11.XFree(image_ptr)
