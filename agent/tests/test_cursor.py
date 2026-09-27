import unittest

from tuxpane.cursor import argb_to_rgba


class CursorTest(unittest.TestCase):
    def test_argb_longs_become_rgba_bytes(self):
        # XFixes stores premultiplied ARGB in the low 32 bits of each (64-bit) long.
        self.assertEqual(argb_to_rgba([0x80FF0000, 0xFF00FF00, 0xFFFFFFFF_00000000 | 0x000000FF]),
                         bytes([255, 0, 0, 128, 0, 255, 0, 255, 0, 0, 255, 0]))


if __name__ == "__main__":
    unittest.main()
