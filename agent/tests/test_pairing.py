import unittest

from tuxpane.pairing import make_pairing_code, pairing_message, parse_pairing_code, private_ipv4_addresses

# The same literal is asserted in mac/Tests/TuxPaneCoreTests/PairingCodeTests.swift.
FIXTURE = ("tuxpane1:eyJuIjoiZXhhbXBsZS1saW51eC1kZXNrdG9wLTAxIiwiaCI6WyIxOTIuMTY4LjEuMjAiLCIxMDAuNjQuMTAwLjI3Il0"
           "sInAiOjczMDAsInQiOiJhYmNkZWZnaGlqa2xtbm9wcXJzdHV2d3h5ejAxMjM0NSIsImYiOiJhYWFhYWFhYWFhYWFhYWFhYWFhYWF"
           "hYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhIn0")

IP_OUTPUT = """\
1: lo    inet 127.0.0.1/8 scope host lo\\       valid_lft forever preferred_lft forever
2: enp1s0    inet 192.168.1.20/24 brd 192.168.1.255 scope global dynamic enp1s0\\       valid_lft 80000sec
3: docker0    inet 172.17.0.1/16 brd 172.17.255.255 scope global docker0\\       valid_lft forever
4: tailscale0    inet 100.64.100.27/32 scope global tailscale0\\       valid_lft forever preferred_lft forever
5: wlan0    inet 81.2.69.160/24 scope global wlan0\\       valid_lft forever preferred_lft forever
6: br-1a2b    inet 172.18.0.1/16 scope global br-1a2b\\       valid_lft forever preferred_lft forever
7: wlp2s0    inet 10.0.0.7/24 scope global wlp2s0\\       valid_lft forever preferred_lft forever
"""


class PairingTest(unittest.TestCase):
    def test_code_matches_cross_language_fixture(self):
        code = make_pairing_code("example-linux-desktop-01", ["192.168.1.20", "100.64.100.27"], 7300,
                                 "abcdefghijklmnopqrstuvwxyz012345", "a" * 64)
        self.assertEqual(code, FIXTURE)

    def test_parse_round_trip(self):
        self.assertEqual(parse_pairing_code(FIXTURE)["h"], ["192.168.1.20", "100.64.100.27"])
        self.assertEqual(parse_pairing_code("  " + FIXTURE + "\n")["p"], 7300)

    def test_parse_rejects_garbage(self):
        for bad in ("", "tuxpane2:abc", "tuxpane1:!!!", "tuxpane1:" + "e30"):
            with self.assertRaises(ValueError):
                parse_pairing_code(bad)

    def test_private_addresses_skip_bridges_and_public(self):
        self.assertEqual(private_ipv4_addresses(IP_OUTPUT), ["192.168.1.20", "10.0.0.7", "100.64.100.27"])

    def test_message_warns_the_code_is_secret(self):
        message = pairing_message(FIXTURE)
        self.assertIn(FIXTURE, message)
        self.assertIn("like a password", message)


# The same lists are asserted in mac/Tests/TuxPaneCoreTests/PairingCodeTests.swift.
PAIRABLE = ["10.1.2.3", "172.16.0.1", "172.31.255.1", "192.168.0.9", "100.64.0.1", "100.127.1.1"]
NOT_PAIRABLE = ["8.8.8.8", "172.32.0.1", "100.128.0.1", "198.18.0.1", "192.0.0.1", "240.0.0.1",
                "203.0.113.9", "169.254.1.1", "127.0.0.1"]

BUSY_HOST = """\
1: lo    inet 127.0.0.1/8 scope host lo\\ x
2: enp1s0    inet 192.168.1.20/24 scope global enp1s0\\ x
3: Meta    inet 198.18.0.1/16 scope global Meta\\ x
4: vboxnet0    inet 192.168.56.1/24 scope global vboxnet0\\ x
5: lxdbr0    inet 10.95.1.1/24 scope global lxdbr0\\ x
6: tun0    inet 10.8.0.2/24 scope global tun0\\ x
7: vmnet8    inet 172.16.5.1/24 scope global vmnet8\\ x
8: wg0    inet 10.9.0.2/24 scope global wg0\\ x
9: incusbr0    inet 10.10.0.1/24 scope global incusbr0\\ x
10: tailscale0    inet 100.64.100.27/32 scope global tailscale0\\ x
11: wlp2s0    inet 192.168.1.30/24 scope global wlp2s0\\ x
"""


class AddressPolicyTest(unittest.TestCase):
    def test_pairable_policy(self):
        from tuxpane.pairing import is_pairable
        for host in PAIRABLE:
            self.assertTrue(is_pairable(host), host)
        for host in NOT_PAIRABLE:
            self.assertFalse(is_pairable(host), host)

    def test_bridges_vpns_and_tun_devices_are_skipped(self):
        self.assertEqual(private_ipv4_addresses(BUSY_HOST), ["192.168.1.20", "192.168.1.30", "100.64.100.27"])

    def test_default_route_interface_comes_first(self):
        self.assertEqual(private_ipv4_addresses(BUSY_HOST, default_interface="wlp2s0"),
                         ["192.168.1.30", "192.168.1.20", "100.64.100.27"])

    def test_default_interface_from_route_table(self):
        from tuxpane.pairing import default_interface
        self.assertEqual(default_interface("default via 192.168.1.1 dev wlp2s0 proto dhcp metric 600\n"), "wlp2s0")
        self.assertIsNone(default_interface(""))

    def test_code_wrapped_by_a_terminal_still_parses(self):
        wrapped = FIXTURE[:70] + "\n  " + FIXTURE[70:150] + " \r\n" + FIXTURE[150:]
        self.assertEqual(parse_pairing_code(wrapped)["p"], 7300)


if __name__ == "__main__":
    unittest.main()
