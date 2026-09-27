"""Loads Xlib through ctypes (no compiled extensions or -dev packages needed)."""
from __future__ import annotations

import ctypes
import ctypes.util
import glob
import logging
import os
import pathlib

log = logging.getLogger(__name__)

_ErrorHandler = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)


@_ErrorHandler
def _log_x_error(_display, _event):
    # Xlib's default handler exits the process; one bad request must not kill the agent.
    log.warning("ignored X protocol error")
    return 0


def load(name: str, fallback: str) -> ctypes.CDLL:
    return ctypes.CDLL(ctypes.util.find_library(name) or fallback)


def _mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def xauthority_candidates(uid: int, home, hint: str | None, glob_fn=glob.glob, mtime=_mtime) -> list[str]:
    """Where display managers keep the X cookie: the service's hint, ~/.Xauthority (LightDM, startx), GDM, then
    SDDM's randomly named file, newest first. Resolved at run time because SDDM picks a new name every login."""
    sddm = sorted(glob_fn(f"/run/user/{uid}/xauth_*"), key=mtime, reverse=True)
    items = [hint, str(pathlib.Path(home) / ".Xauthority"), f"/run/user/{uid}/gdm/Xauthority", *sddm]
    return list(dict.fromkeys(item for item in items if item))


def open_first(candidates, try_open, exists=os.path.exists, display: str = ":0"):
    """Returns (cookie path, handle) for the first candidate that opens the display."""
    for candidate in candidates:
        if not exists(candidate):
            continue
        handle = try_open(candidate)
        if handle:
            return candidate, handle
    raise RuntimeError(f"cannot open X display {display}: is a user logged in to the desktop?")


def open_display(name: str, candidates=None) -> tuple[ctypes.CDLL, ctypes.c_void_p]:
    x11 = load("X11", "libX11.so.6")
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XSetErrorHandler.restype = ctypes.c_void_p
    x11.XSetErrorHandler.argtypes = [_ErrorHandler]
    x11.XFlush.argtypes = [ctypes.c_void_p]
    x11.XFree.argtypes = [ctypes.c_void_p]
    x11.XSetErrorHandler(_log_x_error)
    if candidates is None:
        candidates = xauthority_candidates(os.getuid(), pathlib.Path.home(), os.environ.get("XAUTHORITY"))

    def try_open(candidate: str):
        os.environ["XAUTHORITY"] = candidate  # ffmpeg, xrandr and xclip inherit the cookie that worked
        return x11.XOpenDisplay(name.encode())

    _, display = open_first(candidates, try_open, display=name)
    return x11, ctypes.c_void_p(display)


