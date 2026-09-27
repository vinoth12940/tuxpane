import json
import unittest

from tuxpane import protocol as p
from tuxpane.pairing_protocol import (DISCOVER_QUERY, PAIR_HELLO, commitment, discovery_reply, fields,
                                      is_discovery_query, message, sas_code)

F, NA, NM = bytes([0x11]) * 32, bytes([0x22]) * 32, bytes([0x33]) * 32


class PairingProtocolTest(unittest.TestCase):
    def test_code_matches_the_swift_vector(self):
        self.assertEqual(sas_code(F, NA, NM), "614 176")

    def test_commitment_vector(self):
        self.assertEqual(commitment(NM), "deb0e38ced1e41de6f92e70e80c418d2d356afaaa99e26f5939dbc7d3ef4772a")

    def test_different_certificate_changes_the_code(self):
        self.assertNotEqual(sas_code(bytes([0x12]) * 32, NA, NM), sas_code(F, NA, NM))

    def test_message_round_trip(self):
        frame = message(PAIR_HELLO, v=1, name="Mac", commit="ab")
        self.assertEqual(frame[0], PAIR_HELLO)
        self.assertEqual(fields(frame[5:]), {"v": 1, "name": "Mac", "commit": "ab"})

    def test_fields_rejects_non_objects(self):
        for bad in (b"[]", b"not json", b'"x"'):
            with self.assertRaises(p.ProtocolError):
                fields(bad)

    def test_discovery(self):
        self.assertTrue(is_discovery_query(json.dumps(DISCOVER_QUERY).encode()))
        self.assertFalse(is_discovery_query(b'{"q":"other"}'))
        self.assertFalse(is_discovery_query(b"\xff\xfe"))
        self.assertEqual(json.loads(discovery_reply("box", "Linux Mint 22.3")),
                         {"n": "box", "os": "Linux Mint 22.3", "v": 1, "pp": 7301})


if __name__ == "__main__":
    unittest.main()
