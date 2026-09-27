"""Injects keyboard and mouse input into X through XTest, remembering what is held."""
from __future__ import annotations

import ctypes

from . import x11

EVDEV_TO_X = 8  # X keycode = Linux evdev code + 8
VALID_BUTTONS = {1, 2, 3, 8, 9}  # left, middle, right, back, forward


class InputInjector:
    """Tracks held keys/buttons so they can always be released; subclasses do the injection."""

    def __init__(self) -> None:
        self.held_keys: list[int] = []
        self.held_buttons: list[int] = []

    def ensure_ready(self) -> None:
        """Raises RuntimeError with a user-facing reason when input can't be injected."""

    def key(self, evdev_code: int, down: bool) -> None:
        if not 1 <= evdev_code <= 247:
            return
        self._track(self.held_keys, evdev_code, down)
        self._key(evdev_code + EVDEV_TO_X, down)
        self._flush()

    def move(self, x: int, y: int) -> None:
        self._move(x, y)
        self._flush()

    def button(self, button: int, down: bool) -> None:
        if button not in VALID_BUTTONS:
            return
        self._track(self.held_buttons, button, down)
        self._button(button, down)
        self._flush()

    def scroll(self, dx: int, dy: int) -> None:
        for button, count in ((4, dy), (5, -dy), (6, dx), (7, -dx)):
            for _ in range(max(0, count)):
                self._button(button, True)
                self._button(button, False)
        self._flush()

    def release_all(self) -> None:
        for code in reversed(self.held_keys):
            self._key(code + EVDEV_TO_X, False)
        for button in reversed(self.held_buttons):
            self._button(button, False)
        self.held_keys.clear()
        self.held_buttons.clear()
        self._flush()

    @staticmethod
    def _track(held: list[int], value: int, down: bool) -> None:
        if down and value not in held:
            held.append(value)
        elif not down and value in held:
            held.remove(value)

    def _key(self, keycode: int, down: bool) -> None:
        raise NotImplementedError

    def _button(self, button: int, down: bool) -> None:
        raise NotImplementedError

    def _move(self, x: int, y: int) -> None:
        raise NotImplementedError

    def _flush(self) -> None:
        pass


class XTestInjector(InputInjector):
    """Opens X lazily, so the agent listens (and can explain) even before anyone logs in to the desktop."""

    def __init__(self, display: str = ":0", opener=None) -> None:
        super().__init__()
        self._opener = opener or (lambda: x11.open_display(display))
        self._x11 = None
        self._dpy = None
        self._xt = None

    def ensure_ready(self) -> None:
        if self._dpy is not None:
            return
        lib, dpy = self._opener()
        xt = x11.load("Xtst", "libXtst.so.6")
        xt.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
        xt.XTestFakeButtonEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
        xt.XTestFakeMotionEvent.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_ulong]
        self._x11, self._dpy, self._xt = lib, dpy, xt

    def _key(self, keycode: int, down: bool) -> None:
        if self._dpy is not None:
            self._xt.XTestFakeKeyEvent(self._dpy, keycode, int(down), 0)

    def _button(self, button: int, down: bool) -> None:
        if self._dpy is not None:
            self._xt.XTestFakeButtonEvent(self._dpy, button, int(down), 0)

    def _move(self, x: int, y: int) -> None:
        if self._dpy is not None:
            self._xt.XTestFakeMotionEvent(self._dpy, -1, x, y, 0)

    def _flush(self) -> None:
        if self._dpy is not None:
            self._x11.XFlush(self._dpy)
