import subprocess
import unittest

from tuxpane.display import Display, parse_xrandr

XRANDR = """Screen 0: minimum 320 x 200, current 1920 x 1200, maximum 16384 x 16384
DisplayPort-0 disconnected (normal left inverted right x axis y axis)
HDMI-A-0 connected primary 1920x1200+0+0 (normal left inverted right x axis y axis) 480mm x 270mm
   1920x1080     60.00 + 120.04   144.00
   2560x1600     59.99
   1920x1200     59.95*
DisplayPort-1 disconnected (normal left inverted right x axis y axis)
   3840x2160     60.00
"""


class FakeRun:
    def __init__(self):
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout=XRANDR if args[1] == "--query" else "")


class DisplayTest(unittest.TestCase):
    def test_parse_first_connected_output(self):
        output, current, modes = parse_xrandr(XRANDR)
        self.assertEqual(output, "HDMI-A-0")
        self.assertEqual(current, (1920, 1200))
        self.assertEqual(modes, {(1920, 1080), (2560, 1600), (1920, 1200)})

    def test_switches_to_supported_mode(self):
        run = FakeRun()
        self.assertEqual(Display(run=run).ensure_mode(2560, 1600), (2560, 1600))
        self.assertEqual(run.calls[-1], ["xrandr", "--output", "HDMI-A-0", "--mode", "2560x1600"])

    def test_mac_sizes_snap_to_the_closest_real_mode(self):
        # A notched MacBook's full-screen area is 3456x2170, so presets ask for 2560x1606 / 1920x1206.
        for wanted, expected in (((2560, 1606), (2560, 1600)), ((3456, 2170), (2560, 1600)), ((1920, 1206), (1920, 1200))):
            run = FakeRun()
            self.assertEqual(Display(run=run).ensure_mode(*wanted), expected, wanted)

    def test_16_9_mac_prefers_a_16_9_mode(self):
        run = FakeRun()
        self.assertEqual(Display(run=run).ensure_mode(2560, 1440), (1920, 1080))
        self.assertEqual(run.calls[-1], ["xrandr", "--output", "HDMI-A-0", "--mode", "1920x1080"])

    def test_nothing_small_enough_keeps_current(self):
        run = FakeRun()
        self.assertEqual(Display(run=run).ensure_mode(1280, 720), (1920, 1200))
        self.assertEqual(len(run.calls), 1)

    def test_zero_size_keeps_current(self):
        run = FakeRun()
        self.assertEqual(Display(run=run).ensure_mode(0, 0), (1920, 1200))
        self.assertEqual(len(run.calls), 1)

    def test_current_mode_is_not_reapplied(self):
        run = FakeRun()
        self.assertEqual(Display(run=run).ensure_mode(1920, 1200), (1920, 1200))
        self.assertEqual(len(run.calls), 1)

    def test_match_resolution_off_never_changes_mode(self):
        run = FakeRun()
        self.assertEqual(Display(run=run, match_resolution=False).ensure_mode(2560, 1600), (1920, 1200))
        self.assertEqual(run.calls, [["xrandr", "--query"]])


if __name__ == "__main__":
    unittest.main()
