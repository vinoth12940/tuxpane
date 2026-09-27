#!/usr/bin/env bash
# Builds dist/tuxpane-agent-<version>.tar.gz and dist/install.sh with version and checksum baked in.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(cd "$ROOT/agent" && python3 -c 'import tuxpane; print(tuxpane.__version__)')"
mkdir -p "$ROOT/dist"
TARBALL="$ROOT/dist/tuxpane-agent-$VERSION.tar.gz"
# Record a neutral owner (not your Mac user name) and leave out hidden folders.
COPYFILE_DISABLE=1 tar --no-xattrs --no-fflags --no-acls --uid 0 --gid 0 --uname root --gname root \
  -C "$ROOT/agent" --exclude __pycache__ --exclude ".*" -czf "$TARBALL" tuxpane
SHA="$(shasum -a 256 "$TARBALL" | cut -d' ' -f1)"
sed -e "s/@VERSION@/$VERSION/" -e "s/@SHA256@/$SHA/" "$ROOT/packaging/install.sh" > "$ROOT/dist/install.sh"
chmod +x "$ROOT/dist/install.sh"
echo "dist/tuxpane-agent-$VERSION.tar.gz ($SHA)"
echo "dist/install.sh"
