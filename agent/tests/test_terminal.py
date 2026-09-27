"""Terminal I/O against real pseudo-terminals: the installer must see `ssh -t` as interactive."""
import asyncio
import io
import os
import sys
import threading
import time
import unittest

from tuxpane.pair_session import TerminalPrompt, is_interactive
from tuxpane.setup import _output_stream, tty_ask


def open_pty(test):
    master, slave = os.openpty()
    test.addCleanup(os.close, master)
    test.addCleanup(os.close, slave)
    return master, os.ttyname(slave)


def answer_later(master, data, delay=0.3):
    threading.Thread(target=lambda: (time.sleep(delay), os.write(master, data)), daemon=True).start()


class RealTerminalTest(unittest.TestCase):
    def test_a_real_terminal_is_interactive(self):
        _, path = open_pty(self)
        self.assertTrue(is_interactive(path))
        self.assertFalse(is_interactive("/nonexistent/tty"))

    def test_tty_ask_shows_the_question_and_reads_the_answer(self):
        master, path = open_pty(self)
        answer_later(master, b"n\n")
        self.assertFalse(tty_ask("Allow?", True, path=path))
        self.assertIn("Allow? [Y/n]", os.read(master, 4096).decode())

    def test_tty_ask_empty_answer_takes_the_default(self):
        master, path = open_pty(self)
        answer_later(master, b"\n")
        self.assertTrue(tty_ask("Match?", True, path=path))

    def test_tty_ask_ignores_keys_typed_before_the_question(self):
        master, path = open_pty(self)
        os.write(master, b"y\n")  # stale type-ahead
        answer_later(master, b"n\n")
        self.assertFalse(tty_ask("Allow?", False, path=path))


class RealTerminalPromptTest(unittest.IsolatedAsyncioTestCase):
    async def test_prompt_reads_yes(self):
        master, path = open_pty(self)
        task = asyncio.create_task(TerminalPrompt(path).ask("Pair with this Mac? [y/N]"))
        await asyncio.sleep(0.2)
        os.write(master, b"y\n")
        self.assertTrue(await asyncio.wait_for(task, 2))
        self.assertIn("Pair with this Mac? [y/N]", os.read(master, 4096).decode())

    async def test_prompt_ignores_keys_typed_before_the_question(self):
        master, path = open_pty(self)
        os.write(master, b"y\n")  # typed during an earlier, cancelled attempt
        task = asyncio.create_task(TerminalPrompt(path).ask("Pair? [y/N]"))
        await asyncio.sleep(0.2)
        os.write(master, b"n\n")
        self.assertFalse(await asyncio.wait_for(task, 2))

    async def test_prompt_can_be_cancelled(self):
        _, path = open_pty(self)
        task = asyncio.create_task(TerminalPrompt(path).ask("Pair? [y/N]"))
        await asyncio.sleep(0.2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task


class OutputStreamTest(unittest.TestCase):
    def test_default_output_is_the_real_stdout(self):
        self.assertIs(_output_stream(None), sys.stdout)

    def test_streams_pass_through_and_callables_are_wrapped(self):
        buffer = io.StringIO()
        self.assertIs(_output_stream(buffer), buffer)
        wrapped = _output_stream(lambda line: None)
        self.assertFalse(wrapped.isatty())


if __name__ == "__main__":
    unittest.main()
