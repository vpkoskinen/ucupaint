#!/bin/sh
# Run a Blender UI test script in a private X server.
#
# Why this exists: Blender 4/5 prefers Wayland whenever WAYLAND_DISPLAY is set, even
# under `xvfb-run`. On a Wayland desktop a bare `xvfb-run -a blender ...` therefore still
# opens a *real* window on the user's screen, and if the script raises before its timer
# runs, that window stays open until it is closed by hand. Stripping the Wayland session
# variables forces Blender onto the X server xvfb-run provides.
#
# Keep the `env -u` and the `timeout` wrapper: `timeout` runs *inside* xvfb-run so the
# X server is still reaped by xvfb-run itself. Do not "simplify" this back to a bare
# `xvfb-run blender`, and never run a UI script without --background unless it is through
# this wrapper.
#
# Usage: tests/run_ui.sh [script]        (default: tests/run_tests_ui.py)
#        UI_TIMEOUT=600 tests/run_ui.sh  (default hard timeout: 300 s)
#        BLENDER_BIN=/path/to/blender tests/run_ui.sh   (default: blender from PATH)

set -eu

SCRIPT="${1:-tests/run_tests_ui.py}"
UI_TIMEOUT="${UI_TIMEOUT:-300}"
BLENDER_BIN="${BLENDER_BIN:-blender}"

cd "$(dirname "$0")/.."

exec env -u WAYLAND_DISPLAY -u WAYLAND_SOCKET -u XDG_SESSION_TYPE \
    xvfb-run -a --server-args="-screen 0 1280x800x24 -nolisten tcp" \
    sh -c 'exec timeout "$1" "$3" --factory-startup --python-exit-code 1 --python "$2"' \
    sh "$UI_TIMEOUT" "$SCRIPT" "$BLENDER_BIN"
