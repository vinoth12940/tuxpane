import pathlib
import unittest

from tuxpane.x11 import open_first, xauthority_candidates


class XauthorityCandidatesTest(unittest.TestCase):
    def test_order_covers_lightdm_gdm_and_sddm(self):
        sddm = {"/run/user/1000/xauth_OLD": 1.0, "/run/user/1000/xauth_NEW": 2.0}
        candidates = xauthority_candidates(1000, pathlib.Path("/home/u"), "/stale/hint",
                                           glob_fn=lambda pattern: list(sddm), mtime=sddm.__getitem__)
        self.assertEqual(candidates, ["/stale/hint", "/home/u/.Xauthority", "/run/user/1000/gdm/Xauthority",
                                      "/run/user/1000/xauth_NEW", "/run/user/1000/xauth_OLD"])

    def test_no_hint_and_no_sddm_files(self):
        candidates = xauthority_candidates(1000, pathlib.Path("/home/u"), None, glob_fn=lambda p: [], mtime=None)
        self.assertEqual(candidates, ["/home/u/.Xauthority", "/run/user/1000/gdm/Xauthority"])


class OpenFirstTest(unittest.TestCase):
    def test_skips_missing_and_failing_candidates(self):
        tried = []

        def try_open(candidate):
            tried.append(candidate)
            return "handle" if candidate == "/c" else None

        self.assertEqual(open_first(["/a", "/b", "/c"], try_open, exists=lambda p: p != "/a"), ("/c", "handle"))
        self.assertEqual(tried, ["/b", "/c"])

    def test_explains_when_nothing_opens(self):
        with self.assertRaises(RuntimeError) as caught:
            open_first(["/a"], lambda c: None, exists=lambda p: True, display=":0")
        self.assertIn("logged in to the desktop", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
