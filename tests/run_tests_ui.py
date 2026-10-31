"""Suite runner for a real window, where Blender's undo stack exists.

``tests/run_tests.py`` runs headless and cannot exercise undo: in ``--background`` mode
``bpy.ops.ed.undo.poll()`` is False even with a context override. This runner starts a real UI
under Xvfb, enables the add-on, and discovers/runs the same modules from a timer callback (the
event loop has to run once before the undo stack is usable)::

    ./tests/run_ui.sh

That wrapper starts a private X server and strips the Wayland session variables; a bare
``xvfb-run blender`` still opens a window on a Wayland desktop. The undo tests in
``test_custom_node.py`` skip in the headless run and run here. Exit code is 0 when every test
passes. Background-style runs stay the reference invocation; this one exists for the FR-15 undo
verification (T-7b).
"""

import os
import sys
import traceback
import unittest

import addon_utils
import bpy

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_DIR = os.path.join(REPO_DIR, "tests")
PACKAGE_NAME = os.path.basename(REPO_DIR)


def bail(code):
    """Flush and leave at once, so a failure never leaves an idle window behind."""
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


def watchdog():
    print("run_tests_ui: watchdog expired, aborting", flush=True)
    bail(2)


sys.path.insert(0, os.path.dirname(REPO_DIR))
try:
    addon_utils.enable(PACKAGE_NAME, default_set=True)
except Exception:
    traceback.print_exc()
    bail(1)

UI_WATCHDOG = float(os.environ.get("UI_WATCHDOG", "240"))
bpy.app.timers.register(watchdog, first_interval=UI_WATCHDOG)


def run_suite():
    try:
        suite = unittest.defaultTestLoader.discover(TESTS_DIR, pattern="test_*.py",
                                                    top_level_dir=TESTS_DIR)
        window = getattr(bpy.context, "window", None)
        area = None
        if window is not None and window.screen is not None:
            # The quick-setup and layer operators behave like the 3D-view menu entries; in a real UI
            # the first screen area is the sidebar, which is not the context they expect.
            areas = list(window.screen.areas)
            area = next((item for item in areas if item.type == 'VIEW_3D'),
                        areas[0] if areas else None)
        if window is not None and area is not None:
            override = bpy.context.temp_override(
                window=window, screen=window.screen, area=area
            )
        else:
            override = None

        if override is None:
            result = unittest.TextTestRunner(verbosity=2).run(suite)
        else:
            with override:
                result = unittest.TextTestRunner(verbosity=2).run(suite)
    except Exception:
        traceback.print_exc()
        bail(1)

    bail(0 if result.wasSuccessful() else 1)


# The first tick runs the event loop, which is what initializes the undo stack.
bpy.app.timers.register(run_suite, first_interval=0.5)
