"""Text clipboard access through xclip (already installed on the box)."""
from __future__ import annotations

import logging
import subprocess

log = logging.getLogger(__name__)

MAX_CLIPBOARD = 1024 * 1024


class XClipClipboard:
    def __init__(self, run=subprocess.run) -> None:
        self._run = run

    def get(self) -> str | None:
        try:
            result = self._run(["xclip", "-selection", "clipboard", "-o", "-t", "UTF8_STRING"],
                               capture_output=True, timeout=1)
        except (subprocess.TimeoutExpired, OSError):
            return None
        if result.returncode != 0:
            return None
        return result.stdout[:MAX_CLIPBOARD].decode("utf-8", errors="replace")

    def set(self, text: str) -> None:
        # xclip forks a child that keeps serving the selection after this call returns.
        try:
            self._run(["xclip", "-selection", "clipboard", "-i"], input=text.encode("utf-8"),
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
        except (subprocess.TimeoutExpired, OSError) as exc:
            log.warning("could not set clipboard: %r", exc)
