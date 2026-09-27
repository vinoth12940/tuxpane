#!/usr/bin/env bash
# TuxPane agent installer.
#   curl -fsSL https://github.com/vinoth12940/tuxpane/releases/latest/download/install.sh | bash
set -euo pipefail
VERSION="@VERSION@"
SHA256="@SHA256@"
REPO="vinoth12940/tuxpane"

if [ "$(id -u)" -eq 0 ]; then
  echo "Run this as your normal desktop user, not root (no sudo)." >&2
  exit 1
fi
for tool in curl tar python3 sha256sum; do
  command -v "$tool" >/dev/null 2>&1 || { echo "TuxPane needs '$tool'. Install it with your package manager and run this again." >&2; exit 1; }
done
python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' || { echo "TuxPane needs Python 3.10 or newer." >&2; exit 1; }

DEST="$HOME/.local/share/tuxpane"
mkdir -p "$DEST"
TARBALL="${TUXPANE_TARBALL:-}"
if [ -z "$TARBALL" ]; then
  TARBALL="$(mktemp)"
  trap 'rm -f "$TARBALL"' EXIT
  echo "Downloading TuxPane agent $VERSION…"
  curl -fsSL "https://github.com/$REPO/releases/download/v$VERSION/tuxpane-agent-$VERSION.tar.gz" -o "$TARBALL"
fi
echo "$SHA256  $TARBALL" | sha256sum -c --quiet - || { echo "The download is damaged (checksum mismatch). Please try again." >&2; exit 1; }
rm -rf "${DEST:?}/$VERSION"
mkdir -p "$DEST/$VERSION"
tar -xzf "$TARBALL" -C "$DEST/$VERSION"
ln -sfn "$DEST/$VERSION" "$DEST/current"
PYTHONPATH="$DEST/current" exec python3 -m tuxpane.setup "$@"
