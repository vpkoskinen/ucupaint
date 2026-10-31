"""Parity tests for spec 001 §4.7 rows a–h (FR-23 … FR-30).

Every row builds a ``CUSTOM`` layer and an otherwise identical ``NOISE`` layer in the same
ucupaint node, applies the same operation to both, and compares (1) the channel-chain graph
after the source and (2) the rendered centre pixel. The custom source is a little user group
that outputs a constant; the NOISE source is replaced by the same constant so the comparison
isolates the layer machinery rather than the generator.

Tolerance: the scenes are flat constants rendered at 32×32 with 8 Cycles samples, so the only
error is 8-bit PNG quantisation; a ±2/255 (0.00785) tolerance is used for every pixel check.

FR-27 note: CUSTOM now nests like NOISE for smooth bump, so row e's assertion checks the nested
instance's passthrough input (render unchanged, input link still present). The rendered
CUSTOM-vs-NOISE comparison under nesting lives in
``tests/test_nested_source.py::TestNestedCustomSource::test_06``.
"""

import importlib
import os

import bpy

from test_custom_node import CustomNodeTestBase

common = importlib.import_module(os.path.basename(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) + '.common')
node_connections = importlib.import_module(os.path.basename(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) + '.node_connections')
input_outputs = importlib.import_module(os.path.basename(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) + '.input_outputs')
modifier_common = importlib.import_module(os.path.basename(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) + '.modifier_common')
mask_common = importlib.import_module(os.path.basename(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) + '.mask_common')
MaskModifier = importlib.import_module(os.path.basename(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) + '.MaskModifier')

PIXEL_TOLERANCE = 2.0 / 255.0


class CustomParityBase(CustomNodeTestBase):
    """Helpers shared by the parity rows."""

    # -- scene ---------------------------------------------------------------------------

    def make_constant_group(self, name, color=(1.0, 0.0, 0.0, 1.0), value=0.5):
        group = self.make_group(name, [
            ('Color', 'NodeSocketColor'),
            ('Roughness', 'NodeSocketFloat'),
        ], inputs=[('Vector', 'NodeSocketVector')])
        output = group.nodes.new('NodeGroupOutput')
        rgb = group.nodes.new('ShaderNodeRGB')
        rgb.outputs[0].default_value = color
        number = group.nodes.new('ShaderNodeValue')
        number.outputs[0].default_value = value
        group.links.new(rgb.outputs[0], output.inputs['Color'])
        group.links.new(number.outputs[0], output.inputs['Roughness'])
        return group

    def build_custom(self, color=(1.0, 0.0, 0.0, 1.0), name='Custom'):
        group = self.make_constant_group(name + 'Group', color)
        layer = self.new_custom_layer(group.name, name=name)
        layer.channels[0].enable = True
        return layer

    def build_noise(self, name='Noise'):
        bpy.ops.wm.y_new_layer(name=name, type='NOISE', uv_map='UVMap')
        layer = self.get_active_layer()
        layer.channels[0].enable = True
        return layer

    def layers_by_name(self, *names):
        yp = self.get_yp()
        return [next(lay for lay in yp.layers if lay.name == name) for name in names]

    def build_pair(self, color=(1.0, 0.0, 0.0, 1.0)):
        # Layer insertion can move a stored layer reference to a new collection slot, so the
        # layers are resolved by name once both exist.
        self.build_custom(color)
        self.build_noise()
        return self.layers_by_name('Custom', 'Noise')

    def normalize_noise_source(self, layer, color):
        """Replace the noise generator feed with the same constant the custom group outputs."""
        tree = self.get_layer_tree(layer)
        source = self.get_layer_source(layer)
        targets = [link.to_socket for link in tree.links if link.from_node == source]
        for target in targets:
            for link in list(target.links):
                tree.links.remove(link)
        rgb = tree.nodes.new('ShaderNodeRGB')
        rgb.name = 'ParityConstant'
        rgb.outputs[0].default_value = color
        for target in targets:
            tree.links.new(rgb.outputs[0], target)
        return {source, rgb}

    # -- graph ---------------------------------------------------------------------------

    def chain_links(self, layer, excluded_nodes):
        """Links of the layer tree excluding the source (and the replacement constant)."""
        tree = self.get_layer_tree(layer)
        return sorted(
            (link.from_node.bl_idname, link.from_socket.name,
             link.to_node.bl_idname, link.to_socket.name)
            for link in tree.links
            if link.from_node not in excluded_nodes and link.to_node not in excluded_nodes)

    def custom_excluded(self, layer):
        return {self.get_layer_source(layer)}

    # -- render --------------------------------------------------------------------------

    def assert_pixels_close(self, a, b, label):
        for ca, cb in zip(a, b):
            self.assertAlmostEqual(ca, cb, delta=PIXEL_TOLERANCE,
                                   msg='%s: %r != %r' % (label, a, b))

    def two_layer_pixels(self, custom, noise, label, color):
        """Render each layer alone, re-applying the constant after the reconnect pass."""
        yp = custom.id_data.yp
        restore = self.render_settings()
        try:
            custom.enable = True
            noise.enable = False
            node_connections.reconnect_yp_nodes(yp.id_data)
            custom_pixel = list(self.render_center_pixel(label + '_custom.png'))

            custom.enable = False
            noise.enable = True
            node_connections.reconnect_yp_nodes(yp.id_data)
            # `reconnect_layer_nodes` rebuilds the chain from the noise source, so the constant
            # replacement has to be applied after it and before the render.
            self.normalize_noise_source(noise, color)
            noise_pixel = list(self.render_center_pixel(label + '_noise.png'))
        finally:
            custom.enable = True
            noise.enable = True
            restore()
        return custom_pixel, noise_pixel

class TestParityRowA(CustomParityBase):
    """a — enable/disable, reorder, parent under a Group layer (FR-23)."""

    def test_01_enable_disable_and_reorder(self):
        custom, noise = self.build_pair()
        yp = self.get_yp()

        # Enable/disable: both behave identically and follow the same wiring predicate.
        for layer in (custom, noise):
            self.assert_yp_layer_wired(layer)
            layer.enable = False
            node_connections.reconnect_yp_nodes(yp.id_data)
            self.assert_yp_layer_bypassed(layer)
            layer.enable = True
            node_connections.reconnect_yp_nodes(yp.id_data)
            self.assert_yp_layer_wired(layer)

        # Reorder: move each layer to the bottom and reconnect. Layer insertion/move can shift a
        # stored Python layer reference to another collection slot, so re-resolve by name.
        for name in ('Custom', 'Noise'):
            layer = self.layers_by_name(name)[0]
            index = [lay.name for lay in yp.layers].index(layer.name)
            yp.layers.move(index, 0)
            node_connections.reconnect_yp_nodes(yp.id_data)
            self.assert_yp_layer_wired(self.layers_by_name(name)[0])
        custom, noise = self.layers_by_name('Custom', 'Noise')

        excluded = self.normalize_noise_source(noise, (1.0, 0.0, 0.0, 1.0))
        self.assertEqual(self.chain_links(custom, self.custom_excluded(custom)),
                         self.chain_links(noise, excluded))
        custom_pixel, noise_pixel = self.two_layer_pixels(custom, noise, 'parity_a', (1.0, 0.0, 0.0, 1.0))
        self.assert_pixels_close(custom_pixel, noise_pixel, 'row a enable/reorder')

    def test_02_parent_under_a_group_layer(self):
        # A Group layer first, then both layers are added with that group active, so the real
        # add-layer path parents them (no hand-set indices).
        bpy.ops.wm.y_new_layer(name='Parent', type='GROUP', uv_map='UVMap')
        yp = self.get_yp()
        parent = next(lay for lay in yp.layers if lay.name == 'Parent')
        yp.active_layer_index = [lay.name for lay in yp.layers].index(parent.name)

        custom, noise = self.build_pair()
        parent_index = [lay.name for lay in yp.layers].index(parent.name)

        self.assertEqual(custom.parent_idx, parent_index)
        self.assertEqual(noise.parent_idx, parent_index)
        input_outputs.check_all_channel_ios(yp)
        # A child layer is represented inside the Group layer's channel chain; its parent index is
        # the linkage this row verifies (the render and chain comparisons below cover the result).
        self.assertEqual(custom.parent_idx, parent_index)
        self.assertEqual(noise.parent_idx, parent_index)

        excluded = self.normalize_noise_source(noise, (1.0, 0.0, 0.0, 1.0))
        self.assertEqual(self.chain_links(custom, self.custom_excluded(custom)),
                         self.chain_links(noise, excluded))
        custom_pixel, noise_pixel = self.two_layer_pixels(custom, noise, 'parity_a_parent', (1.0, 0.0, 0.0, 1.0))
        self.assert_pixels_close(custom_pixel, noise_pixel, 'row a parent')


class TestParityRowB(CustomParityBase):
    """b — layer mask, mask blend, transition bump, mask modifiers (FR-24)."""

    def half_mask(self, layer):
        image = bpy.data.images.new('ParityHalfMask', width=4, height=4, float_buffer=True)
        image.colorspace_settings.name = 'Non-Color'
        image.pixels = [0.5] * (4 * 4 * 4)
        mask = mask_common.add_new_mask(layer, 'Half', 'IMAGE', 'UV', 'UVMap', image=image)
        mask.blend_type = 'MULTIPLY'
        layer.enable_masks = True
        return mask

    def test_01_mask_blend_transition_bump_and_modifier(self):
        # A dark layer below so the 50 % mask is visible.
        bpy.ops.wm.y_new_layer(name='Below', type='COLOR',
                               solid_color=(0.05, 0.1, 0.2), uv_map='UVMap')
        below = self.get_active_layer()
        below.channels[0].enable = True

        custom, noise = self.build_pair((1.0, 0.0, 0.0, 1.0))
        yp = self.get_yp()
        below = self.layers_by_name('Below')[0]
        below.channels[0].enable = True
        height_index = [root_ch.name for root_ch in yp.channels].index('Height')

        for layer in (custom, noise):
            mask = self.half_mask(layer)
            # Mask modifier: an invert keeps the same nodes in both mask trees.
            MaskModifier.add_new_mask_modifier(mask, 'INVERT')
            # Transition bump lives on the height channel and needs a mask/stencil chain.
            layer.channels[height_index].enable = True
            layer.channels[height_index].normal_map_type = 'BUMP_MAP'
            layer.channels[height_index].enable_transition_bump = True
            node_connections.reconnect_layer_nodes(layer)
            node_connections.reconnect_yp_nodes(yp.id_data)

        # Both trees build the same mask machinery: layer links, mask links and modifier nodes.
        # The comparison is the layer/mask machinery this row adds, after the source is normalised;
        # the rendered result confirms the whole path.
        excluded = self.normalize_noise_source(noise, (1.0, 0.0, 0.0, 1.0))
        self.assertEqual(self.chain_links(custom, self.custom_excluded(custom)),
                         self.chain_links(noise, excluded))

        custom_pixel, noise_pixel = self.two_layer_pixels(custom, noise, 'parity_b', (1.0, 0.0, 0.0, 1.0))
        self.assert_pixels_close(custom_pixel, noise_pixel, 'row b')


class TestParityRowC(CustomParityBase):
    """c — channel modifiers: invert, curve, math, colour ramp (FR-25)."""

    def add_modifiers(self, layer):
        ch = layer.channels[0]
        for modifier_type in ('INVERT', 'RGB_CURVE', 'MATH', 'COLOR_RAMP'):
            modifier_common.add_new_modifier(ch, modifier_type)
        node_connections.reconnect_layer_nodes(layer)

    def test_01_modifier_stack_matches(self):
        custom, noise = self.build_pair((0.2, 0.6, 0.9, 1.0))
        yp = self.get_yp()

        self.add_modifiers(custom)
        self.add_modifiers(noise)
        node_connections.reconnect_yp_nodes(yp.id_data)

        # The comparison is the modifier chain this row adds, after the source is normalised.
        excluded = self.normalize_noise_source(noise, (0.2, 0.6, 0.9, 1.0))
        self.assertEqual(self.chain_links(custom, self.custom_excluded(custom)),
                         self.chain_links(noise, excluded))

        custom_pixel, noise_pixel = self.two_layer_pixels(custom, noise, 'parity_c', (0.2, 0.6, 0.9, 1.0))
        self.assert_pixels_close(custom_pixel, noise_pixel, 'row c')


class TestParityRowD(CustomParityBase):
    """d — channel override and swizzle (FR-26)."""

    def test_01_swizzle_matches(self):
        custom, noise = self.build_pair((0.2, 0.6, 0.9, 1.0))
        yp = self.get_yp()

        for layer in (custom, noise):
            layer.channels[0].swizzle_input_mode = 'R'
            node_connections.reconnect_layer_nodes(layer)
        node_connections.reconnect_yp_nodes(yp.id_data)

        excluded = self.normalize_noise_source(noise, (0.2, 0.6, 0.9, 1.0))
        self.assertEqual(self.chain_links(custom, self.custom_excluded(custom)),
                         self.chain_links(noise, excluded))

        custom_pixel, noise_pixel = self.two_layer_pixels(custom, noise, 'parity_d', (0.2, 0.6, 0.9, 1.0))
        self.assert_pixels_close(custom_pixel, noise_pixel, 'row d swizzle')

    def test_02_channel_override_matches(self):
        custom, noise = self.build_pair((0.2, 0.6, 0.9, 1.0))
        yp = self.get_yp()

        # The override replaces the layer source with a generated one, in both trees. There is no
        # base-source link left to normalise, so this row compares the graph only.
        for layer in (custom, noise):
            ch = layer.channels[0]
            ch.override_type = 'NOISE'
            ch.override = True
            node_connections.reconnect_layer_nodes(layer)
        node_connections.reconnect_yp_nodes(yp.id_data)

        self.assertEqual(self.chain_links(custom, self.custom_excluded(custom)),
                         self.chain_links(noise, {self.get_layer_source(noise)}))
        self.assertTrue(custom.channels[0].override)
        self.assertTrue(noise.channels[0].override)


class TestParityRowE(CustomParityBase):
    """e — per-channel gamma/linear, smooth bump, uv neighbour (FR-27)."""

    def test_01_linear_colorspace_matches(self):
        custom, noise = self.build_pair((0.2, 0.6, 0.9, 1.0))
        yp = self.get_yp()

        color_ch = next(root_ch for root_ch in yp.channels if root_ch.name == 'Color')
        color_ch.colorspace = 'LINEAR'
        input_outputs.check_all_channel_ios(yp)

        excluded = self.normalize_noise_source(noise, (0.2, 0.6, 0.9, 1.0))
        self.assertEqual(self.chain_links(custom, self.custom_excluded(custom)),
                         self.chain_links(noise, excluded))

        custom_pixel, noise_pixel = self.two_layer_pixels(custom, noise, 'parity_e', (0.2, 0.6, 0.9, 1.0))
        self.assert_pixels_close(custom_pixel, noise_pixel, 'row e linear')

    def test_02_smooth_bump_keeps_the_passthrough_input_and_render(self):
        # A group with a real passthrough input: enabling smooth bump must not drop the link.
        group = self.make_group('ParitySmoothGroup',
            outputs=[('Color', 'NodeSocketColor')],
            inputs=[('Color', 'NodeSocketColor')])
        input_node = group.nodes.new('NodeGroupInput')
        output_node = group.nodes.new('NodeGroupOutput')
        group.links.new(input_node.outputs['Color'], output_node.inputs['Color'])

        layer = self.new_custom_layer('ParitySmoothGroup')
        layer.channels[0].enable = True
        yp = self.get_yp()
        height_index = [root_ch.name for root_ch in yp.channels].index('Height')
        layer.channels[height_index].enable = True
        layer.channels[height_index].normal_map_type = 'BUMP_MAP'
        node_connections.reconnect_layer_nodes(layer)
        node_connections.reconnect_yp_nodes(yp.id_data)

        source = self.get_layer_source(layer)
        self.assertEqual(len(source.inputs['Color'].links), 1,
                         'the passthrough input is not wired before the toggle')

        root_height = common.get_root_height_channel(yp)
        restore = self.render_settings()
        try:
            before = list(self.render_center_pixel('parity_e_smooth_before.png'))
            root_height.enable_smooth_bump = True
            input_outputs.check_all_channel_ios(yp)

            source = self.get_layer_source(layer)
            self.assertIsNotNone(source.inputs.get('Color'),
                                 'the group input disappeared after nesting')
            self.assertEqual(len(source.inputs['Color'].links), 1,
                             'smooth bump dropped the passthrough input link')
            self.assertEqual(source.inputs['Color'].links[0].from_socket.name, 'Color')

            # UV neighbour node is created for the smooth-bump path on both layer types.
            tree = self.get_layer_tree(layer)
            self.assertTrue([node for node in tree.nodes
                             if node.type == 'GROUP'
                             and node.node_tree
                             and 'Neighbor UV' in node.node_tree.name],
                            'no neighbour-UV node after enabling smooth bump')
            after = list(self.render_center_pixel('parity_e_smooth_after.png'))
        finally:
            root_height.enable_smooth_bump = False
            input_outputs.check_all_channel_ios(yp)
            restore()

        self.assert_pixels_close(before, after, 'row e smooth bump (CUSTOM vs itself)')

    def test_03_baked_custom_never_nests(self):
        # The nesting gate used to read `layer.use_baked or layer.type not in {…, 'CUSTOM'}`, so a
        # *baked* CUSTOM layer still entered the broken nested-source path: the source moved into
        # the nested tree and `check_all_channel_ios` then failed (`get_available_source_outputs`
        # received a missing source node) or disconnected the layer. CUSTOM must stay un-nested
        # for every `use_baked` state, so its passthrough input and source node survive.
        group = self.make_group('BakedSmoothGroup',
            outputs=[('Color', 'NodeSocketColor')],
            inputs=[('Color', 'NodeSocketColor')])
        input_node = group.nodes.new('NodeGroupInput')
        output_node = group.nodes.new('NodeGroupOutput')
        group.links.new(input_node.outputs['Color'], output_node.inputs['Color'])

        layer = self.new_custom_layer('BakedSmoothGroup')
        layer.channels[0].enable = True
        yp = self.get_yp()
        height_index = [root_ch.name for root_ch in yp.channels].index('Height')
        layer.channels[height_index].enable = True
        layer.channels[height_index].normal_map_type = 'BUMP_MAP'
        layer.use_baked = True
        node_connections.reconnect_layer_nodes(layer)
        node_connections.reconnect_yp_nodes(yp.id_data)

        source = self.get_layer_source(layer)
        self.assertIsNotNone(source, 'the source node is not in the layer tree')
        self.assertEqual(len(source.inputs['Color'].links), 1,
                         'the passthrough input is not wired before the toggle')

        root_height = common.get_root_height_channel(yp)
        try:
            root_height.enable_smooth_bump = True
            input_outputs.check_all_channel_ios(yp)
        finally:
            root_height.enable_smooth_bump = False
            input_outputs.check_all_channel_ios(yp)

        tree = self.get_layer_tree(layer)
        self.assertIsNone(tree.nodes.get(layer.source_group),
                          'a baked CUSTOM layer entered the nested source path')
        source = self.get_layer_source(layer)
        self.assertIsNotNone(source, 'nesting moved the source out of the layer tree')
        self.assertEqual(len(source.inputs['Color'].links), 1,
                         'smooth bump dropped the passthrough input link')


class TestParityRowF(CustomParityBase):
    """f — layer preview mode and channel preview mode (FR-28).

    Preview is not a layer-tree feature: ``preview_mode.update_preview_mode`` flips the *material*
    tree to an ``Emission Viewer`` fed from the yp group node's viewer/channel output. The old
    version of these tests compared layer-tree links that are identical with preview off, and
    asserted a viewer socket that ``check_all_channel_ios`` always creates, so it passed even with
    preview broken. These tests assert the material and yp wiring that exists only while preview is
    on, plus a rendered CUSTOM-vs-NOISE comparison in normal, layer-preview and channel-preview
    mode.

    The NORMAL and CHANNEL preview comparisons here use a fresh single-layer yp per layer type so
    the other layer cannot contribute to the render. The LAYER preview comparison across two
    layers in one yp, and the active-layer switch that used to raise ``KeyError: '_Layer Viewer'``
    in ``update_preview_mode`` (P1a), live in ``TestParityRowFActiveLayer`` below.
    """

    def apply_preview(self, mode, color_index):
        yp = self.get_yp()
        yp.preview_mode = False
        yp.preview_mode_channel_index = color_index
        yp.preview_mode_type = mode
        yp.preview_mode = True
        return yp

    def rebuild_yp(self):
        bpy.ops.wm.y_remove_yp_node()
        bpy.ops.wm.y_quick_ypaint_node_setup(type='BSDF_PRINCIPLED')

    def assert_link(self, from_socket, to_socket):
        links = [link for link in from_socket.id_data.links
                 if link.from_socket == from_socket and link.to_socket == to_socket]
        self.assertTrue(links, 'missing preview link %s.%s -> %s.%s'
                        % (from_socket.node.name, from_socket.name,
                           to_socket.node.name, to_socket.name))

    def assert_no_link_into(self, socket):
        if socket is None:
            return
        self.assertEqual([link.from_socket.name for link in socket.links], [],
                         'unexpected link into %s.%s' % (socket.node.name, socket.name))

    def single_layer_pixels(self, layer_type, color):
        """Render one layer type alone in all three preview modes; return the centre pixels."""
        if layer_type == 'CUSTOM':
            self.build_custom(color)
        else:
            self.build_noise()
        yp = self.get_yp()
        color_index = [root_ch.name for root_ch in yp.channels].index('Color')
        layer = self.get_active_layer()
        pixels = {}
        restore = self.render_settings()
        try:
            for mode in ('NORMAL', 'LAYER', 'CHANNEL'):
                yp.preview_mode = False
                node_connections.reconnect_yp_nodes(yp.id_data)
                if mode != 'NORMAL':
                    yp.preview_mode_channel_index = color_index
                    yp.preview_mode_type = mode
                    yp.preview_mode = True
                # The reconnect passes rebuild the noise source; normalise after them so the
                # comparison isolates the preview path rather than the generator.
                if layer_type == 'NOISE':
                    self.normalize_noise_source(layer, color)
                pixels[mode] = list(self.render_center_pixel(
                    'row_f_%s_%s.png' % (layer_type.lower(), mode.lower())))
        finally:
            yp.preview_mode = False
            restore()
        return pixels

    def custom_vs_noise_pixels(self, color):
        self.rebuild_yp()
        custom = self.single_layer_pixels('CUSTOM', color)
        self.rebuild_yp()
        noise = self.single_layer_pixels('NOISE', color)
        return custom, noise

    def test_01_layer_preview_matches(self):
        color = (0.2, 0.6, 0.9, 1.0)
        layer = self.build_custom(color)
        yp = self.get_yp()
        color_index = [root_ch.name for root_ch in yp.channels].index('Color')
        end = node_connections.get_essential_node(yp.id_data, common.TREE_END)

        # Preview off: the material has no viewer and the yp viewer interface is unfed.
        self.assertIsNone(self.mat.node_tree.nodes.get(common.EMISSION_VIEWER))
        self.assert_no_link_into(end.get(common.LAYER_VIEWER))

        self.apply_preview('LAYER', color_index)

        group_node = next(node for node in self.mat.node_tree.nodes
                          if node.type == 'GROUP' and node.node_tree
                          and node.node_tree.yp.is_ypaint_node)
        preview = self.mat.node_tree.nodes.get(common.EMISSION_VIEWER)
        self.assertIsNotNone(preview, 'layer preview created no Emission Viewer')
        self.assertEqual(preview.bl_idname, 'ShaderNodeGroup')
        self.assert_link(group_node.outputs[common.LAYER_VIEWER], preview.inputs[0])
        self.assert_link(group_node.outputs[common.LAYER_ALPHA_VIEWER], preview.inputs[1])
        output = common.get_material_output(self.mat)
        self.assert_link(preview.outputs[0], output.inputs[0])

        # yp level: the layer's viewer output feeds the yp interface viewer output.
        layer_node = self.get_yp_layer_node(layer)
        self.assertTrue(end[common.LAYER_VIEWER].links)
        self.assertEqual(end[common.LAYER_VIEWER].links[0].from_node, layer_node)
        self.assertEqual(end[common.LAYER_VIEWER].links[0].from_socket.name,
                         common.LAYER_VIEWER)
        self.assertEqual(end[common.LAYER_ALPHA_VIEWER].links[0].from_node, layer_node)

        # Turning preview off removes the viewer wiring again (the assertion is not vacuous).
        yp.preview_mode = False
        self.assertIsNone(self.mat.node_tree.nodes.get(common.EMISSION_VIEWER))
        self.assert_no_link_into(end.get(common.LAYER_VIEWER))

        custom_pixels, noise_pixels = self.custom_vs_noise_pixels(color)
        for mode in ('NORMAL', 'LAYER'):
            self.assert_pixels_close(custom_pixels[mode], noise_pixels[mode],
                                     'row f layer preview (%s)' % mode)

    def test_02_channel_preview_matches(self):
        color = (0.2, 0.6, 0.9, 1.0)
        layer = self.build_custom(color)
        yp = self.get_yp()
        color_index = [root_ch.name for root_ch in yp.channels].index('Color')
        excluded = self.custom_excluded(layer)
        layer_links_before = self.chain_links(layer, excluded)
        end = node_connections.get_essential_node(yp.id_data, common.TREE_END)

        self.assertIsNone(self.mat.node_tree.nodes.get(common.EMISSION_VIEWER))
        self.apply_preview('CHANNEL', color_index)

        # Channel preview is material-tree only: it must not rebuild the layer tree or create a
        # layer viewer feed (that is the layer-preview mode's job).
        self.assertEqual(self.chain_links(layer, excluded), layer_links_before,
                         'channel preview changed the layer tree')
        self.assert_no_link_into(end.get(common.LAYER_VIEWER))

        group_node = next(node for node in self.mat.node_tree.nodes
                          if node.type == 'GROUP' and node.node_tree
                          and node.node_tree.yp.is_ypaint_node)
        preview = self.mat.node_tree.nodes.get(common.EMISSION_VIEWER)
        self.assertIsNotNone(preview, 'channel preview created no Emission Viewer')
        self.assertEqual(preview.bl_idname, 'ShaderNodeEmission')
        channel_name = yp.channels[color_index].name
        self.assert_link(group_node.outputs[channel_name], preview.inputs[0])
        output = common.get_material_output(self.mat)
        self.assert_link(preview.outputs[0], output.inputs[0])

        yp.preview_mode = False
        self.assertIsNone(self.mat.node_tree.nodes.get(common.EMISSION_VIEWER))

        custom_pixels, noise_pixels = self.custom_vs_noise_pixels(color)
        for mode in ('NORMAL', 'CHANNEL'):
            self.assert_pixels_close(custom_pixels[mode], noise_pixels[mode],
                                     'row f channel preview (%s)' % mode)


class TestParityRowFActiveLayer(CustomParityBase):
    """P1a — layer preview follows the active layer when the yp has more than one layer.

    ``update_preview_mode`` used to resolve the previewed layer from the list-item index while
    ``reconnect_yp_nodes`` wires the viewer from ``yp.layers[yp.active_layer_index]``. With two
    layers only the layer that was active when preview was enabled got the two viewer outputs, so
    switching the active layer raised ``KeyError: '_Layer Viewer'`` inside the update callback and
    the preview silently stayed on the old layer (or went blank).

    These tests build **two** layers in one yp, switch the active layer both ways, switch the
    preview channel and turn preview off. They assert the real post-state — viewer sockets in
    every layer tree, the yp Group Output's viewer input linked from the newly active layer node,
    and the rendered centre pixel — rather than only the absence of a traceback.
    """

    RED = (0.9, 0.05, 0.05, 1.0)
    BLUE = (0.05, 0.05, 0.9, 1.0)

    def rebuild_yp(self):
        bpy.ops.wm.y_remove_yp_node()
        bpy.ops.wm.y_quick_ypaint_node_setup(type='BSDF_PRINCIPLED')

    def build_two_noise(self):
        for name in ('NoiseA', 'NoiseB'):
            bpy.ops.wm.y_new_layer(name=name, type='NOISE', uv_map='UVMap')
            self.get_active_layer().channels[0].enable = True
        return self.layers_by_name('NoiseA', 'NoiseB')

    def layer_index(self, layer):
        return [lay.name for lay in self.get_yp().layers].index(layer.name)

    def refresh_noise_constant(self, layer, color):
        # `reconnect_layer_nodes` rebuilds the chain from the noise generator, so the constant
        # replacement has to be applied after it and before the render.
        node_connections.reconnect_layer_nodes(layer)
        self.normalize_noise_source(layer, color)

    def layer_viewer_outputs(self, layer):
        """The (color, alpha) viewer interface outputs of a layer tree, either may be None."""
        end = node_connections.get_essential_node(self.get_layer_tree(layer), common.TREE_END)
        return end.get(common.LAYER_VIEWER), end.get(common.LAYER_ALPHA_VIEWER)

    def yp_viewer_source(self):
        yp = self.get_yp()
        end = node_connections.get_essential_node(yp.id_data, common.TREE_END)
        socket = end.get(common.LAYER_VIEWER)
        self.assertIsNotNone(socket, 'the yp Group Output has no %r input' % common.LAYER_VIEWER)
        self.assertTrue(socket.links, 'the yp %r input is unfed' % common.LAYER_VIEWER)
        return socket.links[0].from_node

    def assert_viewer_present(self, layers, label):
        for layer in layers:
            col, alpha = self.layer_viewer_outputs(layer)
            self.assertIsNotNone(col, '%s: %r lacks %r'
                                 % (label, layer.name, common.LAYER_VIEWER))
            self.assertIsNotNone(alpha, '%s: %r lacks %r'
                                 % (label, layer.name, common.LAYER_ALPHA_VIEWER))

    def reference_preview(self, name, color):
        """Render one NOISE layer alone under layer preview; return its centre pixel."""
        self.rebuild_yp()
        bpy.ops.wm.y_new_layer(name=name, type='NOISE', uv_map='UVMap')
        layer = self.get_active_layer()
        layer.channels[0].enable = True
        yp = self.get_yp()
        color_index = [ch.name for ch in yp.channels].index('Color')
        yp.preview_mode_channel_index = color_index
        yp.preview_mode_type = 'LAYER'
        yp.preview_mode = True
        self.refresh_noise_constant(layer, color)
        pixel = list(self.render_center_pixel('row_f_p1a_ref_%s.png' % name.lower()))
        yp.preview_mode = False
        return pixel

    def test_01_layer_preview_follows_the_active_layer(self):
        restore = self.render_settings()
        try:
            ref_a = self.reference_preview('NoiseA', self.RED)
            ref_b = self.reference_preview('NoiseB', self.BLUE)
            # The two references must differ, otherwise the pixel assertions below are vacuous.
            self.assertNotAlmostEqual(ref_a[0], ref_b[0], delta=PIXEL_TOLERANCE,
                                      msg='the two reference previews look identical')

            self.rebuild_yp()
            a, b = self.build_two_noise()
            yp = self.get_yp()
            color_index = [ch.name for ch in yp.channels].index('Color')

            # Enable preview while NoiseB is active.
            yp.active_layer_index = self.layer_index(b)
            yp.preview_mode_channel_index = color_index
            yp.preview_mode_type = 'LAYER'
            yp.preview_mode = True
            bpy.context.view_layer.update()
            self.refresh_noise_constant(a, self.RED)
            self.refresh_noise_constant(b, self.BLUE)

            # Both layer trees carry the yp-wide viewer outputs, not only the active one.
            self.assert_viewer_present((a, b), 'preview enabled on NoiseB')
            self.assertEqual(self.yp_viewer_source(), self.get_yp_layer_node(b))
            self.assert_pixels_close(list(self.render_center_pixel('row_f_p1a_b1.png')),
                                     ref_b, 'layer preview follows NoiseB')

            # Switch to NoiseA: this used to raise KeyError: '_Layer Viewer' here.
            yp.active_layer_index = self.layer_index(a)
            bpy.context.view_layer.update()
            self.refresh_noise_constant(a, self.RED)
            self.assert_viewer_present((a, b), 'switched active layer to NoiseA')
            self.assertEqual(self.yp_viewer_source(), self.get_yp_layer_node(a))
            self.assert_pixels_close(list(self.render_center_pixel('row_f_p1a_a.png')),
                                     ref_a, 'layer preview follows NoiseA')

            # Switch back to NoiseB.
            yp.active_layer_index = self.layer_index(b)
            bpy.context.view_layer.update()
            self.refresh_noise_constant(b, self.BLUE)
            self.assert_viewer_present((a, b), 'switched active layer back to NoiseB')
            self.assertEqual(self.yp_viewer_source(), self.get_yp_layer_node(b))
            self.assert_pixels_close(list(self.render_center_pixel('row_f_p1a_b2.png')),
                                     ref_b, 'layer preview follows NoiseB again')

            # Switch the previewed channel while layer preview stays on.
            alt_index = next(i for i, ch in enumerate(yp.channels) if ch.name != 'Color')
            yp.preview_mode_channel_index = alt_index
            bpy.context.view_layer.update()
            self.assert_viewer_present((a, b), 'switched preview channel')
            self.assertEqual(self.yp_viewer_source(), self.get_yp_layer_node(b))

            # Preview off: the viewer outputs disappear from every tree with no orphan links.
            yp.preview_mode = False
            bpy.context.view_layer.update()
            self.assertIsNone(self.mat.node_tree.nodes.get(common.EMISSION_VIEWER))
            for layer in (a, b):
                col, alpha = self.layer_viewer_outputs(layer)
                self.assertIsNone(col, 'preview off left %r in %r'
                                  % (common.LAYER_VIEWER, layer.name))
                self.assertIsNone(alpha, 'preview off left %r in %r'
                                  % (common.LAYER_ALPHA_VIEWER, layer.name))
                tree = self.get_layer_tree(layer)
                self.assertEqual([link for link in tree.links
                                  if common.LAYER_VIEWER in {link.from_socket.name,
                                                             link.to_socket.name}], [],
                                 'preview off left an orphan viewer link in %r' % layer.name)
            end = node_connections.get_essential_node(yp.id_data, common.TREE_END)
            self.assertIsNone(end.get(common.LAYER_VIEWER),
                              'preview off left the yp viewer input')
            self.assertEqual([link for link in yp.id_data.links
                              if common.LAYER_VIEWER in {link.from_socket.name,
                                                         link.to_socket.name}], [],
                             'preview off left an orphan yp viewer link')
        finally:
            restore()

    def test_02_custom_vs_noise_layer_preview_in_one_yp(self):
        """The rendered §4.7 row f LAYER comparison, now with both layers in the same yp.

        The single-layer helper in ``TestParityRowF`` had to rebuild a fresh yp per layer because
        of P1a; with two layers in one yp the preview is switched by making each layer active,
        which is exactly the path this task fixes.
        """
        color = (0.2, 0.6, 0.9, 1.0)
        restore = self.render_settings()
        try:
            self.rebuild_yp()
            self.build_custom(color)
            bpy.ops.wm.y_new_layer(name='Noise', type='NOISE', uv_map='UVMap')
            self.get_active_layer().channels[0].enable = True
            custom, noise = self.layers_by_name('Custom', 'Noise')
            yp = self.get_yp()
            color_index = [ch.name for ch in yp.channels].index('Color')

            # Enable preview with the CUSTOM layer active and render it.
            yp.active_layer_index = self.layer_index(custom)
            yp.preview_mode_channel_index = color_index
            yp.preview_mode_type = 'LAYER'
            yp.preview_mode = True
            bpy.context.view_layer.update()
            self.refresh_noise_constant(noise, color)
            self.assert_viewer_present((custom, noise), 'custom active in a two-layer yp')
            custom_pixel = list(self.render_center_pixel('row_f_p1a_custom.png'))

            # Switch to the NOISE layer and render it in the same yp.
            yp.active_layer_index = self.layer_index(noise)
            bpy.context.view_layer.update()
            self.refresh_noise_constant(noise, color)
            self.assert_viewer_present((custom, noise), 'noise active in a two-layer yp')
            self.assertEqual(self.yp_viewer_source(), self.get_yp_layer_node(noise))
            noise_pixel = list(self.render_center_pixel('row_f_p1a_noise.png'))

            self.assert_pixels_close(custom_pixel, noise_pixel,
                                     'row f layer preview (two layers, one yp)')
        finally:
            restore()


class TestParityRowG(CustomParityBase):
    """g — channel add/remove/rename after the layer exists (FR-29)."""

    def test_01_add_rename_remove_a_root_channel(self):
        custom, noise = self.build_pair()
        yp = self.get_yp()

        before_custom = len(custom.channels)
        before_noise = len(noise.channels)

        bpy.ops.wm.y_add_new_ypaint_channel(name='Extra', type='VALUE')
        self.assertEqual(len(custom.channels), before_custom + 1)
        self.assertEqual(len(noise.channels), before_noise + 1)
        extra_index = [root_ch.name for root_ch in yp.channels].index('Extra')
        # Both layers expose the new channel on their layer node and stay connected.
        for layer in (custom, noise):
            self.assertEqual(layer.channels[extra_index].socket_input_name != '', True)
        node_connections.reconnect_yp_nodes(yp.id_data)
        self.assert_yp_layer_wired(custom)
        self.assert_yp_layer_wired(noise)

        # Rename the root channel: both follow by name without an exception.
        yp.channels[extra_index].name = 'Renamed'
        input_outputs.check_all_channel_ios(yp)
        self.assertEqual(len(custom.channels), before_custom + 1)
        self.assertEqual(len(noise.channels), before_noise + 1)

        # Remove it again through the real operator: both layers drop the channel and stay
        # connected. The operator works on the active root channel index.
        yp.active_channel_index = extra_index
        self.assertEqual(bpy.ops.wm.y_remove_ypaint_channel(), {'FINISHED'})
        self.assertEqual(len(custom.channels), before_custom)
        self.assertEqual(len(noise.channels), before_noise)
        self.assert_yp_layer_wired(custom)
        self.assert_yp_layer_wired(noise)


class TestParityRowH(CustomParityBase):
    """h — the layer blends over what is below (FR-30)."""

    def test_01_partial_blend_matches_noise(self):
        # Below: solid green. Above: the constant layer at 50 % mask, MIX blend.
        bpy.ops.wm.y_new_layer(name='Below', type='COLOR',
                               solid_color=(0.0, 1.0, 0.0), uv_map='UVMap')
        below = self.get_active_layer()
        below.channels[0].enable = True

        custom, noise = self.build_pair((1.0, 0.0, 0.0, 1.0))
        yp = self.get_yp()
        below = self.layers_by_name('Below')[0]
        below.channels[0].enable = True

        image = bpy.data.images.new('ParityBlendMask', width=4, height=4, float_buffer=True)
        image.colorspace_settings.name = 'Non-Color'
        image.pixels = [0.5] * (4 * 4 * 4)
        for layer in (custom, noise):
            ch = layer.channels[0]
            ch.enable = True
            ch.blend_type = 'MIX'
            mask = mask_common.add_new_mask(layer, 'Half', 'IMAGE', 'UV', 'UVMap', image=image)
            mask.blend_type = 'MULTIPLY'
            layer.enable_masks = True
            node_connections.reconnect_layer_nodes(layer)
        node_connections.reconnect_yp_nodes(yp.id_data)

        excluded = self.normalize_noise_source(noise, (1.0, 0.0, 0.0, 1.0))
        self.assertEqual(self.chain_links(custom, self.custom_excluded(custom)),
                         self.chain_links(noise, excluded))

        custom_pixel, noise_pixel = self.two_layer_pixels(custom, noise, 'parity_h', (1.0, 0.0, 0.0, 1.0))
        self.assert_pixels_close(custom_pixel, noise_pixel, 'row h blend')
        # Sanity: the result is between the red layer and the green below, not the raw red.
        self.assertGreater(custom_pixel[0], 0.2)
        self.assertGreater(custom_pixel[1], 0.2)
