#!/bin/sh
# Build a legacy add-on zip for installing this checkout in Blender.
#
# The zip contains a single top-level `ucupaint/` folder, which is the layout
# Blender expects for _Edit > Preferences > Add-ons > Install from Disk_.
# The version is read from blender_manifest.toml, which stays in sync with
# bl_info in __init__.py.
#
# Development files (tests, docs, CI, caches, add-on state) are left out; the
# build is taken from the working tree so uncommitted changes are included.
#
# Usage: ./build.sh            -> dist/ucupaint-<version>.zip

set -eu

cd "$(dirname "$0")"

VERSION=$(sed -n 's/^version = "\([^"]*\)"/\1/p' blender_manifest.toml | head -n 1)
if [ -z "$VERSION" ]; then
    echo "build.sh: could not read version from blender_manifest.toml" >&2
    exit 1
fi

ROOT=$(pwd)
DIST="$ROOT/dist"
ZIP="$DIST/ucupaint-$VERSION.zip"
STAGE=$(mktemp -d "${TMPDIR:-/tmp}/ucupaint-build.XXXXXX")
trap 'rm -rf "$STAGE"' EXIT HUP INT TERM

mkdir -p "$DIST"
rm -f "$ZIP"

rsync -a \
    --exclude='.git/' \
    --exclude='.github/' \
    --exclude='.opencode/' \
    --exclude='dist/' \
    --exclude='__pycache__/' \
    --exclude='*_updater/' \
    --exclude='tests/' \
    --exclude='docs/' \
    --exclude='AGENTS.md' \
    ./ "$STAGE/ucupaint/"

(cd "$STAGE" && zip -qr "$ZIP" ucupaint)

echo "built: $ZIP"
