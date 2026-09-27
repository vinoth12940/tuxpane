"""Shared test doubles and packet builders."""
from __future__ import annotations

import asyncio
import struct

VPS = bytes([32 << 1, 1]) + b"vps"
SPS = bytes([33 << 1, 1]) + b"sps"
PPS = bytes([34 << 1, 1]) + b"pps"
IDR = bytes([19 << 1, 1]) + b"idr-slice"
TRAIL = bytes([1 << 1, 1]) + b"p-slice"


def rtp(payload: bytes, seq: int, marker: bool = False, pt: int = 96, ssrc: int = 1234) -> bytes:
    return struct.pack(">BBHII", 0x80, (0x80 if marker else 0) | pt, seq & 0xFFFF, 0, ssrc) + payload


def ap(*nals: bytes) -> bytes:
    return bytes([48 << 1, 1]) + b"".join(struct.pack(">H", len(n)) + n for n in nals)


def fu_fragments(nal: bytes, size: int) -> list[bytes]:
    body = nal[2:]
    chunks = [body[i:i + size] for i in range(0, len(body), size)]
    header = bytes([(nal[0] & 0x81) | (49 << 1), nal[1]])
    kind = (nal[0] >> 1) & 0x3F
    out = []
    for i, chunk in enumerate(chunks):
        fu = kind | (0x80 if i == 0 else 0) | (0x40 if i == len(chunks) - 1 else 0)
        out.append(header + bytes([fu]) + chunk)
    return out


async def eventually(cond, timeout: float = 2.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not cond():
        if loop.time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.01)


from tuxpane.xinput import InputInjector


class RecordingInjector(InputInjector):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[tuple] = []

    def _key(self, keycode: int, down: bool) -> None:
        self.events.append(("key", keycode, down))

    def _button(self, button: int, down: bool) -> None:
        self.events.append(("button", button, down))

    def _move(self, x: int, y: int) -> None:
        self.events.append(("move", x, y))


class FakeEncoder:
    def __init__(self, on_access_unit, on_failure=None) -> None:
        self.on_access_unit = on_access_unit
        self.on_failure = on_failure
        self.bitrate_mbps = 20
        self.bitrates: list[int] = []
        self.starts: list[tuple[int, int]] = []
        self.stops = 0
        self.keyframe_requests = 0

    async def start(self, width: int, height: int) -> None:
        self.starts.append((width, height))

    async def stop(self) -> None:
        self.stops += 1

    async def request_keyframe(self) -> None:
        self.keyframe_requests += 1

    async def set_bitrate(self, mbps: int) -> None:
        self.bitrate_mbps = mbps
        self.bitrates.append(mbps)


class FakeDisplay:
    def __init__(self, current=(1920, 1200), modes=((2560, 1600), (1920, 1200))) -> None:
        self.current, self.modes = current, set(modes)

    def ensure_mode(self, width: int, height: int) -> tuple[int, int]:
        return (width, height) if (width, height) in self.modes else self.current


class FakeClipboard:
    def __init__(self, text: str | None = "initial") -> None:
        self.text = text
        self.sets: list[str] = []

    def get(self) -> str | None:
        return self.text

    def set(self, text: str) -> None:
        self.sets.append(text)
        self.text = text


import subprocess as _subprocess


class ScriptedRun:
    """subprocess.run stand-in: the first matching rule answers; unmatched commands are 'not installed'."""

    def __init__(self, rules) -> None:
        self.rules = list(rules)
        self.calls: list[list[str]] = []

    def __call__(self, args, **kwargs):
        args = [str(a) for a in args]
        self.calls.append(args)
        for rule in self.rules:
            matcher = rule[0]
            matched = matcher(args) if callable(matcher) else args[:len(matcher)] == list(matcher)
            if not matched:
                continue
            if len(rule) == 2:
                return rule[1](args, kwargs)
            _, code, out, err = rule
            if kwargs.get("check") and code:
                raise _subprocess.CalledProcessError(code, args, out, err)
            as_text = kwargs.get("text")
            return _subprocess.CompletedProcess(args, code, out if as_text else out.encode(),
                                                err if as_text else err.encode())
        raise FileNotFoundError(args[0])
