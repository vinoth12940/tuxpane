"""TuxPane Linux setup, run by install.sh: python3 -m tuxpane.setup [--yes] [--port N] [--reset]."""
from __future__ import annotations

import argparse
import asyncio
import getpass
import io
import glob
import os
import pathlib
import shlex
import shutil
import socket
import subprocess
import sys
import termios
import time
from ctypes.util import find_library

from . import __version__
from .config import AgentConfig, load_config, save_config
from .pair_session import PairingSession, TerminalPrompt, is_interactive, open_terminal, os_pretty_name
from .pairing import default_interface, private_ipv4_addresses
from .security import ensure_security_material
from .ui import Checklist
from .setup_checks import (SetupError, active_firewall, detect_package_manager, firewall_commands, lan_subnets, find_graphical_session, find_xauthority,
                           UFW_CONF, install_command, missing_requirements, probe_encoder, screen_size, x_env)

UNIT = "tuxpane.service"


def unit_file(python: str, agent_root, config_path, display: str, xauthority: str) -> str:
    return (
        "[Unit]\nDescription=TuxPane remote desktop agent\nAfter=graphical-session.target\n\n"
        "[Service]\n"
        f"Environment=DISPLAY={display}\nEnvironment=XAUTHORITY={xauthority}\n"
        f"Environment=PYTHONPATH={agent_root}\n"
        f"ExecStart={python} -m tuxpane --config {config_path}\n"
        "Restart=always\nRestartSec=5\n\n[Install]\nWantedBy=default.target\n"
    )


def cli_wrapper(agent_root) -> str:
    return f'#!/bin/sh\nPYTHONPATH="{agent_root}" exec python3 -m tuxpane.cli "$@"\n'


def systemd_env(environ, uid: int) -> dict:
    runtime = environ.get("XDG_RUNTIME_DIR", f"/run/user/{uid}")
    return {**environ, "XDG_RUNTIME_DIR": runtime,
            "DBUS_SESSION_BUS_ADDRESS": environ.get("DBUS_SESSION_BUS_ADDRESS", f"unix:path={runtime}/bus")}


def _previous_config(path: pathlib.Path) -> AgentConfig | None:
    """Re-running the installer (or `tuxpane update`) keeps the user's port and resolution choice."""
    try:
        return load_config(path) if path.exists() else None
    except ValueError:
        return None


def machine_addresses(run) -> list[str]:
    routes = run(["ip", "-4", "route", "show", "default"], capture_output=True, text=True).stdout
    addresses = run(["ip", "-4", "-o", "addr", "show"], capture_output=True, text=True).stdout
    return private_ipv4_addresses(addresses, default_interface(routes))


def _output_stream(out):
    """The installer writes to the real stdout (so the checklist can see a terminal); tests pass a stream or callable."""
    if out is None:
        return sys.stdout
    return out if hasattr(out, "write") else _CallableStream(out)


def tty_ask(question: str, default: bool, path: str = "/dev/tty") -> bool:
    try:
        reader, writer = open_terminal(path)
    except OSError:
        return default
    with reader, writer:
        try:  # ignore keys typed before the question appeared (e.g. while packages installed)
            termios.tcflush(reader.fileno(), termios.TCIFLUSH)
        except (OSError, termios.error):
            pass
        writer.write(f"{question} [{'Y/n' if default else 'y/N'}] ")
        writer.flush()
        answer = reader.readline().strip().lower()
    return default if not answer else answer.startswith("y")


ENCODER_NAMES = {"vaapi": "GPU hardware (VAAPI)", "nvenc": "NVIDIA hardware (NVENC)",
                 "x265": "software (x265, up to 1920×1200)"}


class _CallableStream(io.TextIOBase):
    """Adapts a print-like callable (tests) to the stream the checklist writes to."""

    def __init__(self, emit) -> None:
        self.emit = emit
        self._buffer = ""

    def write(self, text: str) -> int:
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self.emit(line)
        return len(text)

    def isatty(self) -> bool:
        return False


def _run_pairing_session(config_dir, port, hosts, name, ui) -> str | None:
    """Runs a real pairing session on this terminal; returns the paired Mac's name."""
    from .security import cert_fingerprint
    prompt = TerminalPrompt()

    async def confirm(mac_name: str, code: str) -> bool:
        return await prompt.ask(f"  Same code? Pair with this Mac? [y/N]")

    session = PairingSession(token=(config_dir / "token").read_text().strip(), cert=config_dir / "cert.pem",
                             key=config_dir / "key.pem", fingerprint_hex=cert_fingerprint(config_dir / "cert.pem"),
                             hosts=hosts, agent_port=port, hostname=name, os_name=os_pretty_name(),
                             confirm=confirm, ui=ui)
    try:
        return asyncio.run(session.run())
    except KeyboardInterrupt:
        ui.text()
        ui.text("  Pairing stopped. Run `tuxpane pair` whenever you're ready.")
        return None
    except OSError as exc:
        ui.fail("Pairing", f"Can't listen on port 7301 ({exc.strerror}). Is `tuxpane pair` already running?")
        return None


def main(argv=None, *, run=subprocess.run, which=shutil.which, find_lib=find_library, ask=tty_ask, home=None,
         environ=None, uid=None, euid=None, render_nodes=None, out=None, sleep=time.sleep,
         hostname=socket.gethostname, interactive=None, pair_runner=None, ufw_conf=UFW_CONF) -> int:
    ap = argparse.ArgumentParser(prog="tuxpane-setup")
    ap.add_argument("--yes", action="store_true", help="accept all defaults")
    ap.add_argument("--port", type=int, default=None, help="listen port (default: keep the current one, else 7300)")
    ap.add_argument("--reset", action="store_true", help="new token and certificate (unpairs every Mac)")
    ap.add_argument("--no-pair", action="store_true", help="don't pair a Mac now")
    args = ap.parse_args(argv)
    home = pathlib.Path(home or pathlib.Path.home())
    environ = dict(os.environ if environ is None else environ)
    uid = os.getuid() if uid is None else uid
    euid = os.geteuid() if euid is None else euid
    render_nodes = sorted(glob.glob("/dev/dri/renderD*")) if render_nodes is None else render_nodes
    confirm = (lambda question, default: default) if args.yes else ask

    stream = _output_stream(out)
    ui = Checklist(stream=stream)
    interactive = is_interactive() if interactive is None else interactive
    runner = pair_runner or _run_pairing_session
    label = "Desktop session"
    try:
        ui.header(f"TuxPane {__version__} · Linux setup")
        if euid == 0:
            raise SetupError("Run the installer as your normal desktop user, not root (no sudo).")
        ui.start(label)
        session = find_graphical_session(run, getpass.getuser())
        config_path = home / ".config/tuxpane/agent.json"
        previous = _previous_config(config_path)
        port = args.port or (previous.port if previous else 7300)
        label = "Required packages"
        ui.start(label)
        missing = missing_requirements(which, find_lib)
        installed = ""
        if missing:
            command = install_command(detect_package_manager(which), missing)
            if command is None:
                raise SetupError(f"Please install: {', '.join(missing)} (and ffmpeg with HEVC support), then rerun.")
            ui.end_waiting()
            if not confirm(f"Install missing packages with `{' '.join(command)}`?", False):
                raise SetupError(f"Install them with:\n{' '.join(command)}\nthen run the installer again.")
            run(command, check=True)
            missing = missing_requirements(which, find_lib)
            if missing:
                raise SetupError(f"Still missing after install: {', '.join(missing)}")
            installed = "installed what was missing"
        ui.ok("Desktop session", f"X11 on {session.display}")
        ui.ok(label, installed or "all present")
        label = "Video encoder"
        ui.start(label)
        xauthority = find_xauthority(run, session.display, home, uid, environ)
        env = x_env(environ, session.display, xauthority)
        width, height = screen_size(run, env)
        encoder, device = probe_encoder(run, session.display, env, width, height, render_nodes)
        ui.ok(label, f"{ENCODER_NAMES[encoder]} · {width}×{height}")
        match = confirm("Match your Mac's resolution? (recommended for headless machines with a dummy plug)",
                        previous.match_resolution if previous else True)
        label = "Security keys"
        ui.start(label)
        config_dir = home / ".config/tuxpane"
        had_keys = (config_dir / "cert.pem").exists() and not args.reset
        token, fingerprint = ensure_security_material(config_dir, run, reset=args.reset)
        save_config(config_path, AgentConfig(port=port, encoder=encoder, vaapi_device=device, match_resolution=match))
        ui.ok(label, "kept (paired Macs keep working)" if had_keys else "created")
        label = "Background service"
        ui.start(label)
        service_env = systemd_env(environ, uid)
        agent_root = home / ".local/share/tuxpane/current"
        unit_dir = home / ".config/systemd/user"
        unit_dir.mkdir(parents=True, exist_ok=True)
        (unit_dir / UNIT).write_text(unit_file(sys.executable, agent_root, config_path, session.display, xauthority))
        bin_dir = home / ".local/bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        (bin_dir / "tuxpane").write_text(cli_wrapper(agent_root))
        os.chmod(bin_dir / "tuxpane", 0o755)
        for command in (["daemon-reload"], ["enable", UNIT], ["restart", UNIT]):
            run(["systemctl", "--user", *command], env=service_env, check=True, capture_output=True)
        for _ in range(30):
            if f":{port} " in run(["ss", "-ltn"], capture_output=True, text=True).stdout:
                break
            sleep(0.5)
        else:
            raise SetupError("The TuxPane service did not start. See: journalctl --user -u tuxpane -n 30")
        ui.ok(label, f"running · port {port}")
        ip_output = run(["ip", "-4", "-o", "addr", "show"], capture_output=True, text=True).stdout
        firewall = active_firewall(run, ufw_conf)
        rules = firewall_commands(firewall, lan_subnets(ip_output), port) if firewall else []
        if rules:
            shown = [shlex.join(command) for command in rules]
            ports = "7300–7301" if port == 7300 else f"{port} and 7301"
            blocked = (f"{firewall} is on. Unless you already allowed TuxPane, Macs on your home network can't find "
                       "or reach this machine (Tailscale still works). To allow them, run:")
            if confirm(f"{firewall} is on. Allow TuxPane from your home network (runs sudo)?", False):
                try:
                    for command in rules:
                        run(command, check=True, capture_output=True)
                except (subprocess.CalledProcessError, OSError):
                    ui.warn("Firewall", [f"Changing the {firewall} rules failed. " + blocked, *shown])
                else:
                    ui.ok("Firewall", f"{firewall}: allowed ports {ports} from your home network")
            else:
                ui.warn("Firewall", [blocked, *shown])
        hosts = machine_addresses(run)
        if not hosts:
            raise SetupError("No LAN or Tailscale address found. Connect this machine to your network and rerun.")
        ui.text()
        if interactive and not args.no_pair:
            ui.text(f"  {ui.bold('Open TuxPane on your Mac')} and choose {ui.blue(hostname())}.")
            runner(config_dir, port, hosts, hostname(), ui)
        else:
            ui.text(f"  {ui.bold('Ready.')} To pair a Mac, run `tuxpane pair` in a terminal on this machine.")
            ui.text(f"  (Or print a code to paste manually: `tuxpane pair --code`.)")
        if str(bin_dir) not in environ.get("PATH", "").split(":"):
            ui.text(f"  The `tuxpane` command is {bin_dir / 'tuxpane'}.")
        return 0
    except SetupError as exc:
        ui.fail(label, str(exc))
        return 1
    except FileNotFoundError as exc:
        missing_tool = exc.filename or (exc.args[0] if exc.args else "a system tool")
        ui.fail(label, f"`{missing_tool}` was not found. TuxPane needs systemd (loginctl, systemctl) and "
                       "iproute2 (ip, ss).")
        return 1
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr or b""
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")
        ui.fail(label, f"`{' '.join(map(str, exc.cmd))}` failed. {stderr.strip()}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
