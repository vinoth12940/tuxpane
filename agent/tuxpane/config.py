"""Agent settings, written by setup to ~/.config/tuxpane/agent.json."""
from __future__ import annotations

import dataclasses
import json
import os
import pathlib

CONFIG_DIR = pathlib.Path.home() / ".config" / "tuxpane"
ENCODERS = ("vaapi", "nvenc", "x265")
DEFAULT_VAAPI_DEVICE = "/dev/dri/renderD128"


@dataclasses.dataclass
class AgentConfig:
    port: int = 7300
    encoder: str = "vaapi"
    vaapi_device: str = DEFAULT_VAAPI_DEVICE
    match_resolution: bool = True
    bitrate_mbps: int = 20
    fps: int = 60

    def validate(self) -> None:
        if self.encoder not in ENCODERS:
            raise ValueError(f"unknown encoder {self.encoder!r}; expected one of {', '.join(ENCODERS)}")
        if not 1 <= self.port <= 65535:
            raise ValueError(f"invalid port {self.port}")
        if not 1 <= self.fps <= 120:
            raise ValueError(f"invalid fps {self.fps}")
        if not 1 <= self.bitrate_mbps <= 200:
            raise ValueError(f"invalid bitrate {self.bitrate_mbps} Mbit/s")


def load_config(path) -> AgentConfig:
    data = json.loads(pathlib.Path(path).read_text())
    known = {field.name for field in dataclasses.fields(AgentConfig)}
    config = AgentConfig(**{key: value for key, value in data.items() if key in known})
    config.validate()
    return config


def save_config(path, config: AgentConfig) -> None:
    config.validate()
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dataclasses.asdict(config), indent=2) + "\n")
    os.chmod(path, 0o600)
