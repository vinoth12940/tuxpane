"""The foreground pairing session behind `tuxpane pair` and the end of the installer.

It listens on TCP 7301 (TLS, same certificate as the agent) for one pairing attempt at a time and answers
discovery broadcasts on UDP 7301, until a Mac is paired, three attempts fail, or ten minutes pass."""
from __future__ import annotations

import asyncio
import hmac
import logging
import os
import secrets
import termios

from . import protocol as p
from .pairing_protocol import (MAX_PAIR_MESSAGE, PAIR_ABORT, PAIR_ACCEPT, PAIR_CONFIRM, PAIR_HELLO, PAIR_NONCE,
                               PAIR_PORT, PAIR_REJECT, PAIR_REVEAL, PAIR_VERSION, commitment, discovery_reply,
                               fields, is_discovery_query, message, sas_code)
from .security import is_allowed_peer, server_tls_context

log = logging.getLogger(__name__)


def os_pretty_name(path: str = "/etc/os-release") -> str:
    try:
        for line in open(path, encoding="utf-8"):
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return "Linux"


def open_terminal(path: str = "/dev/tty"):
    """Separate read and write text streams: a terminal isn't seekable, so Python refuses "r+" on it."""
    reader = open(path, "r", encoding="utf-8", errors="replace")
    try:
        writer = open(path, "w", encoding="utf-8")
    except OSError:
        reader.close()
        raise
    return reader, writer


def is_interactive(path: str = "/dev/tty") -> bool:
    try:
        reader, writer = open_terminal(path)
    except OSError:
        return False
    reader.close()
    writer.close()
    return True


class TerminalPrompt:
    """A y/N question on the controlling terminal that can be cancelled (e.g. when the Mac aborts)."""

    def __init__(self, path: str = "/dev/tty") -> None:
        self.path = path

    async def ask(self, question: str) -> bool:
        loop = asyncio.get_running_loop()
        reader, writer = open_terminal(self.path)
        answer: asyncio.Future = loop.create_future()
        try:  # ignore anything typed before the question appeared, so a stray Enter or "y" can't answer it
            termios.tcflush(reader.fileno(), termios.TCIFLUSH)
        except (OSError, termios.error):
            pass
        writer.write(question + " ")
        writer.flush()

        def on_line() -> None:
            if not answer.done():
                answer.set_result(reader.readline().strip().lower())

        loop.add_reader(reader.fileno(), on_line)
        try:
            return (await answer).startswith("y")
        finally:
            loop.remove_reader(reader.fileno())
            reader.close()
            writer.close()


class _Discovery(asyncio.DatagramProtocol):
    def __init__(self, session: "PairingSession") -> None:
        self.session = session
        self.transport = None

    def connection_made(self, transport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, addr) -> None:
        if len(data) > 512 or not self.session.peer_filter(addr[0]) or not is_discovery_query(data):
            return
        self.transport.sendto(discovery_reply(self.session.hostname, self.session.os_name), addr)


class PairingSession:
    def __init__(self, *, token: str, cert, key, fingerprint_hex: str, hosts: list[str], agent_port: int,
                 hostname: str, os_name: str, confirm, ui, peer_filter=is_allowed_peer, attempts: int = 3,
                 attempt_timeout: float = 120.0, session_timeout: float = 600.0, read_timeout: float = 30.0) -> None:
        self.token, self.cert, self.key = token, cert, key
        self.fingerprint = bytes.fromhex(fingerprint_hex)
        self.hosts, self.agent_port, self.hostname, self.os_name = hosts, agent_port, hostname, os_name
        self.confirm, self.ui, self.peer_filter = confirm, ui, peer_filter
        self.attempts_left = attempts
        self.attempt_timeout, self.session_timeout, self.read_timeout = attempt_timeout, session_timeout, read_timeout
        self.started = asyncio.Event()
        self.tcp_port = 0
        self.udp_port = 0
        self._busy = False
        self._done: asyncio.Future | None = None

    async def run(self, host: str = "0.0.0.0", port: int = PAIR_PORT, udp_port: int = PAIR_PORT) -> str | None:
        loop = asyncio.get_running_loop()
        self._done = loop.create_future()
        server = await asyncio.start_server(self._handle, host, port, ssl=server_tls_context(self.cert, self.key),
                                            ssl_handshake_timeout=10)
        transport, _ = await loop.create_datagram_endpoint(lambda: _Discovery(self), local_addr=(host, udp_port))
        self.tcp_port = server.sockets[0].getsockname()[1]
        self.udp_port = transport.get_extra_info("sockname")[1]
        self.started.set()
        countdown = loop.create_task(self._countdown(loop.time() + self.session_timeout))
        try:
            return await asyncio.wait_for(asyncio.shield(self._done), self.session_timeout)
        except asyncio.TimeoutError:
            self.ui.end_waiting()
            self.ui.text(f"  {self.ui.red('✗') if self.ui.color else '[x]'} No Mac paired within "
                         f"{int(self.session_timeout // 60)} minutes. Run `tuxpane pair` to try again.")
            return None
        finally:
            countdown.cancel()
            transport.close()
            server.close()

    async def _countdown(self, deadline: float) -> None:
        loop = asyncio.get_running_loop()
        while True:
            if not self._busy:
                self.ui.waiting(int(deadline - loop.time()))
            await asyncio.sleep(1)

    def _finish(self, result: str | None) -> None:
        if self._done is not None and not self._done.done():
            self._done.set_result(result)

    def _failed_attempt(self) -> None:
        self.attempts_left -= 1
        if self.attempts_left <= 0:
            self.ui.text("  Too many unsuccessful attempts. Run `tuxpane pair` to try again.")
            self._finish(None)

    async def _read(self, reader, expected: int) -> dict:
        msg_type, payload = await asyncio.wait_for(p.read_message(reader, MAX_PAIR_MESSAGE), self.read_timeout)
        if msg_type != expected:
            raise p.ProtocolError(f"expected message {expected:#x}, got {msg_type:#x}")
        return fields(payload)

    async def _handle(self, reader, writer) -> None:
        peer = writer.get_extra_info("peername")
        if not self.peer_filter(peer[0] if peer else ""):
            writer.transport.abort()
            return
        if self._busy or (self._done is not None and self._done.done()):
            writer.write(message(PAIR_REJECT, reason="busy"))
            await writer.drain()
            writer.close()
            return
        self._busy = True
        linux_answer: asyncio.Task | None = None
        mac_answer: asyncio.Task | None = None
        succeeded = False
        try:
            hello = await self._read(reader, PAIR_HELLO)
            # Shown on the terminal: drop control characters so the Mac's name can't move the cursor or retitle it.
            mac_name = "".join(c for c in str(hello.get("name") or "A Mac") if c.isprintable())[:64] or "A Mac"
            commit = str(hello.get("commit", ""))
            if hello.get("v") != PAIR_VERSION or len(commit) != 64:
                raise p.ProtocolError("unsupported pairing request")
            agent_nonce = secrets.token_bytes(32)
            writer.write(message(PAIR_NONCE, nonce=agent_nonce.hex()))
            mac_nonce = bytes.fromhex(str((await self._read(reader, PAIR_REVEAL)).get("nonce", "")))
            if len(mac_nonce) != 32 or not hmac.compare_digest(commitment(mac_nonce), commit):
                raise p.ProtocolError("commitment mismatch")
            code = sas_code(self.fingerprint, agent_nonce, mac_nonce)
            self.ui.end_waiting()
            self.ui.text()
            self.ui.text(f"  {self.ui.yellow(mac_name)} wants to pair. Your Mac should show:")
            self.ui.text()
            self.ui.code_box(code)
            self.ui.text()
            linux_answer = asyncio.create_task(self.confirm(mac_name, code))
            mac_answer = asyncio.create_task(p.read_message(reader, MAX_PAIR_MESSAGE))
            done, _ = await asyncio.wait({linux_answer, mac_answer}, timeout=self.attempt_timeout,
                                         return_when=asyncio.FIRST_COMPLETED)
            if not done:
                raise asyncio.TimeoutError
            if mac_answer in done:
                msg_type, _ = mac_answer.result()
                if msg_type != PAIR_CONFIRM:
                    linux_answer.cancel()
                    self.ui.text()
                    self.ui.text(f"  {self.ui.red('✗') if self.ui.color else '[x]'} Pairing cancelled on the Mac.")
                    return
                linux_ok = await asyncio.wait_for(linux_answer, self.attempt_timeout)
            else:
                linux_ok = linux_answer.result()
                if not linux_ok:
                    writer.write(message(PAIR_REJECT, reason="declined on Linux"))
                    await writer.drain()
                    mac_answer.cancel()
                    self.ui.text("  Pairing declined.")
                    return
                msg_type, _ = await asyncio.wait_for(mac_answer, self.attempt_timeout)
                if msg_type != PAIR_CONFIRM:
                    self.ui.text(f"  {self.ui.red('✗') if self.ui.color else '[x]'} Pairing cancelled on the Mac.")
                    return
            if not linux_ok:
                writer.write(message(PAIR_REJECT, reason="declined on Linux"))
                await writer.drain()
                self.ui.text("  Pairing declined.")
                return
            writer.write(message(PAIR_ACCEPT, token=self.token, port=self.agent_port, hosts=self.hosts,
                                 name=self.hostname))
            await writer.drain()
            succeeded = True
            self.ui.ok(f"Paired with {mac_name}")
            self._finish(mac_name)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionError, p.ProtocolError, ValueError,
                OSError) as exc:
            log.info("pairing attempt from %s failed: %r", peer, exc)
            self.ui.text()
            if isinstance(exc, (asyncio.IncompleteReadError, ConnectionError)):
                self.ui.text(f"  {self.ui.red('✗') if self.ui.color else '[x]'} The Mac disconnected, pairing cancelled.")
            else:
                self.ui.text(f"  Pairing attempt did not complete ({type(exc).__name__}).")
        finally:
            for task in (linux_answer, mac_answer):
                if task is not None and not task.done():
                    task.cancel()
            self._busy = False
            if not succeeded:
                self._failed_attempt()
            writer.close()
