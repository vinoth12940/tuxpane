import io
import unittest

from tuxpane.ui import Checklist


def plain():
    stream = io.StringIO()
    return Checklist(stream=stream, tty=False, color=False), stream


class ChecklistTest(unittest.TestCase):
    def test_plain_checklist_is_ascii_and_aligned(self):
        ui, out = plain()
        ui.header("TuxPane 1.0 · Linux setup")
        ui.start("Desktop session")
        ui.ok("Desktop session", "X11 on :0")
        ui.ok("Required packages")
        self.assertEqual(out.getvalue(),
                         "TuxPane 1.0 · Linux setup\n\n"
                         "  [ok] Desktop session      X11 on :0\n"
                         "  [ok] Required packages\n")

    def test_failure_shows_the_fix_indented(self):
        ui, out = plain()
        ui.fail("Video encoder", "No working HEVC encoder.\nInstall a full ffmpeg.")
        self.assertEqual(out.getvalue(), "  [x] Video encoder\n      No working HEVC encoder.\n      Install a full ffmpeg.\n")

    def test_warning_lists_commands(self):
        ui, out = plain()
        ui.warn("Firewall", ["ufw is on. Run:", "sudo ufw allow 7300"])
        self.assertEqual(out.getvalue(), "  [!] Firewall\n      ufw is on. Run:\n      sudo ufw allow 7300\n")

    def test_colour_mode_uses_ticks_and_rewrites_running_line(self):
        out = io.StringIO()
        ui = Checklist(stream=out, tty=True, color=True)
        ui.start("Video encoder")
        ui.ok("Video encoder", "AMD hardware")
        text = out.getvalue()
        self.assertIn("\033[32m✓\033[0m", text)
        self.assertIn("\r\033[K", text)
        self.assertIn("Video encoder…", text)

    def test_code_box(self):
        ui, out = plain()
        ui.code_box("482 913")
        self.assertEqual(out.getvalue(), "      +-----------+\n      |  482 913  |\n      +-----------+\n")

    def test_waiting_line_only_on_a_terminal(self):
        ui, out = plain()
        ui.waiting(581)
        ui.end_waiting()
        self.assertEqual(out.getvalue(), "")
        out2 = io.StringIO()
        tty = Checklist(stream=out2, tty=True, color=False)
        tty.waiting(581)
        self.assertIn("Waiting for your Mac… 9:41 left", out2.getvalue())


if __name__ == "__main__":
    unittest.main()
