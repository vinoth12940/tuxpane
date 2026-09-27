import sys
import unittest
from unittest import mock

from tuxpane import encoder as encoder_module
from tuxpane.encoder import Encoder, build_ffmpeg_cmd, make_cmd_builder, rtp_output
from tests.fakes import IDR, TRAIL, VPS, eventually, rtp

SENDER = (
    "import socket, sys, time\n"
    "s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)\n"
    "for h in sys.argv[2:]:\n"
    "    s.sendto(bytes.fromhex(h), ('127.0.0.1', int(sys.argv[1])))\n"
    "time.sleep(30)\n"
)


def fake_ffmpeg(packets):
    def build(display, width, height, fps, bitrate, port):
        return [sys.executable, "-c", SENDER, str(port), *(p.hex() for p in packets)]
    return build


class CommandTest(unittest.TestCase):
    def test_vaapi_pipeline(self):
        cmd = build_ffmpeg_cmd("vaapi", ":0", 2560, 1600, 60, 20, rtp_output(5000), vaapi_device="/dev/dri/renderD129")
        joined = " ".join(cmd)
        for part in ("vaapi=va:/dev/dri/renderD129", "-f x11grab", "-draw_mouse 0", "-framerate 60",
                     "-video_size 2560x1600", "-i :0", "-c:v hevc_vaapi", "-async_depth 1", "-bf 0", "-g 120",
                     "-b:v 20M", "-maxrate 40M", "dump_extra=freq=keyframe"):
            self.assertIn(part, joined)
        self.assertEqual(cmd[-1], "rtp://127.0.0.1:5000?pkt_size=16000")

    def test_nvenc_pipeline(self):
        joined = " ".join(build_ffmpeg_cmd("nvenc", ":0", 1920, 1080, 60, 20, ["-f", "null", "-"]))
        for part in ("-c:v hevc_nvenc", "-tune ull", "-zerolatency 1", "-bf 0"):
            self.assertIn(part, joined)
        self.assertNotIn("vaapi", joined)

    def test_x265_is_capped_for_cpu_encoding(self):
        joined = " ".join(build_ffmpeg_cmd("x265", ":0", 2560, 1600, 60, 20, ["-f", "null", "-"]))
        for part in ("-c:v libx265", "-preset ultrafast", "-tune zerolatency", "-framerate 30",
                     "scale='min(1920,iw)':-2", "repeat-headers=1"):
            self.assertIn(part, joined)

    def test_unknown_encoder_is_rejected(self):
        with self.assertRaises(ValueError):
            build_ffmpeg_cmd("h264", ":0", 1, 1, 60, 20, [])

    def test_cmd_builder_keeps_encoder_signature(self):
        cmd = make_cmd_builder("x265", "/dev/dri/renderD128")(":1", 1920, 1080, 60, 10, 6000)
        self.assertIn("libx265", cmd)
        self.assertEqual(cmd[-1], "rtp://127.0.0.1:6000?pkt_size=16000")


class EncoderTest(unittest.IsolatedAsyncioTestCase):
    async def test_emits_access_units_from_process(self):
        units = []
        enc = Encoder(lambda nals, key, pts: units.append((nals, key)),
                      cmd_builder=fake_ffmpeg([rtp(VPS, 1), rtp(IDR, 2, marker=True)]))
        await enc.start(64, 64)
        try:
            await eventually(lambda: units)
        finally:
            await enc.stop()
        self.assertEqual(units[0], ([VPS, IDR], True))

    async def test_keyframe_request_restarts_process_but_is_rate_limited(self):
        enc = Encoder(lambda *a: None, cmd_builder=fake_ffmpeg([]))
        await enc.start(64, 64)
        try:
            await enc.request_keyframe()
            self.assertEqual(enc.spawn_count, 1)
            enc._last_spawn -= 1
            await enc.request_keyframe()
            self.assertEqual(enc.spawn_count, 2)
        finally:
            await enc.stop()

    async def test_request_keyframe_after_stop_does_nothing(self):
        enc = Encoder(lambda *a: None, cmd_builder=fake_ffmpeg([]))
        await enc.start(64, 64)
        await enc.stop()
        enc._last_spawn -= 1
        await enc.request_keyframe()
        self.assertEqual(enc.spawn_count, 1)

    async def test_repeated_fast_exits_report_failure_and_stop(self):
        failures = []

        def crashing(*args):
            return [sys.executable, "-c", "import sys; sys.stderr.write('vaapi init failed'); sys.exit(1)"]

        with mock.patch.object(encoder_module, "RESPAWN_DELAY", 0.01):
            enc = Encoder(lambda *a: None, on_failure=failures.append, cmd_builder=crashing)
            await enc.start(64, 64)
            await eventually(lambda: failures)
            await enc.stop()
        self.assertIn("vaapi init failed", failures[0])
        self.assertEqual(enc.spawn_count, encoder_module.MAX_FAST_EXITS)

    async def test_set_bitrate_restarts_with_new_rate(self):
        rates = []

        def build(display, width, height, fps, bitrate, port):
            rates.append(bitrate)
            return fake_ffmpeg([])(display, width, height, fps, bitrate, port)

        enc = Encoder(lambda *a: None, cmd_builder=build)
        await enc.start(64, 64)
        try:
            await enc.set_bitrate(10)
        finally:
            await enc.stop()
        self.assertEqual(rates, [20, 10])

    async def test_frames_after_packet_loss_wait_for_keyframe(self):
        units = []
        enc = Encoder(lambda nals, key, pts: units.append(nals), cmd_builder=fake_ffmpeg([]))
        enc._on_packet(rtp(IDR, 1, marker=True))
        enc._on_packet(rtp(TRAIL, 3, marker=True))  # seq 2 lost: this frame is dropped
        enc._on_packet(rtp(TRAIL, 4, marker=True))  # references the lost frame: must not be shown
        enc._on_packet(rtp(IDR, 5, marker=True))
        enc._on_packet(rtp(TRAIL, 6, marker=True))
        await enc.stop()
        self.assertEqual(units, [[IDR], [IDR], [TRAIL]])


if __name__ == "__main__":
    unittest.main()
