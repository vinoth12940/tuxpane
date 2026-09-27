import getpass
import io
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

from tests.fakes import ScriptedRun
from tuxpane.pairing import parse_pairing_code
from tuxpane.setup import main, unit_file

XRANDR = "Screen 0: current 1920 x 1200\nHDMI-A-0 connected primary 1920x1200+0+0 (normal)\n   1920x1200 60.00*\n"
IP = "2: enp1s0    inet 192.168.1.20/24 scope global enp1s0\\ x\n4: tailscale0    inet 100.64.100.27/32 scope global tailscale0\\ x\n"


def real(args, kwargs):
    return subprocess.run(args, **kwargs)


def system(session_type="x11"):
    return ScriptedRun([
        (("loginctl", "list-sessions"), 0, f"  2 1000 {getpass.getuser()} seat0 tty7 active no -\n", ""),
        (("loginctl", "show-session"), 0, f"Type={session_type}\nDisplay=:0\nClass=user\n", ""),
        (("xrandr",), 0, XRANDR, ""),
        (lambda a: "hevc_vaapi" in a, 0, "", ""),
        (("openssl",), real), (("systemctl", "is-active"), 3, "inactive\n", ""), (("systemctl",), 0, "", ""), (("gsettings",), 0, "", ""),
        (("ss", "-ltn"), 0, "LISTEN 0 100 0.0.0.0:7300 0.0.0.0:*\nLISTEN 0 100 0.0.0.0:7310 0.0.0.0:*\n", ""),
        (("ip", "-4", "route"), 0, "default via 192.168.1.1 dev enp1s0 proto dhcp\n", ""),
        (("ip", "-4", "-o", "addr", "show"), 0, IP, ""),
    ])


def run_main(home, run, argv=("--yes",), euid=1000, ask=lambda question, default: default, which=None,
             interactive=False, pair_runner=None, ufw_conf=None):
    (home / ".Xauthority").write_text("cookie")
    output = io.StringIO()
    code = main(list(argv), run=run, which=which or (lambda c: f"/usr/bin/{c}"), find_lib=lambda n: f"lib{n}.so",
                ask=ask, home=home, environ={}, uid=1000, euid=euid, render_nodes=["/dev/dri/renderD128"],
                out=output, sleep=lambda s: None, hostname=lambda: "example-linux-desktop-01",
                interactive=interactive, pair_runner=pair_runner,
                ufw_conf=ufw_conf or home / "no-ufw.conf")
    return code, output.getvalue()


@unittest.skipUnless(shutil.which("openssl"), "openssl CLI required")
class SetupMainTest(unittest.TestCase):
    def test_full_install_writes_config_service_and_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            code, output = run_main(home, system())
            self.assertEqual(code, 0, output)
            config = json.loads((home / ".config/tuxpane/agent.json").read_text())
            self.assertEqual((config["encoder"], config["match_resolution"]), ("vaapi", True))
            unit = (home / ".config/systemd/user/tuxpane.service").read_text()
            self.assertIn("Environment=DISPLAY=:0", unit)
            self.assertIn("-m tuxpane --config", unit)
            self.assertTrue(os.access(home / ".local/bin/tuxpane", os.X_OK))
            for line in ("[ok] Desktop session", "[ok] Required packages", "[ok] Video encoder",
                         "[ok] Security keys", "[ok] Background service"):
                self.assertIn(line, output)

    def test_main_twice_keeps_pairing(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            run_main(home, system())
            token = (home / ".config/tuxpane/token").read_text()
            run_main(home, system())
            self.assertEqual(token, (home / ".config/tuxpane/token").read_text())

    def test_main_stops_on_wayland(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, output = run_main(pathlib.Path(tmp), system("wayland"))
        self.assertEqual(code, 1)
        self.assertIn("Xorg", output)

    def test_refuses_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, output = run_main(pathlib.Path(tmp), system(), euid=0)
        self.assertEqual(code, 1)
        self.assertIn("not root", output)


    def test_rerun_keeps_custom_port_and_resolution_choice(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            decline_match = lambda question, default: False if question.startswith("Match") else default
            self.assertEqual(run_main(home, system(), argv=("--port", "7310"), ask=decline_match)[0], 0)
            code, output = run_main(home, system())  # e.g. `tuxpane update`, which runs with --yes
            self.assertEqual(code, 0, output)
            config = json.loads((home / ".config/tuxpane/agent.json").read_text())
            self.assertEqual((config["port"], config["match_resolution"]), (7310, False))

    def test_wayland_stops_before_installing_anything(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            run = system("wayland")
            code, output = run_main(home, run, which=lambda c: None if c == "xclip" else f"/usr/bin/{c}")
            self.assertEqual(code, 1)
            self.assertIn("Xorg", output)
            self.assertFalse((home / ".config/systemd/user/tuxpane.service").exists())
            self.assertFalse(any(call[0] in ("systemctl", "sudo") for call in run.calls), run.calls)

    def test_missing_packages_without_consent_prints_the_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = system()
            code, output = run_main(pathlib.Path(tmp), run, argv=(),
                                    which=lambda c: None if c == "xclip" else f"/usr/bin/{c}")
        self.assertEqual(code, 1)
        self.assertIn("sudo apt-get install -y xclip", output)
        self.assertFalse(any(call[0] == "sudo" for call in run.calls))

    def test_missing_systemd_tools_are_explained(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, output = run_main(pathlib.Path(tmp), ScriptedRun([]))
        self.assertEqual(code, 1)
        self.assertIn("systemd", output)
        self.assertNotIn("Traceback", output)

    def test_non_interactive_install_prints_pair_instructions(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, output = run_main(pathlib.Path(tmp), system(), interactive=False)
        self.assertEqual(code, 0)
        self.assertIn("tuxpane pair", output)
        self.assertNotIn("tuxpane1:", output)

    def test_interactive_install_pairs_at_the_end(self):
        calls = []

        def pair_runner(config_dir, port, hosts, hostname, ui):
            calls.append((port, hosts, hostname))
            return "Sam's MacBook Pro"

        with tempfile.TemporaryDirectory() as tmp:
            code, output = run_main(pathlib.Path(tmp), system(), interactive=True, pair_runner=pair_runner)
        self.assertEqual(code, 0, output)
        self.assertEqual(calls, [(7300, ["192.168.1.20", "100.64.100.27"], "example-linux-desktop-01")])

    def test_no_pair_flag_skips_pairing(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, output = run_main(pathlib.Path(tmp), system(), argv=("--yes", "--no-pair"), interactive=True,
                                    pair_runner=lambda *a: self.fail("must not pair"))
        self.assertEqual(code, 0)

    def test_setup_offers_firewall_rules(self):
        run = system()
        with tempfile.TemporaryDirectory() as tmp:
            conf = pathlib.Path(tmp) / "ufw.conf"
            conf.write_text("ENABLED=yes\n")
            code, output = run_main(pathlib.Path(tmp), run, ufw_conf=conf)
        self.assertEqual(code, 0, output)
        self.assertIn("[!] Firewall", output)
        self.assertIn("sudo ufw allow from 192.168.1.0/24 to any port 7300:7301 proto tcp comment TuxPane", output)
        self.assertFalse(any(call[:2] == ["sudo", "ufw"] for call in run.calls))

    def test_failed_firewall_change_warns_instead_of_failing(self):
        run = system()
        run.rules.insert(0, (("sudo",), 1, "", "sudo: a password is required"))
        yes_to_firewall = lambda question, default: True if "ufw is on" in question else default
        with tempfile.TemporaryDirectory() as tmp:
            conf = pathlib.Path(tmp) / "ufw.conf"
            conf.write_text("ENABLED=yes\n")
            code, output = run_main(pathlib.Path(tmp), run, argv=(), ask=yes_to_firewall, ufw_conf=conf)
        self.assertEqual(code, 0, output)
        self.assertIn("[!] Firewall", output)
        self.assertNotIn("[x]", output)

    def test_firewall_rules_follow_a_custom_port(self):
        with tempfile.TemporaryDirectory() as tmp:
            conf = pathlib.Path(tmp) / "ufw.conf"
            conf.write_text("ENABLED=yes\n")
            code, output = run_main(pathlib.Path(tmp), system(), argv=("--yes", "--port", "7310"), ufw_conf=conf)
        self.assertEqual(code, 0, output)
        self.assertIn("port 7310 proto tcp", output)


class UnitAndMigrationTest(unittest.TestCase):
    def test_unit_file(self):
        unit = unit_file("/usr/bin/python3", "/home/u/.local/share/tuxpane/current",
                         "/home/u/.config/tuxpane/agent.json", ":1", "/home/u/.Xauthority")
        for line in ("Environment=DISPLAY=:1", "Environment=XAUTHORITY=/home/u/.Xauthority",
                     "Environment=PYTHONPATH=/home/u/.local/share/tuxpane/current",
                     "ExecStart=/usr/bin/python3 -m tuxpane --config /home/u/.config/tuxpane/agent.json",
                     "Restart=always", "WantedBy=default.target"):
            self.assertIn(line, unit)
