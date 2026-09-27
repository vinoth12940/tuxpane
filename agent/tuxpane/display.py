"""Reads and sets the dummy-plug resolution through xrandr."""
from __future__ import annotations

import re
import subprocess

_OUTPUT = re.compile(r"^(\S+) connected(?: primary)? (\d+)x(\d+)\+")
_MODE = re.compile(r"^\s+(\d+)x(\d+)")


def parse_xrandr(text: str) -> tuple[str, tuple[int, int], set[tuple[int, int]]]:
    output, current, modes = None, (0, 0), set()
    for line in text.splitlines():
        if not line.startswith(" "):
            if output is not None:
                break
            match = _OUTPUT.match(line)
            if match:
                output = match.group(1)
                current = (int(match.group(2)), int(match.group(3)))
            continue
        if output is not None:
            mode = _MODE.match(line)
            if mode:
                modes.add((int(mode.group(1)), int(mode.group(2))))
    if output is None:
        raise RuntimeError("no connected, active output in xrandr output")
    return output, current, modes


ASPECT_TOLERANCE = 0.02


def best_mode(wanted: tuple[int, int], modes: set[tuple[int, int]]) -> tuple[int, int] | None:
    """The mode to switch to for a requested size: exact if offered, otherwise the largest mode that fits inside it,
    preferring the same shape. Macs ask for odd sizes (a notched MacBook's full-screen area is 3456x2170)."""
    width, height = wanted
    if width <= 0 or height <= 0:
        return None
    if wanted in modes:
        return wanted
    fitting = [m for m in modes if m[0] <= width and m[1] <= height]
    if not fitting:
        return None
    aspect = width / height
    return min(fitting, key=lambda m: (abs(m[0] / m[1] - aspect) > ASPECT_TOLERANCE, -m[0] * m[1]))


class Display:
    def __init__(self, run=subprocess.run, match_resolution: bool = True) -> None:
        self._run = run
        self.match_resolution = match_resolution

    def query(self) -> tuple[str, tuple[int, int], set[tuple[int, int]]]:
        result = self._run(["xrandr", "--query"], capture_output=True, text=True, check=True, timeout=5)
        return parse_xrandr(result.stdout)

    def ensure_mode(self, width: int, height: int) -> tuple[int, int]:
        output, current, modes = self.query()
        mode = best_mode((width, height), modes) if self.match_resolution else None
        if mode is None or mode == current:
            return current
        self._run(["xrandr", "--output", output, "--mode", f"{mode[0]}x{mode[1]}"], check=True, timeout=5)
        return mode
