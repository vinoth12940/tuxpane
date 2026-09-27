"""Runs ffmpeg (x11grab -> HEVC -> RTP on localhost) and turns its packets into access units."""
from __future__ import annotations

import asyncio
import logging
import socket
import subprocess
import time

from .config import DEFAULT_VAAPI_DEVICE
from .rtp import HevcDepacketizer, is_keyframe

log = logging.getLogger(__name__)

KEYFRAME_MIN_INTERVAL = 0.5
RESPAWN_DELAY = 1.0
FAST_EXIT_SECONDS = 3.0
MAX_FAST_EXITS = 3  # ffmpeg dying this often means capture can't work; stop and report


X265_MAX_WIDTH = 1920
X265_MAX_FPS = 30


def build_ffmpeg_cmd(encoder: str, display: str, width: int, height: int, fps: int, bitrate_mbps: int,
                     output: list[str], vaapi_device: str = DEFAULT_VAAPI_DEVICE) -> list[str]:
    """ffmpeg argv for one encoder profile. All profiles emit low-latency HEVC without B-frames."""
    if encoder == "x265":
        fps = min(fps, X265_MAX_FPS)
    gop = str(fps * 2)
    rate, peak = f"{bitrate_mbps}M", f"{bitrate_mbps * 2}M"
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin"]
    if encoder == "vaapi":
        cmd += ["-init_hw_device", f"vaapi=va:{vaapi_device}", "-filter_hw_device", "va"]
    cmd += ["-f", "x11grab", "-draw_mouse", "0", "-framerate", str(fps),
            "-video_size", f"{width}x{height}", "-i", display]
    if encoder == "vaapi":
        cmd += ["-vf", "hwupload,scale_vaapi=format=nv12", "-c:v", "hevc_vaapi", "-async_depth", "1",
                "-bf", "0", "-g", gop, "-rc_mode", "VBR", "-b:v", rate, "-maxrate", peak]
    elif encoder == "nvenc":
        cmd += ["-c:v", "hevc_nvenc", "-preset", "p1", "-tune", "ull", "-zerolatency", "1", "-delay", "0",
                "-bf", "0", "-g", gop, "-rc", "vbr", "-b:v", rate, "-maxrate", peak]
    elif encoder == "x265":
        cmd += ["-vf", f"scale='min({X265_MAX_WIDTH},iw)':-2,format=yuv420p", "-c:v", "libx265",
                "-preset", "ultrafast", "-tune", "zerolatency",
                "-x265-params", f"bframes=0:keyint={gop}:repeat-headers=1", "-b:v", rate]
    else:
        raise ValueError(f"unknown encoder {encoder!r}")
    return cmd + ["-bsf:v", "dump_extra=freq=keyframe"] + output


def rtp_output(port: int) -> list[str]:
    return ["-f", "rtp", f"rtp://127.0.0.1:{port}?pkt_size=16000"]


def make_cmd_builder(encoder: str, vaapi_device: str = DEFAULT_VAAPI_DEVICE):
    def build(display: str, width: int, height: int, fps: int, bitrate_mbps: int, port: int) -> list[str]:
        return build_ffmpeg_cmd(encoder, display, width, height, fps, bitrate_mbps, rtp_output(port), vaapi_device)
    return build


class _RtpReceiver(asyncio.DatagramProtocol):
    def __init__(self, on_packet) -> None:
        self.on_packet = on_packet

    def datagram_received(self, data: bytes, addr) -> None:
        self.on_packet(data)


class Encoder:
    def __init__(self, on_access_unit, display: str = ":0", fps: int = 60, bitrate_mbps: int = 20,
                 cmd_builder=make_cmd_builder("vaapi"), on_failure=None) -> None:
        self.on_access_unit = on_access_unit
        self.on_failure = on_failure
        self.display = display
        self.fps = fps
        self.bitrate_mbps = bitrate_mbps
        self.spawn_count = 0
        self._cmd_builder = cmd_builder
        self._depack = HevcDepacketizer()
        self._transport = None
        self._port = 0
        self._proc: asyncio.subprocess.Process | None = None
        self._size = (0, 0)
        self._stopping = False
        self._last_spawn = 0.0
        self._fast_exits = 0
        self._awaiting_keyframe = False
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()

    async def start(self, width: int, height: int) -> None:
        if self._transport is None:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 * 1024 * 1024)
            sock.bind(("127.0.0.1", 0))
            self._port = sock.getsockname()[1]
            rcvbuf = sock.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)
            log.info("RTP receive buffer %d KiB (raise net.core.rmem_max if keyframes get lost)", rcvbuf // 1024)
            self._transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(
                lambda: _RtpReceiver(self._on_packet), sock=sock)
        self._size = (width, height)
        self._stopping = False
        self._fast_exits = 0
        await self._respawn()

    async def stop(self) -> None:
        self._stopping = True
        async with self._lock:
            await self._kill()

    async def request_keyframe(self) -> None:
        """Restarting ffmpeg is the simplest reliable way to get an IDR with parameter sets."""
        if self._stopping or self._proc is None:
            return
        if time.monotonic() - self._last_spawn < KEYFRAME_MIN_INTERVAL:
            return
        await self._respawn()

    async def set_bitrate(self, mbps: int) -> None:
        self.bitrate_mbps = mbps
        if self._proc is not None and not self._stopping:
            await self._respawn()

    async def _respawn(self) -> None:
        async with self._lock:
            await self._kill()
            if self._stopping:
                return
            self._depack.reset()
            cmd = self._cmd_builder(self.display, *self._size, self.fps, self.bitrate_mbps, self._port)
            self._proc = await asyncio.create_subprocess_exec(
                *cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            self._last_spawn = time.monotonic()
            self.spawn_count += 1
            self._spawn_task(self._watch(self._proc, self._last_spawn))

    async def _kill(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None or proc.returncode is not None:
            return
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), 2)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()

    async def _watch(self, proc: asyncio.subprocess.Process, started: float) -> None:
        stderr = await proc.stderr.read()
        code = await proc.wait()
        if proc is not self._proc or self._stopping:
            return
        tail = stderr.decode(errors="replace").strip()[-500:] or f"ffmpeg exited with {code}"
        log.error("ffmpeg exited with %s: %s", code, tail)
        self._fast_exits = self._fast_exits + 1 if time.monotonic() - started < FAST_EXIT_SECONDS else 0
        if self._fast_exits >= MAX_FAST_EXITS:
            self._fail(tail)
            return
        await asyncio.sleep(RESPAWN_DELAY)
        if proc is self._proc and not self._stopping:
            try:
                await self._respawn()
            except OSError as exc:
                self._fail(f"cannot start ffmpeg: {exc}")

    def _fail(self, message: str) -> None:
        self._proc = None
        if self.on_failure is not None:
            self.on_failure(message)

    def _spawn_task(self, coro) -> None:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _on_packet(self, data: bytes) -> None:
        lost = self._depack.lost
        nals = self._depack.feed(data)
        if self._depack.lost != lost:
            log.warning("RTP packet loss; forcing a keyframe")
            self._awaiting_keyframe = True  # later frames reference the lost one: showing them smears
            self._spawn_task(self.request_keyframe())
        if not nals:
            return
        keyframe = is_keyframe(nals)
        if self._awaiting_keyframe and not keyframe:
            return
        self._awaiting_keyframe = False
        self.on_access_unit(nals, keyframe, time.monotonic_ns() // 1000)
