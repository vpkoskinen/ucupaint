"""Headless unittest runner for the test modules in this directory.

Run it with Blender's Python (see ``tests/README.md``)::

    blender --background --factory-startup --python tests/run_tests.py

The repository directory is the add-on package, so its parent goes on
``sys.path`` and the package is enabled through ``addon_utils`` (that is what
creates the ``AddonPreferences`` entry the add-on expects).  Blender's
background mode has no *current* area, and some operators used by the tests
read ``bpy.context.area``; the whole suite therefore runs inside a
``temp_override`` pointing at the background window's first screen area.

Exit code is 0 when every test passes, 1 otherwise.
"""

import os
import sys
import unittest

import addon_utils
import bpy

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_DIR = os.path.join(REPO_DIR, "tests")
PACKAGE_NAME = os.path.basename(REPO_DIR)

sys.path.insert(0, os.path.dirname(REPO_DIR))

addon_utils.enable(PACKAGE_NAME, default_set=True)

suite = unittest.defaultTestLoader.discover(TESTS_DIR, pattern="test_*.py",
                                            top_level_dir=TESTS_DIR)

window = getattr(bpy.context, "window", None)
if window is not None and window.screen is not None and window.screen.areas:
    override = bpy.context.temp_override(
        window=window, screen=window.screen, area=window.screen.areas[0]
    )
else:  # Very old background builds have no window at all.
    override = None

if override is None:
    result = unittest.TextTestRunner(verbosity=2).run(suite)
else:
    with override:
        result = unittest.TextTestRunner(verbosity=2).run(suite)

sys.stdout.flush()
sys.stderr.flush()
# ``sys.exit`` only raises SystemExit, which Blender swallows in --python; a
# hard exit is what gives the shell a meaningful status.
os._exit(0 if result.wasSuccessful() else 1)
