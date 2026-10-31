"""T-11 acceptance run for spec 001 §6, headless portion.

Run with::

    blender --background --factory-startup --python \
        docs/specs/001-custom-node-layer/acceptance_5_2_3.py

Each checklist line is exercised on Blender 5.2.3 LTS in a fresh scratch object/material.
The script prints one ``ACCEPT <line> PASS|FAIL <evidence>`` record per line and writes the
same records to ``/tmp/opencode/t11_acceptance.txt``.  It never imports the feature's test
module: the checks drive the add-on's public operators and predicates directly.

The undo line needs a real event loop (Blender has no undo stack in ``--background``) and is
covered by ``acceptance_5_2_3_undo.py`` through ``./tests/run_ui.sh``.
"""

import contextlib
import importlib
import io
import os
import sys
import traceback

try:
    import addon_utils
    import bpy

    REPO_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))
    PACKAGE_NAME = os.path.basename(REPO_DIR)
    sys.path.insert(0, os.path.dirname(REPO_DIR))
    addon_utils.enable(PACKAGE_NAME, default_set=True)

    common = importlib.import_module(PACKAGE_NAME + '.common')
    custom_node_common = importlib.import_module(PACKAGE_NAME + '.custom_node_common')
    input_outputs = importlib.import_module(PACKAGE_NAME + '.input_outputs')
    layer_common = importlib.import_module(PACKAGE_NAME + '.layer_common')
    mask_common = importlib.import_module(PACKAGE_NAME + '.mask_common')
    modifier_common = importlib.import_module(PACKAGE_NAME + '.modifier_common')
    node_connections = importlib.import_module(PACKAGE_NAME + '.node_connections')
    bake_common = importlib.import_module(PACKAGE_NAME + '.bake_common')
    Layer = importlib.import_module(PACKAGE_NAME + '.Layer')
    ui = importlib.import_module(PACKAGE_NAME + '.ui')
except Exception:
    # An import-time failure would otherwise leave Blender's exit status at 0. Fail loudly so a
    # shell or CI that only reads the exit code still sees the run as broken. The
    # `--python-exit-code 1` flag in the documented runner covers what this guard cannot, such as
    # a syntax error in this file.
    traceback.print_exc()
    os._exit(1)

OUT_DIR = '/tmp/opencode'
RESULTS = []

CUBE_VERTS = [
    (-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
    (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1),
]
CUBE_FACES = [
    (0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1),
    (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0),
]


# ---------------------------------------------------------------------------------------------
# Small UI doubles, so a menu's real draw body can run without Blender's draw loop.
# ---------------------------------------------------------------------------------------------

class FakeOperator:
    def __init__(self, idname, kwargs):
        self.idname = idname
        self.text = kwargs.get('text', '')
        self.icon = kwargs.get('icon', '')
        self.socket_name = None
        for key, value in kwargs.items():
            setattr(self, key, value)


class FakeLayout:
    def __init__(self):
        self.operators = []
        self.labels = []
        self.menus = []

    def column(self, **kwargs): return self
    def row(self, **kwargs): return self
    def separator(self): pass

    def label(self, text='', icon='', **kwargs):
        self.labels.append((text, icon))

    def context_pointer_set(self, name='', ptr=None):
        pass

    def menu(self, idname, text='', icon='', **kwargs):
        self.menus.append((idname, text))

    def operator(self, idname, text='', icon='', **kwargs):
        op = FakeOperator(idname, dict(kwargs, text=text, icon=icon))
        self.operators.append(op)
        return op


# ---------------------------------------------------------------------------------------------
# Scratch scene
# ---------------------------------------------------------------------------------------------

class Scratch:
    """A fresh object + material + ucupaint node, removed on close."""

    def __init__(self, tag):
        self.tag = tag
        self.groups_before = set(bpy.data.node_groups.keys())
        self.images_before = set(bpy.data.images.keys())

        mesh = bpy.data.meshes.new(tag + 'Mesh')
        mesh.from_pydata(CUBE_VERTS, [], CUBE_FACES)
        mesh.uv_layers.new(name='UVMap')
        mesh.update()

        self.obj = bpy.data.objects.new(tag + 'Object', mesh)
        self.obj_name = self.obj.name
        bpy.context.scene.collection.objects.link(self.obj)

        self.mat = bpy.data.materials.new(tag + 'Material')
        self.mat_name = self.mat.name
        self.obj.data.materials.append(self.mat)

        self.cube = bpy.data.objects.get('Cube')
        self.cube_name = self.cube.name if self.cube else ''
        self.cube_hide = self.cube.hide_render if self.cube else False
        if self.cube: self.cube.hide_render = True

        bpy.context.view_layer.objects.active = self.obj
        self.obj.select_set(True)
        bpy.ops.wm.y_quick_ypaint_node_setup(type='BSDF_PRINCIPLED')

    def close(self):
        # A save/reopen reloads the datablocks, so never read the structs captured in __init__;
        # resolve by the stable names instead.
        cube = bpy.data.objects.get(self.cube_name) if self.cube_name else None
        if cube: cube.hide_render = self.cube_hide
        obj = bpy.data.objects.get(self.obj_name)
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

    def yp(self):
        for node in self.mat.node_tree.nodes:
            if node.type == 'GROUP' and node.node_tree and node.node_tree.yp.is_ypaint_node:
                return node.node_tree.yp
        raise AssertionError('no ucupaint node in ' + self.mat.name)

    def layer(self, name):
        return self.yp().layers[name]

    def active(self):
        yp = self.yp()
        return yp.layers[yp.active_layer_index]


def make_group(name, outputs, inputs=()):
    group = bpy.data.node_groups.new(name, 'ShaderNodeTree')
    for socket_name, socket_type in inputs:
        group.interface.new_socket(name=socket_name, in_out='INPUT', socket_type=socket_type)
    for socket_name, socket_type in outputs:
        group.interface.new_socket(name=socket_name, in_out='OUTPUT', socket_type=socket_type)
    return group


def interface_item(group, name, in_out):
    for item in group.interface.items_tree:
        if item.item_type == 'SOCKET' and item.in_out == in_out and item.name == name:
            return item
    raise AssertionError('no %s item %r in %r' % (in_out, name, group.name))


def source(layer):
    return common.get_source_tree(layer).nodes.get(layer.source)


def tree(layer):
    return common.get_tree(layer)


def constant_group(name, color=(1.0, 0.0, 0.0, 1.0), value=0.5):
    group = make_group(name, [('Color', 'NodeSocketColor'), ('Roughness', 'NodeSocketFloat')])
    output = group.nodes.new('NodeGroupOutput')
    rgb = group.nodes.new('ShaderNodeRGB')
    if len(color) == 3: color = (color[0], color[1], color[2], 1.0)
    rgb.outputs[0].default_value = color
    number = group.nodes.new('ShaderNodeValue')
    number.outputs[0].default_value = value
    group.links.new(rgb.outputs[0], output.inputs['Color'])
    group.links.new(number.outputs[0], output.inputs['Roughness'])
    return group


def new_custom(sc, group_name, name='Custom'):
    bpy.ops.wm.y_new_layer(name=name, type='CUSTOM', group_name=group_name, uv_map='UVMap')
    return sc.active()


def enable_channels(layer, yp, *names):
    for name in names:
        index = [root_ch.name for root_ch in yp.channels].index(name)
        layer.channels[index].enable = True


def reconnect(sc, layer):
    node_connections.reconnect_layer_nodes(layer)
    node_connections.reconnect_yp_nodes(sc.yp().id_data)


def render_setup():
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = 8
    scene.render.resolution_x = 32
    scene.render.resolution_y = 32
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'


def render_pixel(filename):
    render_setup()
    path = os.path.join(OUT_DIR, filename)
    bpy.context.scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    image = bpy.data.images.load(path, check_existing=False)
    width, height = image.size
    index = ((height // 2) * width + (width // 2)) * 4
    pixel = list(image.pixels[index:index + 4])
    bpy.data.images.remove(image)
    return pixel


def close_pixels(a, b, tolerance=2.0 / 255.0):
    return all(abs(x - y) <= tolerance for x, y in zip(a[:3], b[:3]))


def full_square_uvs(obj):
    mesh = obj.data
    uv_layer = mesh.uv_layers.active or mesh.uv_layers.new(name='UVMap')
    corners = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
    for poly in mesh.polygons:
        for k, loop_index in enumerate(poly.loop_indices):
            uv_layer.data[loop_index].uv = corners[k % 4]
    mesh.update()


def bake_target_index(yp, channel_name):
    for i, bt in enumerate(yp.bake_targets):
        if (bt.data_type == 'IMAGE' and bt.r.channel_name == channel_name
                and bt.g.channel_name == channel_name and bt.b.channel_name == channel_name):
            return i
    raise AssertionError('no image bake target for %r' % channel_name)


def configure_and_bake(sc, index):
    yp = sc.yp()
    bt = yp.bake_targets[index]
    bt.bake_settings = 'CUSTOM'
    bt.use_custom_resolution = True
    bt.width = bt.height = 128
    bt.hdr = True
    bt.fxaa = False
    bt.samples = 1
    bt.margin = 0
    bt.use_udim = False
    assert bpy.ops.wm.y_bake_single_target(bake_target_index=index, bake_device='CPU') == {'FINISHED'}
    bt = yp.bake_targets[index]
    for node in yp.id_data.nodes:
        if node.name == bt.baked_node:
            image = node.image
            break
    else:
        raise AssertionError('bake produced no image node')
    return list(image.pixels), tuple(image.size)


def assert_uniform(pixels, expected, tolerance, label):
    bad = []
    for i in range(0, len(pixels), 4):
        for channel, value in enumerate(expected):
            if abs(pixels[i + channel] - value) > tolerance:
                bad.append((i // 4, [round(pixels[i + j], 5) for j in range(3)]))
                break
        if len(bad) >= 3: break
    assert not bad, '%s: %r differ by more than %g' % (label, bad[:3], tolerance)


# ---------------------------------------------------------------------------------------------
# Checklist checks.  Each returns a short evidence string or raises.
# ---------------------------------------------------------------------------------------------

def check_01_picker_excludes_internal_trees():
    sc = Scratch('AccPick')
    try:
        suitable = make_group('AccSuitable', [('Color', 'NodeSocketColor')])
        internal_lib = make_group('~yPL AccInternalLib', [('Color', 'NodeSocketColor')])
        only_shader = make_group('AccOnlyShader', [('Shader', 'NodeSocketShader')])

        # A real layer tree (the `.yP Layer ` namespace, is_ypaint_layer_node set).
        bpy.ops.wm.y_new_layer(name='AccImage', type='COLOR', solid_color=(0.0, 1.0, 0.0),
                               uv_map='UVMap')
        layer_tree_name = tree(sc.active()).name

        names = [group.name for group in custom_node_common.get_custom_group_candidates()]
        assert suitable.name in names, 'the suitable group is missing: %r' % (names,)
        for excluded in (internal_lib.name, only_shader.name, layer_tree_name):
            assert excluded not in names, '%r was offered by the picker: %r' % (excluded, names)

        layout = FakeLayout()
        ui.draw_custom_group_picker(layout, 'wm.y_new_layer')
        offered = [op.text for op in layout.operators if op.idname == 'wm.y_new_layer']
        assert suitable.name in offered, 'the picker did not list the suitable group: %r' % (offered,)
        for excluded in (internal_lib.name, only_shader.name, layer_tree_name):
            assert excluded not in offered, '%r appeared in the picker: %r' % (excluded, offered)

        return 'candidates=%r; picker=%r' % (names, offered)
    finally:
        sc.close()


def check_02_starter_passthrough_and_channel_add():
    sc = Scratch('AccStarter')
    try:
        bpy.ops.wm.y_new_layer(name='Below', type='COLOR', solid_color=(0.0, 0.6, 0.0),
                               uv_map='UVMap')
        bpy.ops.wm.y_new_layer(name='Starter', type='CUSTOM', create_new_group=True,
                               group_name='AccStarterGroup', uv_map='UVMap')
        layer = sc.layer('Starter')
        group = layer.custom_group
        yp = sc.yp()
        assert group is not None, 'create_new_group produced no tree'

        channel_names = [root_ch.name for root_ch in yp.channels]
        inputs = [item.name for item in group.interface.items_tree
                  if item.item_type == 'SOCKET' and item.in_out == 'INPUT']
        outputs = [item.name for item in group.interface.items_tree
                   if item.item_type == 'SOCKET' and item.in_out == 'OUTPUT']
        assert inputs == channel_names + ['Vector'], 'starter inputs: %r' % (inputs,)
        assert outputs == channel_names + ['Alpha'], 'starter outputs: %r' % (outputs,)

        normal_name = next(root_ch.name for root_ch in yp.channels
                           if root_ch.special_type == 'NORMAL')
        group_input = next(n for n in group.nodes if n.type == 'GROUP_INPUT')
        group_output = next(n for n in group.nodes if n.type == 'GROUP_OUTPUT')
        for outp in group_output.inputs:
            assert len(outp.links) == 1, 'starter output %r is not fed once' % outp.name
            source = outp.links[0].from_node
            if outp.name == 'Alpha':
                # FR-31 as amended: Alpha is a constant 1.0 from a value node, not a group input.
                assert source.type == 'VALUE', 'Alpha is not fed from a value node'
                assert source.outputs[0].default_value == 1.0, 'Alpha value is not 1.0'
            elif outp.name == normal_name:
                # FR-31 as amended: Normal is a neutral tangent-space map, not the below stream.
                assert source.type == 'COMBXYZ', 'Normal is not fed from a constant vector'
                assert tuple(s.default_value for s in source.inputs) == (0.5, 0.5, 1.0), \
                    'Normal is not the neutral tangent-space map'
                assert outp.links[0].from_socket != group_input.outputs[outp.name]
            else:
                assert outp.links[0].from_socket == group_input.outputs[outp.name]

        on = render_pixel('acc_starter_on.png')
        layer.enable = False
        off = render_pixel('acc_starter_off.png')
        layer.enable = True
        assert close_pixels(on, off), 'starter layer changed the render: on=%r off=%r' % (on, off)

        before = custom_node_common.get_custom_interface_signature(group)
        bpy.ops.wm.y_add_new_ypaint_channel(name='AccExtra', type='VALUE')
        after = custom_node_common.get_custom_interface_signature(group)
        assert before == after, 'adding a root channel changed the starter group sockets'
        evidence = 'inputs=%r outputs=%r on=%r off=%r signature unchanged' % (
            inputs, outputs, [round(v, 3) for v in on[:3]], [round(v, 3) for v in off[:3]])
    finally:
        sc.close()

    # §6 line 3 / FR-31: a fresh starter layer is opaque. A transparent custom layer below
    # supplies the alpha-0 stream the old `Color Alpha` pass-through would have forwarded; the yp
    # alpha output is wired to the BSDF so the rendered A channel carries the layer alpha.
    opaque_sc = Scratch('AccStarterOpaque')
    try:
        transparent = make_group('AccTransparentBelow',
                                 [('Color', 'NodeSocketColor'), ('Alpha', 'NodeSocketFloat')])
        transparent_output = transparent.nodes.new('NodeGroupOutput')
        rgb = transparent.nodes.new('ShaderNodeRGB')
        rgb.outputs[0].default_value = (0.0, 0.0, 0.0, 0.0)
        number = transparent.nodes.new('ShaderNodeValue')
        number.outputs[0].default_value = 0.0
        transparent.links.new(rgb.outputs[0], transparent_output.inputs['Color'])
        transparent.links.new(number.outputs[0], transparent_output.inputs['Alpha'])

        below = new_custom(opaque_sc, 'AccTransparentBelow', name='Below')
        yp = opaque_sc.yp()
        color_index = [root_ch.name for root_ch in yp.channels].index('Color')
        below.channels[color_index].enable = True
        yp.channels[color_index].enable_alpha = True
        bpy.ops.wm.y_new_layer(name='Starter', type='CUSTOM', create_new_group=True,
                               group_name='AccOpaqueStarterGroup', uv_map='UVMap')
        starter = opaque_sc.layer('Starter')
        starter.channels[color_index].enable = True

        for each in (below, starter):
            input_outputs.check_all_layer_channel_io_and_nodes(each, tree(each))
            reconnect(opaque_sc, each)

        mat = opaque_sc.mat
        node_tree = mat.node_tree
        yp_node = next(n for n in node_tree.nodes
                       if n.type == 'GROUP' and n.node_tree and n.node_tree.yp.is_ypaint_node)
        output_node = node_tree.get_output_node('ALL')
        bsdf = output_node.inputs['Surface'].links[0].from_node
        node_tree.links.new(yp_node.outputs['Color Alpha'], bsdf.inputs['Alpha'])

        scene = bpy.context.scene
        old_film_transparent = scene.render.film_transparent
        old_color_mode = scene.render.image_settings.color_mode
        try:
            scene.render.film_transparent = True
            scene.render.image_settings.color_mode = 'RGBA'
            opaque = render_pixel('acc_starter_opaque.png')
        finally:
            scene.render.film_transparent = old_film_transparent
            scene.render.image_settings.color_mode = old_color_mode
        assert opaque[3] >= 1.0 - 2.0 / 255.0, \
            'fresh starter layer is not opaque: %r' % (opaque,)
        evidence += '; opacity alpha=%.3f pixel=[%.3f, %.3f, %.3f, %.3f]' % (
            opaque[3], opaque[0], opaque[1], opaque[2], opaque[3])
    finally:
        opaque_sc.close()

    return evidence


def check_03_color_roughness_binds_by_name():
    sc = Scratch('AccBind')
    try:
        constant_group('AccBindGroup', (1.0, 0.0, 0.0, 1.0), 0.5)
        layer = new_custom(sc, 'AccBindGroup')
        yp = sc.yp()
        enable_channels(layer, yp, 'Color', 'Roughness')
        reconnect(sc, layer)

        by_name = {root_ch.name: layer.channels[i].socket_input_name
                   for i, root_ch in enumerate(yp.channels)}
        assert by_name['Color'] == 'Color', by_name
        assert by_name['Roughness'] == 'Roughness', by_name
        color_index = [root_ch.name for root_ch in yp.channels].index('Color')
        roughness_index = [root_ch.name for root_ch in yp.channels].index('Roughness')
        assert layer.channels[color_index].enable and layer.channels[roughness_index].enable

        pixel = render_pixel('acc_bind.png')
        assert pixel[0] > pixel[1] + 0.1 and pixel[0] > pixel[2] + 0.1, \
            'the Color+Roughness layer did not render its red constant: %r' % (pixel,)
        return 'bindings=%r pixel=%r' % (
            {k: by_name[k] for k in ('Color', 'Roughness')}, [round(v, 3) for v in pixel[:3]])
    finally:
        sc.close()


def check_04_channel_menu_excludes_shader():
    sc = Scratch('AccMenu')
    try:
        group = make_group('AccMenuGroup', [
            ('Color', 'NodeSocketColor'),
            ('Rough', 'NodeSocketFloat'),
            ('Shader', 'NodeSocketShader'),
        ])
        layer = new_custom(sc, group.name)
        source_node = source(layer)
        available = [outp.name for outp in
                     common.get_available_source_outputs(source_node, layer.type)]

        context = type('FakeContext', (), {'channel': layer.channels[0]})()
        layout = FakeLayout()
        menu_self = type('FakeMenu', (), {'layout': layout})()
        ui.YLayerChannelInputMenu.draw(menu_self, context)
        menu_names = [op.socket_name for op in layout.operators
                      if op.idname == 'wm.y_set_layer_channel_input'
                      and op.text.startswith('Layer ')]
        assert available == ['Color', 'Rough'], 'available outputs: %r' % (available,)
        assert menu_names == ['Color', 'Rough'], 'menu entries: %r' % (menu_names,)
        assert 'Shader' not in menu_names and 'Shader' not in available
        return 'available=%r menu=%r' % (available, menu_names)
    finally:
        sc.close()


def check_05_rename_rewires_and_warns_until_rebound():
    sc = Scratch('AccRename')
    try:
        group = constant_group('AccRenameGroup', (1.0, 0.0, 0.0, 1.0), 0.5)
        layer = new_custom(sc, group.name)
        yp = sc.yp()
        rough_index = [root_ch.name for root_ch in yp.channels].index('Roughness')
        layer.channels[rough_index].enable = True
        reconnect(sc, layer)

        custom_node_common.clear_custom_sync_state()
        custom_node_common.sync_custom_layers(yp)
        bpy.context.view_layer.update()

        ch = layer.channels[rough_index]
        assert ch.socket_input_name == 'Roughness'

        interface_item(group, 'Roughness', 'OUTPUT').name = 'Rough'
        bpy.context.view_layer.update()

        # FR-10: the old name vanished, so the channel re-points automatically and warns.
        live_names = [outp.name for outp in
                      common.get_available_source_outputs(source(layer), layer.type)]
        assert ch.socket_input_name in live_names, \
            'binding %r is not a live output %r' % (ch.socket_input_name, live_names)
        assert ch.custom_fallback_binding, 'the automatic re-point was not flagged'
        warning = custom_node_common.get_custom_channel_warning(layer, ch)
        assert 're-pointed' in warning, 'warning text: %r' % (warning,)

        # Re-binding explicitly acknowledges it, exactly as the channel-source menu does.
        context = type('FakeContext', (), {'channel': ch, 'layer': layer})()
        operator = type('FakeOperator', (), {
            'socket_name': 'Rough', 'set_normal_input': False})()
        Layer.YSetLayerChannelInput.execute(operator, context)
        assert ch.socket_input_name == 'Rough'
        assert not ch.custom_fallback_binding
        assert custom_node_common.get_custom_channel_warning(layer, ch) == ''
        return 'renamed; fallback binding=%r warning=%r; after re-bind=%r' % (
            live_names[0], warning, ch.socket_input_name)
    finally:
        sc.close()


def check_06_delete_bound_output_falls_back():
    sc = Scratch('AccDelete')
    try:
        group = constant_group('AccDeleteGroup', (1.0, 0.0, 0.0, 1.0), 0.5)
        layer = new_custom(sc, group.name)
        yp = sc.yp()
        rough_index = [root_ch.name for root_ch in yp.channels].index('Roughness')
        layer.channels[rough_index].enable = True
        reconnect(sc, layer)

        custom_node_common.clear_custom_sync_state()
        custom_node_common.sync_custom_layers(yp)
        bpy.context.view_layer.update()
        ch = layer.channels[rough_index]
        assert ch.socket_input_name == 'Roughness'

        group.interface.remove(interface_item(group, 'Roughness', 'OUTPUT'))
        bpy.context.view_layer.update()

        live_names = [outp.name for outp in
                      common.get_available_source_outputs(source(layer), layer.type)]
        assert live_names == ['Color'], 'live outputs after deletion: %r' % (live_names,)
        assert ch.socket_input_name == 'Color', 'binding did not fall back: %r' % ch.socket_input_name
        assert ch.custom_fallback_binding
        assert custom_node_common.get_custom_sync_error(yp) == ''
        reconnect(sc, layer)
        pixel = render_pixel('acc_delete.png')
        assert pixel[0] > pixel[1] + 0.1, 'the fallback did not render: %r' % (pixel,)
        return 'binding fell back to %r; pixel=%r; no sync error' % (
            ch.socket_input_name, [round(v, 3) for v in pixel[:3]])
    finally:
        sc.close()


def check_07_vector_mapping_only_when_declared():
    sc = Scratch('AccVector')
    try:
        make_group('AccVectorGroup', [('Color', 'NodeSocketColor')],
                   inputs=[('Vector', 'NodeSocketVector')])
        with_vector = new_custom(sc, 'AccVectorGroup', name='WithVector')
        with_tree = tree(with_vector)
        mapping = with_tree.nodes.get(with_vector.mapping)
        assert mapping is not None, 'no mapping node for a group that declares Vector'
        assert len(source(with_vector).inputs['Vector'].links) == 1
        assert source(with_vector).inputs['Vector'].links[0].from_node == mapping

        make_group('AccNoVectorGroup', [('Color', 'NodeSocketColor')],
                   inputs=[('Color', 'NodeSocketColor')])
        without = new_custom(sc, 'AccNoVectorGroup', name='WithoutVector')
        without_tree = tree(without)
        assert without.mapping == ''
        assert without_tree.nodes.get('Mapping') is None
        dead = ('ShaderNodeMapping', 'ShaderNodeTexCoord', 'ShaderNodeUVMap')
        types = {node.bl_idname for node in without_tree.nodes}
        assert not (types & set(dead)), 'dead vector nodes: %r' % (types & set(dead))
        assert source(without).inputs.get('Vector') is None
        return 'with Vector: mapping=%r linked; without: mapping=%r dead=%r' % (
            mapping.bl_idname, without.mapping, types & set(dead))
    finally:
        sc.close()


def check_08_channel_inputs_receive_below_streams():
    sc = Scratch('AccInputs')
    try:
        make_group('AccWiringGroup',
                   outputs=[('Color', 'NodeSocketColor'), ('Roughness', 'NodeSocketFloat')],
                   inputs=[('Color', 'NodeSocketColor'), ('Color Alpha', 'NodeSocketFloat'),
                           ('Roughness', 'NodeSocketFloat'), ('MyOwnThing', 'NodeSocketFloat')])
        layer = new_custom(sc, 'AccWiringGroup')
        yp = sc.yp()
        for ch in layer.channels:
            ch.enable = True
        yp.channels[[root_ch.name for root_ch in yp.channels].index('Color')].enable_alpha = True
        input_outputs.check_all_layer_channel_io_and_nodes(layer, tree(layer))
        node_connections.reconnect_layer_nodes(layer)

        source_node = source(layer)
        start = tree(layer).nodes[common.TREE_START]
        wired = {}
        for name in ('Color', 'Color Alpha', 'Roughness'):
            inp = source_node.inputs.get(name)
            assert inp is not None, 'group input %r disappeared' % name
            assert len(inp.links) == 1, 'group input %r is not wired' % name
            assert inp.links[0].from_node == start, 'group input %r is not fed by Start' % name
            assert inp.links[0].from_socket.name == name
            wired[name] = inp.links[0].from_socket.name
        assert len(source_node.inputs['MyOwnThing'].links) == 0, 'MyOwnThing was wired'
        return 'wired=%r MyOwnThing unlinked' % (wired,)
    finally:
        sc.close()


def check_09_shared_group_and_make_unique():
    sc = Scratch('AccUnique')
    try:
        bpy.ops.wm.y_new_layer(name='A', type='CUSTOM', create_new_group=True,
                               group_name='AccSharedStarter', uv_map='UVMap')
        yp = sc.yp()
        group = sc.layer('A').custom_group
        color_index = [root_ch.name for root_ch in yp.channels].index('Color')

        bpy.ops.wm.y_new_layer(name='B', type='CUSTOM', group_name='AccSharedStarter',
                               uv_map='UVMap')
        layer_a = sc.layer('A')
        layer_b = sc.layer('B')
        assert layer_a.custom_group is group and layer_b.custom_group is group

        interface_item(group, 'Color', 'OUTPUT').name = 'Colour'
        custom_node_common.sync_custom_layers(yp)
        assert layer_a.channels[color_index].socket_input_name == 'Colour'
        assert layer_b.channels[color_index].socket_input_name == 'Colour'

        assert bpy.ops.wm.y_make_custom_group_unique(layer_name='A') == {'FINISHED'}
        layer_a = sc.layer('A')
        layer_b = sc.layer('B')
        unique = layer_a.custom_group
        assert unique is not group and layer_b.custom_group is group
        assert source(layer_a).node_tree is unique
        assert source(layer_b).node_tree is group

        interface_item(group, 'Colour', 'OUTPUT').name = 'Tint'
        custom_node_common.sync_custom_layers(yp)
        layer_a = sc.layer('A')
        layer_b = sc.layer('B')
        assert layer_b.channels[color_index].socket_input_name == 'Tint'
        assert layer_a.channels[color_index].socket_input_name == 'Colour'
        return 'shared edit followed by both; after Make Unique only B follows (%r vs %r)' % (
            layer_a.channels[color_index].socket_input_name,
            layer_b.channels[color_index].socket_input_name)
    finally:
        sc.close()


def check_10_bake_constant_color():
    sc = Scratch('AccBakeColor')
    try:
        full_square_uvs(sc.obj)
        constant_group('AccBakeConst', (0.25, 0.5, 0.75), 0.3)
        layer = new_custom(sc, 'AccBakeConst')
        yp = sc.yp()
        index = bake_target_index(yp, 'Color')
        enable_channels(layer, yp, 'Color')
        reconnect(sc, layer)
        pixels, size = configure_and_bake(sc, index)
        assert size == (128, 128), size
        assert_uniform(pixels, (0.25, 0.5, 0.75), 1.0 / 255.0, 'Color bake')
        return '128x128 Color bake uniform at (0.25, 0.5, 0.75) +/- 1/255'
    finally:
        sc.close()


def check_11_bake_value_channel():
    sc = Scratch('AccBakeValue')
    try:
        full_square_uvs(sc.obj)
        constant_group('AccBakeValueConst', (0.25, 0.5, 0.75), 0.3)
        layer = new_custom(sc, 'AccBakeValueConst')
        yp = sc.yp()
        index = bake_target_index(yp, 'Roughness')
        enable_channels(layer, yp, 'Roughness')
        reconnect(sc, layer)
        pixels, size = configure_and_bake(sc, index)
        assert_uniform(pixels, (0.3, 0.3, 0.3), 1.0 / 255.0, 'Roughness VALUE bake')
        return '128x128 VALUE bake uniform at 0.3 +/- 1/255'
    finally:
        sc.close()


def check_12_merged_bake_skipped_for_two_objects():
    sc = Scratch('AccMerge')
    try:
        full_square_uvs(sc.obj)
        constant_group('AccMergeConst', (0.25, 0.5, 0.75), 0.3)
        new_custom(sc, 'AccMergeConst')
        mesh2 = sc.obj.data.copy()
        obj2 = bpy.data.objects.new('AccMergeObject2', mesh2)
        bpy.context.scene.collection.objects.link(obj2)
        try:
            yp = sc.yp()
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                problematic = bake_common.is_join_objects_problematic(yp, sc.mat)
            notice = buffer.getvalue()
            assert problematic, 'is_join_objects_problematic returned False for a custom layer'
            assert 'custom node layer' in notice, notice
            assert 'Merged bake is not happening' in notice, notice

            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                objs, _ = bake_common.prepare_objs_before_baking(
                    sc.mat, yp, [sc.obj, obj2], 'UVMap')
            assert len(objs) == 2, 'objects were merged despite the custom layer: %d' % len(objs)

            index = bake_target_index(yp, 'Color')
            pixels, _ = configure_and_bake(sc, index)
            assert_uniform(pixels, (0.25, 0.5, 0.75), 1.0 / 255.0, 'per-object bake')
            return 'merged skipped; notice=%r; per-object bake uniform' % (
                notice.strip().splitlines()[-1] if notice.strip() else '')
        finally:
            bpy.data.objects.remove(obj2, do_unlink=True)
            if mesh2.users == 0: bpy.data.meshes.remove(mesh2)
    finally:
        sc.close()


def check_13a_save_and_reopen():
    sc = Scratch('AccSave')
    path = os.path.join(OUT_DIR, 'acc_save_reopen.blend')
    try:
        constant_group('AccSaveGroup', (1.0, 0.0, 0.0, 1.0), 0.5)
        layer = new_custom(sc, 'AccSaveGroup')
        yp = sc.yp()
        enable_channels(layer, yp, 'Color')
        reconnect(sc, layer)
        layer_name = layer.name
        group_name = layer.custom_group.name
        mat_name = sc.mat_name
        before = render_pixel('acc_save_before.png')

        assert bpy.ops.wm.save_as_mainfile(filepath=path) == {'FINISHED'}
        assert bpy.ops.wm.open_mainfile(filepath=path) == {'FINISHED'}

        mat = bpy.data.materials.get(mat_name)
        assert mat is not None, 'the material did not survive save/reopen'
        yp = None
        for node in mat.node_tree.nodes:
            if node.type == 'GROUP' and node.node_tree and node.node_tree.yp.is_ypaint_node:
                yp = node.node_tree.yp
                break
        assert yp is not None, 'the ucupaint node did not survive save/reopen'
        layer = yp.layers[layer_name]
        assert layer.type == 'CUSTOM'
        assert layer.custom_group is bpy.data.node_groups[group_name]
        assert source(layer).node_tree is bpy.data.node_groups[group_name]
        color_index = [root_ch.name for root_ch in yp.channels].index('Color')
        assert layer.channels[color_index].socket_input_name == 'Color'

        after = render_pixel('acc_save_after.png')
        assert close_pixels(before, after), 'the layer rendered differently after reopen: %r vs %r' % (
            before, after)
        return 'reopened %s: group=%r binding=%r pixel before=%r after=%r' % (
            os.path.basename(path), group_name, layer.channels[color_index].socket_input_name,
            [round(v, 3) for v in before[:3]], [round(v, 3) for v in after[:3]])
    finally:
        sc.close()


def check_14_node_tree_none_missing_state():
    # The literal FR-16 action from spec §6 line 14: clear *only* the source node's tree and leave
    # `layer.custom_group` pointing at the still-valid group. Before the T-11 fix this stayed usable
    # (grey render, channel warning); now it is the missing-group state, bypassed like a disabled
    # layer, and restoring the tree brings it back in one update.
    sc = Scratch('AccMissing')
    try:
        bpy.ops.wm.y_new_layer(name='Green', type='COLOR', solid_color=(0.0, 1.0, 0.0),
                               uv_map='UVMap')
        group = constant_group('AccMissingGroup', (1.0, 0.0, 0.0, 1.0), 0.5)
        layer = new_custom(sc, 'AccMissingGroup')
        yp = sc.yp()
        enable_channels(layer, yp, 'Color')
        reconnect(sc, layer)
        bpy.context.view_layer.update()
        assert custom_node_common.is_custom_layer_group_usable(layer)
        assert layer.custom_group is group, 'the pointer did not name the group before the probe'

        # Pointer intact, source tree gone.
        source(layer).node_tree = None
        bpy.context.view_layer.update()

        assert layer.custom_group is group, 'clearing the source tree changed the pointer'
        assert layer.name in [entry.name for entry in yp.layers], 'the layer left the stack'
        assert custom_node_common.get_custom_layer_warning(layer) == 'Missing node group'
        assert not custom_node_common.is_custom_layer_group_usable(layer)
        assert custom_node_common.get_custom_sync_error(yp) == ''
        node = yp.id_data.nodes.get(layer.group_node)
        touching = [link for link in yp.id_data.links
                    if link.from_node == node or link.to_node == node] if node else []
        assert touching == [], 'the missing layer is still spliced: %r' % (touching,)
        pixel = render_pixel('acc_missing.png')
        assert pixel[1] > pixel[0], 'the below layer did not show through: %r' % (pixel,)

        # Restoring the same tree re-splices in one update and clears the missing state.
        source(layer).node_tree = group
        bpy.context.view_layer.update()
        assert custom_node_common.is_custom_layer_group_usable(layer), \
            'restoring the tree did not make the layer usable again'
        assert custom_node_common.get_custom_layer_warning(layer) == ''
        restored = render_pixel('acc_missing_restored.png')
        assert restored[0] > restored[1], 'the restored layer did not render red: %r' % (restored,)
        return ('pointer kept; warning=%r; bypassed; pixel=%r; restored pixel=%r' % (
            'Missing node group', [round(v, 3) for v in pixel[:3]],
            [round(v, 3) for v in restored[:3]]))
    finally:
        sc.close()


def check_15_toggles_do_not_change_the_render():
    sc = Scratch('AccToggle')
    try:
        group = make_group('AccToggleGroup', [('Color', 'NodeSocketColor')],
                           inputs=[('Color', 'NodeSocketColor')])
        input_node = group.nodes.new('NodeGroupInput')
        output_node = group.nodes.new('NodeGroupOutput')
        # Pass-through of the below-layers colour; with no Alpha output the layer is opaque, so the
        # render is the layer itself and a mask/modifier that is an identity cannot show through.
        group.links.new(input_node.outputs['Color'], output_node.inputs['Color'])
        layer = new_custom(sc, 'AccToggleGroup')
        yp = sc.yp()
        enable_channels(layer, yp, 'Color')
        reconnect(sc, layer)
        baseline = render_pixel('acc_toggle_baseline.png')

        # Smooth bump on the height channel.
        height_index = [root_ch.name for root_ch in yp.channels].index('Height')
        layer.channels[height_index].enable = True
        layer.channels[height_index].normal_map_type = 'BUMP_MAP'
        reconnect(sc, layer)
        root_height = common.get_root_height_channel(yp)
        root_height.enable_smooth_bump = True
        input_outputs.check_all_channel_ios(yp)
        smooth_pixel = render_pixel('acc_toggle_smooth.png')
        root_height.enable_smooth_bump = False
        input_outputs.check_all_channel_ios(yp)

        # A full-white mask: MULTIPLY by 1.0 leaves the render alone.
        image = bpy.data.images.new('AccWhiteMask', width=4, height=4, float_buffer=True)
        image.colorspace_settings.name = 'Non-Color'
        image.pixels = [1.0] * (4 * 4 * 4)
        mask = mask_common.add_new_mask(layer, 'White', 'IMAGE', 'UV', 'UVMap', image=image)
        mask.blend_type = 'MULTIPLY'
        layer.enable_masks = True
        reconnect(sc, layer)
        mask_pixel = render_pixel('acc_toggle_mask.png')

        # An identity MATH modifier (default MULTIPLY by 1.0).
        modifier = modifier_common.add_new_modifier(layer.channels[0], 'MATH')
        reconnect(sc, layer)
        modifier_pixel = render_pixel('acc_toggle_modifier.png')
        modifier.enable = False
        reconnect(sc, layer)
        modifier_off_pixel = render_pixel('acc_toggle_modifier_off.png')

        for label, pixel in (('smooth bump', smooth_pixel), ('mask', mask_pixel),
                             ('modifier', modifier_pixel),
                             ('modifier off', modifier_off_pixel)):
            assert close_pixels(baseline, pixel), \
                '%s changed the render: baseline=%r after=%r' % (label, baseline, pixel)

        # Preview is expected to change *what is displayed*; the acceptance proxy is that its
        # viewer wiring appears and disappears (pixel parity with NOISE is the parity suite's row f).
        yp.preview_mode = False
        yp.preview_mode_channel_index = [root_ch.name for root_ch in yp.channels].index('Color')
        yp.preview_mode_type = 'LAYER'
        yp.preview_mode = True
        assert sc.mat.node_tree.nodes.get(common.EMISSION_VIEWER) is not None, \
            'layer preview created no Emission Viewer'
        yp.preview_mode = False
        assert sc.mat.node_tree.nodes.get(common.EMISSION_VIEWER) is None, \
            'layer preview off left the Emission Viewer behind'

        return ('smooth/mask/modifier unchanged (base=%r); preview viewer present on, absent off'
                % [round(v, 3) for v in baseline[:3]])
    finally:
        sc.close()


CHECKS = [
    ('L1 picker excludes internal trees', check_01_picker_excludes_internal_trees),
    ('L2 starter pass-through + channel add', check_02_starter_passthrough_and_channel_add),
    ('L3 Color+Roughness renders/binds by name', check_03_color_roughness_binds_by_name),
    ('L4 channel source menu excludes shader', check_04_channel_menu_excludes_shader),
    ('L5 rename -> live rewire + warning until rebound', check_05_rename_rewires_and_warns_until_rebound),
    ('L6 delete bound output -> fallback, renders', check_06_delete_bound_output_falls_back),
    ('L7 Vector mapping only when declared', check_07_vector_mapping_only_when_declared),
    ('L8 channel inputs receive below streams', check_08_channel_inputs_receive_below_streams),
    ('L9 shared group then Make Unique', check_09_shared_group_and_make_unique),
    ('L10 bake constant (0.25,0.5,0.75)', check_10_bake_constant_color),
    ('L11 bake VALUE 0.3', check_11_bake_value_channel),
    ('L12 two objects: merged bake skipped', check_12_merged_bake_skipped_for_two_objects),
    ('L13a save and reopen', check_13a_save_and_reopen),
    ('L14 node_tree=None missing state', check_14_node_tree_none_missing_state),
    ('L15 toggles do not change the render', check_15_toggles_do_not_change_the_render),
]


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    lines = []
    for label, function in CHECKS:
        try:
            evidence = function()
            verdict = 'PASS'
        except Exception:
            verdict = 'FAIL'
            evidence = traceback.format_exc().strip().splitlines()[-1]
        lines.append('ACCEPT %s %s %s' % (label, verdict, evidence))
        print(lines[-1], flush=True)

    report = '\n'.join(lines) + '\n'
    with open(os.path.join(OUT_DIR, 't11_acceptance.txt'), 'w') as handle:
        handle.write(report)
    print('\n' + report)
    # A failing line must make the run fail: otherwise a regression in any check is invisible to a
    # shell or CI that only reads the exit status.
    failed = [line for line in lines if ' FAIL ' in line]
    os._exit(1 if failed else 0)


# The bake operator reads `bpy.context.space_data`; background mode has no current area, so run
# the checklist inside the same first-screen-area override `tests/run_tests.py` uses.
try:
    window = getattr(bpy.context, 'window', None)
    if window is not None and window.screen is not None and window.screen.areas:
        override = bpy.context.temp_override(
            window=window, screen=window.screen, area=window.screen.areas[0])
        with override:
            main()
    else:
        main()
except SystemExit:
    raise
except Exception:
    # Any failure before `main` reaches its per-check exit code (for example the override setup)
    # must not report success: Blender exits 0 after a Python exception it did not expect.
    traceback.print_exc()
    os._exit(1)
