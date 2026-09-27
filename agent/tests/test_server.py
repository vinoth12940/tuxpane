import asyncio
import socket
import threading
import unittest
from unittest import mock

from tuxpane import __version__
from tuxpane import protocol as p
from tuxpane import server as server_module
from tuxpane.server import NOTSENT_LOWAT, Server, Session, tune_socket
from tests.fakes import IDR, TRAIL, VPS, FakeClipboard, FakeDisplay, FakeEncoder, RecordingInjector, eventually

TOKEN = "s3cret-token-value"


class ServerTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        patcher = mock.patch.object(server_module, "CLIPBOARD_POLL_SECONDS", 0.01)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.injector = RecordingInjector()
        self.clipboard = FakeClipboard()
        self.server = Server(TOKEN, self.injector, FakeDisplay(), FakeEncoder, clipboard=self.clipboard)
        self.tcp = await asyncio.start_server(self.server.handle, "127.0.0.1", 0)
        self.port = self.tcp.sockets[0].getsockname()[1]
        self.writers = []

    async def asyncTearDown(self):
        for w in self.writers:
            w.close()
        self.tcp.close()

    async def connect(self, token=TOKEN, size=(2560, 1600)):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        self.writers.append(writer)
        writer.write(p.hello(token, *size))
        await writer.drain()
        return reader, writer

    async def read(self, reader, expected_type):
        msg_type, payload = await asyncio.wait_for(p.read_message(reader), 2)
        self.assertEqual(msg_type, expected_type)
        return payload

    async def test_rejects_wrong_token(self):
        reader, _ = await self.connect(token="wrong-token-value!")
        self.assertEqual(await self.read(reader, p.ERROR), b"authentication failed")
        with self.assertRaises(asyncio.IncompleteReadError):
            await asyncio.wait_for(p.read_message(reader), 2)
        self.assertEqual(self.server.encoder.starts, [])

    async def test_first_message_must_be_hello(self):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        self.writers.append(writer)
        writer.write(p.key(30, True))
        with self.assertRaises(asyncio.IncompleteReadError):
            await asyncio.wait_for(p.read_message(reader), 2)
        self.assertEqual(self.injector.events, [])

    async def test_welcome_uses_requested_supported_mode(self):
        reader, _ = await self.connect()
        self.assertEqual(p.parse_welcome(await self.read(reader, p.WELCOME)), (2560, 1600, p.CODEC_HEVC, __version__))
        await eventually(lambda: self.server.encoder.starts == [(2560, 1600)])

    async def test_unsupported_mode_falls_back_to_current(self):
        reader, _ = await self.connect(size=(3456, 2160))
        self.assertEqual(p.parse_welcome(await self.read(reader, p.WELCOME))[:2], (1920, 1200))

    async def test_input_is_injected(self):
        reader, writer = await self.connect()
        await self.read(reader, p.WELCOME)
        writer.write(p.key(30, True) + p.mouse_move(10, 20) + p.mouse_button(1, True) + p.scroll(0, 1))
        await eventually(lambda: len(self.injector.events) == 5)
        self.assertEqual(self.injector.events, [
            ("key", 38, True), ("move", 10, 20), ("button", 1, True), ("button", 4, True), ("button", 4, False)])

    async def test_disconnect_releases_held_input(self):
        reader, writer = await self.connect()
        await self.read(reader, p.WELCOME)
        writer.write(p.key(29, True) + p.mouse_button(1, True))
        await eventually(lambda: self.injector.held_keys == [29])
        writer.close()
        await eventually(lambda: self.server.encoder.stops == 1)
        self.assertEqual((self.injector.held_keys, self.injector.held_buttons), ([], []))
        self.assertIn(("key", 37, False), self.injector.events)
        self.assertIsNone(self.server.session)

    async def test_new_client_replaces_old(self):
        reader_a, _ = await self.connect()
        await self.read(reader_a, p.WELCOME)
        reader_b, _ = await self.connect()
        await self.read(reader_b, p.WELCOME)
        messages = []
        with self.assertRaises(asyncio.IncompleteReadError):
            while True:
                messages.append(await asyncio.wait_for(p.read_message(reader_a), 2))
        # The bumped Mac is told why, so it stops reconnecting instead of bumping the new one back.
        self.assertIn((p.ERROR, p.REPLACED_MESSAGE.encode()), messages)
        self.assertEqual(self.server.encoder.stops, 0)

    async def test_video_waits_for_keyframe(self):
        reader, _ = await self.connect()
        await self.read(reader, p.WELCOME)
        await eventually(lambda: self.server.session is not None)
        self.server.on_access_unit([TRAIL], False, 1)
        await eventually(lambda: self.server.encoder.keyframe_requests == 1)
        self.server.on_access_unit([VPS, IDR], True, 2)
        self.server.on_access_unit([TRAIL], False, 3)
        self.assertEqual(p.parse_video(await self.read(reader, p.VIDEO)), (2, True, [VPS, IDR]))
        self.assertEqual(p.parse_video(await self.read(reader, p.VIDEO)), (3, False, [TRAIL]))

    async def test_ping_is_answered(self):
        reader, writer = await self.connect()
        await self.read(reader, p.WELCOME)
        writer.write(p.ping(42))
        while True:
            msg_type, payload = await asyncio.wait_for(p.read_message(reader), 2)
            if msg_type == p.PONG:
                break
        self.assertEqual(p.parse_timestamp(payload), 42)

    async def test_clipboard_syncs_both_ways(self):
        reader, writer = await self.connect()
        await self.read(reader, p.WELCOME)
        writer.write(p.clipboard("from mac"))
        await eventually(lambda: self.clipboard.sets == ["from mac"])
        await asyncio.sleep(0.05)
        self.clipboard.text = "from linux"
        while True:
            msg_type, payload = await asyncio.wait_for(p.read_message(reader), 2)
            if msg_type == p.CLIPBOARD:
                break
        self.assertEqual(p.parse_clipboard(payload), "from linux")

    async def test_silent_client_gets_held_input_released(self):
        with mock.patch.object(server_module, "INPUT_IDLE_SECONDS", 0.1):
            reader, writer = await self.connect()
            await self.read(reader, p.WELCOME)
            writer.write(p.key(29, True))
            await eventually(lambda: self.injector.held_keys == [29])
            await eventually(lambda: self.injector.held_keys == [])
        self.assertIsNotNone(self.server.session)

    async def test_encoder_failure_is_reported_to_client(self):
        reader, _ = await self.connect()
        await self.read(reader, p.WELCOME)
        self.server.on_capture_failure("vaapi init failed")
        self.assertIn(b"vaapi init failed", await self.read(reader, p.ERROR))
        with self.assertRaises(asyncio.IncompleteReadError):
            await asyncio.wait_for(p.read_message(reader), 2)

    async def test_repeated_congestion_lowers_bitrate(self):
        reader, _ = await self.connect()
        await self.read(reader, p.WELCOME)
        for _ in range(3):
            self.server.note_congestion()
        await eventually(lambda: self.server.encoder.bitrates == [10])

    def test_send_buffer_limit_is_about_150ms_of_video(self):
        self.assertEqual(self.server.send_buffer_limit(), 375_000)

    async def test_oversized_hello_is_rejected_before_auth(self):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        self.writers.append(writer)
        writer.write(p.hello("x" * 4096, 2560, 1600))
        with self.assertRaises(asyncio.IncompleteReadError):
            await asyncio.wait_for(p.read_message(reader), 2)
        self.assertEqual(self.server.encoder.starts, [])

    async def test_version_mismatch_says_so(self):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        self.writers.append(writer)
        writer.write(p.encode(p.HELLO, bytes([0, 9, 0, 1, 0, 1]) + TOKEN.encode()))
        self.assertIn(b"protocol version 9", await self.read(reader, p.ERROR))

    async def test_clipboard_failure_keeps_session(self):
        def broken_set(text):
            raise FileNotFoundError("xclip")
        self.clipboard.set = broken_set
        reader, writer = await self.connect()
        await self.read(reader, p.WELCOME)
        writer.write(p.clipboard("x") + p.ping(7))
        while True:
            msg_type, payload = await asyncio.wait_for(p.read_message(reader), 2)
            if msg_type == p.PONG:
                break
        self.assertEqual(p.parse_timestamp(payload), 7)

    async def test_client_replaced_during_mode_switch_does_not_start_capture(self):
        gate = threading.Event()

        class SlowDisplay(FakeDisplay):
            calls = 0

            def ensure_mode(self, width, height):
                SlowDisplay.calls += 1
                if SlowDisplay.calls == 1:
                    gate.wait(2)
                return super().ensure_mode(width, height)

        self.server.display = SlowDisplay()
        await self.connect()
        await eventually(lambda: SlowDisplay.calls == 1)
        reader_b, _ = await self.connect()
        await self.read(reader_b, p.WELCOME)
        gate.set()
        await asyncio.sleep(0.1)
        self.assertEqual(self.server.encoder.starts, [(2560, 1600)])

    async def test_shutdown_releases_input_and_stops_capture(self):
        reader, writer = await self.connect()
        await self.read(reader, p.WELCOME)
        writer.write(p.key(29, True))
        await eventually(lambda: self.injector.held_keys == [29])
        await self.server.shutdown()
        self.assertEqual(self.injector.held_keys, [])
        self.assertEqual(self.server.encoder.stops, 1)

    async def test_non_private_peer_is_dropped_before_handshake(self):
        server = Server(TOKEN, RecordingInjector(), FakeDisplay(), FakeEncoder, peer_filter=lambda host: False)
        tcp = await asyncio.start_server(server.handle, "127.0.0.1", 0)
        self.addCleanup(tcp.close)
        reader, writer = await asyncio.open_connection("127.0.0.1", tcp.sockets[0].getsockname()[1])
        self.writers.append(writer)
        writer.write(p.hello(TOKEN, 2560, 1600))
        with self.assertRaises((asyncio.IncompleteReadError, ConnectionResetError)):
            await asyncio.wait_for(p.read_message(reader), 2)
        self.assertEqual(server.encoder.starts, [])

    async def test_no_desktop_session_is_reported_to_client(self):
        class NoDesktop(RecordingInjector):
            def ensure_ready(self):
                raise RuntimeError("cannot open X display :0: is a user logged in to the desktop?")

        server = Server(TOKEN, NoDesktop(), FakeDisplay(), FakeEncoder)
        tcp = await asyncio.start_server(server.handle, "127.0.0.1", 0)
        self.addCleanup(tcp.close)
        reader, writer = await asyncio.open_connection("127.0.0.1", tcp.sockets[0].getsockname()[1])
        self.writers.append(writer)
        writer.write(p.hello(TOKEN, 2560, 1600))
        self.assertIn(b"logged in to the desktop", await self.read(reader, p.ERROR))
        self.assertEqual(server.encoder.starts, [])

    async def test_capture_failure_is_reported(self):
        class BrokenDisplay:
            def ensure_mode(self, width, height):
                raise FileNotFoundError("xrandr")

        server = Server(TOKEN, RecordingInjector(), BrokenDisplay(), FakeEncoder)
        tcp = await asyncio.start_server(server.handle, "127.0.0.1", 0)
        self.addCleanup(tcp.close)
        reader, writer = await asyncio.open_connection("127.0.0.1", tcp.sockets[0].getsockname()[1])
        self.writers.append(writer)
        writer.write(p.hello(TOKEN, 2560, 1600))
        self.assertIn(b"cannot start capture", await self.read(reader, p.ERROR))
        await eventually(lambda: server.session is None)


class TuneSocketTest(unittest.TestCase):
    def test_warns_when_notsent_lowat_is_unavailable(self):
        class FakeSock:
            def setsockopt(self, *args):
                raise AssertionError("must not be called")

        with mock.patch.object(server_module.socket, "TCP_NOTSENT_LOWAT", None, create=True):
            with self.assertLogs(server_module.log, "WARNING"):
                tune_socket(FakeSock())

    def test_sets_notsent_lowat_when_available(self):
        calls = []

        class FakeSock:
            def setsockopt(self, *args):
                calls.append(args)

        with mock.patch.object(server_module.socket, "TCP_NOTSENT_LOWAT", 25, create=True):
            tune_socket(FakeSock())
        self.assertEqual(calls, [(socket.IPPROTO_TCP, 25, NOTSENT_LOWAT)])

    def test_missing_socket_is_ignored(self):
        tune_socket(None)


class _Transport:
    def __init__(self):
        self.size = 0
        self.aborted = False

    def abort(self):
        self.aborted = True

    def get_write_buffer_size(self):
        return self.size


class _Writer:
    def __init__(self):
        self.transport = _Transport()
        self.written = []
        self.aborted = False

    def write(self, data):
        self.written.append(data)

    def close(self):
        pass


class _Server:
    def __init__(self):
        self.keyframe_requests = 0
        self.congestion_notes = 0

    def request_keyframe(self):
        self.keyframe_requests += 1

    def send_buffer_limit(self):
        return 1000

    def note_congestion(self):
        self.congestion_notes += 1


class SessionTest(unittest.TestCase):
    def test_no_video_before_welcome(self):
        writer = _Writer()
        Session(_Server(), None, writer).send_video([IDR], True, 1)
        self.assertEqual(writer.written, [])

    def test_abort_drops_connection_immediately(self):
        writer = _Writer()
        session = Session(_Server(), None, writer)
        session.abort()
        self.assertTrue(session.closed and writer.transport.aborted)


class SessionCongestionTest(unittest.TestCase):
    def test_drops_frames_until_keyframe_when_link_is_slow(self):
        server, writer = _Server(), _Writer()
        session = Session(server, None, writer)
        session.ready = True
        session.send_video([VPS, IDR], True, 1)
        self.assertEqual(len(writer.written), 1)
        writer.transport.size = 1001
        session.send_video([TRAIL], False, 2)
        session.send_video([TRAIL], False, 3)
        self.assertEqual((len(writer.written), server.congestion_notes), (1, 1))
        writer.transport.size = 0
        session.send_video([TRAIL], False, 3)
        self.assertEqual((len(writer.written), server.keyframe_requests), (1, 1))
        session.send_video([VPS, IDR], True, 4)
        self.assertEqual(len(writer.written), 2)


if __name__ == "__main__":
    unittest.main()
