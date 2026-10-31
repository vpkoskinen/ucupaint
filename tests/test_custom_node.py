"""Tests for the ``CUSTOM`` layer type (spec 001, FR-4, FR-5, FR-9, FR-30).

The tests build their own object, material and ucupaint node so they do not depend on what
``test_quicksetup.py`` leaves behind, and remove every datablock they create. They assume the
factory startup scene only for the camera and light used by the render assertion.

Run with the suite command from ``tests/README.md``::

    blender --background --factory-startup --python tests/run_tests.py
"""

import contextlib
import importlib
import io
import os
import tempfile
import unittest

import bpy

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE_NAME = os.path.basename(REPO_DIR)

bake_common = importlib.import_module(PACKAGE_NAME + '.bake_common')
common = importlib.import_module(PACKAGE_NAME + '.common')
custom_node_common = importlib.import_module(PACKAGE_NAME + '.custom_node_common')
mask_common = importlib.import_module(PACKAGE_NAME + '.mask_common')
input_outputs = importlib.import_module(PACKAGE_NAME + '.input_outputs')
layer_common = importlib.import_module(PACKAGE_NAME + '.layer_common')
Layer = importlib.import_module(PACKAGE_NAME + '.Layer')
node_connections = importlib.import_module(PACKAGE_NAME + '.node_connections')
ui = importlib.import_module(PACKAGE_NAME + '.ui')

ORIGINAL_ACTIVE_OBJECT = bpy.data.objects.get('Cube')

# Cube geometry for the scratch object, so it sits inside the startup camera's framing.
CUBE_VERTS = [
    (-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
    (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1),
]
CUBE_FACES = [
    (0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1),
    (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0),
]


class FakeOperator:
    """Receives the properties a menu sets on the operator it created."""

    def __init__(self, idname, kwargs):
        self.idname = idname
        self.text = kwargs.get('text', '')
        self.icon = kwargs.get('icon', '')
        self.socket_name = None
        self.enabled = True
        self.layer_name = None


class FakeLayout:
    """Collects what a menu draw would emit, so a menu can be driven without a UI."""

    def __init__(self):
        self.operators = []
        self.labels = []
        self.menus = []
        # `layout.row(...)` returns the layout itself (as in Blender, where a row is a layout), and
        # `row.enabled = False` cascades to its widgets: record it so a test can assert the state.
        self.enabled = True

    def column(self, **kwargs): return self
    def row(self, **kwargs): return self

    def label(self, text='', icon='', **kwargs):
        self.labels.append((text, icon))

    def separator(self): pass

    def context_pointer_set(self, name='', ptr=None):
        # Menus need it to carry a layer into their context; the fake layout only records it.
        self.pointers = getattr(self, 'pointers', {})
        self.pointers[name] = ptr

    def menu(self, idname, text='', icon='', **kwargs):
        self.menus.append((idname, text))

    def operator(self, idname, text='', icon='', **kwargs):
        op = FakeOperator(idname, dict(kwargs, text=text, icon=icon))
        op.enabled = getattr(self, 'enabled', True)
        self.operators.append(op)
        return op


class CustomNodeTestBase(unittest.TestCase):
    """Builds a scratch object, material and ucupaint node, and removes them afterwards."""

    def setUp(self):
        self.groups_before = set(bpy.data.node_groups.keys())
        self.images_before = set(bpy.data.images.keys())

        mesh = bpy.data.meshes.new('CustomNodeTestMesh')
        mesh.from_pydata(CUBE_VERTS, [], CUBE_FACES)
        mesh.uv_layers.new(name='UVMap')
        mesh.update()

        self.obj = bpy.data.objects.new('CustomNodeTestObject', mesh)
        bpy.context.scene.collection.objects.link(self.obj)

        self.mat = bpy.data.materials.new('CustomNodeTestMaterial')
        self.mat_name = self.mat.name
        self.obj.data.materials.append(self.mat)

        bpy.context.view_layer.objects.active = self.obj
        self.obj.select_set(True)

        # The startup Cube sits exactly where this object does; keep it out of renders.
        self.scene_cube = bpy.data.objects.get('Cube')
        self.scene_cube_hide_render = self.scene_cube.hide_render if self.scene_cube else False
        if self.scene_cube: self.scene_cube.hide_render = True

        bpy.ops.wm.y_quick_ypaint_node_setup(type='BSDF_PRINCIPLED')

    def tearDown(self):
        # Undo (in the UI-mode suite) reloads datablocks, so every Python reference captured in
        # setUp can be stale here. Resolve by name; ORIGINAL_ACTIVE_OBJECT is only a fallback for
        # a scene without a Cube.
        cube = bpy.data.objects.get('Cube') or ORIGINAL_ACTIVE_OBJECT
        bpy.context.view_layer.objects.active = cube
        if cube: cube.hide_render = self.scene_cube_hide_render

        obj = bpy.data.objects.get('CustomNodeTestObject')
        if obj:
            mesh = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if mesh.users == 0: bpy.data.meshes.remove(mesh)
        mat = bpy.data.materials.get(self.mat_name)
        if mat: bpy.data.materials.remove(mat)

        for name in list(bpy.data.node_groups.keys()):
            if name not in self.groups_before:
                bpy.data.node_groups.remove(bpy.data.node_groups[name])

        for name in list(bpy.data.images.keys()):
            if name not in self.images_before and bpy.data.images[name].users == 0:
                bpy.data.images.remove(bpy.data.images[name])

    # -- helpers ---------------------------------------------------------------------------

    def make_group(self, name, outputs, inputs=()):
        group = bpy.data.node_groups.new(name, 'ShaderNodeTree')
        for socket_name, socket_type in inputs:
            group.interface.new_socket(name=socket_name, in_out='INPUT', socket_type=socket_type)
        for socket_name, socket_type in outputs:
            group.interface.new_socket(name=socket_name, in_out='OUTPUT', socket_type=socket_type)
        return group

    def get_yp(self):
        for node in self.mat.node_tree.nodes:
            if node.type == 'GROUP' and node.node_tree and node.node_tree.yp.is_ypaint_node:
                return node.node_tree.yp
        return None

    def get_active_layer(self):
        yp = self.get_yp()
        return yp.layers[yp.active_layer_index]

    def new_custom_layer(self, group_name, name='Custom'):
        bpy.ops.wm.y_new_layer(name=name, type='CUSTOM', group_name=group_name, uv_map='UVMap')
        return self.get_active_layer()

    def get_layer_source(self, layer):
        source_tree = common.get_source_tree(layer)
        return source_tree.nodes.get(layer.source)

    def get_layer_tree(self, layer):
        return common.get_tree(layer)

    def get_yp_layer_node(self, layer):
        """The Group node representing this layer inside the yp tree."""
        return layer.id_data.nodes.get(layer.group_node)

    def assert_yp_layer_wired(self, layer):
        """Every enabled channel's layer node is spliced into the yp channel chain.

        This asserts the yp graph itself — the links the render reads — not only the layer tree
        or the absence of a warning. A usability fix that forgets `reconnect_yp_nodes` leaves this
        false even though the layer tree and bindings look healthy.
        """
        yp = layer.id_data.yp
        node = self.get_yp_layer_node(layer)
        self.assertIsNotNone(node, 'the layer group node is missing from the yp tree')
        checked = 0
        for i, ch in enumerate(layer.channels):
            if i >= len(yp.channels): break
            if not ch.enable: continue
            name = yp.channels[i].name
            inp = node.inputs.get(name)
            outp = node.outputs.get(name)
            self.assertIsNotNone(inp, 'yp channel %r has no layer input' % name)
            self.assertIsNotNone(outp, 'yp channel %r has no layer output' % name)
            self.assertTrue(inp.links,
                            'yp channel %r input receives no below-layers stream' % name)
            self.assertTrue(outp.links,
                            'yp channel %r output feeds nothing above' % name)
            checked += 1
        self.assertGreater(checked, 0, 'no enabled channel was checked')
        return node

    def assert_yp_layer_bypassed(self, layer):
        """The layer node touches no link in the yp tree, like a disabled layer."""
        node = self.get_yp_layer_node(layer)
        self.assertIsNotNone(node)
        touching = [link for link in layer.id_data.links
                    if link.from_node == node or link.to_node == node]
        self.assertEqual(touching, [],
                         'the layer is still spliced into the yp tree: %r'
                         % [(link.from_socket.name, link.to_socket.name) for link in touching])
        return node

    def assert_enabled_channels_wired(self, layer):
        """Every enabled channel is bound to an output that actually feeds the layer tree."""
        source = self.get_layer_source(layer)
        tree = self.get_layer_tree(layer)
        for ch in layer.channels:
            if not ch.enable: continue
            self.assertTrue(ch.socket_input_name,
                            'an enabled channel has no bound output name')
            socket = source.outputs.get(ch.socket_input_name)
            self.assertIsNotNone(socket, 'bound output %r is missing on the source node'
                                 % ch.socket_input_name)
            self.assertTrue([link for link in tree.links if link.from_socket == socket],
                            'bound output %r feeds nothing in the layer tree'
                            % ch.socket_input_name)

    def assert_operator_error(self, operator, expected_text, **kwargs):
        """Run `operator` and assert it reports an error.

        `bpy.ops` turns an `ERROR` report into a `RuntimeError`, which is the only way to read a
        report message back from Python (and it is the same path a user sees in the status bar).
        """
        with self.assertRaises(RuntimeError) as raised:
            operator(**kwargs)
        message = str(raised.exception)
        self.assertIn(expected_text, message)
        return message

    def choose_channel_binding(self, layer, ch, socket_name):
        """Drive the real channel-source operator, the code path the menu entries invoke."""
        class FakeContext:
            pass

        context = FakeContext()
        context.channel = ch
        context.layer = layer

        operator = type('FakeOperator', (), {
            'socket_name': socket_name,
            'set_normal_input': False,
        })()
        return Layer.YSetLayerChannelInput.execute(operator, context)

    def get_yp_for(self, mat):
        for node in mat.node_tree.nodes:
            if node.type == 'GROUP' and node.node_tree and node.node_tree.yp.is_ypaint_node:
                return node.node_tree.yp
        return None

    def add_second_material_yp(self, name='CustomNodeTestMaterial2'):
        mat = bpy.data.materials.new(name)
        self.obj.data.materials.append(mat)
        self.addCleanup(bpy.data.materials.remove, mat)
        self.obj.active_material = mat
        bpy.ops.wm.y_quick_ypaint_node_setup(type='BSDF_PRINCIPLED')
        return mat

    def copy_active_layer(self):
        """Drive the real copy operator body; its poll needs a UI context the tests do not have."""
        operator = type('FakeOperator', (), {
            'all_layers': False,
            'report': lambda *args, **kwargs: None,
        })()
        return Layer.YCopyLayer.execute(operator, bpy.context)

    def paste_layer(self):
        operator = type('FakeOperator', (), {
            'packed_duplicate': True,
            'paste_blank': False,
            'ondisk_duplicate': False,
            'set_new_decal_position': False,
            'rebake_bakeds': False,
            'any_baked': False,
            'report': lambda *args, **kwargs: None,
        })()
        return Layer.YPasteLayer.execute(operator, bpy.context)

    def custom_layers(self, yp):
        return [layer for layer in yp.layers if layer.type == 'CUSTOM']

    def custom_layer_snapshot(self, layer):
        """Everything an undo of a group change must restore, not just the pointer."""
        return (layer.custom_group.name if layer.custom_group else None,
                tuple((ch.socket_input_name, ch.enable, ch.custom_fallback_binding)
                      for ch in layer.channels),
                snapshot_tree(self.get_layer_tree(layer)),
                snapshot_tree(layer.id_data))

    def reloaded_yp(self):
        """The yp after an undo/redo: Blender re-created its datablocks, so re-resolve by name."""
        mat = bpy.data.materials.get(self.mat_name)
        self.assertIsNotNone(mat, 'the test material did not survive undo')
        yp = self.get_yp_for(mat)
        self.assertIsNotNone(yp, 'the ucupaint node did not survive undo')
        return yp

    def undo_baseline(self):
        # Undo rewinds the whole file, and a headless run has no event-loop-owned undo context;
        # driving it there corrupts the shared scene for the rest of the suite. Only the UI runner
        # (`tests/run_tests_ui.py`) exercises these tests.
        if bpy.app.background:
            self.skipTest('undo needs a real window; run tests/run_tests_ui.py')
        # `undo_push` is also what initializes the undo stack for a scripted/timer run; polling
        # before the first push is False even in a real window.
        try:
            result = bpy.ops.ed.undo_push(message='test baseline')
        except RuntimeError:
            self.skipTest('undo needs a real window; run tests/run_tests_ui.py')
        if result != {'FINISHED'}:
            self.skipTest('undo needs a real window; run tests/run_tests_ui.py')

    def commit_undo_step(self):
        """Record the operation as one step.

        An operator called from a script or timer returns before Blender commits its own undo
        push, so `ed.undo()` right after it would skip to the previous step. Each operation below
        asserts its operator is `UNDO`-flagged and records that post-operation state as the step
        the tests undo. This is real Blender undo data, not a re-run of the operator (see the T-7b
        commit body for the limitation).
        """
        self.assertEqual(bpy.ops.ed.undo_push(message='test step'), {'FINISHED'})

    def undo_once(self):
        self.assertEqual(bpy.ops.ed.undo(), {'FINISHED'})
        return self.reloaded_yp()

    def redo_once(self):
        self.assertEqual(bpy.ops.ed.redo(), {'FINISHED'})
        return self.reloaded_yp()

    def count_sync_calls(self):
        """Count calls into the T-6b handler's sync entry point until the test ends."""
        calls = {'n': 0}
        original = custom_node_common.sync_custom_layers

        def counted(*args, **kwargs):
            calls['n'] += 1
            return original(*args, **kwargs)

        custom_node_common.sync_custom_layers = counted
        self.addCleanup(setattr, custom_node_common, 'sync_custom_layers', original)
        return calls

    def count_reconnect_calls(self):
        """Count yp-level re-splices (`reconnect_yp_nodes`), the FR-16 repair the handler triggers."""
        calls = {'n': 0}
        original = node_connections.reconnect_yp_nodes

        def counted(*args, **kwargs):
            calls['n'] += 1
            return original(*args, **kwargs)

        node_connections.reconnect_yp_nodes = counted
        self.addCleanup(setattr, node_connections, 'reconnect_yp_nodes', original)
        return calls

    def render_to(self, filename):
        scene = bpy.context.scene
        path = os.path.join(tempfile.gettempdir(), filename)
        scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
        return bpy.data.images.load(path, check_existing=False)

    def center_pixel(self, image):
        width, height = image.size
        index = ((height // 2) * width + (width // 2)) * 4
        return list(image.pixels[index:index + 4])

    def render_center_pixel(self, filename):
        """Render the current scene at test settings and return the centre pixel, then clean up."""
        image = self.render_to(filename)
        try:
            return self.center_pixel(image)
        finally:
            bpy.data.images.remove(image)

    def render_settings(self):
        """Context manager-ish helper: set small render settings, return a restore callable."""
        scene = bpy.context.scene
        old = (scene.render.engine, scene.cycles.samples if hasattr(scene, 'cycles') else None,
               scene.render.resolution_x, scene.render.resolution_y,
               scene.render.resolution_percentage, scene.render.filepath,
               scene.render.image_settings.file_format)

        def restore():
            scene.render.engine = old[0]
            if old[1] is not None: scene.cycles.samples = old[1]
            scene.render.resolution_x, scene.render.resolution_y = old[2], old[3]
            scene.render.resolution_percentage = old[4]
            scene.render.filepath = old[5]
            scene.render.image_settings.file_format = old[6]

        scene.render.engine = 'CYCLES'
        scene.cycles.device = 'CPU'
        scene.cycles.samples = 8
        scene.render.resolution_x = 32
        scene.render.resolution_y = 32
        scene.render.resolution_percentage = 100
        scene.render.image_settings.file_format = 'PNG'
        return restore

    def reachable_mix_factor_sources(self, tree, from_socket):
        """Nodes upstream of any MIX node's Factor input that are fed by ``from_socket``."""
        reached = set()
        found = set()
        frontier = [from_socket]
        while frontier:
            socket = frontier.pop()
            for link in tree.links:
                if link.from_socket != socket: continue
                node = link.to_node
                if node.type == 'MIX' and link.to_socket.name == 'Factor':
                    found.add(socket)
                if node in reached: continue
                reached.add(node)
                for outp in node.outputs:
                    frontier.append(outp)
        return found


class TestCustomSocketFilter(CustomNodeTestBase):
    """FR-4: only value-typed group outputs are offered as channel sources."""

    @staticmethod
    def interface_supports_socket_type(socket_type):
        """Whether this Blender's node-tree interface can create ``socket_type``.

        ``NodeSocketMenu`` is a registered socket type on every version but only became a valid
        ``NodeTreeInterface.new_socket`` argument in 5.0; on 4.x the enum rejects it. Probe rather
        than compare versions, so the test keeps its extra socket wherever it exists.
        """
        probe = bpy.data.node_groups.new('__socket_type_probe__', 'ShaderNodeTree')
        try:
            probe.interface.new_socket(name='Probe', in_out='OUTPUT', socket_type=socket_type)
            return True
        except TypeError:
            return False
        finally:
            bpy.data.node_groups.remove(probe)

    def test_01_available_outputs_skip_shader_and_other_types(self):
        outputs = [
            ('Color', 'NodeSocketColor'),
            ('Rough', 'NodeSocketFloat'),
            ('Shader', 'NodeSocketShader'),
            ('Switch', 'NodeSocketBool'),
        ]
        # Pre-5.0 has no menu interface socket to filter out; the other non-value types still are.
        if self.interface_supports_socket_type('NodeSocketMenu'):
            outputs.append(('Mode', 'NodeSocketMenu'))
        self.make_group('FilterGroup', outputs)
        layer = self.new_custom_layer('FilterGroup')
        source = self.get_layer_source(layer)

        names = [outp.name for outp in common.get_available_source_outputs(source, layer.type)]
        self.assertEqual(names, ['Color', 'Rough'])

        # The same filter is what the candidate picker uses; the shader socket never qualifies.
        group = bpy.data.node_groups['FilterGroup']
        self.assertEqual([outp.name for outp in custom_node_common.get_custom_compatible_outputs(group)],
                         ['Color', 'Rough'])

    def test_02_int_vector_and_float_factor_types_are_compatible(self):
        self.make_group('TypeGroup',
            outputs=[
                ('Int', 'NodeSocketInt'),
                ('Vec', 'NodeSocketVector'),
            ],
            inputs=[
                ('Int In', 'NodeSocketInt'),
                ('Vec In', 'NodeSocketVector'),
            ])
        layer = self.new_custom_layer('TypeGroup')
        source = self.get_layer_source(layer)

        names = [outp.name for outp in common.get_available_source_outputs(source, layer.type)]
        self.assertEqual(names, ['Int', 'Vec'])

        # Inputs are filtered by the same type rule (T-5's input wiring relies on it).
        group = bpy.data.node_groups['TypeGroup']
        input_sockets = [item for item in group.interface.items_tree
                         if item.item_type == 'SOCKET' and item.in_out == 'INPUT']
        self.assertTrue(all(custom_node_common.is_custom_socket_compatible(item)
                            for item in input_sockets))

        # NodeSocketFloatFactor cannot be created on a 5.x group interface any more, so the
        # whitelist entry is checked against a socket-like stand-in with the same socket_type.
        class StubSocket:
            socket_type = 'NodeSocketFloatFactor'
        class StubShaderSocket:
            socket_type = 'NodeSocketShader'

        self.assertTrue(custom_node_common.is_custom_socket_compatible(StubSocket()))
        self.assertFalse(custom_node_common.is_custom_socket_compatible(StubShaderSocket()))
        self.assertFalse(custom_node_common.is_custom_socket_compatible(None))


class TestCustomAlpha(CustomNodeTestBase):
    """FR-5: an output named Alpha supplies alpha; otherwise alpha is the one-value node."""

    def test_01_alpha_output_feeds_channel_alpha(self):
        self.make_group('AlphaGroup', [
            ('Color', 'NodeSocketColor'),
            ('Alpha', 'NodeSocketFloat'),
        ])
        layer = self.new_custom_layer('AlphaGroup')
        source = self.get_layer_source(layer)
        tree = self.get_layer_tree(layer)

        alpha_socket = source.outputs.get('Alpha')
        self.assertIsNotNone(alpha_socket)

        links = [link for link in tree.links if link.from_socket == alpha_socket]
        self.assertTrue(links, 'no link leaves the source Alpha socket')
        self.assertTrue(self.reachable_mix_factor_sources(tree, alpha_socket),
                        'the Alpha socket does not reach the blend factor')

    def test_02_missing_alpha_output_uses_one_value_node(self):
        self.make_group('NoAlphaGroup', [
            ('Color', 'NodeSocketColor'),
            ('Rough', 'NodeSocketFloat'),
        ])
        layer = self.new_custom_layer('NoAlphaGroup')
        source = self.get_layer_source(layer)
        tree = self.get_layer_tree(layer)

        self.assertIsNone(source.outputs.get('Alpha'))

        one_value_socket = node_connections.get_essential_node(tree, common.ONE_VALUE)[0]
        self.assertTrue(self.reachable_mix_factor_sources(tree, one_value_socket),
                        'no path from the one-value node to the blend factor')


class TestCustomDefaultBinding(CustomNodeTestBase):
    """FR-9: same-named output first, else the first compatible output in socket order."""

    def test_01_same_named_output_wins_over_socket_order(self):
        # Roughness is first in socket order, so a same-name match is a real decision.
        self.make_group('BindingGroup', [
            ('Roughness', 'NodeSocketFloat'),
            ('Color', 'NodeSocketColor'),
        ])
        layer = self.new_custom_layer('BindingGroup')
        yp = self.get_yp()

        by_name = {root_ch.name: layer.channels[i].socket_input_name
                   for i, root_ch in enumerate(yp.channels)}

        self.assertEqual(by_name['Color'], 'Color')
        self.assertEqual(by_name['Roughness'], 'Roughness')

    def test_02_channel_without_match_binds_first_compatible_output(self):
        self.make_group('BindingGroup', [
            ('Roughness', 'NodeSocketFloat'),
            ('Color', 'NodeSocketColor'),
        ])
        layer = self.new_custom_layer('BindingGroup')
        yp = self.get_yp()

        metallic_idx = [root_ch.name for root_ch in yp.channels].index('Metallic')
        self.assertEqual(layer.channels[metallic_idx].socket_input_name, 'Roughness')

    def test_03_root_channel_added_later_binds_without_touching_others(self):
        self.make_group('LaterGroup', [
            ('Roughness', 'NodeSocketFloat'),
            ('Color', 'NodeSocketColor'),
        ])
        layer = self.new_custom_layer('LaterGroup')
        yp = self.get_yp()

        before = [ch.socket_input_name for ch in layer.channels]

        bpy.ops.wm.y_add_new_ypaint_channel(name='Extra', type='VALUE')

        self.assertEqual(len(layer.channels), len(before) + 1)
        self.assertEqual([ch.socket_input_name for ch in layer.channels[:len(before)]], before)

        extra_idx = len(before)
        self.assertEqual(yp.channels[extra_idx].name, 'Extra')
        self.assertEqual(layer.channels[extra_idx].socket_input_name, 'Roughness')

    def test_05_replace_layer_type_binds_and_requires_a_group(self):
        self.make_group('ReplaceGroup', [
            ('Roughness', 'NodeSocketFloat'),
            ('Color', 'NodeSocketColor'),
        ])
        bpy.ops.wm.y_new_layer(name='Image', uv_map='UVMap')
        layer = self.get_active_layer()
        yp = self.get_yp()

        # No group: refused, layer untouched.
        self.assertFalse(layer_common.replace_layer_type(layer, 'CUSTOM'))
        self.assertEqual(layer.type, 'IMAGE')

        # With a group: retargeted and bound with the FR-9 defaults.
        self.assertTrue(layer_common.replace_layer_type(layer, 'CUSTOM', group_name='ReplaceGroup'))
        self.assertEqual(layer.type, 'CUSTOM')
        by_name = {root_ch.name: layer.channels[i].socket_input_name
                   for i, root_ch in enumerate(yp.channels)}
        self.assertEqual(by_name['Color'], 'Color')
        self.assertEqual(by_name['Roughness'], 'Roughness')

        # Retargeting away leaves no custom cache entry behind (there is no such property).
        self.assertTrue(layer_common.replace_layer_type(layer, 'IMAGE'))
        self.assertEqual(layer.type, 'IMAGE')
        self.assertFalse(hasattr(layer, 'cache_custom'))

    def test_04_non_custom_layers_keep_their_binding(self):
        # A group whose first output is not named Color must not leak into other layer types.
        self.make_group('BindingGroup', [
            ('Roughness', 'NodeSocketFloat'),
            ('Color', 'NodeSocketColor'),
        ])
        bpy.ops.wm.y_new_layer(name='Image', uv_map='UVMap')
        layer = self.get_active_layer()

        self.assertEqual(layer.type, 'IMAGE')
        self.assertTrue(all(ch.socket_input_name == 'Color' for ch in layer.channels))


class TestCustomChannelMenu(CustomNodeTestBase):
    """FR-4: the channel-source menu offers exactly get_available_source_outputs.

    ``NODE_MT_y_layer_channel_input_menu`` cannot be instantiated headlessly (bpy menus are
    created by Blender's draw code), so this drives its real ``draw`` method with a fake layout
    and a context carrying only ``channel`` — the only two things that method reads. The
    collected ``wm.y_set_layer_channel_input`` operators are the menu entries themselves.
    """

    def test_01_menu_entries_match_available_outputs(self):
        self.make_group('MenuGroup', [
            ('Color', 'NodeSocketColor'),
            ('Rough', 'NodeSocketFloat'),
            ('Shader', 'NodeSocketShader'),
        ])
        layer = self.new_custom_layer('MenuGroup')
        source = self.get_layer_source(layer)
        ch = layer.channels[0]

        class FakeContext:
            channel = None

        context = FakeContext()
        context.channel = ch

        layout = FakeLayout()
        menu_self = type('FakeMenu', (), {'layout': layout})()
        ui.YLayerChannelInputMenu.draw(menu_self, context)

        menu_names = [op.socket_name for op in layout.operators
                      if op.idname == 'wm.y_set_layer_channel_input'
                      and op.text.startswith('Layer ')]
        available = [outp.name for outp in common.get_available_source_outputs(source, layer.type)]

        self.assertEqual(menu_names, ['Color', 'Rough'])
        self.assertEqual(menu_names, available)


class TestCustomBlendOverBelow(CustomNodeTestBase):
    """FR-30: a custom layer blends over what is below, in the graph and in a render."""

    def test_01_graph_and_render(self):
        # Below layer: solid green.
        bpy.ops.wm.y_new_layer(name='Green', type='COLOR', solid_color=(0.0, 1.0, 0.0), uv_map='UVMap')

        # Hand-built group: red Color, Roughness 0.5.
        group = self.make_group('RenderGroup', [
            ('Color', 'NodeSocketColor'),
            ('Roughness', 'NodeSocketFloat'),
        ])
        rgb = group.nodes.new('ShaderNodeRGB')
        rgb.outputs[0].default_value = (1.0, 0.0, 0.0, 1.0)
        value = group.nodes.new('ShaderNodeValue')
        value.outputs[0].default_value = 0.5
        group_output = group.nodes.new('NodeGroupOutput')
        group.links.new(rgb.outputs[0], group_output.inputs['Color'])
        group.links.new(value.outputs[0], group_output.inputs['Roughness'])

        layer = self.new_custom_layer('RenderGroup')
        layer.channels[0].enable = True
        source = self.get_layer_source(layer)
        tree = self.get_layer_tree(layer)
        color_ch = layer.channels[0]

        # Graph: the blend's B input is the custom source, its A input is what is below.
        blend = tree.nodes.get(color_ch.blend)
        self.assertIsNotNone(blend)
        b_links = [link for link in blend.inputs['B'].links]
        a_links = [link for link in blend.inputs['A'].links]
        self.assertTrue(b_links and b_links[0].from_node == source)
        self.assertEqual(b_links[0].from_socket.name, 'Color')
        self.assertTrue(a_links and a_links[0].from_node.type == 'GROUP_INPUT')

        # Render: the custom layer wins over the green layer below, and turning it off
        # brings the green layer back. Checked by comparing the rendered centre pixel.
        scene = bpy.context.scene
        old_engine = scene.render.engine
        old_samples = scene.cycles.samples if hasattr(scene, 'cycles') else None
        old_x, old_y = scene.render.resolution_x, scene.render.resolution_y
        old_percentage = scene.render.resolution_percentage
        old_filepath = scene.render.filepath
        old_format = scene.render.image_settings.file_format

        try:
            scene.render.engine = 'CYCLES'
            scene.cycles.device = 'CPU'
            scene.cycles.samples = 8
            scene.render.resolution_x = 32
            scene.render.resolution_y = 32
            scene.render.resolution_percentage = 100
            scene.render.image_settings.file_format = 'PNG'

            on_image = self.render_to('custom_node_on.png')
            on_pixel = self.center_pixel(on_image)
            bpy.data.images.remove(on_image)

            layer.enable = False
            off_image = self.render_to('custom_node_off.png')
            off_pixel = self.center_pixel(off_image)
            bpy.data.images.remove(off_image)

            self.assertGreater(on_pixel[0], on_pixel[1],
                               'custom layer did not render red: %r' % (on_pixel,))
            self.assertGreater(off_pixel[1], off_pixel[0],
                               'below layer did not show after disable: %r' % (off_pixel,))
        finally:
            layer.enable = True
            scene.render.engine = old_engine
            if old_samples is not None: scene.cycles.samples = old_samples
            scene.render.resolution_x, scene.render.resolution_y = old_x, old_y
            scene.render.resolution_percentage = old_percentage
            scene.render.filepath = old_filepath
            scene.render.image_settings.file_format = old_format

class TestCustomInputWiring(CustomNodeTestBase):
    """FR-6: channel-named group inputs receive the below-layers streams."""

    def test_01_channel_and_alpha_inputs_get_start_links(self):
        self.make_group('WiringGroup',
            outputs=[
                ('Color', 'NodeSocketColor'),
                ('Roughness', 'NodeSocketFloat'),
            ],
            inputs=[
                ('Color', 'NodeSocketColor'),
                ('Color Alpha', 'NodeSocketFloat'),
                ('Roughness', 'NodeSocketFloat'),
                ('MyOwnThing', 'NodeSocketFloat'),
            ])
        layer = self.new_custom_layer('WiringGroup')
        yp = self.get_yp()
        tree = self.get_layer_tree(layer)

        # Enable every channel and the colour alpha so `Start` declares all the names the test
        # asserts on; the tree interface is rebuilt by the IO check, then wired by the reconnect.
        for ch in layer.channels:
            ch.enable = True
        yp.channels[[root_ch.name for root_ch in yp.channels].index('Color')].enable_alpha = True
        input_outputs.check_all_layer_channel_io_and_nodes(layer, tree)
        node_connections.reconnect_layer_nodes(layer)

        source = self.get_layer_source(layer)
        start = tree.nodes[common.TREE_START]

        for name in ('Color', 'Color Alpha', 'Roughness'):
            inp = source.inputs.get(name)
            self.assertIsNotNone(inp, 'group input %r disappeared' % name)
            self.assertEqual(len(inp.links), 1, 'group input %r is not wired' % name)
            # The stream must come from the tree's Start group-input socket, not from the source.
            self.assertEqual(inp.links[0].from_node, start)
            self.assertEqual(inp.links[0].from_socket.name, name)

        # An input matching no channel keeps the user's default (no link at all).
        self.assertEqual(len(source.inputs['MyOwnThing'].links), 0)

    def test_02_unmatched_and_vector_inputs_stay_alone(self):
        self.make_group('WiringQuietGroup',
            outputs=[('Color', 'NodeSocketColor')],
            inputs=[
                ('Vector', 'NodeSocketVector'),
                ('MyOwnThing', 'NodeSocketFloat'),
            ])
        layer = self.new_custom_layer('WiringQuietGroup')
        source = self.get_layer_source(layer)

        # `MyOwnThing` matches no channel; `Vector` belongs to the vector path, which wires it to
        # the mapping output, never to a below-layers stream.
        self.assertEqual(len(source.inputs['MyOwnThing'].links), 0)
        vector_links = source.inputs['Vector'].links
        self.assertEqual(len(vector_links), 1)
        self.assertNotEqual(vector_links[0].from_node.type, 'GROUP_INPUT')


class TestCustomVector(CustomNodeTestBase):
    """FR-7 and FR-18: the vector path exists only for a declared `Vector` input."""

    def test_01_group_with_vector_gets_mapping_and_link(self):
        self.make_group('VectorGroup',
            outputs=[('Color', 'NodeSocketColor')],
            inputs=[('Vector', 'NodeSocketVector')])
        layer = self.new_custom_layer('VectorGroup')
        tree = self.get_layer_tree(layer)
        source = self.get_layer_source(layer)

        mapping = tree.nodes.get(layer.mapping)
        self.assertIsNotNone(mapping, 'no mapping node for a group with a Vector input')
        self.assertEqual(mapping.bl_idname, 'ShaderNodeMapping')

        links = source.inputs['Vector'].links
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].from_node, mapping)
        self.assertTrue(common.is_mapping_possible(layer.type, layer))
        self.assertTrue(common.is_layer_using_vector(layer))

    def test_02_group_without_vector_gets_no_vector_nodes(self):
        self.make_group('NoVectorGroup',
            outputs=[('Color', 'NodeSocketColor')],
            inputs=[('Color', 'NodeSocketColor')])
        layer = self.new_custom_layer('NoVectorGroup')
        tree = self.get_layer_tree(layer)
        source = self.get_layer_source(layer)

        self.assertFalse(common.is_mapping_possible(layer.type, layer))
        self.assertFalse(common.is_layer_using_vector(layer))
        self.assertEqual(layer.mapping, '')
        self.assertIsNone(tree.nodes.get('Mapping'))

        self.assertIsNone(source.inputs.get('Vector'))

        node_types = {node.bl_idname for node in tree.nodes}
        for dead in ('ShaderNodeMapping', 'ShaderNodeTexCoord', 'ShaderNodeUVMap'):
            self.assertNotIn(dead, node_types)

    def test_03_removing_and_restoring_the_vector_input(self):
        group = self.make_group('ToggleVectorGroup',
            outputs=[('Color', 'NodeSocketColor')],
            inputs=[('Vector', 'NodeSocketVector')])
        layer = self.new_custom_layer('ToggleVectorGroup')
        tree = self.get_layer_tree(layer)
        source = self.get_layer_source(layer)

        self.assertIsNotNone(tree.nodes.get(layer.mapping))
        self.assertEqual(len(source.inputs['Vector'].links), 1)

        def refresh():
            # The reconnect path a manual sync drives in T-6a: tree IO first, then the wiring.
            input_outputs.check_all_layer_channel_io_and_nodes(layer, tree)
            node_connections.reconnect_layer_nodes(layer)

        vector_item = [item for item in group.interface.items_tree
                       if item.item_type == 'SOCKET' and item.name == 'Vector'][0]
        group.interface.remove(vector_item)
        refresh()

        self.assertEqual(layer.mapping, '')
        self.assertIsNone(tree.nodes.get('Mapping'))
        self.assertIsNone(source.inputs.get('Vector'))
        self.assertEqual([node for node in tree.nodes if node.bl_idname == 'ShaderNodeMapping'], [])

        group.interface.new_socket(name='Vector', in_out='INPUT', socket_type='NodeSocketVector')
        refresh()

        mapping = tree.nodes.get(layer.mapping)
        self.assertIsNotNone(mapping, 'the mapping node did not come back')
        self.assertEqual(len(source.inputs['Vector'].links), 1)
        self.assertEqual(source.inputs['Vector'].links[0].from_node, mapping)
        self.assertEqual(len([node for node in tree.nodes if node.bl_idname == 'ShaderNodeMapping']), 1)


class TestCustomNodeInventory(CustomNodeTestBase):
    """FR-18: a fresh custom layer's tree holds exactly the nodes it needs.

    Frames are arrangement decoration, not graph nodes, so they are excluded from the inventory.
    """

    # Source group, Start/End, the alpha fallback value, one blend factor per enabled channel and
    # the colour blend itself. No mapping, no texcoord: the group declares no `Vector` input.
    MINIMAL_NODE_TYPES = {
        'NodeGroupInput': 1,
        'NodeGroupOutput': 1,
        'ShaderNodeGroup': 1,
        'ShaderNodeValue': 1,
        'ShaderNodeMath': 2,
        'ShaderNodeMix': 1,
    }

    def test_01_fresh_layer_matches_minimal_inventory(self):
        self.make_group('InventoryGroup',
            outputs=[('Color', 'NodeSocketColor')],
            inputs=[('Color', 'NodeSocketColor')])
        layer = self.new_custom_layer('InventoryGroup')
        tree = self.get_layer_tree(layer)

        inventory = {}
        for node in tree.nodes:
            if node.bl_idname == 'NodeFrame': continue
            inventory[node.bl_idname] = inventory.get(node.bl_idname, 0) + 1

        self.assertEqual(inventory, self.MINIMAL_NODE_TYPES)


class TestNonCustomMappingRegression(CustomNodeTestBase):
    """T-5 must not change mapping creation for the existing layer types."""

    def test_01_image_and_noise_still_get_mapping(self):
        bpy.ops.wm.y_new_layer(name='Image', uv_map='UVMap')
        image_layer = self.get_active_layer()
        self.assertEqual(image_layer.type, 'IMAGE')
        self.assertTrue(common.is_mapping_possible(image_layer.type, image_layer))
        self.assertTrue(common.is_layer_using_vector(image_layer))
        self.assertIsNotNone(self.get_layer_tree(image_layer).nodes.get(image_layer.mapping))

        bpy.ops.wm.y_new_layer(name='Noise', type='NOISE', uv_map='UVMap')
        noise_layer = self.get_active_layer()
        self.assertEqual(noise_layer.type, 'NOISE')
        self.assertTrue(common.is_mapping_possible(noise_layer.type, noise_layer))
        self.assertTrue(common.is_layer_using_vector(noise_layer))
        self.assertIsNotNone(self.get_layer_tree(noise_layer).nodes.get(noise_layer.mapping))



def snapshot_tree(tree):
    """Ordered link list and node count of one node tree, for "nothing changed" assertions."""
    if tree is None: return ([], 0)
    links = sorted((link.from_node.name, link.from_socket.name,
                    link.to_node.name, link.to_socket.name) for link in tree.links)
    return (links, len(tree.nodes))


class TestCustomInterfaceSignature(CustomNodeTestBase):
    """FR-12/FR-14: the signature tracks declaration topology only."""

    def signature(self, group):
        return custom_node_common.get_custom_interface_signature(group)

    def output_item(self, group, name):
        return [item for item in group.interface.items_tree
                if item.item_type == 'SOCKET' and item.in_out == 'OUTPUT' and item.name == name][0]

    def test_01_missing_group_has_the_defined_empty_signature(self):
        self.assertEqual(self.signature(None), ())
        empty = bpy.data.node_groups.new('EmptySignatureGroup', 'ShaderNodeTree')
        self.assertEqual(self.signature(empty), ())

    def test_02_signature_shape(self):
        group = self.make_group('ShapeGroup',
            outputs=[('Color', 'NodeSocketColor')],
            inputs=[('Factor', 'NodeSocketFloat')])
        signature = self.signature(group)

        self.assertEqual(len(signature), 2)
        for entry in signature:
            self.assertEqual(len(entry), 4)
            in_out, name, socket_type, enabled = entry
            self.assertIn(in_out, {'INPUT', 'OUTPUT'})
            self.assertIsInstance(socket_type, str)
            self.assertTrue(socket_type.startswith('NodeSocket'))
            self.assertIsInstance(enabled, bool)

    def test_03_add_remove_rename_and_retype_change_it(self):
        group = self.make_group('SignatureGroup', outputs=[('Color', 'NodeSocketColor')])
        base = self.signature(group)
        self.assertTrue(base)

        # Add.
        added = group.interface.new_socket('Extra', in_out='OUTPUT', socket_type='NodeSocketFloat')
        added_signature = self.signature(group)
        self.assertNotEqual(added_signature, base)

        # Remove.
        group.interface.remove(added)
        self.assertEqual(self.signature(group), base)

        # Rename.
        item = self.output_item(group, 'Color')
        item.name = 'Renamed'
        renamed_signature = self.signature(group)
        self.assertNotEqual(renamed_signature, base)
        item.name = 'Color'
        self.assertEqual(self.signature(group), base)

        # Retype.
        item.socket_type = 'NodeSocketVector'
        self.assertNotEqual(self.signature(group), base)

    def test_04_default_value_location_and_mute_do_not_change_it(self):
        group = self.make_group('SignatureStableGroup',
            outputs=[('Color', 'NodeSocketColor')],
            inputs=[('Factor', 'NodeSocketFloat')])
        base = self.signature(group)

        # Editing a socket default is explicitly not a topology change (FR-12).
        self.output_item(group, 'Color').default_value = (1.0, 0.0, 0.0, 1.0)

        # Neither is moving or muting a node inside the group.
        node = group.nodes.new('ShaderNodeValue')
        node.location = (123.0, -456.0)
        node.mute = True

        self.assertEqual(self.signature(group), base)


class TestCustomSyncIdempotency(CustomNodeTestBase):
    """FR-14: a healthy tree is not touched by the sync entry point."""

    def snapshots(self, layer):
        # Layer tree, nested source tree (if any) and the ucupaint root tree.
        return [snapshot_tree(self.get_layer_tree(layer)),
                snapshot_tree(common.get_source_tree(layer)),
                snapshot_tree(layer.id_data)]

    def test_01_running_twice_changes_no_link_and_no_node(self):
        self.make_group('IdempotentGroup',
            outputs=[('Color', 'NodeSocketColor'), ('Roughness', 'NodeSocketFloat')],
            inputs=[('Color', 'NodeSocketColor')])
        layer = self.new_custom_layer('IdempotentGroup')
        yp = self.get_yp()

        before = self.snapshots(layer)
        first = custom_node_common.sync_custom_layers(yp)
        after_first = self.snapshots(layer)
        second = custom_node_common.sync_custom_layers(yp)

        self.assertEqual(first, '')
        self.assertEqual(second, '')
        self.assertEqual(after_first, before)
        self.assertEqual(self.snapshots(layer), before)


class TestCustomSyncOperator(CustomNodeTestBase):
    """FR-14: ``wm.y_custom_sync`` repairs a mis-wired layer and then does nothing."""

    def snapshots(self, layer):
        return [snapshot_tree(self.get_layer_tree(layer)),
                snapshot_tree(common.get_source_tree(layer)),
                snapshot_tree(layer.id_data)]

    def run_operator(self):
        ypup = common.get_user_preferences()
        old = ypup.developer_mode
        ypup.developer_mode = True
        try:
            return bpy.ops.wm.y_custom_sync()
        finally:
            ypup.developer_mode = old

    def test_01_repairs_a_broken_link_then_changes_nothing(self):
        self.make_group('RepairGroup',
            outputs=[('Color', 'NodeSocketColor')],
            inputs=[('Color', 'NodeSocketColor')])
        layer = self.new_custom_layer('RepairGroup')
        layer.channels[0].enable = True
        yp = self.get_yp()

        # Healthy baseline; also primes the signature cache.
        custom_node_common.sync_custom_layers(yp)

        source = self.get_layer_source(layer)
        target = source.inputs['Color']
        self.assertEqual(len(target.links), 1, 'the channel input is not wired before the test')
        tree = self.get_layer_tree(layer)

        # Deliberate mis-wire: one expected link is gone, the signature is unchanged.
        tree.links.remove(target.links[0])
        self.assertEqual(len(target.links), 0)

        self.assertEqual(self.run_operator(), {'FINISHED'})
        self.assertEqual(len(target.links), 1, 'the operator did not repair the broken link')

        repaired = self.snapshots(layer)
        self.assertEqual(self.run_operator(), {'FINISHED'})
        self.assertEqual(self.snapshots(layer), repaired)

    def test_02_reports_nothing_on_a_healthy_tree(self):
        self.make_group('HealthyGroup', outputs=[('Color', 'NodeSocketColor')])
        layer = self.new_custom_layer('HealthyGroup')
        yp = self.get_yp()

        # Health baseline first, then the operator must be a no-op that reports nothing.
        custom_node_common.sync_custom_layers(yp)
        self.assertEqual(custom_node_common.sync_custom_layers(yp), '')
        self.assertEqual(self.run_operator(), {'FINISHED'})

    def test_02_shared_group_resyncs_every_layer(self):
        # Two layers on one group: a rename must re-bind both, not only the first one visited.
        group = self.make_group('SharedGroup',
            outputs=[('Color', 'NodeSocketColor'), ('Roughness', 'NodeSocketFloat')])
        first = self.new_custom_layer('SharedGroup', name='First')
        second = self.new_custom_layer('SharedGroup', name='Second')
        yp = self.get_yp()
        custom_node_common.sync_custom_layers(yp)

        color_index = [root_ch.name for root_ch in yp.channels].index('Color')
        self.assertEqual(first.channels[color_index].socket_input_name, 'Color')
        self.assertEqual(second.channels[color_index].socket_input_name, 'Color')

        color_item = [item for item in group.interface.items_tree
                      if item.item_type == 'SOCKET' and item.name == 'Color'][0]
        color_item.name = 'Colour'
        custom_node_common.sync_custom_layers(yp)

        # FR-10 fallback: the gone binding moves to the first compatible output on every layer.
        self.assertEqual(first.channels[color_index].socket_input_name, 'Colour')
        self.assertEqual(second.channels[color_index].socket_input_name, 'Colour')


def interface_item(group, name, in_out):
    return [item for item in group.interface.items_tree
            if item.item_type == 'SOCKET' and item.in_out == in_out and item.name == name][0]


class TestCustomSyncSharedGroupAcrossMaterials(CustomNodeTestBase):
    """T-6a follow-up: one group referenced by two materials' yps is repaired in both."""

    def add_second_material_yp(self):
        mat = bpy.data.materials.new('CustomNodeTestMaterial2')
        self.obj.data.materials.append(mat)
        self.addCleanup(bpy.data.materials.remove, mat)
        self.obj.active_material = mat
        bpy.ops.wm.y_quick_ypaint_node_setup(type='BSDF_PRINCIPLED')
        return mat

    def get_yp_for(self, mat):
        for node in mat.node_tree.nodes:
            if node.type == 'GROUP' and node.node_tree and node.node_tree.yp.is_ypaint_node:
                return node.node_tree.yp
        return None

    def new_layer_for(self, mat, group_name, name='Custom'):
        self.obj.active_material = mat
        bpy.ops.wm.y_new_layer(name=name, type='CUSTOM', group_name=group_name, uv_map='UVMap')
        yp = self.get_yp_for(mat)
        return yp.layers[yp.active_layer_index]

    def snapshots(self, layer):
        return [snapshot_tree(self.get_layer_tree(layer)),
                snapshot_tree(common.get_source_tree(layer)),
                snapshot_tree(layer.id_data)]

    def test_01_each_material_resyncs_the_shared_group(self):
        group = self.make_group('CrossMaterialGroup',
            outputs=[('Color', 'NodeSocketColor'), ('Roughness', 'NodeSocketFloat')],
            inputs=[('Color', 'NodeSocketColor'), ('Vector', 'NodeSocketVector')])

        mat_a = self.mat
        mat_b = self.add_second_material_yp()
        layer_a = self.new_layer_for(mat_a, 'CrossMaterialGroup', name='A')
        layer_b = self.new_layer_for(mat_b, 'CrossMaterialGroup', name='B')
        yp_a = self.get_yp_for(mat_a)
        yp_b = self.get_yp_for(mat_b)
        self.assertIsNot(yp_a, yp_b)

        # Prime each yp's cache independently: the shared group is now cached per material.
        custom_node_common.sync_custom_layers(yp_a)
        custom_node_common.sync_custom_layers(yp_b)

        # Both layers start on the vector path, so the shared `Vector` input has a mapping node.
        for layer in (layer_a, layer_b):
            self.assertIsNotNone(self.get_layer_tree(layer).nodes.get(layer.mapping))

        color_index = [root_ch.name for root_ch in yp_a.channels].index('Color')
        rough_index = [root_ch.name for root_ch in yp_a.channels].index('Roughness')

        # Rename one output, remove another, and remove the `Vector` input at once.
        interface_item(group, 'Color', 'OUTPUT').name = 'Colour'
        group.interface.remove(interface_item(group, 'Roughness', 'OUTPUT'))
        group.interface.remove(interface_item(group, 'Vector', 'INPUT'))

        # Reviewer's scenario: sync material A first, then B. With a name-keyed cache B would be
        # skipped; per-yp keying must repair both.
        report_a = custom_node_common.sync_custom_layers(yp_a)
        report_b = custom_node_common.sync_custom_layers(yp_b)
        self.assertIn('group interface changed', report_a)
        self.assertIn('group interface changed', report_b)

        for layer in (layer_a, layer_b):
            # Renamed Color and removed Roughness both fall back to the same-named/first output.
            self.assertEqual(layer.channels[color_index].socket_input_name, 'Colour')
            self.assertEqual(layer.channels[rough_index].socket_input_name, 'Colour')
            # Removed Vector: no dead mapping node, no stored mapping name, no warning from the
            # input side (the fallback warning below is about the channel bindings, not Vector).
            self.assertEqual(layer.mapping, '')
            self.assertEqual([node for node in self.get_layer_tree(layer).nodes
                              if node.bl_idname == 'ShaderNodeMapping'], [])
            source = self.get_layer_source(layer)
            self.assertIsNone(source.inputs.get('Vector'))
            # FR-10: the automatic fallback keeps warning until the user re-chooses the binding.
            self.assertIn('re-pointed', custom_node_common.get_custom_layer_warning(layer))

        # Idempotent for both yps: a second pass changes no link and creates no node.
        snapshot_a = self.snapshots(layer_a)
        snapshot_b = self.snapshots(layer_b)
        self.assertEqual(custom_node_common.sync_custom_layers(yp_a), '')
        self.assertEqual(custom_node_common.sync_custom_layers(yp_b), '')
        self.assertEqual(self.snapshots(layer_a), snapshot_a)
        self.assertEqual(self.snapshots(layer_b), snapshot_b)


class TestCustomSyncRetryAfterFailure(CustomNodeTestBase):
    """T-6a follow-up: a failed repair must leave the cache so the next pass retries."""

    def test_01_failed_repair_is_retried_and_repaired(self):
        group = self.make_group('RetryGroup', outputs=[('Color', 'NodeSocketColor')])
        layer = self.new_custom_layer('RetryGroup')
        yp = self.get_yp()
        # Healthy baseline primes the cache with the original signature.
        custom_node_common.sync_custom_layers(yp)

        interface_item(group, 'Color', 'OUTPUT').name = 'Colour'

        calls = {'n': 0}
        original = node_connections.reconnect_layer_nodes

        def fail_once(*args, **kwargs):
            calls['n'] += 1
            raise RuntimeError('injected reconnect failure')

        node_connections.reconnect_layer_nodes = fail_once
        try:
            with self.assertRaises(RuntimeError):
                custom_node_common.sync_custom_layers(yp)
        finally:
            node_connections.reconnect_layer_nodes = original

        self.assertEqual(calls['n'], 1, 'the injected failure did not reach the rewire')

        # The failed repair rolled its automatic re-binding back (Defect B(c)): the binding still
        # names the pre-call output, and the fallback flag was not left set.
        color_index = [root_ch.name for root_ch in yp.channels].index('Color')
        self.assertEqual(layer.channels[color_index].socket_input_name, 'Color')
        self.assertFalse(layer.channels[color_index].custom_fallback_binding)

        # The cache was restored, so the next pass still sees a change and repairs.
        report = custom_node_common.sync_custom_layers(yp)
        self.assertIn('re-bound', report)
        self.assertEqual(layer.channels[color_index].socket_input_name, 'Colour')
        # FR-10: the repair was an automatic fallback, so the warning stays until re-chosen.
        self.assertIn('re-pointed', custom_node_common.get_custom_layer_warning(layer))

        # Hard requirement for T-6b: once repaired, a further pass is silent.
        self.assertEqual(custom_node_common.sync_custom_layers(yp), '')



class TestCustomFailureIsolation(CustomNodeTestBase):
    """Defect B: one failing group must not block a healthy group in the same yp."""

    def test_01_failure_rolls_back_isolates_and_retries_without_a_storm(self):
        group_a = self.make_group('IsolatedA', outputs=[('Color', 'NodeSocketColor')])
        self.new_custom_layer('IsolatedA', name='A')
        group_b = self.make_group('IsolatedB', outputs=[('Color', 'NodeSocketColor')])
        self.new_custom_layer('IsolatedB', name='B')
        yp = self.get_yp()
        # `new_custom_layer` returns the active layer; with two layers in one yp, pick by name.
        layer_a = next(layer for layer in yp.layers if layer.name == 'A')
        layer_b = next(layer for layer in yp.layers if layer.name == 'B')

        custom_node_common.clear_custom_sync_state()
        custom_node_common.sync_custom_layers(yp)
        bpy.context.view_layer.update()

        interface_item(group_a, 'Color', 'OUTPUT').name = 'ColourA'
        interface_item(group_b, 'Color', 'OUTPUT').name = 'ColourB'

        a_index = [root_ch.name for root_ch in yp.channels].index('Color')
        attempts = {'a': 0, 'b': 0}
        original = node_connections.reconnect_layer_nodes

        def inject(layer, *args, **kwargs):
            if layer == layer_a:
                attempts['a'] += 1
                raise RuntimeError('injected failure for A')
            attempts['b'] += 1
            return original(layer, *args, **kwargs)

        node_connections.reconnect_layer_nodes = inject
        try:
            bpy.context.view_layer.update()
            self.assertEqual(attempts['a'], 1)
            self.assertEqual(attempts['b'], 1, 'the healthy group was skipped after A failed')

            # B repaired; A failed after re-binding but its snapshot rolled the binding back.
            self.assertEqual(layer_b.channels[a_index].socket_input_name, 'ColourB')
            self.assert_enabled_channels_wired(layer_b)
            self.assertEqual(layer_a.channels[a_index].socket_input_name, 'Color')
            self.assertFalse(layer_a.channels[a_index].custom_fallback_binding)
            self.assertIn('injected failure for A', custom_node_common.get_custom_sync_error(yp))

            # 20 rapid updates stay inside the retry window: no attempt storm, report kept.
            for _ in range(20):
                bpy.context.view_layer.update()
            self.assertEqual(attempts['a'], 1, 'a failing group retried on every depsgraph update')
            self.assertIn('injected failure for A', custom_node_common.get_custom_sync_error(yp))

            # Expire the throttle so the next update is allowed to retry (no developer-mode op).
            for key, (signature, _retry_after) in list(custom_node_common._custom_sync_throttle.items()):
                if key[1] == group_a.as_pointer():
                    custom_node_common._custom_sync_throttle[key] = (signature, 0.0)
        finally:
            node_connections.reconnect_layer_nodes = original

        # Cause removed: a plain depsgraph update retries A and repairs it.
        self.obj.location.x += 0.001
        bpy.context.view_layer.update()
        self.assertEqual(layer_a.channels[a_index].socket_input_name, 'ColourA')
        self.assertIn('re-pointed', custom_node_common.get_custom_layer_warning(layer_a))
        self.assertEqual(custom_node_common.get_custom_sync_error(yp), '')
        self.assert_enabled_channels_wired(layer_a)


class TestCustomLiveResync(CustomNodeTestBase):
    """T-6b / FR-11–FR-13: one depsgraph update repairs a topology change, once."""

    def prepare(self):
        group = self.make_group('LiveGroup',
            outputs=[('Color', 'NodeSocketColor'), ('Roughness', 'NodeSocketFloat')])
        layer = self.new_custom_layer('LiveGroup')
        yp = self.get_yp()

        # Two enabled channels so "every enabled channel" has something to assert.
        rough_index = [root_ch.name for root_ch in yp.channels].index('Roughness')
        layer.channels[rough_index].enable = True

        # Cold start, then establish the baseline the handler compares against.
        custom_node_common.clear_custom_sync_state()
        custom_node_common.sync_custom_layers(yp)
        bpy.context.view_layer.update()
        self.assert_enabled_channels_wired(layer)
        return group, layer, yp

    def test_01_add_remove_rename_repairs_on_one_update_each(self):
        group, layer, yp = self.prepare()
        calls = self.count_sync_calls()

        # Add an output: one update must pick it up, all channels stay wired.
        group.interface.new_socket('Extra', in_out='OUTPUT', socket_type='NodeSocketFloat')
        bpy.context.view_layer.update()
        self.assertEqual(calls['n'], 1, 'adding an output did not trigger exactly one sync')
        self.assert_enabled_channels_wired(layer)

        # Remove it again.
        group.interface.remove(interface_item(group, 'Extra', 'OUTPUT'))
        bpy.context.view_layer.update()
        self.assertEqual(calls['n'], 2)
        self.assert_enabled_channels_wired(layer)

        # Rename the bound output: the channel falls back to a live output and is wired there.
        interface_item(group, 'Color', 'OUTPUT').name = 'BaseColor'
        bpy.context.view_layer.update()
        self.assertEqual(calls['n'], 3)
        self.assert_enabled_channels_wired(layer)
        source = self.get_layer_source(layer)
        self.assertIsNone(source.outputs.get('Color'), 'a stale output socket survived the rename')
        live_sockets = set(source.outputs)
        remaining = [link for link in self.get_layer_tree(layer).links if link.from_node == source]
        self.assertTrue(all(link.from_socket in live_sockets for link in remaining),
                        'a link still leaves a socket the group no longer declares')

        # Remove the bound output: every enabled channel must land on an existing output.
        group.interface.remove(interface_item(group, 'BaseColor', 'OUTPUT'))
        bpy.context.view_layer.update()
        self.assertEqual(calls['n'], 4)
        self.assert_enabled_channels_wired(layer)

    def test_02_default_value_node_move_and_mute_never_sync(self):
        group, layer, yp = self.prepare()

        # Create the node before counting; creating it is not one of FR-12's edits.
        node = group.nodes.new('ShaderNodeValue')
        before = snapshot_tree(self.get_layer_tree(layer))
        calls = self.count_sync_calls()

        interface_item(group, 'Color', 'OUTPUT').default_value = (0.5, 0.25, 0.0, 1.0)
        node.location = (321.0, -123.0)
        node.mute = True
        bpy.context.view_layer.update()
        bpy.context.view_layer.update()

        self.assertEqual(calls['n'], 0, 'a non-topology edit reached the sync entry point')
        self.assertEqual(snapshot_tree(self.get_layer_tree(layer)), before,
                         'a non-topology edit rebuilt links')

    def test_03_rename_runs_exactly_once_and_does_not_loop(self):
        group, layer, yp = self.prepare()
        calls = self.count_sync_calls()

        interface_item(group, 'Color', 'OUTPUT').name = 'Colour'
        bpy.context.view_layer.update()

        self.assertEqual(calls['n'], 1, 'one rename must run the sync exactly once')
        for _ in range(5):
            bpy.context.view_layer.update()
        self.assertEqual(calls['n'], 1, 'the rewire re-triggered itself (FR-13 loop)')

        color_index = [root_ch.name for root_ch in yp.channels].index('Color')
        self.assertEqual(layer.channels[color_index].socket_input_name, 'Colour')
        self.assert_enabled_channels_wired(layer)

    def test_04_missing_group_warns_and_handler_does_not_raise(self):
        group, layer, yp = self.prepare()
        color_index = [root_ch.name for root_ch in yp.channels].index('Color')
        ch = layer.channels[color_index]

        # A gone binding is the FR-10 channel warning until the next update repairs it.
        interface_item(group, 'Color', 'OUTPUT').name = 'Gone'
        self.assertFalse(custom_node_common.is_custom_channel_binding_valid(layer, ch))
        self.assertIn('not bound', custom_node_common.get_custom_layer_warning(layer))

        bpy.context.view_layer.update()
        # The handler re-points the binding to an existing socket, but that was an automatic
        # fallback: the warning must survive until the user re-chooses the binding (FR-10).
        self.assertEqual(ch.socket_input_name, 'Gone')
        self.assertTrue(ch.custom_fallback_binding)
        self.assertIn('re-pointed', custom_node_common.get_custom_layer_warning(layer))
        self.assert_enabled_channels_wired(layer)

        # Re-binding through the channel-source menu operator acknowledges the fallback.
        self.choose_channel_binding(layer, ch, 'Gone')
        self.assertFalse(ch.custom_fallback_binding)
        self.assertEqual(custom_node_common.get_custom_layer_warning(layer), '')

        # A deleted group is the FR-16 state; the handler skips it without a traceback. The pointer
        # is the source of truth since T-7a, so a real deletion clears both it and the node's tree.
        layer.custom_group = None
        self.get_layer_source(layer).node_tree = None
        bpy.context.view_layer.update()
        bpy.context.view_layer.update()
        self.assertEqual(custom_node_common.get_custom_layer_warning(layer), 'Missing node group')
        self.assertEqual(custom_node_common.get_custom_sync_error(yp), '')

    def test_05_failure_is_reported_once_throttled_and_retried_on_change(self):
        group, layer, yp = self.prepare()
        interface_item(group, 'Color', 'OUTPUT').name = 'Colour'

        calls = {'n': 0}
        original = custom_node_common.sync_custom_layers

        def failing(*args, **kwargs):
            calls['n'] += 1
            raise RuntimeError('injected handler failure')

        custom_node_common.sync_custom_layers = failing
        try:
            bpy.context.view_layer.update()
            self.assertEqual(calls['n'], 1)
            self.assertIn('injected handler failure', custom_node_common.get_custom_sync_error(yp))

            # Throttled: a deterministic failure must not retry on every update.
            for _ in range(5):
                bpy.context.view_layer.update()
            self.assertEqual(calls['n'], 1, 'a failing group retried on every depsgraph update')

            # A new interface signature is a new attempt, not a silent permanent break.
            interface_item(group, 'Colour', 'OUTPUT').name = 'Colour2'
            bpy.context.view_layer.update()
            self.assertEqual(calls['n'], 2)
        finally:
            custom_node_common.sync_custom_layers = original

        # A manual success clears both the throttle and the report.
        custom_node_common.sync_custom_layers(yp)
        self.assertEqual(custom_node_common.get_custom_sync_error(yp), '')
        bpy.context.view_layer.update()
        self.assert_enabled_channels_wired(layer)


class TestCustomStaleSyncState(CustomNodeTestBase):
    """T-6b follow-up: a failed group's report must not outlive the layer that referenced it."""

    def test_01_stale_error_clears_after_the_failing_layer_is_removed(self):
        group_a = self.make_group('StaleA', outputs=[('Color', 'NodeSocketColor')])
        self.new_custom_layer('StaleA', name='A')
        self.make_group('StaleB', outputs=[('Color', 'NodeSocketColor')])
        self.new_custom_layer('StaleB', name='B')
        yp = self.get_yp()
        layer_a = next(layer for layer in yp.layers if layer.name == 'A')

        custom_node_common.clear_custom_sync_state()
        custom_node_common.sync_custom_layers(yp)
        bpy.context.view_layer.update()

        interface_item(group_a, 'Color', 'OUTPUT').name = 'ColourA'
        original = node_connections.reconnect_layer_nodes

        def fail_for_a(layer, *args, **kwargs):
            if layer == layer_a: raise RuntimeError('injected failure for A')
            return original(layer, *args, **kwargs)

        node_connections.reconnect_layer_nodes = fail_for_a
        try:
            bpy.context.view_layer.update()
        finally:
            node_connections.reconnect_layer_nodes = original

        self.assertIn('StaleA', custom_node_common.get_custom_sync_error(yp))

        # The failing layer goes away. Nothing references StaleA any more, so a manual Refresh
        # (the same `finally` as the handler) must prune its throttle, report and error entries;
        # leaving a red row that no Refresh can clear is the bug this test pins. Removing from the
        # collection is enough here; `layer_common.remove_layer` needs a live layers panel.
        yp.layers.remove([layer.name for layer in yp.layers].index('A'))
        custom_node_common.sync_custom_layers(yp)

        self.assertEqual(custom_node_common.get_custom_sync_error(yp), '')
        self.assertFalse([key for key in custom_node_common._custom_sync_throttle
                          if key[1] == group_a.as_pointer()])
        self.assertFalse([key for key in custom_node_common._custom_sync_errors
                          if key[1] == group_a.as_pointer()])


class TestCustomSyncErrorNamesGroups(CustomNodeTestBase):
    """T-6b follow-up: the report must say which group failed, not just the exception."""

    def test_01_two_failing_groups_are_both_named(self):
        group_a = self.make_group('NamedA', outputs=[('Color', 'NodeSocketColor')])
        self.new_custom_layer('NamedA', name='A')
        group_b = self.make_group('NamedB', outputs=[('Color', 'NodeSocketColor')])
        self.new_custom_layer('NamedB', name='B')
        yp = self.get_yp()

        custom_node_common.clear_custom_sync_state()
        custom_node_common.sync_custom_layers(yp)
        bpy.context.view_layer.update()

        interface_item(group_a, 'Color', 'OUTPUT').name = 'ColourA'
        interface_item(group_b, 'Color', 'OUTPUT').name = 'ColourB'

        original = node_connections.reconnect_layer_nodes

        def fail_every_group(layer, *args, **kwargs):
            raise RuntimeError('injected failure for ' + layer.name)

        node_connections.reconnect_layer_nodes = fail_every_group
        try:
            bpy.context.view_layer.update()
        finally:
            node_connections.reconnect_layer_nodes = original

        error = custom_node_common.get_custom_sync_error(yp)
        self.assertIn('NamedA', error)
        self.assertIn('NamedB', error)


class TestCustomChannelWarning(CustomNodeTestBase):
    """T-6b follow-up: row predicate and `get_custom_layer_warning` share one rule."""

    def test_01_disabled_and_overridden_channels_agree(self):
        self.make_group('WarningGroup', outputs=[('Color', 'NodeSocketColor')])
        layer = self.new_custom_layer('WarningGroup')
        yp = self.get_yp()
        color_index = [root_ch.name for root_ch in yp.channels].index('Color')
        ch = layer.channels[color_index]

        custom_node_common.clear_custom_sync_state()
        custom_node_common.sync_custom_layers(yp)

        # A disabled channel feeds nothing: its stale flag is not a warning anywhere.
        ch.custom_fallback_binding = True
        ch.enable = False
        self.assertEqual(custom_node_common.get_custom_layer_warning(layer), '')
        self.assertEqual(custom_node_common.get_custom_channel_warning(layer, ch), '')

        # Enabled again: both report the FR-10 fallback.
        ch.enable = True
        self.assertIn('re-pointed', custom_node_common.get_custom_layer_warning(layer))
        self.assertIn('re-pointed', custom_node_common.get_custom_channel_warning(layer, ch))

        # The "Custom Color" override pick makes the channel ignore the group output: it clears
        # the flag, and the row predicate agrees with the layer predicate that it is healthy.
        self.choose_channel_binding(layer, ch, '')
        self.assertTrue(ch.override)
        self.assertFalse(ch.custom_fallback_binding)
        self.assertEqual(custom_node_common.get_custom_layer_warning(layer), '')
        self.assertEqual(custom_node_common.get_custom_channel_warning(layer, ch), '')


class TestCustomGroupPointer(CustomNodeTestBase):
    """T-7a / FR-15: the group is a data-block pointer, not a name.

    Renaming the group, saving and reopening keeps the reference with no update handler. The
    save/reopen half runs in a second Blender process (see the T-7a commit body); here the pointer
    semantics that make it work are pinned: rename does not touch the pointer, and leaving the type
    releases it.
    """

    def test_01_layer_stores_the_pointer_and_survives_a_rename(self):
        group = self.make_group('PointerGroup',
            outputs=[('Color', 'NodeSocketColor')],
            inputs=[('Color', 'NodeSocketColor')])
        layer = self.new_custom_layer('PointerGroup')
        source = self.get_layer_source(layer)

        self.assertIs(layer.custom_group, group)
        self.assertIs(source.node_tree, group)

        # Rename: the pointer follows the datablock, and the source node follows the pointer.
        group.name = 'RenamedPointerGroup'
        self.assertIs(layer.custom_group, group)
        self.assertEqual(layer.custom_group.name, 'RenamedPointerGroup')
        self.assertIs(source.node_tree, group)

        # No handler is involved: a plain reconnect keeps the binding and the input link.
        node_connections.reconnect_layer_nodes(layer)
        self.assertEqual(layer.channels[0].socket_input_name, 'Color')
        self.assertEqual(len(source.inputs['Color'].links), 1)
        self.assertEqual(custom_node_common.get_custom_layer_warning(layer), '')

    def test_02_leaving_the_type_clears_the_pointer(self):
        self.make_group('LeaveGroup', outputs=[('Color', 'NodeSocketColor')])
        layer = self.new_custom_layer('LeaveGroup')
        self.assertIsNotNone(layer.custom_group)

        self.assertTrue(layer_common.replace_layer_type(layer, 'NOISE'))
        self.assertEqual(layer.type, 'NOISE')
        self.assertIsNone(layer.custom_group)

    def test_03_pre_pointer_layer_behaves_like_a_missing_group(self):
        # A file saved before this property loads with `custom_group` None while the source node
        # still carries a tree (the T-3a stopgap). Reading the pointer first and falling back to the
        # node keeps that file working; clearing both is the FR-16 state.
        group = self.make_group('LegacyGroup', outputs=[('Color', 'NodeSocketColor')])
        layer = self.new_custom_layer('LegacyGroup')
        source = self.get_layer_source(layer)

        layer.custom_group = None
        self.assertIs(custom_node_common.get_custom_layer_group(layer), group)
        layer_common.check_layer_source(layer)
        self.assertIs(source.node_tree, group)

        source.node_tree = None
        self.assertIsNone(custom_node_common.get_custom_layer_group(layer))
        self.assertEqual(custom_node_common.get_custom_layer_warning(layer), 'Missing node group')


class TestCustomMissingGroupFallback(CustomNodeTestBase):
    """T-7a / FR-16: a missing or unusable group falls through like a disabled layer.

    Every transition here goes through the depsgraph handler or the relink operator — no manual
    `reconnect_yp_nodes` call — because the review defect was precisely that the pointer changed
    while the yp graph did not. The assertions inspect the yp links and a render, not the warning.
    """

    def build_stack(self, name='FallbackGroup', color=(1.0, 0.0, 0.0, 1.0)):
        """Below layer (green) and a custom layer (``color``) over it."""
        bpy.ops.wm.y_new_layer(name='Green', type='COLOR', solid_color=(0.0, 1.0, 0.0), uv_map='UVMap')
        group = self.make_group(name, outputs=[('Color', 'NodeSocketColor')])
        rgb = group.nodes.new('ShaderNodeRGB')
        rgb.outputs[0].default_value = color
        output = group.nodes.new('NodeGroupOutput')
        group.links.new(rgb.outputs[0], output.inputs['Color'])

        layer = self.new_custom_layer(name)
        layer.channels[0].enable = True
        return group, layer, rgb, output

    def channel_end_source(self, layer):
        """The node feeding the yp tree's channel `End` input for Color, i.e. the channel result."""
        tree = layer.id_data
        end_socket = node_connections.get_essential_node(tree, common.TREE_END).get('Color')
        self.assertTrue(end_socket.links, 'the Color channel end input is not fed')
        return end_socket.links[0].from_node

    def assert_pixels_equal(self, a, b, message):
        for value_a, value_b in zip(a, b):
            self.assertAlmostEqual(value_a, value_b, places=3, msg=message % (a, b))

    def test_01_missing_group_equals_a_disabled_layer(self):
        group, layer, rgb, output = self.build_stack()
        tree = layer.id_data

        restore = self.render_settings()
        try:
            # Baseline: the handler must have seen this layer usable before the transition.
            bpy.context.view_layer.update()
            self.assert_yp_layer_wired(layer)
            on_pixel = self.render_center_pixel('custom_node_fallback_on.png')
            self.assertGreater(on_pixel[0], on_pixel[1], 'the custom layer did not render red')

            # Drop the group on both the pointer and the node, as a deletion does. One depsgraph
            # update must re-splice the yp by itself.
            layer.custom_group = None
            self.get_layer_source(layer).node_tree = None
            bpy.context.view_layer.update()

            self.assert_yp_layer_bypassed(layer)
            missing_source = self.channel_end_source(layer)
            missing_pixel = self.render_center_pixel('custom_node_fallback_missing.png')
            self.assertGreater(missing_pixel[1], missing_pixel[0],
                               'the below layer did not show through: %r' % (missing_pixel,))

            # An otherwise identical disabled layer produces the same graph result and the same pixel.
            layer.enable = False
            self.assert_yp_layer_bypassed(layer)
            self.assertEqual(self.channel_end_source(layer).name, missing_source.name)
            disabled_pixel = self.render_center_pixel('custom_node_fallback_disabled.png')
            self.assert_pixels_equal(
                missing_pixel, disabled_pixel,
                'missing group %r != disabled layer %r')
        finally:
            layer.enable = True
            restore()

        self.assertEqual(custom_node_common.get_custom_layer_warning(layer), 'Missing node group')
        self.assertEqual(custom_node_common.get_custom_sync_error(self.get_yp()), '')

    def test_02_live_deletion_reconnects_once_and_falls_through(self):
        group, layer, rgb, output = self.build_stack()
        bpy.context.view_layer.update()
        self.assert_yp_layer_wired(layer)

        calls = self.count_reconnect_calls()

        # Live datablock deletion: Blender clears the pointer and the node's tree. The handler must
        # notice the usability flip, bypass the layer once, then stay quiet.
        bpy.data.node_groups.remove(group)
        self.assertIsNone(layer.custom_group)
        self.assertIsNone(self.get_layer_source(layer).node_tree)

        bpy.context.view_layer.update()
        self.assertEqual(calls['n'], 1, 'a live deletion did not re-splice the yp exactly once')
        self.assert_yp_layer_bypassed(layer)
        for _ in range(20):
            bpy.context.view_layer.update()
        self.assertEqual(calls['n'], 1, 'a missing group reconnected on every update (FR-13 loop)')

        self.assertEqual(custom_node_common.get_custom_layer_warning(layer), 'Missing node group')
        self.assertEqual(custom_node_common.get_custom_sync_error(self.get_yp()), '')

        restore = self.render_settings()
        try:
            missing_pixel = self.render_center_pixel('custom_node_deleted_missing.png')
            self.assertGreater(missing_pixel[1], missing_pixel[0],
                               'the below layer did not show through after deletion')

            layer.enable = False
            self.assert_yp_layer_bypassed(layer)
            disabled_pixel = self.render_center_pixel('custom_node_deleted_disabled.png')
            self.assert_pixels_equal(
                missing_pixel, disabled_pixel,
                'deleted group %r != disabled layer %r')
        finally:
            layer.enable = True
            restore()

    def test_03_emptying_and_restoring_reconnect_once_each(self):
        group, layer, rgb, output = self.build_stack()
        bpy.context.view_layer.update()
        self.assert_yp_layer_wired(layer)

        calls = self.count_reconnect_calls()

        # Remove the last compatible output: the signature changes too, but the usability flip is
        # the part that must bypass the layer in the yp chain.
        group.interface.remove(interface_item(group, 'Color', 'OUTPUT'))
        bpy.context.view_layer.update()
        self.assertEqual(calls['n'], 1, 'emptying did not re-splice the yp exactly once')
        self.assert_yp_layer_bypassed(layer)
        self.assertEqual(custom_node_common.get_custom_layer_warning(layer),
                         'Node group has no compatible outputs')
        for _ in range(20):
            bpy.context.view_layer.update()
        self.assertEqual(calls['n'], 1, 'an emptied group reconnected on every update')

        # Restore a compatible output and its value: one update brings the layer back.
        group.interface.new_socket(name='Color', in_out='OUTPUT', socket_type='NodeSocketColor')
        group.links.new(rgb.outputs[0], output.inputs['Color'])
        bpy.context.view_layer.update()
        self.assertEqual(calls['n'], 2, 'restoring did not re-splice the yp exactly once')
        self.assert_yp_layer_wired(layer)
        self.assertEqual(custom_node_common.get_custom_layer_warning(layer), '')
        for _ in range(20):
            bpy.context.view_layer.update()
        self.assertEqual(calls['n'], 2, 'restoring looped the reconnect (FR-13)')

    def test_05_source_tree_clear_with_pointer_intact_bypasses_once(self):
        # The literal FR-16 action (spec §6 line 14): only the *source node* loses its tree while
        # `layer.custom_group` still points at a valid group. That must be the missing state, not a
        # healthy layer with a channel warning. This failed before the T-11 fix: usability was read
        # from the pointer alone, so the layer stayed spliced and rendered grey.
        group, layer, rgb, output = self.build_stack()
        bpy.context.view_layer.update()
        self.assert_yp_layer_wired(layer)
        self.assertTrue(custom_node_common.is_custom_layer_group_usable(layer))

        source = self.get_layer_source(layer)
        self.assertIs(layer.custom_group, group)
        calls = self.count_reconnect_calls()

        # Pointer intact, source tree cleared: exactly one depsgraph update must re-splice.
        source.node_tree = None
        bpy.context.view_layer.update()

        self.assertIs(layer.custom_group, group, 'the pointer was changed by the probe')
        self.assertEqual(calls['n'], 1,
                         'clearing only the source tree did not re-splice the yp exactly once')
        self.assertFalse(custom_node_common.is_custom_layer_group_usable(layer))
        self.assert_yp_layer_bypassed(layer)
        self.assertEqual(custom_node_common.get_custom_layer_warning(layer), 'Missing node group')
        layout = FakeLayout()
        ui.draw_custom_layer_group_state(layout, layer)
        self.assertEqual(layout.labels, [('', 'ERROR')], 'the layer row did not show the missing state')
        self.assertTrue([op for op in layout.menus
                         if op[0] == 'NODE_MT_y_replace_layer_type_custom_group_menu'],
                        'the row lost the relink action')

        restore = self.render_settings()
        try:
            missing_pixel = self.render_center_pixel('custom_node_source_none_missing.png')
            self.assertGreater(missing_pixel[1], missing_pixel[0],
                               'the below layer did not show through: %r' % (missing_pixel,))

            # The missing state equals an otherwise identical disabled layer, graph and pixel.
            missing_source = self.channel_end_source(layer)
            layer.enable = False
            self.assert_yp_layer_bypassed(layer)
            self.assertEqual(self.channel_end_source(layer).name, missing_source.name)
            disabled_pixel = self.render_center_pixel('custom_node_source_none_disabled.png')
            self.assert_pixels_equal(
                missing_pixel, disabled_pixel,
                'source node missing %r != disabled layer %r')
            layer.enable = True
        finally:
            restore()

        for _ in range(20):
            bpy.context.view_layer.update()
        self.assertEqual(calls['n'], 1, 'the missing state reconnected on every update (FR-13)')

        # Restoring the same tree brings the layer back with one more update, no relink needed.
        before_restore = calls['n']
        self.get_layer_source(layer).node_tree = group
        bpy.context.view_layer.update()
        self.assertEqual(calls['n'], before_restore + 1,
                         'restoring the source tree did not re-splice the yp exactly once')
        self.assertTrue(custom_node_common.is_custom_layer_group_usable(layer))
        self.assert_yp_layer_wired(layer)
        self.assertEqual(custom_node_common.get_custom_layer_warning(layer), '')
        for _ in range(20):
            bpy.context.view_layer.update()
        self.assertEqual(calls['n'], before_restore + 1, 'restoring looped the reconnect (FR-13)')

    def test_04_relink_from_missing_renders_the_new_group(self):
        group, layer, rgb, output = self.build_stack()
        bpy.context.view_layer.update()

        # Missing state first, as a deleted group leaves it.
        layer.custom_group = None
        self.get_layer_source(layer).node_tree = None
        bpy.context.view_layer.update()
        self.assert_yp_layer_bypassed(layer)

        target = self.make_group('RelinkTarget', outputs=[('Color', 'NodeSocketColor')])
        target_rgb = target.nodes.new('ShaderNodeRGB')
        target_rgb.outputs[0].default_value = (0.0, 0.0, 1.0, 1.0)
        target_output = target.nodes.new('NodeGroupOutput')
        target.links.new(target_rgb.outputs[0], target_output.inputs['Color'])

        restore = self.render_settings()
        try:
            # Relink through the real Replace Layer Type picker path. No enable toggle afterwards.
            result = bpy.ops.wm.y_replace_layer_type(
                type='CUSTOM', group_name='RelinkTarget', layer_name=layer.name)
            self.assertEqual(result, {'FINISHED'})
            self.assertIs(layer.custom_group, target)
            self.assert_yp_layer_wired(layer)
            self.assertEqual(custom_node_common.get_custom_layer_warning(layer), '')

            pixel = self.render_center_pixel('custom_node_relinked.png')
            self.assertGreater(pixel[2], pixel[0], 'the relinked group did not render blue: %r'
                               % (pixel,))
            self.assertGreater(pixel[2], pixel[1], 'the below layer still won after relink: %r'
                               % (pixel,))
        finally:
            restore()


class TestCustomUsabilityCacheIdentity(CustomNodeTestBase):
    """T-7a follow-up / FR-16: the usability cache must not key a layer by its collection slot.

    `layer.as_pointer()` is a slot address that Blender hands to the next layer when one is
    removed, so a cached false from a missing layer could be read as the neighbour's state and mask
    a real flip. These tests reproduce that at the list level and pin the stable key and the
    pointer-first predicate.
    """

    def build_two_custom_layers(self):
        """Green below layer, a missing custom layer A and a usable red custom layer B above it."""
        bpy.ops.wm.y_new_layer(name='Green', type='COLOR', solid_color=(0.0, 1.0, 0.0),
                               uv_map='UVMap')

        # A has a compatible group interface but is put into the FR-16 missing state below; only its
        # cache entry matters here.
        self.make_group('CacheIdentityA', outputs=[('Color', 'NodeSocketColor')])
        group_b = self.make_group('CacheIdentityB', outputs=[('Color', 'NodeSocketColor')])
        rgb = group_b.nodes.new('ShaderNodeRGB')
        rgb.outputs[0].default_value = (1.0, 0.0, 0.0, 1.0)
        output = group_b.nodes.new('NodeGroupOutput')
        group_b.links.new(rgb.outputs[0], output.inputs['Color'])

        layer_a = self.new_custom_layer('CacheIdentityA', name='A')
        yp = self.get_yp()
        # Insert B between A and the below layer, so the list is [A, B, Green]: A occupies slot 0
        # (the reviewer's case) and removing it shifts B into that slot.
        yp.active_layer_index = 1
        layer_b = self.new_custom_layer('CacheIdentityB', name='B')
        self.assertEqual([lay.name for lay in yp.layers], ['A', 'B', 'Green'])
        layer_a.channels[0].enable = True
        layer_b.channels[0].enable = True
        return layer_a, layer_b, yp

    def test_01_removing_a_missing_layer_does_not_mask_the_next_layers_flip(self):
        layer_a, layer_b, yp = self.build_two_custom_layers()

        # A is the FR-16 missing state: nothing to render, it is bypassed like a disabled layer.
        layer_a.custom_group = None
        self.get_layer_source(layer_a).node_tree = None

        custom_node_common.clear_custom_sync_state()
        bpy.context.view_layer.update()
        bpy.context.view_layer.update()
        self.assert_yp_layer_bypassed(layer_a)
        self.assert_yp_layer_wired(layer_b)
        self.assertFalse(custom_node_common.is_custom_layer_group_usable(layer_a))
        self.assertTrue(custom_node_common.is_custom_layer_group_usable(layer_b))

        restore = self.render_settings()
        try:
            on_pixel = self.render_center_pixel('custom_node_cache_before.png')
            self.assertGreater(on_pixel[0], on_pixel[1],
                               'the usable custom layer did not render red: %r' % (on_pixel,))

            # The reviewer's p8 scenario, in one update window: the missing layer is removed (which
            # hands its slot address to B) and B loses its group immediately after.
            index_a = [layer.name for layer in yp.layers].index('A')
            a_pointer = layer_a.as_pointer()
            calls = self.count_reconnect_calls()

            yp.layers.remove(index_a)
            layer_b = next(layer for layer in yp.layers if layer.name == 'B')
            self.assertEqual(layer_b.as_pointer(), a_pointer,
                             'the slot address was not reused, so this test cannot reproduce the '
                             'T-7a defect on this Blender build')
            layer_b.custom_group = None
            self.get_layer_source(layer_b).node_tree = None

            bpy.context.view_layer.update()

            # One transition, one re-splice, even though B's slot now holds A's old cache key.
            self.assertEqual(calls['n'], 1,
                             'the masked flip was not repaired: B inherited A\'s cached false')
            self.assert_yp_layer_bypassed(layer_b)
            self.assertEqual(custom_node_common.get_custom_layer_warning(layer_b),
                             'Missing node group')
            missing_pixel = self.render_center_pixel('custom_node_cache_after.png')
            self.assertGreater(missing_pixel[1], missing_pixel[0],
                               'the below layer did not show through: %r' % (missing_pixel,))

            for _ in range(20):
                bpy.context.view_layer.update()
            self.assertEqual(calls['n'], 1, 'the repaired layer reconnected on every update')
        finally:
            restore()

        self.assertEqual(custom_node_common.get_custom_sync_error(yp), '')

    def build_cached_custom_layer(self):
        group = self.make_group('FlipCacheGroup', outputs=[('Color', 'NodeSocketColor')])
        rgb = group.nodes.new('ShaderNodeRGB')
        rgb.outputs[0].default_value = (1.0, 0.0, 0.0, 1.0)
        output = group.nodes.new('NodeGroupOutput')
        group.links.new(rgb.outputs[0], output.inputs['Color'])

        layer = self.new_custom_layer('FlipCacheGroup')
        layer.channels[0].enable = True

        custom_node_common.clear_custom_sync_state()
        bpy.context.view_layer.update()
        bpy.context.view_layer.update()
        self.assert_yp_layer_wired(layer)
        return group, layer

    def assert_duplicate_then_flip_reconnects_once(self, make_second_layer):
        group, layer = self.build_cached_custom_layer()
        yp = self.get_yp()
        yp.active_layer_index = list(yp.layers).index(layer)
        make_second_layer()

        # The layer-list mutation and the group losing its only output happen before one update:
        # a slot-address cache could let the new/shifted layer inherit a stale `usable` and mask
        # the flip. The stable key must still see one transition and rebuild once.
        calls = self.count_reconnect_calls()
        group.interface.remove(interface_item(group, 'Color', 'OUTPUT'))
        bpy.context.view_layer.update()

        self.assertEqual(calls['n'], 1,
                         'duplicate/paste + usability flip did not re-splice the yp exactly once')
        layers = self.custom_layers(yp)
        self.assertEqual(len(layers), 2)
        for item in layers:
            self.assert_yp_layer_bypassed(item)
            self.assertEqual(custom_node_common.get_custom_layer_warning(item),
                             'Node group has no compatible outputs')

        for _ in range(20):
            bpy.context.view_layer.update()
        self.assertEqual(calls['n'], 1, 'the flipped group reconnected on every update')

    def test_04_duplicate_then_usability_flip_reconnects_once(self):
        self.assert_duplicate_then_flip_reconnects_once(
            lambda: self.assertEqual(bpy.ops.wm.y_duplicate_layer(), {'FINISHED'}))

    def test_05_paste_then_usability_flip_reconnects_once(self):
        def paste():
            self.assertEqual(self.copy_active_layer(), {'FINISHED'})
            self.assertEqual(self.paste_layer(), {'FINISHED'})
        self.assert_duplicate_then_flip_reconnects_once(paste)

    def test_02_inserting_a_layer_before_a_custom_layer_keeps_one_reconnect(self):
        bpy.ops.wm.y_new_layer(name='Green', type='COLOR', solid_color=(0.0, 1.0, 0.0),
                               uv_map='UVMap')
        self.make_group('InsertFlip', outputs=[('Color', 'NodeSocketColor')])
        layer = self.new_custom_layer('InsertFlip', name='Flip')
        yp = self.get_yp()
        layer.channels[0].enable = True

        custom_node_common.clear_custom_sync_state()
        bpy.context.view_layer.update()
        bpy.context.view_layer.update()
        self.assert_yp_layer_wired(layer)

        # Insert a layer before the custom layer. The custom layer's slot moves; its identity must
        # not, or the upcoming flip would be compared against another layer's cached value.
        yp.active_layer_index = [lay.name for lay in yp.layers].index('Flip')
        bpy.ops.wm.y_new_layer(name='Inserted', type='COLOR',
                               solid_color=(0.0, 0.0, 1.0), uv_map='UVMap')
        bpy.context.view_layer.update()
        names = [lay.name for lay in yp.layers]
        self.assertLess(names.index('Inserted'), names.index('Flip'),
                        'the layer was not inserted before the custom layer')
        layer = next(lay for lay in yp.layers if lay.name == 'Flip')

        calls = self.count_reconnect_calls()
        layer.custom_group = None
        self.get_layer_source(layer).node_tree = None
        bpy.context.view_layer.update()

        self.assertEqual(calls['n'], 1, 'the flip after an insertion did not reconnect exactly once')
        self.assert_yp_layer_bypassed(layer)
        for _ in range(20):
            bpy.context.view_layer.update()
        self.assertEqual(calls['n'], 1, 'the flip looped after an insertion')

    def test_03_the_pointer_wins_over_a_stale_source_tree(self):
        bpy.ops.wm.y_new_layer(name='Green', type='COLOR', solid_color=(0.0, 1.0, 0.0),
                               uv_map='UVMap')
        group_a = self.make_group('DisagreeA', outputs=[('Color', 'NodeSocketColor')])
        layer = self.new_custom_layer('DisagreeA', name='D')
        yp = self.get_yp()
        layer.channels[0].enable = True
        source = self.get_layer_source(layer)

        custom_node_common.clear_custom_sync_state()
        bpy.context.view_layer.update()
        bpy.context.view_layer.update()
        self.assert_yp_layer_wired(layer)

        # Pointer and source disagree: the pointer names a shader-only group while the source node
        # still instantiates the usable old one. The pointer is the single source of truth, so the
        # layer must go the missing/unusable way even though the stale source looks usable.
        shader_only = self.make_group('DisagreeShaderOnly', [('Shader', 'NodeSocketShader')])
        layer.custom_group = shader_only
        self.assertIs(source.node_tree, group_a, 'the source tree was not left stale')
        # A pointer edit alone does not tag the tree in this headless harness; a UI edit would.
        # Tag it explicitly so the depsgraph handler runs for this update.
        yp.id_data.update_tag()

        calls = self.count_reconnect_calls()
        bpy.context.view_layer.update()
        self.assertEqual(calls['n'], 1,
                         'the pointer-driven unusable state did not reconnect exactly once')
        self.assertFalse(custom_node_common.is_custom_layer_group_usable(layer))
        self.assert_yp_layer_bypassed(layer)
        self.assertEqual(custom_node_common.get_custom_layer_warning(layer),
                         'Node group has no compatible outputs')
        layout = FakeLayout()
        ui.draw_custom_layer_group_state(layout, layer)
        self.assertEqual(layout.labels, [('', 'ERROR')], 'the row disagreed with the predicate')

        # Pointing the pointer back at the usable group (the source is still stale) restores it.
        layer.custom_group = group_a
        yp.id_data.update_tag()
        bpy.context.view_layer.update()
        self.assertEqual(calls['n'], 2,
                         'restoring a usable pointer did not reconnect exactly once')
        self.assertTrue(custom_node_common.is_custom_layer_group_usable(layer))
        self.assert_yp_layer_wired(layer)
        self.assertEqual(custom_node_common.get_custom_layer_warning(layer), '')
        for _ in range(20):
            bpy.context.view_layer.update()
        self.assertEqual(calls['n'], 2, 'the pointer-driven state looped')


class TestCustomGroupSwap(CustomNodeTestBase):
    """T-7a follow-up: re-picking the group of an existing CUSTOM layer works in one step."""

    def snapshots(self, layer):
        return [snapshot_tree(self.get_layer_tree(layer)),
                snapshot_tree(common.get_source_tree(layer)),
                snapshot_tree(layer.id_data)]

    def test_01_replace_layer_type_repicks_the_group(self):
        group_a = self.make_group('SwapA',
            outputs=[('Color', 'NodeSocketColor'), ('Roughness', 'NodeSocketFloat')],
            inputs=[('Color', 'NodeSocketColor'), ('MyOwnThing', 'NodeSocketFloat')])
        self.make_group('SwapB',
            outputs=[('BaseColor', 'NodeSocketColor'), ('Roughness', 'NodeSocketFloat')],
            inputs=[('Color', 'NodeSocketColor'), ('Renamed', 'NodeSocketFloat')])
        layer = self.new_custom_layer('SwapA')
        yp = self.get_yp()
        source = self.get_layer_source(layer)
        color_index = [root_ch.name for root_ch in yp.channels].index('Color')
        rough_index = [root_ch.name for root_ch in yp.channels].index('Roughness')
        layer.channels[rough_index].enable = True
        initial = self.snapshots(layer)

        # A pre-existing link into an input the new group does not share, as a prior swap leaves
        # behind: Blender would remap it by index onto `Renamed` without the swap guard.
        start = self.get_layer_tree(layer).nodes[common.TREE_START]
        self.get_layer_tree(layer).links.new(start.outputs['Color'], source.inputs['MyOwnThing'])
        self.assertEqual(len(source.inputs['MyOwnThing'].links), 1)

        result = bpy.ops.wm.y_replace_layer_type(type='CUSTOM', group_name='SwapB',
                                                 layer_name=layer.name)
        self.assertEqual(result, {'FINISHED'})

        self.assertIs(layer.custom_group, bpy.data.node_groups['SwapB'])
        self.assertIs(self.get_layer_source(layer).node_tree, bpy.data.node_groups['SwapB'])

        # FR-9 re-bind against the new group: same name first, else the first compatible output.
        self.assertEqual(layer.channels[color_index].socket_input_name, 'BaseColor')
        self.assertEqual(layer.channels[rough_index].socket_input_name, 'Roughness')
        self.assertFalse(layer.channels[color_index].custom_fallback_binding)
        self.assertFalse(layer.channels[rough_index].custom_fallback_binding)

        # Stale links are gone: an input matching no channel stays unlinked (FR-6).
        source = self.get_layer_source(layer)
        self.assertEqual(len(source.inputs['Renamed'].links), 0)
        self.assertEqual(len(source.inputs['Color'].links), 1)
        self.assertEqual(source.inputs['Color'].links[0].from_node,
                         self.get_layer_tree(layer).nodes[common.TREE_START])
        self.assert_enabled_channels_wired(layer)
        self.assert_yp_layer_wired(layer)
        self.assertEqual(custom_node_common.get_custom_layer_warning(layer), '')

        # The swap is one undoable operator step: swapping back reconstructs the previous group
        # and the identical, connected tree (the undo half; `bpy.ops.ed.undo` needs a real UI).
        bpy.ops.wm.y_replace_layer_type(type='CUSTOM', group_name='SwapA', layer_name=layer.name)
        self.assertIs(layer.custom_group, bpy.data.node_groups['SwapA'])
        self.assertEqual(layer.channels[color_index].socket_input_name, 'Color')
        self.assert_yp_layer_wired(layer)
        self.assertEqual(self.snapshots(layer), initial)

    def test_02_same_type_without_a_group_is_still_a_no_op(self):
        self.make_group('NoopGroup', outputs=[('Color', 'NodeSocketColor')])
        layer = self.new_custom_layer('NoopGroup')

        self.assertEqual(bpy.ops.wm.y_replace_layer_type(type='CUSTOM', layer_name=layer.name),
                         {'CANCELLED'})
        self.assertIs(layer.custom_group, bpy.data.node_groups['NoopGroup'])

    def test_03_relink_menu_offers_the_candidates(self):
        self.make_group('RelinkGroup', outputs=[('Color', 'NodeSocketColor')])
        self.new_custom_layer('RelinkGroup')

        class FakeContext:
            layer = None

        context = FakeContext()
        context.layer = self.get_active_layer()

        layout = FakeLayout()
        menu_self = type('FakeMenu', (), {'layout': layout})()
        ui.YReplaceLayerTypeCustomGroupMenu.draw(menu_self, context)

        entries = [op for op in layout.operators if op.idname == 'wm.y_replace_layer_type']
        self.assertIn('RelinkGroup', [op.text for op in entries])
        # FR-31: the same menu also offers a generated starter group; only the existing-group
        # entries carry a group name.
        self.assertIn('Generate Starter Group', [op.text for op in entries])
        candidates = [op for op in entries if not op.create_new_group]
        self.assertTrue(all(op.group_name and op.layer_name == context.layer.name
                            for op in candidates))


class TestCustomVectorChannelCollision(CustomNodeTestBase):
    """T-7a follow-up: a root channel literally named `Vector` cannot hijack the vector input.

    Only the literal `Vector` input is reserved; `<channel> Alpha` must still be feedable even when
    the root channel is named `Vector`.
    """

    def test_01_vector_channel_does_not_take_the_reserved_input(self):
        self.make_group('VectorCollisionGroup',
            outputs=[('Color', 'NodeSocketColor')],
            inputs=[('Vector', 'NodeSocketVector'), ('Vector Alpha', 'NodeSocketFloat')])
        layer = self.new_custom_layer('VectorCollisionGroup')
        tree = self.get_layer_tree(layer)
        source = self.get_layer_source(layer)

        bpy.ops.wm.y_add_new_ypaint_channel(name='Vector', type='VECTOR')
        yp = self.get_yp()
        vector_index = [root_ch.name for root_ch in yp.channels].index('Vector')
        layer.channels[vector_index].enable = True
        # Give the `Vector` root channel an alpha so the Start group declares `Vector Alpha`.
        yp.channels[vector_index].enable_alpha = True

        input_outputs.check_all_layer_channel_io_and_nodes(layer, tree)
        node_connections.reconnect_layer_nodes(layer)

        mapping = tree.nodes.get(layer.mapping)
        self.assertIsNotNone(mapping, 'the mapping node disappeared')
        links = source.inputs['Vector'].links
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].from_node, mapping,
                         'the `Vector` channel input hijacked the reserved group input')
        self.assertNotEqual(links[0].from_node.type, 'GROUP_INPUT')

        # The literal `Vector Alpha` input is not reserved and must receive the below-layers alpha.
        alpha_links = source.inputs['Vector Alpha'].links
        self.assertEqual(len(alpha_links), 1,
                         '`Vector Alpha` stayed unlinked because the whole `Vector` channel was skipped')
        self.assertEqual(alpha_links[0].from_node, tree.nodes[common.TREE_START])
        self.assertEqual(alpha_links[0].from_socket.name, 'Vector Alpha')

        # The channel itself still binds to an output and is wired through its layer channel.
        self.assertTrue(layer.channels[vector_index].socket_input_name)
        self.assert_enabled_channels_wired(layer)


class TestCustomMissingGroupRow(CustomNodeTestBase):
    """T-7a / FR-16: the layer row shows the missing state and offers the relink action."""

    def test_01_row_state_and_relink_action(self):
        self.make_group('RowGroup', outputs=[('Color', 'NodeSocketColor')])
        layer = self.new_custom_layer('RowGroup')

        # Healthy layer: the row draws no warning and no relink button.
        layout = FakeLayout()
        ui.draw_custom_layer_group_state(layout, layer)
        self.assertEqual(layout.labels, [])
        self.assertEqual(layout.menus, [])

        layer.custom_group = None
        self.get_layer_source(layer).node_tree = None

        layout = FakeLayout()
        ui.draw_custom_layer_group_state(layout, layer)
        self.assertEqual(layout.labels, [('', 'ERROR')])
        self.assertEqual(layout.menus,
                         [('NODE_MT_y_replace_layer_type_custom_group_menu', '')])
        self.assertIs(layout.pointers['layer'], layer)

        # A group with no compatible output is the same row state.
        layer.custom_group = self.make_group('RowShaderOnly', [('Shader', 'NodeSocketShader')])
        self.get_layer_source(layer).node_tree = layer.custom_group
        layout = FakeLayout()
        ui.draw_custom_layer_group_state(layout, layer)
        self.assertEqual(layout.labels, [('', 'ERROR')])
        self.assertEqual(len(layout.menus), 1)

        # Non-custom layers never draw it.
        bpy.ops.wm.y_new_layer(name='Plain', type='NOISE', uv_map='UVMap')
        layout = FakeLayout()
        ui.draw_custom_layer_group_state(layout, self.get_active_layer())
        self.assertEqual(layout.labels, [])
        self.assertEqual(layout.menus, [])


class TestCustomDuplicateAndPaste(CustomNodeTestBase):
    """T-7b / FR-17: duplicate and paste keep the group reference; no deep copy happens."""

    def test_01_duplicate_layer_shares_one_group_datablock(self):
        group = self.make_group('DupShareGroup',
            outputs=[('Color', 'NodeSocketColor'), ('Roughness', 'NodeSocketFloat')])
        layer = self.new_custom_layer('DupShareGroup')
        yp = self.get_yp()
        yp.active_layer_index = list(yp.layers).index(layer)

        self.assertIn('UNDO', Layer.YDuplicateLayer.bl_options)
        self.assertEqual(bpy.ops.wm.y_duplicate_layer(), {'FINISHED'})

        layers = self.custom_layers(yp)
        self.assertEqual(len(layers), 2)
        original, duplicate = layers

        # One datablock, referenced twice: the source node's tree and the pointer agree for both.
        self.assertEqual(len([g for g in bpy.data.node_groups
                              if g.name == 'DupShareGroup']), 1)
        for item in layers:
            self.assertIs(item.custom_group, group)
            self.assertIs(self.get_layer_source(item).node_tree, group)
        self.assertIsNot(self.get_layer_tree(original), self.get_layer_tree(duplicate))
        # Two users per layer: the source group node and the `custom_group` pointer. The material
        # also holds one dummy instance of the group for the Shader Editor, hence 5.
        self.assertEqual(group.users, 5)

        # Editing a node inside the group is visible through both layers (same tree).
        marker = group.nodes.new('ShaderNodeValue')
        marker.name = 'SharedMarker'
        for item in layers:
            self.assertEqual(
                self.get_layer_source(item).node_tree.nodes['SharedMarker'].as_pointer(),
                marker.as_pointer())

        self.assert_yp_layer_wired(original)
        self.assert_yp_layer_wired(duplicate)

    def test_02_paste_between_materials_keeps_the_reference(self):
        group = self.make_group('PasteShareGroup',
            outputs=[('Color', 'NodeSocketColor'), ('Roughness', 'NodeSocketFloat')])
        layer_a = self.new_custom_layer('PasteShareGroup')
        yp_a = self.get_yp()
        yp_a.active_layer_index = list(yp_a.layers).index(layer_a)
        self.assertEqual(self.copy_active_layer(), {'FINISHED'})

        mat_b = self.add_second_material_yp()
        yp_b = self.get_yp_for(mat_b)
        self.assertEqual(self.paste_layer(), {'FINISHED'})

        pasted = self.custom_layers(yp_b)
        self.assertEqual(len(pasted), 1)
        layer_b = pasted[0]
        self.assertIs(layer_b.custom_group, group)
        self.assertIs(self.get_layer_source(layer_b).node_tree, group)
        self.assertIsNot(self.get_layer_tree(layer_a), self.get_layer_tree(layer_b))
        # Two users per layer (source node + pointer) plus one dummy instance in each material.
        self.assertEqual(group.users, 6)

        marker = group.nodes.new('ShaderNodeValue')
        marker.name = 'PasteMarker'
        for item in (layer_a, layer_b):
            self.assertEqual(
                self.get_layer_source(item).node_tree.nodes['PasteMarker'].as_pointer(),
                marker.as_pointer())

        self.assert_yp_layer_wired(layer_a)
        self.assert_yp_layer_wired(layer_b)

    def test_03_paste_with_a_missing_group_stays_missing(self):
        self.make_group('PasteMissingGroup', outputs=[('Color', 'NodeSocketColor')])
        layer = self.new_custom_layer('PasteMissingGroup')
        yp = self.get_yp()
        yp.active_layer_index = list(yp.layers).index(layer)
        self.assertEqual(self.copy_active_layer(), {'FINISHED'})

        # Delete the group between copy and paste: the clipboard names the layer tree, whose
        # source now has no tree (FR-16's state).
        group = bpy.data.node_groups['PasteMissingGroup']
        bpy.data.node_groups.remove(group)

        mat_b = self.add_second_material_yp()
        yp_b = self.get_yp_for(mat_b)
        self.assertEqual(self.paste_layer(), {'FINISHED'})

        pasted = self.custom_layers(yp_b)[0]
        self.assertIsNone(pasted.custom_group)
        self.assertIsNone(self.get_layer_source(pasted).node_tree)
        self.assertEqual(custom_node_common.get_custom_layer_warning(pasted), 'Missing node group')
        self.assert_yp_layer_bypassed(pasted)


class TestCustomPasteChannelMismatch(CustomNodeTestBase):
    """T-7b: paste into a yp with different root channel order/names (FR-9/FR-10)."""

    def copy_from_a(self, group_name):
        layer = self.new_custom_layer(group_name)
        yp_a = self.get_yp()
        yp_a.active_layer_index = list(yp_a.layers).index(layer)
        self.assertEqual(self.copy_active_layer(), {'FINISHED'})
        return layer

    def test_01_reordered_channels_keep_name_bindings_and_wire(self):
        self.make_group('MismatchGroup',
            outputs=[('Color', 'NodeSocketColor'), ('Roughness', 'NodeSocketFloat')])
        self.copy_from_a('MismatchGroup')

        mat_b = self.add_second_material_yp()
        yp_b = self.get_yp_for(mat_b)
        yp_b.channels.move(0, 2)  # Color moves later in the destination's order
        self.assertEqual(self.paste_layer(), {'FINISHED'})
        pasted = self.custom_layers(yp_b)[0]
        color_index = [root_ch.name for root_ch in yp_b.channels].index('Color')

        self.assertIs(pasted.custom_group, bpy.data.node_groups['MismatchGroup'])
        self.assertEqual(pasted.channels[color_index].socket_input_name, 'Color')
        self.assertTrue(pasted.channels[color_index].enable)
        for ch in pasted.channels:
            self.assertTrue(ch.socket_input_name)
            self.assertTrue(custom_node_common.is_custom_channel_binding_valid(pasted, ch))
        self.assertEqual(custom_node_common.get_custom_layer_warning(pasted), '')
        self.assert_yp_layer_wired(pasted)
        self.assert_enabled_channels_wired(pasted)

    def test_02_renamed_channel_gets_the_fr9_default_binding(self):
        # The group's colour output is deliberately not named ``Color``: the channel property's
        # default is ``Color``, so a binding that was never applied would look right if the group
        # also had a ``Color`` output (that made the original T-7b test vacuous). ``Foo`` can only
        # come from the FR-9 default, which needs the pasted layer's group node/source to exist.
        self.make_group('MismatchNameGroup',
            outputs=[('Foo', 'NodeSocketColor'), ('Metallic', 'NodeSocketFloat'),
                     ('Roughness', 'NodeSocketFloat'), ('Height', 'NodeSocketFloat'),
                     ('Normal', 'NodeSocketVector')])
        self.copy_from_a('MismatchNameGroup')

        mat_b = self.add_second_material_yp()
        yp_b = self.get_yp_for(mat_b)
        color_index = [root_ch.name for root_ch in yp_b.channels].index('Color')
        yp_b.channels[color_index].name = 'Albedo'
        self.assertEqual(self.paste_layer(), {'FINISHED'})
        pasted = self.custom_layers(yp_b)[0]
        albedo_index = [root_ch.name for root_ch in yp_b.channels].index('Albedo')

        # FR-9: no same-named output, so the first compatible output (`Foo`) is the default.
        self.assertIs(pasted.custom_group, bpy.data.node_groups['MismatchNameGroup'])
        albedo = pasted.channels[albedo_index]
        self.assertEqual(albedo.socket_input_name, 'Foo')
        self.assertTrue(custom_node_common.is_custom_channel_binding_valid(pasted, albedo))
        self.assertFalse(albedo.custom_fallback_binding)
        for ch in pasted.channels:
            self.assertTrue(ch.socket_input_name)
            self.assertTrue(custom_node_common.is_custom_channel_binding_valid(pasted, ch))
        self.assertEqual(custom_node_common.get_custom_layer_warning(pasted), '')

        # The destination's own default leaves the renamed channel disabled (existing paste
        # policy for a channel with no source counterpart), so no yp link is the legitimate
        # "none"; enabling it on the real reconnect path wires the FR-9 binding.
        if not pasted.channels[albedo_index].enable:
            pasted.channels[albedo_index].enable = True
            node_connections.reconnect_yp_nodes(self.get_yp_for(mat_b).id_data)
        self.assert_yp_layer_wired(pasted)
        self.assert_enabled_channels_wired(pasted)


class TestCustomUndo(CustomNodeTestBase):
    """T-7b / FR-15: each custom-layer edit is one undoable step that restores group and graph.

    Only real-window runs have an undo stack; `tests/run_tests_ui.py` runs them. See
    `commit_undo_step` for why the post-operation state is recorded explicitly.
    """

    def test_01_undo_redo_layer_creation(self):
        self.make_group('UndoCreateGroup', outputs=[('Color', 'NodeSocketColor')])
        self.undo_baseline()

        self.assertIn('UNDO', Layer.YNewLayer.bl_options)
        self.assertEqual(bpy.ops.wm.y_new_layer(
            name='UndoCreate', type='CUSTOM', group_name='UndoCreateGroup', uv_map='UVMap'),
            {'FINISHED'})
        self.commit_undo_step()
        self.assertEqual(len(self.custom_layers(self.get_yp())), 1)

        yp = self.undo_once()
        self.assertEqual(self.custom_layers(yp), [])

        yp = self.redo_once()
        layer = self.custom_layers(yp)[0]
        self.assertIs(layer.custom_group, bpy.data.node_groups['UndoCreateGroup'])
        self.assert_yp_layer_wired(layer)
        self.assert_enabled_channels_wired(layer)
        self.assertEqual(custom_node_common.get_custom_layer_warning(layer), '')

    def test_02_undo_redo_group_change(self):
        self.make_group('UndoGroupA',
            outputs=[('Color', 'NodeSocketColor'), ('Roughness', 'NodeSocketFloat')])
        self.make_group('UndoGroupB',
            outputs=[('BaseColor', 'NodeSocketColor'), ('Roughness', 'NodeSocketFloat')])
        layer = self.new_custom_layer('UndoGroupA')
        yp = self.get_yp()
        rough_index = [root_ch.name for root_ch in yp.channels].index('Roughness')
        layer.channels[rough_index].enable = True
        self.undo_baseline()
        before = self.custom_layer_snapshot(layer)

        self.assertIn('UNDO', Layer.YReplaceLayerType.bl_options)
        self.assertEqual(bpy.ops.wm.y_replace_layer_type(
            type='CUSTOM', group_name='UndoGroupB', layer_name=layer.name), {'FINISHED'})
        self.commit_undo_step()
        layer = self.custom_layers(self.get_yp())[0]
        self.assertIs(layer.custom_group, bpy.data.node_groups['UndoGroupB'])
        self.assertEqual(layer.channels[0].socket_input_name, 'BaseColor')
        self.assert_yp_layer_wired(layer)

        yp = self.undo_once()
        layer = self.custom_layers(yp)[0]
        self.assertEqual(self.custom_layer_snapshot(layer), before)
        self.assertIs(layer.custom_group, bpy.data.node_groups['UndoGroupA'])
        self.assertEqual(layer.channels[0].socket_input_name, 'Color')
        self.assert_yp_layer_wired(layer)
        self.assert_enabled_channels_wired(layer)

        yp = self.redo_once()
        layer = self.custom_layers(yp)[0]
        self.assertIs(layer.custom_group, bpy.data.node_groups['UndoGroupB'])
        self.assertEqual(layer.channels[0].socket_input_name, 'BaseColor')
        self.assert_yp_layer_wired(layer)
        self.assert_enabled_channels_wired(layer)

    def test_03_undo_redo_channel_binding(self):
        self.make_group('UndoBindGroup',
            outputs=[('Color', 'NodeSocketColor'), ('Roughness', 'NodeSocketFloat')])
        layer = self.new_custom_layer('UndoBindGroup')
        yp = self.get_yp()
        color_index = [root_ch.name for root_ch in yp.channels].index('Color')
        channel = layer.channels[color_index]
        self.undo_baseline()
        before = self.custom_layer_snapshot(layer)
        self.assertEqual(channel.socket_input_name, 'Color')

        self.assertIn('UNDO', Layer.YSetLayerChannelInput.bl_options)
        with bpy.context.temp_override(layer=layer, channel=channel):
            self.assertEqual(bpy.ops.wm.y_set_layer_channel_input(
                socket_name='Roughness'), {'FINISHED'})
        self.commit_undo_step()
        layer = self.custom_layers(self.get_yp())[0]
        self.assertEqual(layer.channels[color_index].socket_input_name, 'Roughness')
        self.assert_yp_layer_wired(layer)

        yp = self.undo_once()
        layer = self.custom_layers(yp)[0]
        self.assertEqual(self.custom_layer_snapshot(layer), before)
        self.assertEqual(layer.channels[color_index].socket_input_name, 'Color')
        self.assert_yp_layer_wired(layer)
        self.assert_enabled_channels_wired(layer)

        yp = self.redo_once()
        layer = self.custom_layers(yp)[0]
        self.assertEqual(layer.channels[color_index].socket_input_name, 'Roughness')
        self.assert_yp_layer_wired(layer)

    def test_04_undo_redo_group_swap_restores_the_old_tree_and_links(self):
        self.make_group('UndoSwapA',
            outputs=[('Color', 'NodeSocketColor'), ('Roughness', 'NodeSocketFloat')],
            inputs=[('Color', 'NodeSocketColor'), ('MyOwnThing', 'NodeSocketFloat')])
        self.make_group('UndoSwapB',
            outputs=[('BaseColor', 'NodeSocketColor'), ('Roughness', 'NodeSocketFloat')],
            inputs=[('Color', 'NodeSocketColor'), ('Renamed', 'NodeSocketFloat')])
        layer = self.new_custom_layer('UndoSwapA')
        yp = self.get_yp()
        rough_index = [root_ch.name for root_ch in yp.channels].index('Roughness')
        layer.channels[rough_index].enable = True

        # A stale input link that exists before the swap; undo must bring it back with group A.
        source = self.get_layer_source(layer)
        start = self.get_layer_tree(layer).nodes[common.TREE_START]
        self.get_layer_tree(layer).links.new(start.outputs['Color'], source.inputs['MyOwnThing'])

        self.undo_baseline()
        before = self.custom_layer_snapshot(layer)

        self.assertEqual(bpy.ops.wm.y_replace_layer_type(
            type='CUSTOM', group_name='UndoSwapB', layer_name=layer.name), {'FINISHED'})
        self.commit_undo_step()
        layer = self.custom_layers(self.get_yp())[0]
        self.assertIs(layer.custom_group, bpy.data.node_groups['UndoSwapB'])
        self.assertEqual(layer.channels[0].socket_input_name, 'BaseColor')
        self.assertEqual(len(self.get_layer_source(layer).inputs['Renamed'].links), 0)
        self.assert_yp_layer_wired(layer)

        yp = self.undo_once()
        layer = self.custom_layers(yp)[0]
        self.assertEqual(self.custom_layer_snapshot(layer), before)
        self.assertIs(layer.custom_group, bpy.data.node_groups['UndoSwapA'])
        self.assertEqual(layer.channels[0].socket_input_name, 'Color')
        self.assertEqual(len(self.get_layer_source(layer).inputs['MyOwnThing'].links), 1)
        self.assert_yp_layer_wired(layer)
        self.assert_enabled_channels_wired(layer)

        yp = self.redo_once()
        layer = self.custom_layers(yp)[0]
        self.assertIs(layer.custom_group, bpy.data.node_groups['UndoSwapB'])
        self.assertEqual(layer.channels[0].socket_input_name, 'BaseColor')
        self.assertEqual(len(self.get_layer_source(layer).inputs['Renamed'].links), 0)
        self.assert_yp_layer_wired(layer)
        self.assert_enabled_channels_wired(layer)


class TestCustomBaking(CustomNodeTestBase):
    """FR-19…FR-22: a custom layer bakes by emission like any other source.

    Bake targets use a custom 128x128 HDR (float, linear) image rather than the default 1024
    sRGB one: the target's custom resolution is the smallest it accepts, the bake is a fraction
    of a second, and float pixels need no sRGB decode before a ±1/255 comparison. The test mesh
    gets a full-square UV layout so every texel is inside the island; the layer output is a
    constant, so the value must be uniform.
    """

    def set_full_square_uvs(self):
        mesh = self.obj.data
        uv_layer = mesh.uv_layers.active or mesh.uv_layers.new(name='UVMap')
        corners = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
        for poly in mesh.polygons:
            for k, loop_index in enumerate(poly.loop_indices):
                uv_layer.data[loop_index].uv = corners[k % 4]
        mesh.update()

    def make_constant_group(self, name, color, value):
        group = self.make_group(name, [
            ('Color', 'NodeSocketColor'),
            ('Roughness', 'NodeSocketFloat'),
        ])
        group_output = group.nodes.new('NodeGroupOutput')
        rgb = group.nodes.new('ShaderNodeRGB')
        rgb.outputs[0].default_value = (color[0], color[1], color[2], 1.0)
        number = group.nodes.new('ShaderNodeValue')
        number.outputs[0].default_value = value
        group.links.new(rgb.outputs[0], group_output.inputs['Color'])
        group.links.new(number.outputs[0], group_output.inputs['Roughness'])
        return group, rgb

    def get_yp_node(self):
        for node in self.mat.node_tree.nodes:
            if node.type == 'GROUP' and node.node_tree and node.node_tree.yp.is_ypaint_node:
                return node
        self.fail('the ucupaint node is missing')

    def bake_target_index(self, channel_name):
        for i, bt in enumerate(self.get_yp().bake_targets):
            if (bt.data_type == 'IMAGE' and bt.r.channel_name == channel_name
                    and bt.g.channel_name == channel_name and bt.b.channel_name == channel_name):
                return i
        self.fail('no image bake target for channel %r' % channel_name)

    def configure_bake_target(self, index):
        bt = self.get_yp().bake_targets[index]
        bt.bake_settings = 'CUSTOM'
        bt.use_custom_resolution = True
        bt.width = bt.height = 128
        bt.hdr = True
        bt.fxaa = False
        bt.samples = 1
        bt.margin = 0
        bt.use_udim = False

    def bake_and_read(self, index):
        result = bpy.ops.wm.y_bake_single_target(bake_target_index=index, bake_device='CPU')
        self.assertEqual(result, {'FINISHED'})
        bt = self.get_yp().bake_targets[index]
        baked_node = self.get_yp_node().node_tree.nodes.get(bt.baked_node)
        self.assertIsNotNone(baked_node, 'the bake did not create its image node')
        image = baked_node.image
        self.assertEqual(tuple(image.size), (128, 128))
        return image, list(image.pixels)

    def assert_uniform_pixels(self, pixels, expected, tolerance, label):
        """Every texel is inside the full-square island, so every texel must match."""
        failures = []
        for i in range(0, len(pixels), 4):
            for channel, value in enumerate(expected):
                if abs(pixels[i + channel] - value) > tolerance:
                    failures.append((i // 4, [round(pixels[i + j], 6) for j in range(3)]))
                    break
            if len(failures) >= 5:
                break
        self.assertEqual(failures, [],
                         '%s: %d texels differ by more than %.6f' % (label, len(failures), tolerance))

    def test_01_constant_color_and_value_channels(self):
        self.set_full_square_uvs()
        self.make_constant_group('BakeConst', (0.25, 0.5, 0.75), 0.3)
        layer = self.new_custom_layer('BakeConst')

        yp = self.get_yp()
        rough_index = [root_ch.name for root_ch in yp.channels].index('Roughness')
        layer.channels[rough_index].enable = True
        node_connections.reconnect_layer_nodes(layer)
        node_connections.reconnect_yp_nodes(self.get_yp_node().node_tree)

        color_index = self.bake_target_index('Color')
        self.configure_bake_target(color_index)
        _, pixels = self.bake_and_read(color_index)
        self.assert_uniform_pixels(pixels, (0.25, 0.5, 0.75), 1.0 / 255.0, 'Color channel')

        rough_index = self.bake_target_index('Roughness')
        self.configure_bake_target(rough_index)
        _, pixels = self.bake_and_read(rough_index)
        self.assert_uniform_pixels(pixels, (0.3, 0.3, 0.3), 1.0 / 255.0, 'Roughness VALUE channel')

    def make_half_mask(self):
        image = bpy.data.images.new('CustomNodeHalfMask', width=4, height=4, float_buffer=True)
        image.colorspace_settings.name = 'Non-Color'
        image.pixels = [0.5] * (4 * 4 * 4)
        return image

    def add_mask(self, layer, image):
        mask = mask_common.add_new_mask(layer, 'Half', 'IMAGE', 'UV', 'UVMap', image=image)
        layer.enable_masks = True
        return mask

    def test_02_masked_layer_matches_noise_reference(self):
        self.set_full_square_uvs()
        half = self.make_half_mask()

        bpy.ops.wm.y_new_layer(name='Base', type='COLOR', solid_color=(0.05, 0.1, 0.2), uv_map='UVMap')
        base = self.get_active_layer()
        base.blend_type = 'MIX'

        self.make_constant_group('MaskedConst', (0.25, 0.5, 0.75), 0.3)
        custom = self.new_custom_layer('MaskedConst')
        custom.blend_type = 'MIX'
        self.add_mask(custom, half)
        node_connections.reconnect_layer_nodes(custom)
        node_connections.reconnect_yp_nodes(self.get_yp_node().node_tree)

        color_index = self.bake_target_index('Color')
        self.configure_bake_target(color_index)
        _, custom_pixels = self.bake_and_read(color_index)

        # Reference: an otherwise identical NOISE layer. Its generated colour is replaced by the
        # same constant (the Mix that blends the generator into the layer is what receives it), so
        # the reference differs only in layer type; its 50 % mask and MIX blend stay untouched.
        custom.enable = False
        bpy.ops.wm.y_new_layer(name='NoiseRef', type='NOISE', uv_map='UVMap')
        noise = self.get_active_layer()
        noise.blend_type = 'MIX'
        self.add_mask(noise, half)
        node_connections.reconnect_layer_nodes(noise)
        node_connections.reconnect_yp_nodes(self.get_yp_node().node_tree)

        tree = self.get_layer_tree(noise)
        noise_socket = None
        for node in tree.nodes:
            if node.type != 'MIX': continue
            for socket in node.inputs:
                if (socket.name == 'B' and socket.is_linked
                        and socket.links[0].from_node.type == 'TEX_NOISE'):
                    noise_socket = socket
                    break
        self.assertIsNotNone(noise_socket, 'the noise generator output was not found')
        for link in list(noise_socket.links):
            tree.links.remove(link)
        constant = tree.nodes.new('ShaderNodeRGB')
        constant.outputs[0].default_value = (0.25, 0.5, 0.75, 1.0)
        tree.links.new(constant.outputs[0], noise_socket)

        _, noise_pixels = self.bake_and_read(color_index)

        expected = (0.15, 0.3, 0.475)
        self.assert_uniform_pixels(custom_pixels, expected, 2.0 / 255.0, 'masked custom layer')
        self.assert_uniform_pixels(noise_pixels, expected, 2.0 / 255.0, 'masked NOISE reference')
        differences = [abs(custom_pixels[i] - noise_pixels[i])
                       for i in range(0, len(custom_pixels), 4)
                       for c in range(3)]
        worst = max(differences)
        self.assertLessEqual(worst, 2.0 / 255.0,
                             'custom and NOISE reference differ by %.6f' % worst)

    def test_03_merged_bake_is_skipped_with_notice(self):
        self.set_full_square_uvs()
        self.make_constant_group('JoinConst', (0.25, 0.5, 0.75), 0.3)
        layer = self.new_custom_layer('JoinConst')

        # A second mesh with its own copy of the geometry and the same material, so the material
        # has two users and the bake operator takes its multi-object path.
        mesh2 = self.obj.data.copy()
        obj2 = bpy.data.objects.new('CustomNodeTestObject2', mesh2)
        bpy.context.scene.collection.objects.link(obj2)
        try:
            yp = self.get_yp()
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                problematic = bake_common.is_join_objects_problematic(yp, self.mat)
            notice = buffer.getvalue()
            self.assertTrue(problematic)
            self.assertIn('custom node layer', notice)
            self.assertIn('INFO: Merged bake is not happening', notice)

            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                objs, _ = bake_common.prepare_objs_before_baking(
                    self.mat, yp, [self.obj, obj2], 'UVMap')
            self.assertEqual(len(objs), 2, 'the objects were merged despite the custom layer')
            self.assertIn('custom node layer', buffer.getvalue())

            color_index = self.bake_target_index('Color')
            self.configure_bake_target(color_index)
            _, pixels = self.bake_and_read(color_index)
            self.assert_uniform_pixels(pixels, (0.25, 0.5, 0.75), 1.0 / 255.0,
                                       'per-object bake with a custom layer')
        finally:
            bpy.data.objects.remove(obj2, do_unlink=True)
            if mesh2.users == 0: bpy.data.meshes.remove(mesh2)

    def bake_layer_to_image(self, layer, name):
        props = bake_common.dotdict()
        for key, value in dict(
                bake_device='CPU', samples=1, margin=0, margin_type='ADJACENT_FACES',
                uv_map='UVMap', hdr=True, use_udim=False, name=name, width=128, height=128,
                blur=False, blur_type='GAUSS', blur_factor=1.0, blur_size=10.0,
                denoise=False, use_image_atlas=False, fxaa=False).items():
            props[key] = value
        result = bake_common.bake_entity_as_image(layer, props, set_image_to_entity=True)
        self.assertEqual(result['message'], '')
        return result['image']

    def test_04_use_baked_bypasses_the_live_graph_and_says_so(self):
        self.set_full_square_uvs()
        group, rgb = self.make_constant_group('BakedConst', (0.25, 0.5, 0.75), 0.3)
        layer = self.new_custom_layer('BakedConst')

        baked = self.bake_layer_to_image(layer, 'CustomNodeBakedLayer')
        self.assertTrue(layer.use_baked)
        self.assertEqual(layer.baked_source != '', True)

        # The baked image holds the old live value; now the live graph says something else.
        rgb.outputs[0].default_value = (0.8, 0.1, 0.1, 1.0)

        notice = ui.get_custom_layer_baked_notice(layer)
        self.assertIn('bypass', notice.lower())
        layout = FakeLayout()
        ui.draw_custom_layer_baked_notice(layout, layer)
        self.assertEqual(layout.labels, [(notice, 'INFO')])

        restore = self.render_settings()
        try:
            layer.use_baked = True
            on_pixel = self.render_center_pixel('custom_node_baked_on.png')
            layer.use_baked = False
            off_pixel = self.render_center_pixel('custom_node_baked_off.png')
        finally:
            restore()

        # Baked A=(0.25, 0.5, 0.75) is blue; the live B=(0.8, 0.1, 0.1) is red.
        self.assertGreater(on_pixel[2], on_pixel[0],
                           'Use Baked did not render the baked image: %r' % (on_pixel,))
        self.assertGreater(off_pixel[0], off_pixel[2],
                           'switching Use Baked off did not restore the live graph: %r' % (off_pixel,))

        color_index = self.bake_target_index('Color')
        self.configure_bake_target(color_index)
        for use_baked, expected, label in (
                (True, (0.25, 0.5, 0.75), 'baked image'),
                (False, (0.8, 0.1, 0.1), 'live graph')):
            layer.use_baked = use_baked
            self.get_yp().use_baked = False
            _, pixels = self.bake_and_read(color_index)
            self.assert_uniform_pixels(pixels, expected, 1.0 / 255.0, label)


class TestCustomStarterGroup(CustomNodeTestBase):
    """FR-31/FR-32/FR-8: starter group shape, one-time write, and Make Unique."""

    def starter_layer(self, name='Starter', group_name='StarterGroup'):
        bpy.ops.wm.y_new_layer(name=name, type='CUSTOM',
                               create_new_group=True, group_name=group_name, uv_map='UVMap')
        return self.get_active_layer()

    def interface_snapshot(self, group):
        return custom_node_common.get_custom_interface_signature(group)

    def interface_names(self, group, in_out):
        return [item.name for item in group.interface.items_tree
                if item.item_type == 'SOCKET' and item.in_out == in_out]

    def test_01_shape_and_passthrough_links(self):
        layer = self.starter_layer()
        yp = self.get_yp()
        group = layer.custom_group

        self.assertIsNotNone(group, 'create_new_group produced no group')
        self.assertEqual(group.name, 'StarterGroup')
        self.assertEqual(layer.type, 'CUSTOM')
        self.assertIs(self.get_layer_source(layer).node_tree, group)

        channel_names = [ch.name for ch in yp.channels]
        self.assertEqual(self.interface_names(group, 'INPUT'),
                         channel_names + ['Vector'])
        self.assertEqual(self.interface_names(group, 'OUTPUT'),
                         channel_names + ['Alpha'])

        # Types follow the layer tree's own Start/End dictionaries, one pair per channel.
        entries = {(item.in_out, item.name): item
                   for item in group.interface.items_tree if item.item_type == 'SOCKET'}
        for root_ch in yp.channels:
            # 4.x flattens NodeSocketFloatFactor to Float (subtype FACTOR); it still feeds a value
            # channel, so that is the expected declaration.
            for in_out, expected in (
                    ('INPUT', common.channel_socket_input_bl_idnames[root_ch.type]),
                    ('OUTPUT', common.channel_socket_output_bl_idnames[root_ch.type])):
                if expected == 'NodeSocketFloatFactor': expected = 'NodeSocketFloat'
                self.assertEqual(entries[(in_out, root_ch.name)].socket_type, expected)
        self.assertEqual(entries[('INPUT', 'Vector')].socket_type, 'NodeSocketVector')

        # Every channel output is linked from its same-named input; Alpha comes from a value node.
        group_input = next(n for n in group.nodes if n.type == 'GROUP_INPUT')
        group_output = next(n for n in group.nodes if n.type == 'GROUP_OUTPUT')
        for outp in group_output.inputs:
            self.assertEqual(len(outp.links), 1, 'output %r is not fed once' % outp.name)
            if outp.name == 'Alpha':
                # FR-31: Alpha is a constant 1.0, never a group input.
                source = outp.links[0].from_node
                self.assertEqual(source.type, 'VALUE',
                                 'Alpha is not fed from a value node')
                self.assertEqual(source.outputs[0].default_value, 1.0)
            else:
                self.assertEqual(outp.links[0].from_socket,
                                 group_input.outputs[outp.name])

        # FR-31: every channel binds to the same-named output.
        self.assertEqual([ch.socket_input_name for ch in layer.channels], channel_names)

    def test_02_renders_as_below(self):
        bpy.ops.wm.y_new_layer(name='Below', type='COLOR',
                               solid_color=(0.0, 0.6, 0.0), uv_map='UVMap')
        layer = self.starter_layer()

        restore = self.render_settings()
        try:
            on_pixel = self.render_center_pixel('custom_starter_on.png')
            layer.enable = False
            off_pixel = self.render_center_pixel('custom_starter_off.png')
        finally:
            layer.enable = True
            restore()

        tolerance = 2.0 / 255.0
        for i in range(3):
            self.assertLessEqual(abs(on_pixel[i] - off_pixel[i]), tolerance,
                                 'starter layer changed the render: on=%r off=%r'
                                 % (on_pixel, off_pixel))

    def test_02b_fresh_starter_layer_is_opaque(self):
        # FR-31 as amended: the starter group's Alpha output is a constant 1.0, so a fresh layer
        # contributes alpha instead of forwarding a transparent below-layers stream. Before T-13
        # Alpha came from the unlinked `Color Alpha` input, so over a transparent below layer the
        # centre alpha was 0. The below layer is a custom group whose alpha output is 0; the yp
        # alpha output is wired to the BSDF so the render's A channel carries the layer alpha.
        transparent = self.make_group(
            'TransparentBelow',
            outputs=[('Color', 'NodeSocketColor'), ('Alpha', 'NodeSocketFloat')])
        out = transparent.nodes.new('NodeGroupOutput')
        rgb = transparent.nodes.new('ShaderNodeRGB')
        rgb.outputs[0].default_value = (0.0, 0.0, 0.0, 0.0)
        value = transparent.nodes.new('ShaderNodeValue')
        value.outputs[0].default_value = 0.0
        node_connections.create_link(transparent, rgb.outputs[0], out.inputs['Color'])
        node_connections.create_link(transparent, value.outputs[0], out.inputs['Alpha'])

        below = self.new_custom_layer('TransparentBelow', name='Below')
        yp = self.get_yp()
        color_idx = [ch.name for ch in yp.channels].index('Color')
        below.channels[color_idx].enable = True
        yp.channels[color_idx].enable_alpha = True

        layer = self.starter_layer()
        layer.channels[color_idx].enable = True

        for each in (below, layer):
            tree = self.get_layer_tree(each)
            input_outputs.check_all_layer_channel_io_and_nodes(each, tree)
            node_connections.reconnect_layer_nodes(each)
        node_connections.reconnect_yp_nodes(layer.id_data)

        # Wire the yp alpha output to the surface so the rendered A channel is the layer alpha.
        material = bpy.data.materials[self.mat_name]
        node_tree = material.node_tree
        yp_node = next(n for n in node_tree.nodes if n.type == 'GROUP'
                       and n.node_tree and n.node_tree.name.endswith(self.mat_name))
        output_node = node_tree.get_output_node('ALL')
        bsdf = output_node.inputs['Surface'].links[0].from_node
        node_tree.links.new(yp_node.outputs['Color Alpha'], bsdf.inputs['Alpha'])

        scene = bpy.context.scene
        old_film_transparent = scene.render.film_transparent
        old_color_mode = scene.render.image_settings.color_mode
        restore = self.render_settings()
        try:
            scene.render.film_transparent = True
            scene.render.image_settings.color_mode = 'RGBA'
            pixel = self.render_center_pixel('custom_starter_opaque.png')
        finally:
            scene.render.film_transparent = old_film_transparent
            scene.render.image_settings.color_mode = old_color_mode
            restore()

        self.assertGreaterEqual(pixel[3], 1.0 - 2.0 / 255.0,
                                'the fresh starter layer is not opaque: %r' % (pixel,))

    def test_03_fr32_group_is_never_modified(self):
        layer = self.starter_layer()
        group = layer.custom_group
        before = self.interface_snapshot(group)

        bpy.ops.wm.y_add_new_ypaint_channel(name='Extra', type='VALUE')
        yp = self.get_yp()
        extra_idx = [ch.name for ch in yp.channels].index('Extra')
        # Adding a channel inserts into `layer.channels`; re-resolve the layer by name so the
        # assertion reads live data rather than a possibly relocated property array.
        layer = yp.layers['Starter']

        self.assertEqual(self.interface_snapshot(group), before,
                         'adding a root channel modified the starter group')

        # The new channel reports the FR-10 fallback instead of the group growing a socket.
        self.assertTrue(layer.channels[extra_idx].custom_fallback_binding,
                        'new channel did not report the FR-10 fallback')
        layer.channels[extra_idx].enable = True
        self.assertTrue(custom_node_common.get_custom_channel_warning(
            layer, layer.channels[extra_idx]))

        yp.active_channel_index = extra_idx
        bpy.ops.wm.y_remove_ypaint_channel()
        yp = self.get_yp()
        layer = yp.layers['Starter']

        self.assertEqual(self.interface_snapshot(group), before,
                         'removing a root channel modified the starter group')

    def test_04_fr8_shared_group_then_make_unique(self):
        layer_a = self.starter_layer(name='A', group_name='SharedStarter')
        yp = self.get_yp()
        group = layer_a.custom_group
        color_idx = [ch.name for ch in yp.channels].index('Color')

        layer_b = self.new_custom_layer('SharedStarter', name='B')
        # Adding a layer inserts into `yp.layers`; re-resolve both layers by name afterwards.
        layer_a = yp.layers['A']
        layer_b = yp.layers['B']
        self.assertIs(layer_a.custom_group, group)
        self.assertIs(layer_b.custom_group, group)
        self.assertIs(self.get_layer_source(layer_b).node_tree, group)

        # One edit in the shared group changes both layers' bindings.
        color_out = next(i for i in group.interface.items_tree
                         if i.item_type == 'SOCKET' and i.in_out == 'OUTPUT'
                         and i.name == 'Color')
        color_out.name = 'Colour'
        custom_node_common.sync_custom_layers(yp)
        self.assertEqual(layer_a.channels[color_idx].socket_input_name, 'Colour')
        self.assertEqual(layer_b.channels[color_idx].socket_input_name, 'Colour')

        # Make Unique copies the tree and repoints exactly one layer.
        groups_before = len(bpy.data.node_groups)
        self.assertEqual(bpy.ops.wm.y_make_custom_group_unique(layer_name='A'), {'FINISHED'})
        layer_a = yp.layers['A']
        layer_b = yp.layers['B']
        unique = layer_a.custom_group
        self.assertIsNot(unique, group)
        self.assertIs(layer_b.custom_group, group)
        self.assertIs(self.get_layer_source(layer_a).node_tree, unique)
        self.assertIs(self.get_layer_source(layer_b).node_tree, group)
        self.assertEqual(len(bpy.data.node_groups), groups_before + 1)
        self.assertFalse(unique.name.startswith('~yPL '))

        # The next edit of the original group is followed by B only.
        colour_out = next(i for i in group.interface.items_tree
                          if i.item_type == 'SOCKET' and i.in_out == 'OUTPUT'
                          and i.name == 'Colour')
        colour_out.name = 'Tint'
        custom_node_common.sync_custom_layers(yp)
        layer_a = yp.layers['A']
        layer_b = yp.layers['B']

        self.assertEqual(layer_b.channels[color_idx].socket_input_name, 'Tint')
        self.assertEqual(layer_a.channels[color_idx].socket_input_name, 'Colour',
                         'the unique copy still followed the original group')

    def test_04b_make_unique_preserves_explicit_binding_and_render(self):
        # FR-8: Make Unique duplicates the tree and repoints only that layer; an explicit binding
        # (Color channel -> Blue output) is part of the layer's behaviour and must survive. On
        # 91cd59f the repoint re-applied the FR-9 defaults, so the render flipped from blue to red.
        # A red layer below feeds the starter's pass-through Color output, so the bug (Color
        # rebound to `Color`) renders red while the explicit `Blue` stays blue.
        bpy.ops.wm.y_new_layer(name='Below', type='COLOR',
                               solid_color=(1.0, 0.0, 0.0), uv_map='UVMap')
        layer = self.starter_layer(name='A', group_name='BoundStarter')
        yp = self.get_yp()
        group = layer.custom_group
        color_idx = [ch.name for ch in yp.channels].index('Color')

        # A second, blue output next to the starter's pass-through Color output.
        common.new_tree_output(group, 'Blue', 'NodeSocketColor')
        group_output = next(n for n in group.nodes if n.type == 'GROUP_OUTPUT')
        rgb = group.nodes.new('ShaderNodeRGB')
        rgb.outputs[0].default_value = (0.0, 0.0, 1.0, 1.0)
        node_connections.create_link(group, rgb.outputs[0], group_output.inputs['Blue'])

        ch = layer.channels[color_idx]
        self.choose_channel_binding(layer, ch, 'Blue')
        self.assertEqual(ch.socket_input_name, 'Blue')
        self.assertFalse(ch.custom_fallback_binding)
        self.assertEqual(custom_node_common.get_custom_channel_warning(layer, ch), '')

        restore = self.render_settings()
        try:
            before = self.render_center_pixel('custom_unique_binding_before.png')
            self.assertGreater(before[2], before[0] + 0.2,
                               'the explicit Blue binding did not render blue: %r' % (before,))

            self.assertEqual(bpy.ops.wm.y_make_custom_group_unique(layer_name='A'),
                             {'FINISHED'})
            layer = yp.layers['A']
            ch = layer.channels[color_idx]
            self.assertIsNot(layer.custom_group, group)
            self.assertEqual(ch.socket_input_name, 'Blue',
                             'Make Unique re-applied the FR-9 default and lost the binding')
            self.assertFalse(ch.custom_fallback_binding,
                             'a preserved binding must not be flagged as a fallback')
            self.assertEqual(custom_node_common.get_custom_channel_warning(layer, ch), '')

            after = self.render_center_pixel('custom_unique_binding_after.png')
        finally:
            restore()

        for i in range(3):
            self.assertLessEqual(abs(before[i] - after[i]), 2.0 / 255.0,
                                 'Make Unique changed the render: before=%r after=%r'
                                 % (before, after))

    def test_04c_make_unique_falls_back_when_the_copy_lacks_the_binding(self):
        # FR-10: preserving a binding is conditional on the copy still offering that output name;
        # when it does not, the channel falls back to the FR-9 default and the warning stays.
        layer = self.starter_layer(name='A', group_name='FallbackStarter')
        yp = self.get_yp()
        group = layer.custom_group
        color_idx = [ch.name for ch in yp.channels].index('Color')

        common.new_tree_output(group, 'Blue', 'NodeSocketColor')
        group_output = next(n for n in group.nodes if n.type == 'GROUP_OUTPUT')
        rgb = group.nodes.new('ShaderNodeRGB')
        rgb.outputs[0].default_value = (0.0, 0.0, 1.0, 1.0)
        node_connections.create_link(group, rgb.outputs[0], group_output.inputs['Blue'])

        ch = layer.channels[color_idx]
        self.choose_channel_binding(layer, ch, 'Blue')
        self.assertEqual(ch.socket_input_name, 'Blue')

        copy = group.copy()
        for item in list(copy.interface.items_tree):
            if item.item_type == 'SOCKET' and item.in_out == 'OUTPUT' and item.name == 'Blue':
                copy.interface.remove(item)

        self.assertTrue(custom_node_common.set_custom_layer_group(
            layer, copy, preserve_bindings=True))
        layer = yp.layers['A']
        ch = layer.channels[color_idx]
        self.assertEqual(ch.socket_input_name, 'Color',
                         'a binding absent from the copy did not fall back to FR-9')
        self.assertTrue(ch.custom_fallback_binding,
                        'the FR-10 fallback was not flagged')
        self.assertTrue(custom_node_common.get_custom_channel_warning(layer, ch),
                        'the FR-10 fallback produced no warning')

    def test_05_panel_and_menu_entries(self):
        layer = self.starter_layer()
        group = layer.custom_group

        layout = FakeLayout()
        ui.draw_custom_layer_group_props(layout, layer)

        self.assertIn((group.name, ''), [(t, '') for t, i in layout.labels])
        make_unique = [op for op in layout.operators
                       if op.idname == 'wm.y_make_custom_group_unique']
        self.assertTrue(make_unique, 'the panel has no Make Unique button')
        self.assertEqual(make_unique[0].text, 'Make Unique')
        self.assertEqual(make_unique[0].layer_name, layer.name)
        self.assertIn(('NODE_MT_y_replace_layer_type_custom_group_menu', 'Change Group'),
                      layout.menus)

        # The row is exactly Make Unique + Change Group: the Edit Group action was removed because
        # it reported success without changing the editor in real use (the dummy instance is the
        # supported workflow instead).
        self.assertEqual([op.idname for op in layout.operators],
                         ['wm.y_make_custom_group_unique'])
        self.assertNotIn('wm.y_edit_custom_group',
                         [op.idname for op in layout.operators])
        self.assertIn(('NODE_MT_y_replace_layer_type_custom_group_menu', 'Change Group'),
                      layout.menus)

        # Missing group: the row keeps the same two actions; Change Group is the recovery action
        # the FR-16 alert above points at.
        picker = FakeLayout()
        ui.draw_custom_group_picker(picker, 'wm.y_new_layer')
        starter = [op for op in picker.operators if op.create_new_group]
        self.assertTrue(starter, 'the picker has no generate-starter entry')
        self.assertEqual(starter[0].text, 'Generate Starter Group')
        existing = [op for op in picker.operators
                    if not op.create_new_group and op.idname == 'wm.y_new_layer']
        self.assertIn(group.name, [op.text for op in existing])

        # Make Unique from the panel is functional, not just drawn.
        bpy.ops.wm.y_make_custom_group_unique(layer_name=layer.name)
        self.assertIsNot(layer.custom_group, group)
        self.assertEqual(bpy.ops.wm.y_make_custom_group_unique(layer_name=layer.name),
                         {'FINISHED'})

        # Panel state for a missing group: still Make Unique + Change Group, no Edit Group.
        self.assertTrue(custom_node_common.set_custom_layer_group(layer, None))
        missing_layout = FakeLayout()
        ui.draw_custom_layer_group_props(missing_layout, layer)
        self.assertEqual([op.idname for op in missing_layout.operators],
                         ['wm.y_make_custom_group_unique'])
        self.assertNotIn('wm.y_edit_custom_group',
                         [op.idname for op in missing_layout.operators])
        self.assertIn(('NODE_MT_y_replace_layer_type_custom_group_menu', 'Change Group'),
                      missing_layout.menus)


class TestCustomDummyInstances(CustomNodeTestBase):
    """The dummy-instance workflow: a group with no instance cannot be opened in the Shader Editor.

    A CUSTOM layer gets one unconnected instance of its group in the *material* tree, inside a
    labelled frame, so the user can Tab into it and edit the same datablock the layer source uses.
    The dummy is identified by a custom property plus its group pointer, never by name, and it is
    pruned when no CUSTOM layer references that group any more.
    """

    def material_tree(self):
        return self.mat.node_tree

    def yp_tree(self):
        return self.get_yp().id_data

    def yp_node(self):
        yp_tree = self.yp_tree()
        return next((n for n in self.material_tree().nodes
                     if n.type == 'GROUP' and n.node_tree is yp_tree), None)

    def dummy_frame(self):
        return next((n for n in self.material_tree().nodes
                     if n.type == 'FRAME'
                     and n.label == custom_node_common.CUSTOM_DUMMY_FRAME_LABEL), None)

    def dummies(self):
        return [n for n in self.material_tree().nodes
                if n.type == 'GROUP' and n.get(custom_node_common.CUSTOM_DUMMY_PROP)]

    def dummies_for(self, group):
        return [n for n in self.dummies() if n.node_tree is group]

    def material_links(self):
        return sorted((link.from_node.name, link.from_socket.name,
                       link.to_node.name, link.to_socket.name)
                      for link in self.material_tree().links)

    def prepare_layer_ui(self, layer):
        # `layer_common.remove_layer` resets the per-channel layer panel state at the end; in
        # headless runs nothing has populated it yet, so mirror `ui.update_yp_ui` first.
        channels = bpy.context.window_manager.ypui.layer_ui.channels
        channels.clear()
        for _ in layer.channels:
            channels.add()

    def test_01_creation_adds_one_unlinked_dummy_in_the_labeled_frame(self):
        group = self.make_group('DummyCreate', outputs=[('Color', 'NodeSocketColor')])
        layer = self.new_custom_layer('DummyCreate', name='DummyLayer')

        frame = self.dummy_frame()
        self.assertIsNotNone(frame, 'no dummy frame in the material tree')
        self.assertEqual(frame.label, 'Custom Layers: edit here, do not connect')
        self.assertTrue(frame.get(custom_node_common.CUSTOM_DUMMY_FRAME_PROP))

        dummies = self.dummies()
        self.assertEqual(len(dummies), 1)
        node = dummies[0]
        self.assertIs(node.node_tree, group)
        self.assertTrue(node.get(custom_node_common.CUSTOM_DUMMY_PROP))
        self.assertEqual(node.parent.as_pointer(), frame.as_pointer())

        # No links at all: the dummy must never become part of the material graph.
        touching = [link for link in self.material_tree().links
                    if link.from_node is node or link.to_node is node]
        self.assertEqual(touching, [])
        for socket in list(node.inputs) + list(node.outputs):
            self.assertEqual(len(socket.links), 0)

        # It lives in the material tree, never inside ucupaint's generated yp tree.
        self.assertEqual(node.id_data.as_pointer(), self.material_tree().as_pointer())
        self.assertNotEqual(layer.id_data.as_pointer(), self.material_tree().as_pointer())
        self.assertNotIn(node.name, [n.name for n in self.yp_tree().nodes])

        # Clear of the ucupaint node: left and down.
        yp_node = self.yp_node()
        self.assertIsNotNone(yp_node)
        self.assertLess(frame.location.x, yp_node.location.x)
        self.assertLess(frame.location.y, yp_node.location.y)

        # Idempotent, and the user's frame position is never changed by a later sync.
        location = tuple(frame.location)
        custom_node_common.ensure_custom_group_dummy(layer)
        self.assertEqual(self.dummy_frame().as_pointer(), frame.as_pointer())
        self.assertEqual(tuple(frame.location), location)
        self.assertEqual(len(self.dummies()), 1)

    def test_02_two_layers_on_one_group_share_a_dummy_two_groups_get_two(self):
        group_a = self.make_group('DummySharedA', outputs=[('Color', 'NodeSocketColor')])
        group_b = self.make_group('DummySharedB', outputs=[('Color', 'NodeSocketColor')])

        self.new_custom_layer('DummySharedA', name='SharedOne')
        self.new_custom_layer('DummySharedA', name='SharedTwo')
        self.assertEqual(len(self.dummies_for(group_a)), 1,
                         'two layers on one group duplicated the dummy')

        self.new_custom_layer('DummySharedB', name='SharedThree')
        self.assertEqual(len(self.dummies_for(group_a)), 1)
        self.assertEqual(len(self.dummies_for(group_b)), 1)
        self.assertEqual(len(self.dummies()), 2)

    def test_03_change_group_replaces_the_dummy_and_leaves_user_nodes(self):
        group_a = self.make_group('DummyChangeA', outputs=[('Color', 'NodeSocketColor')])
        group_b = self.make_group('DummyChangeB', outputs=[('Color', 'NodeSocketColor')])
        layer = self.new_custom_layer('DummyChangeA', name='ChangeLayer')
        self.assertEqual(len(self.dummies_for(group_a)), 1)

        # User-authored material nodes and a link between them: the dummy sync must not touch them.
        tree = self.material_tree()
        rgb = tree.nodes.new('ShaderNodeRGB')
        emission = tree.nodes.new('ShaderNodeEmission')
        tree.links.new(rgb.outputs[0], emission.inputs[0])
        user_names = {rgb.name, emission.name}
        user_links = self.material_links()

        self.assertEqual(bpy.ops.wm.y_replace_layer_type(
            type='CUSTOM', group_name='DummyChangeB', layer_name=layer.name), {'FINISHED'})

        self.assertEqual(self.dummies_for(group_a), [],
                         'the old group dummy survived a Change Group')
        self.assertEqual(len(self.dummies_for(group_b)), 1)
        self.assertEqual(len(self.dummies()), 1)
        self.assertEqual(user_links, self.material_links())
        self.assertTrue(user_names.issubset({n.name for n in tree.nodes}))

    def test_04_make_unique_adds_a_dummy_for_the_copy_and_keeps_the_originals(self):
        group = self.make_group('DummyUnique', outputs=[('Color', 'NodeSocketColor')])
        first = self.new_custom_layer('DummyUnique', name='UniqueOne')
        self.new_custom_layer('DummyUnique', name='UniqueTwo')
        self.assertEqual(len(self.dummies_for(group)), 1)

        self.assertEqual(bpy.ops.wm.y_make_custom_group_unique(layer_name=first.name),
                         {'FINISHED'})
        copy = first.custom_group
        self.assertIsNot(copy, group)
        self.assertEqual(len(self.dummies_for(group)), 1,
                         'the original group is still referenced by the other layer')
        self.assertEqual(len(self.dummies_for(copy)), 1,
                         'the copied group has no dummy instance')
        self.assertEqual(len(self.dummies()), 2)

    def test_05_removing_the_last_layer_prunes_its_dummy_and_frame(self):
        group = self.make_group('DummyDelete', outputs=[('Color', 'NodeSocketColor')])
        layer = self.new_custom_layer('DummyDelete', name='DeleteLayer')
        self.assertEqual(len(self.dummies_for(group)), 1)

        self.prepare_layer_ui(layer)
        yp = self.get_yp()
        layer_common.remove_layer(yp, common.get_layer_index(layer))

        self.assertEqual(self.dummies_for(group), [])
        self.assertEqual(self.dummies(), [])
        self.assertIsNone(self.dummy_frame(), 'the empty dummy frame was left behind')

    def test_06_a_layer_on_another_group_keeps_its_dummy_when_one_is_removed(self):
        group_a = self.make_group('DummyKeepA', outputs=[('Color', 'NodeSocketColor')])
        group_b = self.make_group('DummyKeepB', outputs=[('Color', 'NodeSocketColor')])
        self.new_custom_layer('DummyKeepA', name='KeepA')
        layer_b = self.new_custom_layer('DummyKeepB', name='KeepB')
        self.assertEqual(len(self.dummies()), 2)

        self.prepare_layer_ui(layer_b)
        yp = self.get_yp()
        layer_common.remove_layer(yp, common.get_layer_index(layer_b))

        self.assertEqual(self.dummies_for(group_b), [])
        self.assertEqual(len(self.dummies_for(group_a)), 1)
        self.assertIsNotNone(self.dummy_frame())

    def test_07_sync_and_reconnect_leave_the_dummy_untouched_and_unlinked(self):
        group = self.make_group('DummySync', outputs=[('Color', 'NodeSocketColor')])
        layer = self.new_custom_layer('DummySync', name='SyncLayer')
        node = self.dummies_for(group)[0]
        frame = self.dummy_frame()
        location = tuple(node.location)
        frame_location = tuple(frame.location)
        links_before = self.material_links()

        yp = self.get_yp()
        # Both repair entry points, plus the per-layer passes the handler uses.
        custom_node_common.sync_custom_layers(yp)
        custom_node_common.reconnect_custom_yp(yp)
        input_outputs.check_all_layer_channel_io_and_nodes(layer)
        node_connections.reconnect_layer_nodes(layer)

        self.assertEqual(self.dummies_for(group)[0].as_pointer(), node.as_pointer())
        self.assertEqual(self.dummy_frame().as_pointer(), frame.as_pointer())
        self.assertEqual(tuple(node.location), location)
        self.assertEqual(tuple(frame.location), frame_location)
        self.assertEqual(links_before, self.material_links())
        touching = [link for link in self.material_tree().links
                    if link.from_node is node or link.to_node is node]
        self.assertEqual(touching, [])

    def test_08_converting_away_prunes_the_dummy_and_frame(self):
        # CUSTOM -> NOISE: the dead `ensure_custom_group_dummy` branch left the old group's dummy
        # and frame behind even though the pointer was released.
        group = self.make_group('DummyConvertNoise', outputs=[('Color', 'NodeSocketColor')])
        layer = self.new_custom_layer('DummyConvertNoise', name='ConvertNoise')
        self.assertEqual(len(self.dummies_for(group)), 1)

        self.assertTrue(layer_common.replace_layer_type(layer, 'NOISE'))
        self.assertEqual(layer.type, 'NOISE')
        self.assertIsNone(layer.custom_group)
        self.assertEqual(self.dummies_for(group), [], 'the converted-away layer kept its dummy')
        self.assertEqual(self.dummies(), [])
        self.assertIsNone(self.dummy_frame(), 'the empty dummy frame survived the conversion')
        self.assertEqual(group.users, 0, 'the old group is still referenced')

    def test_09_converting_away_to_color_prunes_the_dummy_and_frame(self):
        # A second conversion target: the prune must not be specific to NOISE.
        group = self.make_group('DummyConvertColor', outputs=[('Color', 'NodeSocketColor')])
        layer = self.new_custom_layer('DummyConvertColor', name='ConvertColor')
        self.assertEqual(len(self.dummies_for(group)), 1)

        self.assertTrue(layer_common.replace_layer_type(layer, 'COLOR'))
        self.assertEqual(layer.type, 'COLOR')
        self.assertIsNone(layer.custom_group)
        self.assertEqual(self.dummies_for(group), [])
        self.assertEqual(self.dummies(), [])
        self.assertIsNone(self.dummy_frame())
        self.assertEqual(group.users, 0)

    def dummies_in(self, tree):
        return [node for node in tree.nodes
                if node.type == 'GROUP' and node.get(custom_node_common.CUSTOM_DUMMY_PROP)]

    def test_10_paste_into_another_material_adds_its_own_dummy(self):
        group = self.make_group('DummyPasteCross', outputs=[('Color', 'NodeSocketColor')])
        layer_a = self.new_custom_layer('DummyPasteCross', name='PasteSource')
        yp_a = self.get_yp()
        yp_a.active_layer_index = list(yp_a.layers).index(layer_a)
        self.assertEqual(self.copy_active_layer(), {'FINISHED'})
        self.assertEqual(len(self.dummies_for(group)), 1, 'the source material lost its dummy')
        source_dummy = self.dummies_for(group)[0]

        mat_b = self.add_second_material_yp()
        mat_b_tree = mat_b.node_tree
        yp_b = self.get_yp_for(mat_b)
        self.assertEqual(self.dummies_in(mat_b_tree), [], 'the fresh material started with a dummy')

        self.assertEqual(self.paste_layer(), {'FINISHED'})
        pasted = self.custom_layers(yp_b)[0]
        self.assertIs(pasted.custom_group, group)

        pasted_dummies = self.dummies_in(mat_b_tree)
        self.assertEqual(len(pasted_dummies), 1,
                         'paste into another material created no dummy there')
        node = pasted_dummies[0]
        self.assertIs(node.node_tree, group)
        self.assertEqual(node.label, '', 'the pasted dummy froze the group name in its label')
        touching = [link for link in mat_b_tree.links
                    if link.from_node is node or link.to_node is node]
        self.assertEqual(touching, [], 'the pasted dummy was connected to the material graph')

        # The source material's dummy is the same node as before and still there.
        self.assertEqual(self.dummies_for(group)[0].as_pointer(), source_dummy.as_pointer())
        self.assertEqual(len(self.dummies_in(self.material_tree())), 1)

    def test_11_deleting_the_group_datablock_prunes_the_blank_dummy(self):
        group = self.make_group('DummyLiveDelete', outputs=[('Color', 'NodeSocketColor')])
        layer = self.new_custom_layer('DummyLiveDelete', name='LiveDelete')
        self.assertEqual(len(self.dummies_for(group)), 1)

        # Prime the handler's usability cache before the deletion, so this is a real flip.
        bpy.context.view_layer.update()
        bpy.data.node_groups.remove(group)
        self.assertIsNone(layer.custom_group)
        bpy.context.view_layer.update()

        self.assertEqual(self.dummies(), [], 'the dummy whose group was deleted survived')
        self.assertIsNone(self.dummy_frame(), 'the empty frame survived a live group deletion')

    def test_12_renaming_the_group_updates_what_the_dummy_shows(self):
        group = self.make_group('DummyRenameOld', outputs=[('Color', 'NodeSocketColor')])
        layer = self.new_custom_layer('DummyRenameOld', name='RenameLayer')
        node = self.dummies_for(group)[0]
        self.assertEqual(node.label, '', 'a fresh dummy must not freeze the group name')

        # Simulate a dummy created by the earlier version, which wrote the then-current name.
        node.label = group.name
        group.name = 'DummyRenameNew'
        custom_node_common.ensure_custom_group_dummy(layer)

        node = self.dummies_for(group)[0]
        self.assertEqual(node.label, '', 'the stale label was not cleared')
        self.assertEqual(node.node_tree.name, 'DummyRenameNew',
                         'the dummy does not show the renamed group')

    def test_13_removing_the_ucupaint_node_prunes_the_dummy_and_frame(self):
        group = self.make_group('DummyRemoveYp', outputs=[('Color', 'NodeSocketColor')])
        self.new_custom_layer('DummyRemoveYp', name='RemoveYpLayer')
        self.assertEqual(len(self.dummies_for(group)), 1)
        self.assertIsNotNone(self.yp_node())

        self.assertEqual(bpy.ops.wm.y_remove_yp_node(), {'FINISHED'})

        self.assertIsNone(self.get_yp(), 'the ucupaint node was not removed')
        self.assertEqual(self.dummies_for(group), [],
                         'removing the ucupaint node left the dummy in the material tree')
        self.assertIsNone(self.dummy_frame(), 'removing the ucupaint node left the empty frame')

    def test_14_editing_through_the_dummy_changes_the_render(self):
        # The user workflow: Tab into the dummy and edit the group datablock. The render must follow.
        bpy.ops.wm.y_new_layer(name='Green', type='COLOR',
                               solid_color=(0.0, 1.0, 0.0), uv_map='UVMap')
        group = self.make_group('DummyRender', outputs=[('Color', 'NodeSocketColor')])
        rgb = group.nodes.new('ShaderNodeRGB')
        rgb.outputs[0].default_value = (1.0, 0.0, 0.0, 1.0)
        output = group.nodes.new('NodeGroupOutput')
        group.links.new(rgb.outputs[0], output.inputs['Color'])

        layer = self.new_custom_layer('DummyRender', name='RenderLayer')
        layer.channels[0].enable = True
        dummy = self.dummies_for(group)[0]
        self.assertIs(dummy.node_tree, layer.custom_group)

        restore = self.render_settings()
        try:
            red_pixel = self.render_center_pixel('custom_node_dummy_edit_red.png')
            self.assertGreater(red_pixel[0], red_pixel[1],
                               'the custom layer did not render red: %r' % (red_pixel,))

            # The edit goes through the dummy's own tree, i.e. the user Tab-ing into the instance.
            edited_rgb = next(node for node in dummy.node_tree.nodes
                              if node.type == 'RGB')
            edited_rgb.outputs[0].default_value = (0.0, 0.0, 1.0, 1.0)
            bpy.context.view_layer.update()

            blue_pixel = self.render_center_pixel('custom_node_dummy_edit_blue.png')
            self.assertGreater(blue_pixel[2], blue_pixel[0],
                               'the render did not follow the edit through the dummy: %r'
                               % (blue_pixel,))
            self.assertGreater(blue_pixel[2], blue_pixel[1],
                               'the render did not become blue: %r' % (blue_pixel,))
        finally:
            restore()
