import pathlib
import shutil
import tempfile
import unittest

from tests.fakes import ScriptedRun
from tests.test_setup import IP, real
from tuxpane.cli import main
from tuxpane.config import AgentConfig, save_config
from tuxpane.pairing import parse_pairing_code
from tuxpane.security import ensure_security_material


def installed_home(tmp: str) -> pathlib.Path:
    home = pathlib.Path(tmp)
    ensure_security_material(home / ".config/tuxpane")
    save_config(home / ".config/tuxpane/agent.json", AgentConfig(port=7301))
    for path in (".local/share/tuxpane/1.0.0", ".local/bin"):
        (home / path).mkdir(parents=True, exist_ok=True)
    (home / ".local/bin/tuxpane").write_text("#!/bin/sh\n")
    (home / ".config/systemd/user").mkdir(parents=True, exist_ok=True)
    (home / ".config/systemd/user/tuxpane.service").write_text("[Unit]\n")
    return home


def cli(home, *argv, **options):
    output = []
    run = ScriptedRun([(("ip", "-4", "route"), 0, "default via 192.168.1.1 dev enp1s0\n", ""), (("ip",), 0, IP, ""), (("openssl",), real), (("systemctl",), 0, "active\n", ""),
                       (("journalctl",), 0, "INFO listening\n", ""), (("sh",), 0, "", "")])
    code = main(list(argv), run=run, home=home, environ={}, uid=1000, out=output.append, hostname=lambda: "box",
                **options)
    return code, "\n".join(output), run


@unittest.skipUnless(shutil.which("openssl"), "openssl CLI required")
class CliTest(unittest.TestCase):
    def test_pair_prints_code_for_this_machine(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, output, _ = cli(installed_home(tmp), "pair", "--code")
        line = next(l.strip() for l in output.splitlines() if l.strip().startswith("tuxpane1:"))
        data = parse_pairing_code(line)
        self.assertEqual((code, data["n"], data["p"], data["h"]), (0, "box", 7301, ["192.168.1.20", "100.64.100.27"]))

    def test_pair_reset_rotates_and_restarts(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = installed_home(tmp)
            before = (home / ".config/tuxpane/token").read_text()
            code, _, run = cli(home, "pair", "--reset", "--code")
            self.assertNotEqual(before, (home / ".config/tuxpane/token").read_text())
            self.assertIn(["systemctl", "--user", "restart", "tuxpane.service"], run.calls)

    def test_status_reports_service_and_addresses(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, output, _ = cli(installed_home(tmp), "status")
        self.assertEqual(code, 0)
        for text in ("active", "192.168.1.20", "7301", "vaapi"):
            self.assertIn(text, output)

    def test_uninstall_removes_everything(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = installed_home(tmp)
            code, _, run = cli(home, "uninstall")
            self.assertEqual(code, 0)
            self.assertIn(["systemctl", "--user", "disable", "--now", "tuxpane.service"], run.calls)
            for gone in (".config/tuxpane", ".local/share/tuxpane", ".local/bin/tuxpane",
                         ".config/systemd/user/tuxpane.service"):
                self.assertFalse((home / gone).exists(), gone)


class NotInstalledTest(unittest.TestCase):
    def test_pair_and_status_explain_how_to_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            for command in ("pair", "status"):
                code, output, _ = cli(pathlib.Path(tmp), command)
                self.assertEqual(code, 1, command)
                self.assertIn("installer", output)


class PairCommandTest(unittest.TestCase):
    def test_pair_without_a_terminal_explains(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = installed_home(tmp)
            output = []
            run = ScriptedRun([(("ip",), 0, IP, ""), (("systemctl",), 0, "active\n", "")])
            code = main(["pair"], run=run, home=home, environ={}, uid=1000, out=output.append,
                        hostname=lambda: "box", interactive=False)
        self.assertEqual(code, 1)
        self.assertIn("terminal", "\n".join(output))
        self.assertIn("--code", "\n".join(output))


@unittest.skipUnless(shutil.which("openssl"), "openssl CLI required")
class SafeCommandTest(unittest.TestCase):
    def test_update_never_starts_pairing(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, run = cli(installed_home(tmp), "update")
        self.assertTrue(any(call[0] == "sh" and "--no-pair" in call[-1] for call in run.calls), run.calls)

    def test_reset_without_a_terminal_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = installed_home(tmp)
            token = (home / ".config/tuxpane/token").read_text()
            code, output, run = cli(home, "pair", "--reset", interactive=False)
            self.assertEqual(code, 1)
            self.assertEqual(token, (home / ".config/tuxpane/token").read_text())
            self.assertFalse(any("restart" in call for call in run.calls))

