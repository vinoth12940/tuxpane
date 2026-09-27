import json
import os
import pathlib
import tempfile
import unittest

from tuxpane.config import AgentConfig, load_config, save_config


class ConfigTest(unittest.TestCase):
    def test_round_trip_and_private_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "sub" / "agent.json"
            save_config(path, AgentConfig(encoder="x265", match_resolution=False, port=7310))
            self.assertEqual(load_config(path), AgentConfig(encoder="x265", match_resolution=False, port=7310))
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_unknown_keys_are_ignored_and_defaults_fill_gaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "agent.json"
            path.write_text(json.dumps({"encoder": "nvenc", "future_option": 1}))
            self.assertEqual(load_config(path), AgentConfig(encoder="nvenc"))

    def test_invalid_values_are_rejected(self):
        for bad in (AgentConfig(encoder="h264"), AgentConfig(port=0), AgentConfig(fps=500), AgentConfig(bitrate_mbps=0)):
            with self.assertRaises(ValueError):
                bad.validate()


if __name__ == "__main__":
    unittest.main()
