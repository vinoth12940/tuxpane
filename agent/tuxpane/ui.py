"""Installer and `tuxpane pair` output: a clean checklist. Colour only on a real terminal (and never with NO_COLOR)."""
from __future__ import annotations

import os
import sys

LABEL_WIDTH = 20


class Checklist:
    def __init__(self, stream=None, tty: bool | None = None, color: bool | None = None) -> None:
        self.stream = stream or sys.stdout
        self.tty = self.stream.isatty() if tty is None else tty
        self.color = (self.tty and "NO_COLOR" not in os.environ) if color is None else color
        self._line_open = False

    # --- styling
    def _style(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.color else text

    def bold(self, text: str) -> str: return self._style("1", text)
    def dim(self, text: str) -> str: return self._style("2", text)
    def green(self, text: str) -> str: return self._style("32", text)
    def red(self, text: str) -> str: return self._style("31", text)
    def yellow(self, text: str) -> str: return self._style("33", text)
    def blue(self, text: str) -> str: return self._style("34", text)

    def _mark(self, kind: str) -> str:
        if not self.color:
            return {"ok": "[ok]", "fail": "[x]", "warn": "[!]"}[kind]
        return {"ok": self.green("✓"), "fail": self.red("✗"), "warn": self.yellow("!")}[kind]

    def _write(self, text: str) -> None:
        self.stream.write(text)
        self.stream.flush()

    def _close_line(self) -> None:
        if self._line_open:
            self._write("\r\033[K")
            self._line_open = False

    # --- checklist
    def header(self, text: str) -> None:
        self._write(self.bold(text) + "\n\n")

    def start(self, label: str) -> None:
        """A running step: shown (and later replaced in place) only on a terminal."""
        if self.tty:
            self._close_line()
            self._write(f"  {self.blue('◐')} {label}…")
            self._line_open = True

    def ok(self, label: str, detail: str = "") -> None:
        self._close_line()
        line = f"  {self._mark('ok')} {label.ljust(LABEL_WIDTH)} {self.dim(detail)}" if detail else f"  {self._mark('ok')} {label}"
        self._write(line + "\n")

    def warn(self, label: str, lines: list[str]) -> None:
        self._close_line()
        self._write(f"  {self._mark('warn')} {label}\n" + "".join(f"      {line}\n" for line in lines))

    def fail(self, label: str, fix: str) -> None:
        self._close_line()
        self._write(f"  {self._mark('fail')} {label}\n" + "".join(f"      {line}\n" for line in fix.splitlines()))

    def text(self, line: str = "") -> None:
        self._close_line()
        self._write(line + "\n")

    def code_box(self, code: str) -> None:
        inner = f"  {code}  "
        edge = "-" * len(inner)
        shown = self.bold(inner) if self.color else inner
        self._write(f"      +{edge}+\n      |{shown}|\n      +{edge}+\n")

    # --- pairing countdown
    def waiting(self, seconds_left: int) -> None:
        if not self.tty:
            return
        minutes, seconds = divmod(max(0, seconds_left), 60)
        self._write(f"\r\033[K  {self.dim(f'Waiting for your Mac… {minutes}:{seconds:02d} left')}")
        self._line_open = True

    def end_waiting(self) -> None:
        self._close_line()
