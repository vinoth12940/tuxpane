"""Checks the installer runs before touching anything; each failure says exactly how to fix it."""
from __future__ import annotations

import dataclasses
import glob
import ipaddress
import os
import pathlib
import re
import subprocess

from .config import DEFAULT_VAAPI_DEVICE, ENCODERS
from .display import parse_xrandr
from .encoder import build_ffmpeg_cmd
from .x11 import xauthority_candidates

WAYLAND_HELP = """Your desktop is running Wayland. TuxPane v1 needs an X11 (Xorg) session.
  1. Log out.
  2. On the login screen, click your name, then the gear icon at the bottom right.
  3. Choose "Ubuntu on Xorg" / "GNOME on Xorg" / "Plasma (X11)" and log in.
  4. Run the installer again."""

NO_SESSION_HELP = """No logged-in X11 desktop was found for your user.
TuxPane shows the desktop that is already running, so a user must be logged in to it.
For a headless machine: enable auto-login for this user and plug in an HDMI dummy plug
(or keep a monitor attached), reboot, then run the installer again."""

COMMANDS = ("ffmpeg", "xrandr", "xclip", "openssl")
LIBRARIES = ("X11", "Xtst", "Xfixes")
PACKAGES = {
    "apt": {"ffmpeg": "ffmpeg", "xrandr": "x11-xserver-utils", "xclip": "xclip", "openssl": "openssl",
            "X11": "libx11-6", "Xtst": "libxtst6", "Xfixes": "libxfixes3"},
    "dnf": {"ffmpeg": "ffmpeg", "xrandr": "xrandr", "xclip": "xclip", "openssl": "openssl",
            "X11": "libX11", "Xtst": "libXtst", "Xfixes": "libXfixes"},
    "pacman": {"ffmpeg": "ffmpeg", "xrandr": "xorg-xrandr", "xclip": "xclip", "openssl": "openssl",
               "X11": "libx11", "Xtst": "libxtst", "Xfixes": "libxfixes"},
    "zypper": {"ffmpeg": "ffmpeg", "xrandr": "xrandr", "xclip": "xclip", "openssl": "openssl",
               "X11": "libX11-6", "Xtst": "libXtst6", "Xfixes": "libXfixes3"},
}
INSTALLERS = {
    "apt": ["sudo", "apt-get", "install", "-y"],
    "dnf": ["sudo", "dnf", "install", "-y"],
    "pacman": ["sudo", "pacman", "-S", "--needed", "--noconfirm"],
    "zypper": ["sudo", "zypper", "install", "-y"],
}
PACKAGE_MANAGER_BINARIES = (("apt", "apt-get"), ("dnf", "dnf"), ("pacman", "pacman"), ("zypper", "zypper"))


NO_OUTPUT_HELP = """The desktop has no active screen output, so there is nothing to show.
On a headless machine, plug in an HDMI dummy plug (or a monitor), reboot, and run the installer again."""


class SetupError(Exception):
    """A problem the user must fix; the message says how."""


@dataclasses.dataclass
class GraphicalSession:
    session_id: str
    display: str


def _props(text: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)


def find_graphical_session(run, user: str) -> GraphicalSession:
    listing = run(["loginctl", "list-sessions", "--no-legend"], capture_output=True, text=True).stdout
    saw_wayland = False
    for line in listing.splitlines():
        fields = line.split()
        if len(fields) < 3 or fields[2] != user:
            continue
        props = _props(run(["loginctl", "show-session", fields[0], "-p", "Type", "-p", "Display", "-p", "Class"],
                           capture_output=True, text=True).stdout)
        if props.get("Class", "user") != "user":
            continue
        if props.get("Type") == "x11":
            return GraphicalSession(fields[0], props.get("Display") or ":0")
        saw_wayland = saw_wayland or props.get("Type") == "wayland"
    raise SetupError(WAYLAND_HELP if saw_wayland else NO_SESSION_HELP)


def x_env(environ, display: str, xauthority: str) -> dict:
    return {**environ, "DISPLAY": display, "XAUTHORITY": xauthority}


def find_xauthority(run, display: str, home: pathlib.Path, uid: int, environ, exists=os.path.exists,
                    glob_fn=glob.glob) -> str:
    for candidate in xauthority_candidates(uid, home, environ.get("XAUTHORITY"), glob_fn=glob_fn):
        if not exists(candidate):
            continue
        result = run(["xrandr", "--query"], capture_output=True, text=True,
                     env=x_env(environ, display, candidate), timeout=10)
        if result.returncode == 0:
            return candidate
    raise SetupError(f"Cannot open the X display {display}.\n"
                     "Run the installer as the same user who is logged in to the desktop.")


def missing_requirements(which, find_lib) -> list[str]:
    return [c for c in COMMANDS if not which(c)] + [lib for lib in LIBRARIES if not find_lib(lib)]


def detect_package_manager(which) -> str | None:
    for name, binary in PACKAGE_MANAGER_BINARIES:
        if which(binary):
            return name
    return None


def install_command(package_manager: str | None, missing: list[str]) -> list[str] | None:
    if package_manager not in INSTALLERS:
        return None
    names = PACKAGES[package_manager]
    return INSTALLERS[package_manager] + [names[item] for item in missing]


def screen_size(run, env) -> tuple[int, int]:
    result = run(["xrandr", "--query"], capture_output=True, text=True, env=env, check=True, timeout=10)
    try:
        return parse_xrandr(result.stdout)[1]
    except RuntimeError as exc:
        raise SetupError(NO_OUTPUT_HELP) from exc


def probe_encoder(run, display: str, env, width: int, height: int, render_nodes: list[str]) -> tuple[str, str]:
    """1-second test encodes of the real screen; the first HEVC encoder that works wins."""
    failures = []
    for encoder in ENCODERS:
        devices = (render_nodes or [DEFAULT_VAAPI_DEVICE]) if encoder == "vaapi" else [DEFAULT_VAAPI_DEVICE]
        for device in devices:
            cmd = build_ffmpeg_cmd(encoder, display, width, height, 30, 10, ["-t", "1", "-f", "null", "-"], device)
            try:
                result = run(cmd, capture_output=True, text=True, env=env, timeout=60)
            except (OSError, subprocess.TimeoutExpired) as exc:
                failures.append(f"  {encoder}: {exc}")
                continue
            if result.returncode == 0:
                return encoder, device
            reason = (result.stderr.strip().splitlines() or ["failed"])[-1]
            failures.append(f"  {encoder}: {reason}")
    raise SetupError("No working HEVC video encoder was found:\n" + "\n".join(failures) +
                     "\nInstall a full ffmpeg build (on Fedora: enable RPM Fusion and `sudo dnf swap ffmpeg-free "
                     "ffmpeg --allowerasing`), and GPU drivers if you have an Intel, AMD or NVIDIA GPU.")


UFW_CONF = pathlib.Path("/etc/ufw/ufw.conf")


def active_firewall(run, ufw_conf: pathlib.Path = UFW_CONF) -> str | None:
    """ufw is judged by ENABLED=yes in its (world-readable) config: its systemd unit reports "active" even when
    ufw is disabled. firewalld is a normal service."""
    try:
        if re.search(r"^\s*ENABLED\s*=\s*yes\s*$", ufw_conf.read_text(), re.MULTILINE | re.IGNORECASE):
            return "ufw"
    except OSError:
        pass
    try:
        result = run(["systemctl", "is-active", "firewalld"], capture_output=True, text=True)
    except OSError:
        return None
    return "firewalld" if result.stdout.strip() == "active" else None


_IP_PREFIX_LINE = re.compile(r"^\d+:\s+(\S+)\s+inet\s+(\d+\.\d+\.\d+\.\d+/\d+)", re.MULTILINE)


def lan_subnets(ip_output: str) -> list[str]:
    """The home-network subnets the Mac can come from (not Tailscale, bridges or VPNs)."""
    from .pairing import IGNORED_INTERFACES, is_pairable
    from .security import TAILSCALE_CGNAT
    subnets = []
    for interface, cidr in _IP_PREFIX_LINE.findall(ip_output):
        address = cidr.split("/")[0]
        if interface.lower().startswith(IGNORED_INTERFACES) or not is_pairable(address):
            continue
        if ipaddress.ip_address(address) in TAILSCALE_CGNAT:
            continue
        subnets.append(str(ipaddress.ip_network(cidr, strict=False)))
    return list(dict.fromkeys(subnets))


def firewall_commands(firewall: str, subnets: list[str], port: int = 7300) -> list[list[str]]:
    """Rules allowing the agent port (TCP) and pairing port 7301 (TCP + UDP discovery) from home subnets only."""
    if not subnets:
        return []
    tcp_ports = ["7300:7301"] if port == 7300 else [str(port), "7301"]
    if firewall == "ufw":
        commands = []
        for subnet in subnets:
            for ports in tcp_ports:
                commands.append(["sudo", "ufw", "allow", "from", subnet, "to", "any", "port", ports, "proto", "tcp",
                                 "comment", "TuxPane"])
            commands.append(["sudo", "ufw", "allow", "from", subnet, "to", "any", "port", "7301", "proto", "udp",
                             "comment", "TuxPane"])
        return commands
    if firewall == "firewalld":
        commands = []
        for subnet in subnets:
            for ports, protocol in [(ports.replace(":", "-"), "tcp") for ports in tcp_ports] + [("7301", "udp")]:
                commands.append(["sudo", "firewall-cmd", "--permanent", "--add-rich-rule",
                                 f"rule family=ipv4 source address={subnet} port port={ports} protocol={protocol} accept"])
        return commands + [["sudo", "firewall-cmd", "--reload"]]
    return []
