import json
import pathlib
import tempfile
import unittest

from tuxpane.__main__ import load_agent_files, parse_args
from tuxpane.config import CONFIG_DIR, AgentConfig


class MainTest(unittest.TestCase):
    def test_defaults(self):
        args = parse_args([])
        self.assertEqual(args.config, CONFIG_DIR / "agent.json")
        self.assertEqual(args.bind, "0.0.0.0")

    def test_loads_config_token_and_cert_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            (d / "agent.json").write_text(json.dumps({"encoder": "x265"}))
            (d / "token").write_text("a-long-enough-token-value\n")
            (d / "cert.pem").write_text("x")
            (d / "key.pem").write_text("x")
            config, token, cert, key = load_agent_files(d / "agent.json")
        self.assertEqual((config, token, cert.name, key.name),
                         (AgentConfig(encoder="x265"), "a-long-enough-token-value", "cert.pem", "key.pem"))

    def test_missing_files_explain_how_to_fix(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit) as caught:
                load_agent_files(pathlib.Path(tmp) / "agent.json")
        self.assertIn("run the TuxPane installer again", str(caught.exception))

    def test_short_token_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            (d / "agent.json").write_text("{}")
            (d / "token").write_text("short")
            (d / "cert.pem").write_text("x")
            (d / "key.pem").write_text("x")
            with self.assertRaises(SystemExit):
                load_agent_files(d / "agent.json")


if __name__ == "__main__":
    unittest.main()
