import subprocess
import unittest

from tuxpane.clipboard import MAX_CLIPBOARD, XClipClipboard


class FakeRun:
    def __init__(self, result=None, exc=None):
        self.result, self.exc, self.calls = result, exc, []

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        if self.exc:
            raise self.exc
        return self.result


class ClipboardTest(unittest.TestCase):
    def test_get_returns_text(self):
        run = FakeRun(subprocess.CompletedProcess([], 0, stdout="héllo".encode()))
        self.assertEqual(XClipClipboard(run=run).get(), "héllo")
        self.assertEqual(run.calls[0][0], ["xclip", "-selection", "clipboard", "-o", "-t", "UTF8_STRING"])

    def test_get_returns_none_when_empty_or_hung(self):
        self.assertIsNone(XClipClipboard(run=FakeRun(subprocess.CompletedProcess([], 1, stdout=b""))).get())
        self.assertIsNone(XClipClipboard(run=FakeRun(exc=subprocess.TimeoutExpired("xclip", 1))).get())

    def test_get_returns_none_when_xclip_is_missing(self):
        self.assertIsNone(XClipClipboard(run=FakeRun(exc=FileNotFoundError("xclip"))).get())

    def test_set_swallows_xclip_failures(self):
        XClipClipboard(run=FakeRun(exc=subprocess.TimeoutExpired("xclip", 2))).set("x")
        XClipClipboard(run=FakeRun(exc=FileNotFoundError("xclip"))).set("x")

    def test_get_truncates_huge_clipboard(self):
        run = FakeRun(subprocess.CompletedProcess([], 0, stdout=b"a" * (MAX_CLIPBOARD + 10)))
        self.assertEqual(len(XClipClipboard(run=run).get()), MAX_CLIPBOARD)

    def test_set_pipes_text_to_xclip(self):
        run = FakeRun(subprocess.CompletedProcess([], 0))
        XClipClipboard(run=run).set("from mac")
        args, kwargs = run.calls[0]
        self.assertEqual(args, ["xclip", "-selection", "clipboard", "-i"])
        self.assertEqual(kwargs["input"], b"from mac")


if __name__ == "__main__":
    unittest.main()
