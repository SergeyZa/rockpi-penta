#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_DIR="$ROOT_DIR/rockpi-penta"
OUT_DEB="$ROOT_DIR/rockpi-penta.deb"

if [[ ! -d "$PKG_DIR/DEBIAN" ]]; then
  echo "Error: package directory not found: $PKG_DIR" >&2
  exit 1
fi

chmod -R 775 "$PKG_DIR/DEBIAN/"

if dpkg-deb --help | grep -q -- '--root-owner-group'; then
  dpkg-deb --build -Z gzip --root-owner-group "$PKG_DIR" "$OUT_DEB"
else
  dpkg-deb --build -Z gzip "$PKG_DIR" "$OUT_DEB"
fi

echo "Built package: $OUT_DEB"
