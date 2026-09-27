"""Accepts one Mac client at a time and bridges it to screen capture and input injection."""
from __future__ import annotations

import asyncio
import hmac
import logging
import socket
import subprocess
import time

from . import __version__
from . import protocol as p
from .security import is_allowed_peer

log = logging.getLogger(__name__)

SEND_BUFFER_SECONDS = 0.15  # queue at most this much video before dropping frames
MIN_SEND_BUFFER = 256 * 1024
NOTSENT_LOWAT = 128 * 1024
INPUT_IDLE_SECONDS = 3.0  # the Mac pings every second; silence this long means the link is gone
MIN_BITRATE_MBPS = 4
CONGESTION_WINDOW = 10.0
CONGESTION_EVENTS = 3
HELLO_TIMEOUT = 5.0
MAX_HELLO = 1024  # unauthenticated peers must not make us buffer megabytes
CURSOR_POLL_SECONDS = 0.05
CLIPBOARD_POLL_SECONDS = 0.5


def tune_socket(sock) -> None:
    """Keep unsent video in asyncio's buffer, where send_video can see it, not in a multi-MB kernel buffer."""
    option = getattr(socket, "TCP_NOTSENT_LOWAT", None)
    if option is None:
        log.warning("TCP_NOTSENT_LOWAT unavailable: slow links may queue extra latency in the kernel")
        return
    if sock is not None:
        sock.setsockopt(socket.IPPROTO_TCP, option, NOTSENT_LOWAT)


class Session:
    """One authenticated client connection."""

    def __init__(self, server, reader, writer) -> None:
        self.server = server
        self.reader = reader
        self.writer = writer
        self.waiting_for_keyframe = True
        self.closed = False
        self.ready = False  # set once WELCOME is written; video before it would confuse the client
        self.last_heard = time.monotonic()

    def send(self, data: bytes) -> None:
        if not self.closed:
            self.writer.write(data)

    def send_video(self, nals: list[bytes], keyframe: bool, pts_us: int) -> None:
        if self.closed or not self.ready:
            return
        if self.writer.transport.get_write_buffer_size() > self.server.send_buffer_limit():
            # The link can't keep up: drop frames rather than queue seconds of latency.
            if not self.waiting_for_keyframe:
                self.server.note_congestion()
            self.waiting_for_keyframe = True
            return
        if self.waiting_for_keyframe:
            if not keyframe:
                self.server.request_keyframe()
                return
            self.waiting_for_keyframe = False
        self.writer.write(p.video(pts_us, keyframe, nals))

    def close(self) -> None:
        """Closes after flushing queued data (e.g. an ERROR message)."""
        self.closed = True
        self.writer.close()

    def replace(self) -> None:
        """Tells a bumped client why, so it stops reconnecting, then drops it; a stalled link can't hold us up."""
        if self.closed:
            return
        self.writer.write(p.error(p.REPLACED_MESSAGE))
        self.closed = True
        self.writer.close()
        asyncio.get_running_loop().call_later(1.0, self.writer.transport.abort)

    def abort(self) -> None:
        """Drops the connection now; close() would wait for a stalled client's buffer to drain."""
        self.closed = True
        self.writer.transport.abort()


class Server:
    def __init__(self, token: str, injector, display, encoder_factory, cursor=None, clipboard=None,
                 peer_filter=is_allowed_peer) -> None:
        self.token = token
        self.peer_filter = peer_filter
        self.injector = injector
        self.display = display
        self.encoder = encoder_factory(self.on_access_unit, self.on_capture_failure)
        self._initial_bitrate = self.encoder.bitrate_mbps
        self._congestion: list[float] = []
        self.cursor = cursor
        self.clipboard = clipboard
        self.session: Session | None = None
        self._clipboard_last: str | None = None
        self._tasks: set[asyncio.Task] = set()

    def on_access_unit(self, nals: list[bytes], keyframe: bool, pts_us: int) -> None:
        if self.session is not None:
            self.session.send_video(nals, keyframe, pts_us)

    def request_keyframe(self) -> None:
        self._spawn(self.encoder.request_keyframe())

    def on_capture_failure(self, message: str) -> None:
        log.error("capture failed: %s", message)
        if self.session is not None:
            self.session.send(p.error(f"capture failed: {message}"))
            self.session.close()

    async def shutdown(self) -> None:
        """Called on SIGTERM: never leave a key held on Linux when the agent stops."""
        if self.session is not None:
            self.session.abort()
            self.session = None
        self.injector.release_all()
        await self.encoder.stop()

    def send_buffer_limit(self) -> int:
        return max(MIN_SEND_BUFFER, int(self.encoder.bitrate_mbps * 1_000_000 / 8 * SEND_BUFFER_SECONDS))

    def note_congestion(self) -> None:
        now = time.monotonic()
        self._congestion = [t for t in self._congestion if now - t < CONGESTION_WINDOW] + [now]
        if len(self._congestion) >= CONGESTION_EVENTS and self.encoder.bitrate_mbps > MIN_BITRATE_MBPS:
            lower = max(MIN_BITRATE_MBPS, self.encoder.bitrate_mbps // 2)
            log.warning("link too slow; lowering bitrate to %d Mbit/s", lower)
            self._congestion.clear()
            self._spawn(self.encoder.set_bitrate(lower))

    def _spawn(self, coro) -> asyncio.Task:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def handle(self, reader, writer) -> None:
        peer = writer.get_extra_info("peername")
        if not self.peer_filter(peer[0] if peer else ""):
            log.warning("refused connection from non-private address %s", peer)
            writer.transport.abort()
            return
        session = None
        helpers: list[asyncio.Task] = []
        try:
            msg_type, payload = await asyncio.wait_for(p.read_message(reader, MAX_HELLO), HELLO_TIMEOUT)
            if msg_type != p.HELLO:
                raise p.ProtocolError("expected HELLO")
            version, want_w, want_h, token = p.parse_hello(payload)
            if version != p.VERSION:
                log.warning("client %s speaks protocol version %d", peer, version)
                writer.write(p.error(f"unsupported protocol version {version} (agent speaks {p.VERSION}); "
                                     "update the app and agent to the same release"))
                await writer.drain()
                return
            if not hmac.compare_digest(token.encode(), self.token.encode()):
                log.warning("rejected client %s", peer)
                writer.write(p.error("authentication failed"))
                await writer.drain()
                return
            if self.session is not None:
                log.info("client %s replaces the previous one", peer)
                self.session.replace()
                self.injector.release_all()
            session = Session(self, reader, writer)
            self.session = session
            tune_socket(writer.get_extra_info("socket"))
            self.encoder.bitrate_mbps = self._initial_bitrate
            self._congestion.clear()
            try:
                self.injector.ensure_ready()
                width, height = await asyncio.to_thread(self.display.ensure_mode, want_w, want_h)
                if session.closed:
                    return  # replaced by a newer client while switching modes
                writer.write(p.welcome(width, height, __version__))
                session.ready = True
                await self.encoder.start(width, height)
            except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
                log.error("cannot start capture: %r", exc)
                writer.write(p.error(f"agent cannot start capture: {exc}"))
                await writer.drain()
                return
            helpers.append(self._spawn(self._input_watchdog(session)))
            if self.cursor is not None:
                helpers.append(self._spawn(self._cursor_loop(session)))
            if self.clipboard is not None:
                helpers.append(self._spawn(self._clipboard_loop(session)))
            log.info("client %s connected at %dx%d", peer, width, height)
            await self._read_loop(session)
        except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionError, p.ProtocolError) as exc:
            log.info("client %s disconnected: %r", peer, exc)
        finally:
            for task in helpers:
                task.cancel()
            if session is not None:
                session.closed = True
                if self.session is session:
                    self.session = None
                    self.injector.release_all()
                    await self.encoder.stop()
            writer.close()

    async def _read_loop(self, session: Session) -> None:
        while not session.closed:
            msg_type, payload = await p.read_message(session.reader)
            if session.closed:
                return
            session.last_heard = time.monotonic()
            if msg_type == p.KEY:
                self.injector.key(*p.parse_key(payload))
            elif msg_type == p.MOUSE_MOVE:
                self.injector.move(*p.parse_mouse_move(payload))
            elif msg_type == p.MOUSE_BTN:
                self.injector.button(*p.parse_mouse_button(payload))
            elif msg_type == p.SCROLL:
                self.injector.scroll(*p.parse_scroll(payload))
            elif msg_type == p.RELEASE_ALL:
                self.injector.release_all()
            elif msg_type == p.REQUEST_KEYFRAME:
                session.waiting_for_keyframe = True
                self.request_keyframe()
            elif msg_type == p.PING:
                session.send(p.pong(p.parse_timestamp(payload)))
            elif msg_type == p.CLIPBOARD and self.clipboard is not None:
                text = p.parse_clipboard(payload)
                self._clipboard_last = text
                try:
                    await asyncio.to_thread(self.clipboard.set, text)
                except (OSError, subprocess.SubprocessError) as exc:
                    log.warning("clipboard update failed: %r", exc)
            else:
                log.debug("ignoring message type %#x", msg_type)

    async def _input_watchdog(self, session: Session) -> None:
        # A silently dropped link would otherwise leave keys autorepeating on Linux until TCP gives up.
        while not session.closed:
            await asyncio.sleep(min(1.0, INPUT_IDLE_SECONDS / 2))
            idle = time.monotonic() - session.last_heard
            if idle > INPUT_IDLE_SECONDS and (self.injector.held_keys or self.injector.held_buttons):
                log.warning("client silent for %.1fs; releasing held input", idle)
                self.injector.release_all()

    async def _cursor_loop(self, session: Session) -> None:
        self.cursor.reset()
        while not session.closed:
            shape = self.cursor.poll()
            if shape is not None:
                session.send(p.cursor(*shape))
            await asyncio.sleep(CURSOR_POLL_SECONDS)

    async def _clipboard_loop(self, session: Session) -> None:
        self._clipboard_last = await asyncio.to_thread(self.clipboard.get)
        while not session.closed:
            await asyncio.sleep(CLIPBOARD_POLL_SECONDS)
            text = await asyncio.to_thread(self.clipboard.get)
            if text is not None and text != self._clipboard_last:
                self._clipboard_last = text
                session.send(p.clipboard(text))
