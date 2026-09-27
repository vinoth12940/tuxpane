"""Compare-and-confirm pairing: both screens show a 6-digit code derived from this machine's certificate and two
nonces, with the Mac committing to its nonce first so a man in the middle can't make the codes match."""
from __future__ import annotations

import hashlib
import json

from . import protocol as p

PAIR_PORT = 7301
PAIR_VERSION = 1
PAIR_HELLO = 0x40
PAIR_NONCE = 0x41
PAIR_REVEAL = 0x42
PAIR_CONFIRM = 0x43
PAIR_ABORT = 0x44
PAIR_ACCEPT = 0x45
PAIR_REJECT = 0x46
DISCOVER_QUERY = {"q": "tuxpane-discover", "v": 1}
MAX_PAIR_MESSAGE = 4096


def sas_code(fingerprint: bytes, agent_nonce: bytes, mac_nonce: bytes) -> str:
    digest = hashlib.sha256(b"tuxpane-sas-v1" + fingerprint + agent_nonce + mac_nonce).digest()
    value = int.from_bytes(digest[:8], "big") % 1_000_000
    return "%03d %03d" % divmod(value, 1000)


def commitment(nonce: bytes) -> str:
    return hashlib.sha256(nonce).hexdigest()


def message(msg_type: int, **values) -> bytes:
    return p.encode(msg_type, json.dumps(values, separators=(",", ":")).encode())


def fields(payload: bytes) -> dict:
    try:
        data = json.loads(payload)
    except (ValueError, UnicodeDecodeError) as exc:
        raise p.ProtocolError("bad pairing message") from exc
    if not isinstance(data, dict):
        raise p.ProtocolError("bad pairing message")
    return data


def is_discovery_query(data: bytes) -> bool:
    try:
        return json.loads(data) == DISCOVER_QUERY
    except (ValueError, UnicodeDecodeError):
        return False


def discovery_reply(name: str, os_name: str) -> bytes:
    return json.dumps({"n": name, "os": os_name, "v": PAIR_VERSION, "pp": PAIR_PORT}, separators=(",", ":")).encode()
