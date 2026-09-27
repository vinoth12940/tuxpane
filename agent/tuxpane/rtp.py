"""Reassembles HEVC access units from ffmpeg's RTP output (RFC 7798).

The RTP marker bit flags the last packet of each frame, so a frame can be
forwarded the moment it is complete instead of waiting for the next one.
"""
from __future__ import annotations

import struct

PAYLOAD_TYPE = 96
NAL_AP = 48
NAL_FU = 49
IRAP_TYPES = range(16, 24)  # BLA / IDR / CRA: decodable without earlier frames


def nal_type(nal: bytes) -> int:
    return (nal[0] >> 1) & 0x3F


def is_keyframe(nals: list[bytes]) -> bool:
    return any(nal_type(n) in IRAP_TYPES for n in nals)


class HevcDepacketizer:
    def __init__(self) -> None:
        self.lost = 0
        self.reset()

    def reset(self) -> None:
        self._nals: list[bytes] = []
        self._fu: bytearray | None = None
        self._broken = False
        self._seq: int | None = None
        self._ssrc: int | None = None

    def feed(self, packet: bytes) -> list[bytes] | None:
        """Consume one RTP packet; return the frame's NALs once its marker packet arrives."""
        if len(packet) < 12 or packet[0] >> 6 != 2 or packet[1] & 0x7F != PAYLOAD_TYPE:
            return None
        seq, = struct.unpack_from(">H", packet, 2)
        ssrc, = struct.unpack_from(">I", packet, 8)
        if ssrc != self._ssrc:
            self.reset()  # ffmpeg restarted: start clean
            self._ssrc = ssrc
        elif self._seq is not None and seq != (self._seq + 1) & 0xFFFF:
            self._mark_broken()
        self._seq = seq

        offset = 12 + 4 * (packet[0] & 0x0F)
        if packet[0] & 0x10:  # header extension
            if len(packet) < offset + 4:
                return None
            offset += 4 + 4 * struct.unpack_from(">H", packet, offset + 2)[0]
        end = len(packet) - (packet[-1] if packet[0] & 0x20 else 0)
        payload = packet[offset:end]
        if len(payload) >= 2:
            self._consume(payload)

        if not packet[1] & 0x80:
            return None
        nals, broken = self._nals, self._broken
        self._nals, self._fu, self._broken = [], None, False
        return None if broken or not nals else nals

    def _mark_broken(self) -> None:
        if not self._broken:
            self.lost += 1
        self._broken = True

    def _consume(self, payload: bytes) -> None:
        kind = nal_type(payload)
        if kind == NAL_AP:
            pos = 2
            while pos + 2 <= len(payload):
                size, = struct.unpack_from(">H", payload, pos)
                pos += 2
                if size == 0 or pos + size > len(payload):
                    self._mark_broken()
                    return
                self._nals.append(bytes(payload[pos:pos + size]))
                pos += size
        elif kind == NAL_FU:
            if len(payload) < 3:
                self._mark_broken()
                return
            fu = payload[2]
            if fu & 0x80:
                self._fu = bytearray([(payload[0] & 0x81) | ((fu & 0x3F) << 1), payload[1]])
            elif self._fu is None:
                self._mark_broken()
                return
            self._fu += payload[3:]
            if fu & 0x40:
                self._nals.append(bytes(self._fu))
                self._fu = None
        else:
            self._nals.append(bytes(payload))
