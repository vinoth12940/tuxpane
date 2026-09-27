#!/usr/bin/env python3
"""Blocks personal and security details from entering the repository.

Checks added lines (and file names) for:
  - IPv4 addresses and Tailscale IPv6 addresses that aren't approved placeholders in .sensitive-allowlist
  - home-folder paths (/Users/<name>, /home/<name>) and email addresses not in the allowlist
  - private keys, API tokens and credential files
  - anything matching your private denylist (never committed), by default ~/.config/tuxpane-dev/sensitive-patterns:
    one regular expression per line, e.g. your real hostname, user names and addresses

Usage:
  check-sensitive.py --staged           staged changes (the pre-commit hook)
  check-sensitive.py --message FILE     a commit message (the commit-msg hook)
  check-sensitive.py --all              every tracked file (CI)
"""
from __future__ import annotations

import argparse
import os
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
ALLOWLIST = ROOT / ".sensitive-allowlist"
DENYLIST = pathlib.Path(os.environ.get("TUXPANE_SENSITIVE_PATTERNS",
                                       "~/.config/tuxpane-dev/sensitive-patterns")).expanduser()

IPV4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.]*\d)")
TAILSCALE_V6 = re.compile(r"fd7a:115c:a1e0:[0-9a-f:]*[0-9a-f]", re.IGNORECASE)  # a full address, not the prefix
HOME_PATH = re.compile(r"(?:/Users|/home)/([A-Za-z0-9._-]+)")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
SECRETS = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "a private key"),
    (re.compile(r"\bAuthKey_[A-Z0-9]{8,}"), "an App Store Connect key name"),
    (re.compile(r"\b(?:ghp|gho|ghs|ghu)_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}"), "a GitHub token"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"), "an API key"),
    (re.compile(r"\btskey-[A-Za-z0-9-]{10,}"), "a Tailscale auth key"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), "a Slack token"),
]
SECRET_FILES = re.compile(r"(^|/)(\.env(\..*)?|.*\.(pem|key|p12|p8|pfx|mobileprovision)|AuthKey_.*|token|id_(rsa|ed25519|ecdsa)(\.pub)?)$")
# Addresses that are never personal.
ALWAYS_OK_IPS = {"0.0.0.0", "127.0.0.1", "255.255.255.255"}


def load_allowlist() -> set[str]:
    if not ALLOWLIST.exists():
        return set()
    return {line.split("#", 1)[0].strip() for line in ALLOWLIST.read_text().splitlines()} - {""}


def load_denylist() -> list[re.Pattern]:
    if not DENYLIST.exists():
        return []
    patterns = []
    for line in DENYLIST.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.append(re.compile(line, re.IGNORECASE))
    return patterns


def problems_in(text: str, allowed: set[str], denied: list[re.Pattern]) -> list[str]:
    found = []
    for ip in IPV4.findall(text):
        if ip not in ALWAYS_OK_IPS and ip not in allowed and all(0 <= int(part) <= 255 for part in ip.split(".")):
            found.append(f"IP address {ip}")
    for ip in TAILSCALE_V6.findall(text):
        if ip.lower() not in allowed:
            found.append(f"Tailscale address {ip}")
    for name in HOME_PATH.findall(text):
        if name not in allowed:
            found.append(f"home folder of '{name}'")
    for email in EMAIL.findall(text):
        lowered = email.lower()
        if (lowered in allowed or lowered.startswith("noreply@")
                or lowered.endswith(("@example.com", "@example.org", "@users.noreply.github.com"))):
            continue
        found.append(f"email address {email}")
    for pattern, what in SECRETS:
        if pattern.search(text):
            found.append(what)
    for pattern in denied:
        if pattern.search(text):
            found.append(f"a match for your private pattern /{pattern.pattern}/")
    return found


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def staged_items() -> tuple[list[tuple[str, str]], list[str]]:
    """(location, added text) for every staged file, plus its name."""
    items = []
    names = [n for n in git("diff", "--cached", "--name-only", "--diff-filter=ACMR").splitlines() if n]
    for name in names:
        items.append((name, "\n".join(line[1:] for line in git("diff", "--cached", "-U0", "--", name).splitlines()
                                      if line.startswith("+") and not line.startswith("+++"))))
    return items, names


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--staged", action="store_true")
    mode.add_argument("--all", action="store_true")
    mode.add_argument("--message")
    args = ap.parse_args(argv)
    allowed, denied = load_allowlist(), load_denylist()

    if args.message:
        items, names = [("commit message", pathlib.Path(args.message).read_text())], []
    elif args.staged:
        items, names = staged_items()
    else:
        names = [n for n in git("ls-files").splitlines() if n]
        items = []
        for name in names:
            try:
                items.append((name, (ROOT / name).read_text()))
            except (UnicodeDecodeError, OSError):
                continue  # binary files

    failures = [f"{name}: looks like a credential file" for name in names if SECRET_FILES.search(name)]
    if args.staged:
        # Commit author emails are public: only a no-reply address may be used.
        email = git("config", "user.email").strip().lower()
        if not (email.endswith("@users.noreply.github.com") or email.startswith("noreply@")):
            failures.append(f"commit author email {email}: use your GitHub no-reply address "
                            "(git config user.email <id>+<user>@users.noreply.github.com)")
    for location, text in items:
        if location == ".sensitive-allowlist":
            continue
        for problem in dict.fromkeys(problems_in(text, allowed, denied)):
            failures.append(f"{location}: {problem}")

    if failures:
        print("Blocked: this may leak personal or security details.\n", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        print("\nUse a made-up placeholder instead. If it really is a made-up example, add it to "
              ".sensitive-allowlist.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
