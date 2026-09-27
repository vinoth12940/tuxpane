"""The `tuxpane` command on Linux: pair, status, uninstall, update."""
from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import socket
import subprocess
import sys

from .config import load_config
from .pair_session import is_interactive
from .pairing import make_pairing_code, pairing_message
from .security import ensure_security_material
from .setup import UNIT, machine_addresses, systemd_env

INSTALL_URL = "https://github.com/vinoth12940/tuxpane/releases/latest/download/install.sh"


def main(argv=None, *, run=subprocess.run, home=None, environ=None, uid=None, out=print,
         hostname=socket.gethostname, interactive=None) -> int:
    ap = argparse.ArgumentParser(prog="tuxpane", description="Manage the TuxPane agent on this machine.")
    sub = ap.add_subparsers(dest="command", required=True)
    pair = sub.add_parser("pair", help="show the pairing code for the Mac app")
    pair.add_argument("--reset", action="store_true", help="new token and certificate; unpairs every Mac")
    pair.add_argument("--code", action="store_true", help="print a pairing code to paste instead")
    sub.add_parser("status", help="show service state and addresses")
    sub.add_parser("uninstall", help="stop and remove TuxPane")
    sub.add_parser("update", help="install the latest release")
    args = ap.parse_args(argv)
    home = pathlib.Path(home or pathlib.Path.home())
    environ = dict(os.environ if environ is None else environ)
    env = systemd_env(environ, os.getuid() if uid is None else uid)
    config_dir = home / ".config/tuxpane"

    def addresses() -> list[str]:
        return machine_addresses(run)

    if args.command in ("pair", "status") and not (config_dir / "agent.json").exists():
        out(f"TuxPane isn't installed on this machine yet. Run the installer:\n  curl -fsSL {INSTALL_URL} | bash")
        return 1

    if args.command == "pair":
        config = load_config(config_dir / "agent.json")
        if not args.code and not (is_interactive() if interactive is None else interactive):
            # Check before --reset rotates the keys: otherwise every Mac is unpaired and none can pair again here.
            out("Pairing needs you at a terminal on this machine: run `tuxpane pair` there.\n"
                "Or print a code to paste into the Mac app instead: `tuxpane pair --code`.")
            return 1
        token, fingerprint = ensure_security_material(config_dir, run, reset=args.reset)
        if args.reset:
            run(["systemctl", "--user", "restart", UNIT], env=env, capture_output=True)
            out("New keys created; every previously paired Mac must pair again.")
        if args.code:
            out(pairing_message(make_pairing_code(hostname(), addresses(), config.port, token, fingerprint)))
            return 0
        from .setup import _run_pairing_session
        from .ui import Checklist
        ui = Checklist()
        ui.header("TuxPane · Pair a Mac")
        ui.text(f"  {ui.bold('Open TuxPane on your Mac')} and choose {ui.blue(hostname())}.")
        return 0 if _run_pairing_session(config_dir, config.port, addresses(), hostname(), ui) else 1

    if args.command == "status":
        state = run(["systemctl", "--user", "is-active", UNIT], env=env, capture_output=True, text=True).stdout.strip()
        config = load_config(config_dir / "agent.json")
        out(f"service:   {state or 'unknown'}")
        out(f"port:      {config.port}  encoder: {config.encoder}  match resolution: {config.match_resolution}")
        out(f"addresses: {', '.join(addresses()) or 'none found'}")
        logs = run(["journalctl", "--user", "-u", UNIT, "-n", "10", "--no-pager", "-o", "cat"],
                   env=env, capture_output=True, text=True).stdout
        out("recent log:\n" + logs.rstrip())
        return 0 if state == "active" else 1
    if args.command == "uninstall":
        run(["systemctl", "--user", "disable", "--now", UNIT], env=env, capture_output=True)
        (home / ".config/systemd/user" / UNIT).unlink(missing_ok=True)
        run(["systemctl", "--user", "daemon-reload"], env=env, capture_output=True)
        shutil.rmtree(config_dir, ignore_errors=True)
        shutil.rmtree(home / ".local/share/tuxpane", ignore_errors=True)
        (home / ".local/bin/tuxpane").unlink(missing_ok=True)
        out("TuxPane was removed. Remove the machine from the Mac app too.")
        return 0
    return run(["sh", "-c", f"curl -fsSL {INSTALL_URL} | bash -s -- --yes --no-pair"]).returncode


if __name__ == "__main__":
    sys.exit(main())
