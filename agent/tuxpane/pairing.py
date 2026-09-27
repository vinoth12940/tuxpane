"""Pairing code: everything the Mac needs to find and trust this machine, in one pasteable string."""
from __future__ import annotations

import base64
import ipaddress
import json
import re

from .security import TAILSCALE_CGNAT

PREFIX = "tuxpane1:"
# Container bridges, VM host networks and VPN/TUN devices: the Mac can't reach these, and each dead address
# costs it a 3 s connect timeout. Tailscale (tailscale0) is handled separately.
IGNORED_INTERFACES = ("docker", "br-", "veth", "virbr", "lxc", "lxd", "incus", "cni", "flannel", "podman",
                      "vnet", "vmnet", "vboxnet", "mpqemu", "tun", "tap", "wg", "zt", "ppp", "meta", "clash", "utun")
PAIRABLE_NETWORKS = tuple(ipaddress.ip_network(n) for n in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10"))
_DEFAULT_ROUTE = re.compile(r"^default\b.*?\bdev\s+(\S+)", re.MULTILINE)
_IP_LINE = re.compile(r"^\d+:\s+(\S+)\s+inet\s+(\d+\.\d+\.\d+\.\d+)/", re.MULTILINE)


def make_pairing_code(name: str, hosts: list[str], port: int, token: str, fingerprint: str) -> str:
    payload = json.dumps({"n": name, "h": hosts, "p": port, "t": token, "f": fingerprint}, separators=(",", ":"))
    return PREFIX + base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def parse_pairing_code(code: str) -> dict:
    code = code.strip()
    if not code.startswith(PREFIX):
        raise ValueError("not a TuxPane pairing code")
    body = "".join(code[len(PREFIX):].split())  # terminals may hard-wrap the long line
    try:
        data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("pairing code is damaged") from exc
    if not isinstance(data, dict) or not {"n", "h", "p", "t", "f"} <= data.keys():
        raise ValueError("pairing code is incomplete")
    return data


def is_pairable(host: str) -> bool:
    """Addresses a Mac may be told to dial: LAN (RFC 1918) and Tailscale only. Mirrors PrivateAddress in Swift."""
    try:
        ip = ipaddress.IPv4Address(host)
    except ValueError:
        return False
    return any(ip in network for network in PAIRABLE_NETWORKS)


def default_interface(route_output: str) -> str | None:
    """The interface of the default route (`ip -4 route show default`): the most likely way in from the Mac."""
    match = _DEFAULT_ROUTE.search(route_output)
    return match.group(1) if match else None


def private_ipv4_addresses(ip_output: str, default_interface: str | None = None) -> list[str]:
    """Default-route address first, then other LAN addresses, then Tailscale; bridges and VPNs are skipped."""
    first, lan, tailnet = [], [], []
    for interface, address in _IP_LINE.findall(ip_output):
        if interface.lower().startswith(IGNORED_INTERFACES) or not is_pairable(address):
            continue
        if ipaddress.ip_address(address) in TAILSCALE_CGNAT:
            tailnet.append(address)
        elif interface == default_interface:
            first.append(address)
        else:
            lan.append(address)
    return first + lan + tailnet


def pairing_message(code: str) -> str:
    return (
        "\nPairing code (paste it into TuxPane on your Mac):\n\n"
        f"  {code}\n\n"
        "Keep it private: it gives full control of this desktop, like a password.\n"
        "Show it again with `tuxpane pair`; revoke all paired Macs with `tuxpane pair --reset`.\n"
    )
