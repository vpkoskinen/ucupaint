"""T-11 acceptance run, undo half of checklist line 13 (save/reopen + undo after group switch).

Blender has no undo stack in ``--background``, so this must run in a real window::

    ./tests/run_ui.sh docs/specs/001-custom-node-layer/acceptance_5_2_3_undo.py

It performs a group switch through ``wm.y_replace_layer_type`` (an UNDO operator), records the
post-operation state as one undo step, presses ``bpy.ops.ed.undo()`` and asserts the previous
group and a connected yp chain are back.  Interactive Ctrl+Z is the one remaining human step.
"""

import importlib
import os
import sys
import traceback

import addon_utils
import bpy

REPO_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
PACKAGE_NAME = os.path.basename(REPO_DIR)


def bail(code):
    """Flush and leave at once, so a failure never leaves an idle window behind."""
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


def watchdog():
    print('ACCEPT L13b undo after group switch FAIL watchdog expired', flush=True)
    bail(2)


sys.path.insert(0, os.path.dirname(REPO_DIR))
try:
    addon_utils.enable(PACKAGE_NAME, default_set=True)

    common = importlib.import_module(PACKAGE_NAME + '.common')
    node_connections = importlib.import_module(PACKAGE_NAME + '.node_connections')
except Exception:
    traceback.print_exc()
    bail(1)

UI_WATCHDOG = float(os.environ.get('UI_WATCHDOG', '240'))
bpy.app.timers.register(watchdog, first_interval=UI_WATCHDOG)

CUBE_VERTS = [
    (-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
    (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1),
]
CUBE_FACES = [
    (0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1),
    (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0),
]


def make_group(name, outputs):
    group = bpy.data.node_groups.new(name, 'ShaderNodeTree')
    for socket_name, socket_type in outputs:
        group.interface.new_socket(name=socket_name, in_out='OUTPUT', socket_type=socket_type)
    output = group.nodes.new('NodeGroupOutput')
    rgb = group.nodes.new('ShaderNodeRGB')
    rgb.outputs[0].default_value = (1.0, 0.0, 0.0, 1.0)
    group.links.new(rgb.outputs[0], output.inputs[outputs[0][0]])
    return group


def yp_of(mat):
    for node in mat.node_tree.nodes:
        if node.type == 'GROUP' and node.node_tree and node.node_tree.yp.is_ypaint_node:
            return node.node_tree.yp
    return None


def run():
    result = 'FAIL'
    evidence = ''
    try:
        mesh = bpy.data.meshes.new('AccUndoMesh')
        mesh.from_pydata(CUBE_VERTS, [], CUBE_FACES)
        mesh.uv_layers.new(name='UVMap')
        mesh.update()
        obj = bpy.data.objects.new('AccUndoObject', mesh)
        bpy.context.scene.collection.objects.link(obj)
        mat = bpy.data.materials.new('AccUndoMaterial')
        obj.data.materials.append(mat)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        cube = bpy.data.objects.get('Cube')
        if cube: cube.hide_render = True

        bpy.ops.wm.y_quick_ypaint_node_setup(type='BSDF_PRINCIPLED')
        make_group('AccUndoA', [('Color', 'NodeSocketColor'),
                                ('Roughness', 'NodeSocketFloat')])
        make_group('AccUndoB', [('BaseColor', 'NodeSocketColor'),
                                ('Roughness', 'NodeSocketFloat')])
        bpy.ops.wm.y_new_layer(name='UndoLayer', type='CUSTOM', group_name='AccUndoA',
                               uv_map='UVMap')
        yp = yp_of(mat)
        layer = yp.layers['UndoLayer']
        rough_index = [root_ch.name for root_ch in yp.channels].index('Roughness')
        layer.channels[rough_index].enable = True

        # Undo baseline; `undo_push` also initializes the stack for a timer-driven run.
        assert bpy.ops.ed.undo_push(message='acceptance baseline') == {'FINISHED'}

        assert {'UNDO'} <= set(bpy.ops.wm.y_replace_layer_type.bl_options)
        assert bpy.ops.wm.y_replace_layer_type(
            type='CUSTOM', group_name='AccUndoB', layer_name='UndoLayer') == {'FINISHED'}
        # Record the post-operation state as the step to undo (a scripted operator returns before
        # Blender commits its own push; see tests/test_custom_node.py's commit_undo_step).
        assert bpy.ops.ed.undo_push(message='acceptance step') == {'FINISHED'}

        assert bpy.ops.ed.undo() == {'FINISHED'}

        mat = bpy.data.materials.get('AccUndoMaterial')
        yp = yp_of(mat)
        layer = yp.layers['UndoLayer']
        assert layer.custom_group is not None
        assert layer.custom_group.name == 'AccUndoA', layer.custom_group.name
        assert layer.channels[0].socket_input_name == 'Color', layer.channels[0].socket_input_name

        node = yp.id_data.nodes.get(layer.group_node)
        assert node is not None, 'the layer group node is missing after undo'
        checked = []
        for i, ch in enumerate(layer.channels):
            if i >= len(yp.channels) or not ch.enable: continue
            name = yp.channels[i].name
            inp = node.inputs.get(name)
            assert inp is not None and inp.links, \
                'channel %r is not connected after undo' % name
            checked.append(name)
        assert checked, 'no enabled channel was checked'
        assert len([link for link in yp.id_data.links
                    if link.from_node == node or link.to_node == node]) > 0

        result = 'PASS'
        evidence = 'group=%r binding=%r connected=%r' % (
            layer.custom_group.name, layer.channels[0].socket_input_name, checked)
    except Exception:
        evidence = traceback.format_exc().strip().replace('\n', ' | ')

    line = 'ACCEPT L13b undo after group switch %s %s' % (result, evidence)
    print(line, flush=True)
    with open('/tmp/opencode/t11_acceptance_undo.txt', 'w') as handle:
        handle.write(line + '\n')
    os._exit(0 if result == 'PASS' else 1)


def start():
    try:
        window = getattr(bpy.context, 'window', None)
        area = None
        if window is not None and window.screen is not None:
            areas = list(window.screen.areas)
            area = next((item for item in areas if item.type == 'VIEW_3D'),
                        areas[0] if areas else None)
        if window is not None and area is not None:
            with bpy.context.temp_override(window=window, screen=window.screen, area=area):
                run()
        else:
            run()
    except Exception:
        traceback.print_exc()
        bail(1)


# The first tick runs the event loop, which initializes the undo stack.
bpy.app.timers.register(start, first_interval=0.5)
