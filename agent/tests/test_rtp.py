import unittest

from tuxpane.rtp import HevcDepacketizer, is_keyframe
from tests.fakes import IDR, PPS, SPS, TRAIL, VPS, ap, fu_fragments, rtp


class DepacketizerTest(unittest.TestCase):
    def setUp(self):
        self.d = HevcDepacketizer()

    def test_single_nal_packets_complete_at_marker(self):
        self.assertIsNone(self.d.feed(rtp(VPS, 1)))
        self.assertEqual(self.d.feed(rtp(IDR, 2, marker=True)), [VPS, IDR])
        self.assertEqual(self.d.feed(rtp(TRAIL, 3, marker=True)), [TRAIL])

    def test_aggregation_packet_is_split(self):
        self.assertIsNone(self.d.feed(rtp(ap(VPS, SPS, PPS), 1)))
        self.assertEqual(self.d.feed(rtp(IDR, 2, marker=True)), [VPS, SPS, PPS, IDR])

    def test_fragmented_nal_is_reassembled_with_original_header(self):
        big = bytes([19 << 1, 1]) + bytes(range(256)) * 20
        frags = fu_fragments(big, 1000)
        results = [self.d.feed(rtp(f, i + 1, marker=(i == len(frags) - 1))) for i, f in enumerate(frags)]
        self.assertTrue(all(r is None for r in results[:-1]))
        self.assertEqual(results[-1], [big])

    def test_sequence_gap_drops_access_unit_and_counts_loss(self):
        self.d.feed(rtp(VPS, 1))
        self.assertIsNone(self.d.feed(rtp(IDR, 3, marker=True)))
        self.assertEqual(self.d.lost, 1)
        self.assertEqual(self.d.feed(rtp(TRAIL, 4, marker=True)), [TRAIL])

    def test_sequence_wraps_around(self):
        self.assertEqual(self.d.feed(rtp(TRAIL, 0xFFFF, marker=True)), [TRAIL])
        self.assertEqual(self.d.feed(rtp(TRAIL, 0, marker=True)), [TRAIL])
        self.assertEqual(self.d.lost, 0)

    def test_fragment_without_start_is_dropped(self):
        frags = fu_fragments(bytes([19 << 1, 1]) + b"x" * 30, 10)
        self.assertIsNone(self.d.feed(rtp(frags[1], 1)))
        self.assertIsNone(self.d.feed(rtp(frags[2], 2, marker=True)))

    def test_ignores_rtcp_and_other_payload_types(self):
        self.assertIsNone(self.d.feed(rtp(IDR, 1, marker=True, pt=72)))
        self.assertIsNone(self.d.feed(b"\x00" * 5))

    def test_new_ssrc_resets_without_counting_loss(self):
        self.d.feed(rtp(VPS, 10, ssrc=1))
        self.assertEqual(self.d.feed(rtp(IDR, 500, marker=True, ssrc=2)), [IDR])
        self.assertEqual(self.d.lost, 0)

    def test_keyframe_detection(self):
        self.assertTrue(is_keyframe([VPS, SPS, PPS, IDR]))
        self.assertFalse(is_keyframe([TRAIL]))


if __name__ == "__main__":
    unittest.main()
