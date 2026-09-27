import pathlib
import tempfile
import unittest

from tests.fakes import ScriptedRun
from tuxpane.setup_checks import (SetupError, detect_package_manager, find_graphical_session, find_xauthority,
                                  install_command, missing_requirements, probe_encoder, screen_size)

SESSIONS = "     2 1000 alice seat0 tty7 active no -\n    c9 1001 bob -     -    active no -\n"
XRANDR = "Screen 0: minimum 320 x 200, current 1920 x 1200\nHDMI-A-0 connected primary 1920x1200+0+0 (normal)\n   1920x1200 60.00*\n"


def loginctl(session_type):
    return ScriptedRun([
        (("loginctl", "list-sessions"), 0, SESSIONS, ""),
        (("loginctl", "show-session", "2"), 0, f"Type={session_type}\nDisplay=:0\nClass=user\n", ""),
    ])


class SessionTest(unittest.TestCase):
    def test_finds_x11_session_of_this_user(self):
        session = find_graphical_session(loginctl("x11"), "alice")
        self.assertEqual((session.session_id, session.display), ("2", ":0"))

    def test_wayland_session_explains_xorg(self):
        with self.assertRaises(SetupError) as caught:
            find_graphical_session(loginctl("wayland"), "alice")
        self.assertIn("Xorg", str(caught.exception))

    def test_no_desktop_session_explains_auto_login(self):
        with self.assertRaises(SetupError) as caught:
            find_graphical_session(loginctl("x11"), "someone-else")
        self.assertIn("auto-login", str(caught.exception))


class XauthorityTest(unittest.TestCase):
    def test_uses_first_candidate_that_opens_the_display(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            (home / ".Xauthority").write_text("cookie")
            run = ScriptedRun([(lambda a: a[:1] == ["xrandr"], 0, XRANDR, "")])
            self.assertEqual(find_xauthority(run, ":0", home, 1000, {}), str(home / ".Xauthority"))

    def test_explains_when_display_cannot_be_opened(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            (home / ".Xauthority").write_text("cookie")
            run = ScriptedRun([(("xrandr",), 1, "", "Can't open display")])
            with self.assertRaises(SetupError) as caught:
                find_xauthority(run, ":0", home, 1000, {})
            self.assertIn("same user", str(caught.exception))


class DependencyTest(unittest.TestCase):
    def test_reports_missing_commands_and_libraries(self):
        which = {"ffmpeg": "/usr/bin/ffmpeg", "xrandr": "/usr/bin/xrandr", "openssl": "/usr/bin/openssl"}.get
        find_lib = {"X11": "libX11.so.6", "Xfixes": "libXfixes.so.3"}.get
        self.assertEqual(missing_requirements(which, find_lib), ["xclip", "Xtst"])

    def test_package_manager_commands(self):
        self.assertEqual(detect_package_manager({"apt-get": "/usr/bin/apt-get"}.get), "apt")
        self.assertEqual(detect_package_manager({"pacman": "/usr/bin/pacman"}.get), "pacman")
        self.assertIsNone(detect_package_manager({}.get))
        self.assertEqual(install_command("apt", ["xclip", "Xtst"]),
                         ["sudo", "apt-get", "install", "-y", "xclip", "libxtst6"])
        self.assertEqual(install_command("dnf", ["xrandr"]), ["sudo", "dnf", "install", "-y", "xrandr"])
        self.assertIsNone(install_command(None, ["xclip"]))


class ScreenAndEncoderTest(unittest.TestCase):
    def test_screen_size_from_xrandr(self):
        self.assertEqual(screen_size(ScriptedRun([(("xrandr",), 0, XRANDR, "")]), {}), (1920, 1200))

    def test_first_working_encoder_wins(self):
        run = ScriptedRun([
            (lambda a: "hevc_vaapi" in a and "vaapi=va:/dev/dri/renderD128" in a, 1, "", "No VA display\n"),
            (lambda a: "hevc_vaapi" in a and "vaapi=va:/dev/dri/renderD129" in a, 0, "", ""),
        ])
        self.assertEqual(probe_encoder(run, ":0", {}, 1920, 1200, ["/dev/dri/renderD128", "/dev/dri/renderD129"]),
                         ("vaapi", "/dev/dri/renderD129"))

    def test_falls_back_to_software_x265(self):
        run = ScriptedRun([
            (lambda a: "hevc_vaapi" in a or "hevc_nvenc" in a, 1, "", "unavailable\n"),
            (lambda a: "libx265" in a, 0, "", ""),
        ])
        self.assertEqual(probe_encoder(run, ":0", {}, 1920, 1200, ["/dev/dri/renderD128"])[0], "x265")

    def test_no_encoder_explains_why(self):
        run = ScriptedRun([(("ffmpeg",), 1, "", "Unknown encoder\n")])
        with self.assertRaises(SetupError) as caught:
            probe_encoder(run, ":0", {}, 1920, 1200, [])
        self.assertIn("RPM Fusion", str(caught.exception))


class HeadlessAndSddmTest(unittest.TestCase):
    def test_finds_sddm_cookie_with_random_name(self):
        run = ScriptedRun([(lambda a: a[:1] == ["xrandr"], 0, XRANDR, "")])
        found = find_xauthority(run, ":0", pathlib.Path("/nonexistent-home"), 1000, {},
                                exists=lambda p: p == "/run/user/1000/xauth_Xa1b2",
                                glob_fn=lambda pattern: ["/run/user/1000/xauth_Xa1b2"])
        self.assertEqual(found, "/run/user/1000/xauth_Xa1b2")

    def test_screen_without_output_explains_dummy_plug(self):
        run = ScriptedRun([(("xrandr",), 0, "Screen 0: minimum 320 x 200, current 1024 x 768\nHDMI-1 disconnected\n", "")])
        with self.assertRaises(SetupError) as caught:
            screen_size(run, {})
        self.assertIn("dummy plug", str(caught.exception))


class FirewallTest(unittest.TestCase):
    def test_detects_active_firewall(self):
        run = ScriptedRun([(("systemctl", "is-active", "firewalld"), 0, "active\n", "")])
        from tuxpane.setup_checks import active_firewall
        missing = pathlib.Path("/nonexistent/ufw.conf")
        self.assertEqual(active_firewall(run, ufw_conf=missing), "firewalld")
        self.assertIsNone(active_firewall(ScriptedRun([(("systemctl",), 3, "inactive\n", "")]), ufw_conf=missing))

    def test_lan_subnets_from_ip_output(self):
        from tuxpane.setup_checks import lan_subnets
        ip = ("2: enp1s0    inet 192.168.1.20/24 brd 192.168.1.255 scope global enp1s0\\ x\n"
              "3: docker0    inet 172.17.0.1/16 scope global docker0\\ x\n"
              "4: tailscale0    inet 100.64.100.27/32 scope global tailscale0\\ x\n"
              "5: wlp2s0    inet 192.168.1.30/24 scope global wlp2s0\\ x\n")
        self.assertEqual(lan_subnets(ip), ["192.168.1.0/24"])

    def test_firewall_commands_for_ufw_and_firewalld(self):
        from tuxpane.setup_checks import firewall_commands
        self.assertEqual(firewall_commands("ufw", ["192.168.1.0/24"]), [
            ["sudo", "ufw", "allow", "from", "192.168.1.0/24", "to", "any", "port", "7300:7301", "proto", "tcp",
             "comment", "TuxPane"],
            ["sudo", "ufw", "allow", "from", "192.168.1.0/24", "to", "any", "port", "7301", "proto", "udp",
             "comment", "TuxPane"],
        ])
        self.assertEqual(firewall_commands("firewalld", ["10.0.0.0/24"]), [
            ["sudo", "firewall-cmd", "--permanent", "--add-rich-rule",
             "rule family=ipv4 source address=10.0.0.0/24 port port=7300-7301 protocol=tcp accept"],
            ["sudo", "firewall-cmd", "--permanent", "--add-rich-rule",
             "rule family=ipv4 source address=10.0.0.0/24 port port=7301 protocol=udp accept"],
            ["sudo", "firewall-cmd", "--reload"],
        ])
        self.assertEqual(firewall_commands("ufw", []), [])


class FirewallDetailTest(unittest.TestCase):
    def test_ufw_is_on_only_when_enabled_in_its_config(self):
        from tuxpane.setup_checks import active_firewall
        with tempfile.TemporaryDirectory() as tmp:
            conf = pathlib.Path(tmp) / "ufw.conf"
            inactive = ScriptedRun([(("systemctl",), 3, "inactive\n", "")])
            conf.write_text("# comment\nENABLED=no\nLOGLEVEL=low\n")
            self.assertIsNone(active_firewall(inactive, ufw_conf=conf))
            conf.write_text("ENABLED=yes\n")
            self.assertEqual(active_firewall(inactive, ufw_conf=conf), "ufw")
            self.assertIsNone(active_firewall(inactive, ufw_conf=pathlib.Path(tmp) / "missing.conf"))

    def test_rules_follow_a_custom_agent_port(self):
        from tuxpane.setup_checks import firewall_commands
        self.assertEqual(firewall_commands("ufw", ["10.0.0.0/24"], port=7310), [
            ["sudo", "ufw", "allow", "from", "10.0.0.0/24", "to", "any", "port", "7310", "proto", "tcp", "comment", "TuxPane"],
            ["sudo", "ufw", "allow", "from", "10.0.0.0/24", "to", "any", "port", "7301", "proto", "tcp", "comment", "TuxPane"],
            ["sudo", "ufw", "allow", "from", "10.0.0.0/24", "to", "any", "port", "7301", "proto", "udp", "comment", "TuxPane"],
        ])


if __name__ == "__main__":
    unittest.main()
