"""Wire protocol shared with the Mac client. Frame = type:u8 | len:u32 BE | payload."""
from __future__ import annotations

import struct

VERSION = 2
CODEC_HEVC = 1
MAX_PAYLOAD = 16 * 1024 * 1024

HELLO = 0x01
WELCOME = 0x02
VIDEO = 0x03
KEY = 0x10
MOUSE_MOVE = 0x11
MOUSE_BTN = 0x12
SCROLL = 0x13
RELEASE_ALL = 0x14
REQUEST_KEYFRAME = 0x15
PING = 0x20
PONG = 0x21
CLIPBOARD = 0x30
CURSOR = 0x31
ERROR = 0x7F

REPLACED_MESSAGE = "replaced by another connection"

_HEADER = struct.Struct(">BI")


class ProtocolError(Exception):
    pass


def encode(msg_type: int, payload: bytes = b"") -> bytes:
    if len(payload) > MAX_PAYLOAD:
        raise ProtocolError(f"payload too large: {len(payload)}")
    return _HEADER.pack(msg_type, len(payload)) + payload


async def read_message(reader, max_payload: int = MAX_PAYLOAD) -> tuple[int, bytes]:
    msg_type, length = _HEADER.unpack(await reader.readexactly(_HEADER.size))
    if length > max_payload:
        raise ProtocolError(f"payload too large: {length}")
    payload = await reader.readexactly(length) if length else b""
    return msg_type, payload


def _unpack(fmt: str, payload: bytes, name: str) -> tuple:
    try:
        return struct.unpack(fmt, payload)
    except struct.error as exc:
        raise ProtocolError(f"bad {name} payload") from exc


def _text(payload: bytes, name: str) -> str:
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProtocolError(f"bad {name} text") from exc


def hello(token: str, width: int, height: int) -> bytes:
    return encode(HELLO, struct.pack(">HHH", VERSION, width, height) + token.encode())


def parse_hello(payload: bytes) -> tuple[int, int, int, str]:
    if len(payload) < 6:
        raise ProtocolError("bad HELLO payload")
    version, width, height = struct.unpack_from(">HHH", payload)
    return version, width, height, _text(payload[6:], "HELLO")


def welcome(width: int, height: int, agent_version: str) -> bytes:
    return encode(WELCOME, struct.pack(">HHB", width, height, CODEC_HEVC) + agent_version.encode("utf-8"))


def parse_welcome(payload: bytes) -> tuple[int, int, int, str]:
    if len(payload) < 5:
        raise ProtocolError("bad WELCOME payload")
    width, height, codec = struct.unpack_from(">HHB", payload)
    return width, height, codec, _text(payload[5:], "WELCOME")


def video(pts_us: int, keyframe: bool, nals: list[bytes]) -> bytes:
    body = b"".join(struct.pack(">I", len(nal)) + nal for nal in nals)
    return encode(VIDEO, struct.pack(">QB", pts_us, int(keyframe)) + body)


def parse_video(payload: bytes) -> tuple[int, bool, list[bytes]]:
    if len(payload) < 9:
        raise ProtocolError("bad VIDEO payload")
    pts, keyframe = struct.unpack_from(">QB", payload)
    nals, pos = [], 9
    while pos < len(payload):
        if pos + 4 > len(payload):
            raise ProtocolError("truncated NAL length")
        (size,) = struct.unpack_from(">I", payload, pos)
        pos += 4
        if pos + size > len(payload):
            raise ProtocolError("truncated NAL")
        nals.append(payload[pos:pos + size])
        pos += size
    return pts, bool(keyframe), nals


def key(code: int, down: bool) -> bytes:
    return encode(KEY, struct.pack(">HB", code, int(down)))


def parse_key(payload: bytes) -> tuple[int, bool]:
    code, down = _unpack(">HB", payload, "KEY")
    return code, bool(down)


def mouse_move(x: int, y: int) -> bytes:
    return encode(MOUSE_MOVE, struct.pack(">HH", x, y))


def parse_mouse_move(payload: bytes) -> tuple[int, int]:
    return _unpack(">HH", payload, "MOUSE_MOVE")


def mouse_button(button: int, down: bool) -> bytes:
    return encode(MOUSE_BTN, struct.pack(">BB", button, int(down)))


def parse_mouse_button(payload: bytes) -> tuple[int, bool]:
    button, down = _unpack(">BB", payload, "MOUSE_BTN")
    return button, bool(down)


def scroll(dx: int, dy: int) -> bytes:
    def clamp(v: int) -> int:
        return max(-128, min(127, v))
    return encode(SCROLL, struct.pack(">bb", clamp(dx), clamp(dy)))


def parse_scroll(payload: bytes) -> tuple[int, int]:
    return _unpack(">bb", payload, "SCROLL")


def ping(timestamp: int) -> bytes:
    return encode(PING, struct.pack(">Q", timestamp))


def pong(timestamp: int) -> bytes:
    return encode(PONG, struct.pack(">Q", timestamp))


def parse_timestamp(payload: bytes) -> int:
    return _unpack(">Q", payload, "timestamp")[0]


def clipboard(text: str) -> bytes:
    return encode(CLIPBOARD, text.encode("utf-8"))


def parse_clipboard(payload: bytes) -> str:
    return _text(payload, "CLIPBOARD")


def cursor(xhot: int, yhot: int, width: int, height: int, rgba: bytes) -> bytes:
    return encode(CURSOR, struct.pack(">HHHH", xhot, yhot, width, height) + rgba)


def error(message: str) -> bytes:
    return encode(ERROR, message.encode("utf-8"))
