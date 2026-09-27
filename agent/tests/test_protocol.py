import asyncio
import struct
import unittest

from tuxpane import protocol as p


class ProtocolTest(unittest.TestCase):
    def test_hello_bytes_match_swift_client(self):
        self.assertEqual(
            p.hello("abc", 2560, 1600),
            bytes([0x01, 0, 0, 0, 9, 0, 2, 0x0A, 0x00, 0x06, 0x40]) + b"abc",
        )

    def test_hello_round_trip(self):
        self.assertEqual(p.parse_hello(p.hello("tok", 2560, 1600)[5:]), (p.VERSION, 2560, 1600, "tok"))

    def test_video_round_trip(self):
        nals = [b"\x40\x01a", b"\x26\x01bc"]
        self.assertEqual(p.parse_video(p.video(7, True, nals)[5:]), (7, True, nals))

    def test_input_messages_round_trip(self):
        self.assertEqual(p.parse_key(p.key(30, True)[5:]), (30, True))
        self.assertEqual(p.parse_mouse_move(p.mouse_move(2559, 1599)[5:]), (2559, 1599))
        self.assertEqual(p.parse_mouse_button(p.mouse_button(3, False)[5:]), (3, False))
        self.assertEqual(p.parse_timestamp(p.ping(123456789)[5:]), 123456789)

    def test_scroll_clamps_to_int8(self):
        self.assertEqual(p.parse_scroll(p.scroll(500, -500)[5:]), (127, -128))

    def test_welcome_carries_agent_version(self):
        frame = p.welcome(2560, 1600, "1.0.0")
        self.assertEqual(frame, bytes([0x02, 0, 0, 0, 10, 0x0A, 0x00, 0x06, 0x40, 1]) + b"1.0.0")
        self.assertEqual(p.parse_welcome(frame[5:]), (2560, 1600, p.CODEC_HEVC, "1.0.0"))

    def test_cursor_layout(self):
        self.assertEqual(p.cursor(1, 2, 1, 1, b"\x09\x08\x07\x06"),
                         bytes([0x31, 0, 0, 0, 12, 0, 1, 0, 2, 0, 1, 0, 1, 9, 8, 7, 6]))

    def test_truncated_payloads_raise(self):
        with self.assertRaises(p.ProtocolError):
            p.parse_key(b"\x00")
        with self.assertRaises(p.ProtocolError):
            p.parse_video(struct.pack(">QB", 1, 0) + struct.pack(">I", 10) + b"abc")
        with self.assertRaises(p.ProtocolError):
            p.parse_clipboard(b"\xff\xfe")


class ReadMessageTest(unittest.IsolatedAsyncioTestCase):
    async def test_reads_consecutive_frames_then_eof(self):
        reader = asyncio.StreamReader()
        reader.feed_data(p.key(30, True) + p.ping(5))
        reader.feed_eof()
        self.assertEqual(await p.read_message(reader), (p.KEY, b"\x00\x1e\x01"))
        self.assertEqual(await p.read_message(reader), (p.PING, struct.pack(">Q", 5)))
        with self.assertRaises(asyncio.IncompleteReadError):
            await p.read_message(reader)

    async def test_caller_can_lower_the_size_limit(self):
        reader = asyncio.StreamReader()
        reader.feed_data(p.hello("x" * 2000, 1, 1))
        with self.assertRaises(p.ProtocolError):
            await p.read_message(reader, max_payload=1024)

    async def test_rejects_oversized_frame(self):
        reader = asyncio.StreamReader()
        reader.feed_data(struct.pack(">BI", p.VIDEO, p.MAX_PAYLOAD + 1))
        with self.assertRaises(p.ProtocolError):
            await p.read_message(reader)


if __name__ == "__main__":
    unittest.main()
