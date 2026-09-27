import asyncio
import io
import json
import pathlib
import shutil
import socket
import tempfile
import unittest

from tests.pairing_client import pair
from tuxpane.pair_session import PairingSession
from tuxpane.pairing_protocol import DISCOVER_QUERY
from tuxpane.security import ensure_security_material
from tuxpane.ui import Checklist


@unittest.skipUnless(shutil.which("openssl"), "openssl CLI required")
class PairingSessionTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = pathlib.Path(self.tmp.name)
        self.token, self.fp = ensure_security_material(d)
        self.cert, self.key = d / "cert.pem", d / "key.pem"
        self.out = io.StringIO()
        self.answers: list[bool] = []
        self.asked: list[tuple[str, str]] = []

    async def confirm(self, mac_name, code):
        self.asked.append((mac_name, code))
        if not self.answers:
            await asyncio.sleep(3600)  # nobody answers on Linux
        return self.answers.pop(0)

    def session(self, **overrides):
        options = dict(token=self.token, cert=self.cert, key=self.key, fingerprint_hex=self.fp,
                       hosts=["192.168.1.20", "100.64.100.27"], agent_port=7300, hostname="box",
                       os_name="Linux Mint 22.3", confirm=self.confirm,
                       ui=Checklist(stream=self.out, tty=False, color=False), peer_filter=lambda h: True,
                       attempt_timeout=5.0, session_timeout=30.0, read_timeout=5.0)
        options.update(overrides)
        return PairingSession(**options)

    async def start(self, session):
        task = asyncio.create_task(session.run(host="127.0.0.1", port=0, udp_port=0))
        await asyncio.wait_for(session.started.wait(), 5)
        self.addCleanup(task.cancel)
        return task

    async def test_token_is_sent_only_after_both_confirm(self):
        self.answers = [True]
        session = self.session()
        task = await self.start(session)
        result = await pair("127.0.0.1", session.tcp_port, mac_name="Sam's MacBook Pro")
        self.assertEqual(result["result"], "accepted")
        self.assertEqual(result["accept"], {"token": self.token, "port": 7300,
                                            "hosts": ["192.168.1.20", "100.64.100.27"], "name": "box"})
        self.assertEqual(self.asked, [("Sam's MacBook Pro", result["code"])])
        self.assertIn(result["code"], self.out.getvalue())
        self.assertEqual(await asyncio.wait_for(task, 5), "Sam's MacBook Pro")
        self.assertIn("Paired with Sam's MacBook Pro", self.out.getvalue())

    async def test_linux_declines(self):
        self.answers = [False]
        session = self.session(attempts=1)
        task = await self.start(session)
        result = await pair("127.0.0.1", session.tcp_port)
        self.assertEqual((result["result"], result["reason"]), ("rejected", "declined on Linux"))
        self.assertIsNone(await asyncio.wait_for(task, 5))

    async def test_mac_abort_cancels_linux_prompt(self):
        session = self.session(attempts=1)
        task = await self.start(session)
        result = await pair("127.0.0.1", session.tcp_port, confirm=False)
        self.assertIn(result["result"], ("rejected", "closed"))
        self.assertIsNone(await asyncio.wait_for(task, 5))
        self.assertIn("cancelled on the Mac", self.out.getvalue())

    async def test_bad_commitment_is_rejected(self):
        self.answers = [True]
        session = self.session(attempts=1)
        task = await self.start(session)
        result = await pair("127.0.0.1", session.tcp_port, reveal_nonce=bytes(32))
        self.assertNotEqual(result["result"], "accepted")
        self.assertEqual(self.asked, [])
        self.assertIsNone(await asyncio.wait_for(task, 5))

    async def test_disconnect_mid_attempt_counts_as_failed(self):
        session = self.session(attempts=1)
        task = await self.start(session)
        await pair("127.0.0.1", session.tcp_port, stop_after="reveal")
        self.assertIsNone(await asyncio.wait_for(task, 5))

    async def test_three_failed_attempts_end_the_session(self):
        self.answers = [False, False, False]
        session = self.session()
        task = await self.start(session)
        for _ in range(3):
            await pair("127.0.0.1", session.tcp_port)
        self.assertIsNone(await asyncio.wait_for(task, 5))

    async def test_second_mac_is_told_busy(self):
        session = self.session(attempts=1)
        await self.start(session)
        first = asyncio.create_task(pair("127.0.0.1", session.tcp_port))
        await asyncio.sleep(0.3)
        second = await pair("127.0.0.1", session.tcp_port)
        self.assertEqual((second["result"], second["reason"]), ("rejected", "busy"))
        first.cancel()

    async def test_session_times_out(self):
        session = self.session(session_timeout=0.3)
        task = await self.start(session)
        self.assertIsNone(await asyncio.wait_for(task, 5))

    async def test_discovery_replies_while_pairing(self):
        session = self.session()
        await self.start(session)
        loop = asyncio.get_running_loop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setblocking(False)
        self.addCleanup(sock.close)
        sock.sendto(json.dumps(DISCOVER_QUERY).encode(), ("127.0.0.1", session.udp_port))
        reply = await asyncio.wait_for(loop.sock_recv(sock, 2048), 3)
        self.assertEqual(json.loads(reply), {"n": "box", "os": "Linux Mint 22.3", "v": 1, "pp": 7301})

    async def test_discovery_ignores_junk_and_public_peers(self):
        session = self.session(peer_filter=lambda host: False)
        await self.start(session)
        loop = asyncio.get_running_loop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setblocking(False)
        self.addCleanup(sock.close)
        for data in (json.dumps(DISCOVER_QUERY).encode(), b"\xff\xfe junk"):
            sock.sendto(data, ("127.0.0.1", session.udp_port))
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(loop.sock_recv(sock, 2048), 0.5)


@unittest.skipUnless(shutil.which("openssl"), "openssl CLI required")
class PairingSessionHardeningTest(PairingSessionTest):
    async def test_mac_name_cannot_control_the_terminal(self):
        self.answers = [True]
        session = self.session()
        await self.start(session)
        await pair("127.0.0.1", session.tcp_port, mac_name="Evil\x1b[2J\x1b]0;x\x07Mac\n")
        name = self.asked[0][0]
        self.assertFalse(any(not c.isprintable() for c in name), repr(name))
        self.assertNotIn("\x1b", self.out.getvalue())

    async def test_mac_disconnect_is_reported_as_cancelled(self):
        session = self.session(attempts=1)
        task = await self.start(session)
        await pair("127.0.0.1", session.tcp_port, stop_after="reveal")
        await asyncio.wait_for(task, 5)
        self.assertIn("The Mac disconnected", self.out.getvalue())

    async def test_terminal_errors_do_not_escape(self):
        async def broken(mac_name, code):
            raise OSError("terminal went away")

        errors = []
        asyncio.get_running_loop().set_exception_handler(lambda loop, context: errors.append(context))
        session = self.session(attempts=1, confirm=broken)
        task = await self.start(session)
        result = await pair("127.0.0.1", session.tcp_port)
        await asyncio.sleep(0.2)
        self.assertEqual(errors, [], "no unhandled exception may reach the event loop")
        self.assertNotEqual(result["result"], "accepted")
        self.assertIsNone(await asyncio.wait_for(task, 5))


if __name__ == "__main__":
    unittest.main()
