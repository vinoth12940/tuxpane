import unittest

from tests.fakes import RecordingInjector


class InjectorTest(unittest.TestCase):
    def setUp(self):
        self.inj = RecordingInjector()

    def test_key_uses_x_keycode_and_tracks_held(self):
        self.inj.key(30, True)
        self.assertEqual(self.inj.events, [("key", 38, True)])
        self.assertEqual(self.inj.held_keys, [30])
        self.inj.key(30, False)
        self.assertEqual(self.inj.held_keys, [])

    def test_out_of_range_keys_are_ignored(self):
        self.inj.key(0, True)
        self.inj.key(248, True)
        self.assertEqual(self.inj.events, [])

    def test_unknown_buttons_are_ignored(self):
        self.inj.button(4, True)
        self.assertEqual(self.inj.events, [])

    def test_scroll_maps_to_wheel_buttons(self):
        self.inj.scroll(-1, 2)
        self.assertEqual(self.inj.events, [
            ("button", 4, True), ("button", 4, False), ("button", 4, True), ("button", 4, False),
            ("button", 7, True), ("button", 7, False),
        ])

    def test_release_all_releases_in_reverse_order(self):
        self.inj.key(29, True)
        self.inj.key(46, True)
        self.inj.button(1, True)
        self.inj.events.clear()
        self.inj.release_all()
        self.assertEqual(self.inj.events, [("key", 54, False), ("key", 37, False), ("button", 1, False)])
        self.assertEqual((self.inj.held_keys, self.inj.held_buttons), ([], []))


class LazyXTestTest(unittest.TestCase):
    def test_x_is_opened_only_when_a_session_needs_it(self):
        from tuxpane.xinput import XTestInjector

        def no_desktop():
            raise RuntimeError("cannot open X display :0: is a user logged in to the desktop?")

        injector = XTestInjector(":0", opener=no_desktop)  # the agent starts listening even with no desktop
        injector.key(30, True)  # dropped, not a crash
        with self.assertRaises(RuntimeError):
            injector.ensure_ready()


if __name__ == "__main__":
    unittest.main()
