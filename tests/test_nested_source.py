"""Regression tests for P1b: nested source trees must be wired, not just declared.

A NOISE/IMAGE layer whose height channel uses global smooth bump moves its source into a nested
`source_group` tree. `refresh_source_tree_ios` only regenerated that tree's interface; nothing fed
the nested `Start`, the nested source or the nested `End`, and the outer `source_group` instance had
no inputs. The layer rendered disconnected (black). The same shallow pass builds channel-override
and mask source trees. These tests assert the wiring *and* the rendered pixel, because links alone
can look plausible while the render is black.
"""

import importlib
import os
import unittest

import bpy

from test_custom_node import CustomNodeTestBase

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE_NAME = os.path.basename(REPO_DIR)

common = importlib.import_module(PACKAGE_NAME + '.common')
node_connections = importlib.import_module(PACKAGE_NAME + '.node_connections')
input_outputs = importlib.import_module(PACKAGE_NAME + '.input_outputs')
mask_common = importlib.import_module(PACKAGE_NAME + '.mask_common')
custom_node_common = importlib.import_module(PACKAGE_NAME + '.custom_node_common')

PIXEL_TOLERANCE = 2.0 / 255.0


class NestedSourceTestBase(CustomNodeTestBase):

    def height_index(self):
        yp = self.get_yp()
        return [root_ch.name for root_ch in yp.channels].index('Height')

    def enable_height_bump(self, layer):
        layer.channels[self.height_index()].enable = True
        layer.channels[self.height_index()].normal_map_type = 'BUMP_MAP'
        node_connections.reconnect_layer_nodes(layer)
        node_connections.reconnect_yp_nodes(self.get_yp().id_data)

    def set_smooth_bump(self, enabled):
        yp = self.get_yp()
        common.get_root_height_channel(yp).enable_smooth_bump = enabled
        input_outputs.check_all_channel_ios(yp)

    def assert_pixels_close(self, a, b, label):
        for ca, cb in zip(a, b):
            self.assertAlmostEqual(ca, cb, delta=PIXEL_TOLERANCE,
                                   msg='%s: %r != %r' % (label, a, b))

    def make_constant_image(self, name, color=(0.2, 0.6, 0.9, 1.0)):
        image = bpy.data.images.new(name, width=4, height=4, float_buffer=True)
        image.colorspace_settings.name = 'Non-Color'
        image.pixels = list(color) * (4 * 4)
        return image

    # -- nested graph assertions -----------------------------------------------------------

    def nested_end(self, tree):
        end = tree.nodes.get(common.TREE_END)
        self.assertIsNotNone(end, 'the nested tree has no End node')
        return end

    def assert_nested_source_wired(self, group, inner_source):
        self.assertIsNotNone(group, 'no nested group instance')
        self.assertIsNotNone(group.node_tree, 'the nested instance has no tree')
        tree = group.node_tree

        # The generated Start input(s) feed the inner source, the outer instance gets its inputs,
        # and every End input is fed exactly once.
        for inp in inner_source.inputs:
            start_out = tree.nodes.get(common.TREE_START).outputs.get(inp.name)
            if start_out is not None:
                self.assertTrue(inp.links, 'nested source input %r is unlinked' % inp.name)

        for inp in group.inputs:
            self.assertTrue(inp.links, 'outer instance input %r is unlinked' % inp.name)

        named_inputs = [inp for inp in self.nested_end(tree).inputs if inp.name]
        self.assertTrue(named_inputs, 'the nested End has no named inputs')
        for inp in named_inputs:
            self.assertEqual(len(inp.links), 1,
                             'nested End input %r has %d links, expected 1'
                             % (inp.name, len(inp.links)))

    def assert_layer_nested(self, layer):
        tree = self.get_layer_tree(layer)
        group = tree.nodes.get(layer.source_group)
        nested = group.node_tree
        self.assert_nested_source_wired(group, nested.nodes.get(layer.source))

    def assert_channel_nested(self, layer, ch):
        tree = self.get_layer_tree(layer)
        group = tree.nodes.get(ch.source_group)
        nested = group.node_tree
        self.assert_nested_source_wired(group, nested.nodes.get(ch.source))

    def assert_mask_nested(self, layer, mask):
        tree = self.get_layer_tree(layer)
        group = tree.nodes.get(mask.group_node)
        nested = group.node_tree
        self.assert_nested_source_wired(group, nested.nodes.get(mask.source))

    def render_with(self, entity, prop_name, layer, value, filename):
        self.set_prop_input(entity, prop_name, value)
        node_connections.reconnect_layer_nodes(layer)
        node_connections.reconnect_yp_nodes(self.get_yp().id_data)
        return list(self.render_center_pixel(filename))

    def assert_distance_moves_the_pixel(self, small, large, label):
        delta = max(abs(a - b) for a, b in zip(small, large))
        self.assertGreater(delta, PIXEL_TOLERANCE,
                           '%s: ao_distance did not move the centre pixel (delta %r); the '
                           'occluder scene is wrong' % (label, delta))

    def add_occluder(self, name='NestedOccluder'):
        """A box beside the shaded +X face, close enough for AO to see it.

        The render's centre pixel shades the cube's +X face at roughly (1, -0.9, 0.6) with the +X
        normal; a convex cube alone has nothing in that hemisphere, so `ao_distance` changes
        nothing. This wall sits in the hemisphere but off the camera ray, and a 0.2 → 4.0 distance
        change moves the centre pixel by ~12/255 (49/255 max over the image).
        """
        x0, x1, y0, y1, z0, z1 = 2.0, 2.6, 0.2, 2.0, -1.0, 2.0
        verts = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
                 (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
        faces = [(0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)]
        mesh = bpy.data.meshes.new(name + 'Mesh')
        mesh.from_pydata(verts, [], faces)
        mesh.update()
        ob = bpy.data.objects.new(name, mesh)
        bpy.context.scene.collection.objects.link(ob)
        self.addCleanup(self.remove_object, ob)
        return ob

    def remove_object(self, ob):
        mesh = ob.data
        bpy.data.objects.remove(ob, do_unlink=True)
        if mesh.users == 0: bpy.data.meshes.remove(mesh)

    def set_prop_input(self, entity, prop_name, value):
        """Set an entity property the way the UI does: through the layer-tree `Start` tunnel."""
        common.set_entity_prop_value(entity, prop_name, value)

    def assert_start_source_input(self, group, inner_source, entity, prop_name, socket_name, label):
        """A source input the flat path feeds from `Start` must survive nesting, same stream.

        Without this a nested AO layer reads `Distance`'s 1.0 default while the flat one reads
        `ao_distance`, so the two render differently and the property silently does nothing.
        """
        self.assertIn(socket_name, group.inputs,
                      '%s: the nested instance has no %r input' % (label, socket_name))
        tunnel = common.get_entity_input_name(entity, prop_name)
        start = group.id_data.nodes.get(common.TREE_START)
        self.assertIsNotNone(start, '%s: the outer tree has no Start' % label)
        outer = start.outputs.get(tunnel)
        self.assertIsNotNone(outer, '%s: Start has no %r tunnel' % (label, tunnel))
        links = group.inputs[socket_name].links
        self.assertEqual(len(links), 1,
                         '%s: instance input %r has %d links' % (label, socket_name, len(links)))
        self.assertEqual(links[0].from_socket, outer,
                         '%s: instance input %r is not fed from the flat source stream'
                         % (label, socket_name))

        self.assertIn(socket_name, inner_source.inputs,
                      '%s: the inner source has no %r input' % (label, socket_name))
        inner_links = inner_source.inputs[socket_name].links
        self.assertEqual(len(inner_links), 1,
                         '%s: inner source input %r has %d links'
                         % (label, socket_name, len(inner_links)))
        self.assertEqual(inner_links[0].from_socket.name, socket_name,
                         '%s: inner source input %r is not fed from the nested Start'
                         % (label, socket_name))


class TestNestedLayerSource(NestedSourceTestBase):

    def test_01_noise_smooth_bump_render_matches_unbumped(self):
        bpy.ops.wm.y_new_layer(name='NestedNoise', type='NOISE', uv_map='UVMap')
        layer = self.get_active_layer()
        layer.channels[0].enable = True
        self.enable_height_bump(layer)

        restore = self.render_settings()
        try:
            before = list(self.render_center_pixel('nested_noise_before.png'))
            self.set_smooth_bump(True)
            self.assert_layer_nested(layer)
            after = list(self.render_center_pixel('nested_noise_after.png'))
        finally:
            self.set_smooth_bump(False)
            restore()

        self.assert_pixels_close(before, after, 'noise smooth bump')

    def test_02_image_smooth_bump_render_matches_unbumped(self):
        image = self.make_constant_image('NestedSourceImage')
        bpy.ops.wm.y_new_layer(name='NestedImage', type='IMAGE', uv_map='UVMap')
        layer = self.get_active_layer()
        layer.channels[0].enable = True
        self.get_layer_source(layer).image = image
        self.enable_height_bump(layer)

        restore = self.render_settings()
        try:
            before = list(self.render_center_pixel('nested_image_before.png'))
            self.set_smooth_bump(True)
            self.assert_layer_nested(layer)
            after = list(self.render_center_pixel('nested_image_after.png'))
        finally:
            self.set_smooth_bump(False)
            restore()

        self.assert_pixels_close(before, after, 'image smooth bump')

    def test_03_channel_override_smooth_bump_is_wired_and_renders(self):
        bpy.ops.wm.y_new_layer(name='NestedOverride', type='NOISE', uv_map='UVMap')
        layer = self.get_active_layer()
        layer.channels[0].enable = True
        # Channel source trees are built by the height-channel pass; override the height channel.
        ch = layer.channels[self.height_index()]
        ch.enable = True
        ch.override = True
        ch.override_type = 'NOISE'
        self.enable_height_bump(layer)

        restore = self.render_settings()
        try:
            before = list(self.render_center_pixel('nested_override_before.png'))
            self.set_smooth_bump(True)
            self.assert_channel_nested(layer, ch)
            after = list(self.render_center_pixel('nested_override_after.png'))
        finally:
            self.set_smooth_bump(False)
            restore()

        self.assert_pixels_close(before, after, 'channel override smooth bump')

    def test_04_mask_source_tree_smooth_bump_still_evaluates(self):
        bpy.ops.wm.y_new_layer(name='NestedBelow', type='COLOR',
                               solid_color=(0.02, 0.03, 0.04), uv_map='UVMap')
        self.get_active_layer().channels[0].enable = True

        bpy.ops.wm.y_new_layer(name='NestedMasked', type='COLOR',
                               solid_color=(1.0, 0.0, 0.0), uv_map='UVMap')
        layer = self.get_active_layer()
        layer.channels[0].enable = True
        self.enable_height_bump(layer)

        image = self.make_constant_image('NestedMaskImage', (0.5, 0.5, 0.5, 1.0))
        mask = mask_common.add_new_mask(layer, 'Half', 'IMAGE', 'UV', 'UVMap', image=image)
        mask.blend_type = 'MULTIPLY'
        layer.enable_masks = True
        mask.channels[self.height_index()].enable = True
        node_connections.reconnect_layer_nodes(layer)
        node_connections.reconnect_yp_nodes(self.get_yp().id_data)

        restore = self.render_settings()
        try:
            before = list(self.render_center_pixel('nested_mask_before.png'))
            self.set_smooth_bump(True)
            self.assert_mask_nested(layer, mask)
            after = list(self.render_center_pixel('nested_mask_after.png'))
        finally:
            self.set_smooth_bump(False)
            restore()

        # A culled/black mask would make the pixels differ far beyond tolerance.
        self.assert_pixels_close(before, after, 'mask source smooth bump')

    def test_05_check_all_channel_ios_is_idempotent(self):
        bpy.ops.wm.y_new_layer(name='NestedIdempotent', type='NOISE', uv_map='UVMap')
        layer = self.get_active_layer()
        layer.channels[0].enable = True
        self.enable_height_bump(layer)
        self.set_smooth_bump(True)

        tree = self.get_layer_tree(layer)
        group = tree.nodes.get(layer.source_group)
        nested = group.node_tree

        def counts():
            return (
                len(tree.nodes), len(tree.links),
                len(nested.nodes), len(nested.links),
                len(group.inputs),
            )

        first = counts()
        input_outputs.check_all_channel_ios(self.get_yp())
        second = counts()
        self.assertEqual(first, second, 'running the IO check twice changed the graph')
        self.assert_layer_nested(layer)

    def test_06_disabling_smooth_bump_restores_the_un_nested_graph(self):
        bpy.ops.wm.y_new_layer(name='NestedToggle', type='NOISE', uv_map='UVMap')
        layer = self.get_active_layer()
        layer.channels[0].enable = True
        self.enable_height_bump(layer)

        restore = self.render_settings()
        try:
            before = list(self.render_center_pixel('nested_toggle_before.png'))
            self.set_smooth_bump(True)
            tree = self.get_layer_tree(layer)
            nested = tree.nodes.get(layer.source_group).node_tree
            nested_name = nested.name
            after_enable = list(self.render_center_pixel('nested_toggle_enabled.png'))

            self.set_smooth_bump(False)
            after_disable = list(self.render_center_pixel('nested_toggle_after.png'))
        finally:
            restore()

        self.assert_pixels_close(before, after_enable, 'smooth bump on')
        self.assert_pixels_close(before, after_disable, 'smooth bump off')

        tree = self.get_layer_tree(layer)
        self.assertIsNone(tree.nodes.get(layer.source_group),
                          'the source_group instance survived un-nesting')
        for prop in ('source_n', 'source_s', 'source_e', 'source_w'):
            self.assertIsNone(tree.nodes.get(getattr(layer, prop)),
                              'orphan %s node survived un-nesting' % prop)
        self.assertIsNone(bpy.data.node_groups.get(nested_name),
                          'the nested tree datablock was left orphaned')


class TestNestedPreviousNormal(NestedSourceTestBase):
    """P1b review: a nested source must carry the previous-normal stream or fall back safely.

    `reconnect_layer_nodes` reads the nested `source_group` instance, but the interface only
    declared `Vector`. An AO layer (or a baked HEMI/EDGE_DETECT layer) with
    `hemi_use_prev_normal` therefore raised `KeyError: 'Normal'` and aborted the whole graph
    rebuild. These tests pin no-crash, a complete nested graph, and (where the stream can be
    forwarded) the rendered parity with the un-nested layer.
    """

    def add_layer(self, name, layer_type):
        bpy.ops.wm.y_new_layer(name=name, type=layer_type, uv_map='UVMap')
        return self.get_active_layer()

    def assert_normal_forwarded(self, group, inner_source, label):
        self.assertIsNotNone(group, '%s did not nest' % label)
        self.assertIsNotNone(group.node_tree, '%s: the instance has no tree' % label)
        tree = group.node_tree

        # The outer instance must accept the previous-normal stream instead of aborting.
        self.assertIn('Normal', group.inputs, '%s: the instance has no Normal input' % label)
        self.assertTrue(group.inputs['Normal'].links,
                        '%s: the outer Normal input is unlinked' % label)
        self.assertEqual(group.inputs['Normal'].links[0].from_socket.name, 'Normal')

        # Where the inner source has a Normal input it must be fed from the nested Start. A baked
        # image has no such input, so there the leg deliberately stays at the default normal.
        normal_in = inner_source.inputs.get('Normal')
        if normal_in is not None:
            self.assertTrue(normal_in.links,
                            '%s: the nested source Normal input is unlinked' % label)
            self.assertEqual(normal_in.links[0].from_socket.name, 'Normal')

        # The nested tree must still be complete: every named End input is fed exactly once.
        named_inputs = [inp for inp in self.nested_end(tree).inputs if inp.name]
        self.assertTrue(named_inputs, '%s: the nested End has no named inputs' % label)
        for inp in named_inputs:
            self.assertEqual(len(inp.links), 1,
                             '%s: nested End input %r has %d links, expected 1'
                             % (label, inp.name, len(inp.links)))

    def compare_nested_and_un_nested(self, layer, label):
        restore = self.render_settings()
        try:
            nested = list(self.render_center_pixel('nested_prev_normal_%s_nested.png' % label))
            self.set_smooth_bump(False)
            self.assertIsNone(self.get_layer_tree(layer).nodes.get(layer.source_group),
                              '%s did not un-nest' % label)
            un_nested = list(self.render_center_pixel('nested_prev_normal_%s_flat.png' % label))
        finally:
            self.set_smooth_bump(False)
            restore()
        self.assert_pixels_close(nested, un_nested, label)

    def test_01_ao_layer_added_under_smooth_bump_does_not_abort(self):
        self.add_occluder()
        noise = self.add_layer('NestedAONoise', 'NOISE')
        noise.channels[0].enable = True
        self.enable_height_bump(noise)
        self.set_smooth_bump(True)

        # The reviewer's reproducer: adding this layer while smooth bump is on used to raise
        # KeyError: 'Normal' inside reconnect_layer_nodes (half-built graph).
        ao = self.add_layer('NestedAO', 'AO')
        self.assertTrue(ao.hemi_use_prev_normal,
                        'the AO previous-normal switch is expected to default on')
        self.enable_height_bump(ao)

        tree = self.get_layer_tree(ao)
        group = tree.nodes.get(ao.source_group)
        self.assertIsNotNone(group, 'the AO layer did not enter the nested source path')
        self.assert_normal_forwarded(group, group.node_tree.nodes.get(ao.source), 'AO layer')

        # The bump output, not the raw below-layers normal, must reach the instance.
        bump = tree.nodes.get(ao.bump_process)
        self.assertIsNotNone(bump, 'the AO layer has no bump process')
        normal_links = group.inputs['Normal'].links
        self.assertEqual(len(normal_links), 1)
        self.assertEqual(normal_links[0].from_socket, bump.outputs['Normal'],
                         'the previous-normal leg was replaced by the raw Start normal')

        # P1b review: `ao_distance` is fed by a Start tunnel, so it must be declared and forwarded
        # into the nested tree; otherwise the nested layer ignores it (it reads the 1.0 default).
        self.assert_start_source_input(
            group, group.node_tree.nodes.get(ao.source), ao, 'ao_distance', 'Distance', 'AO layer')

        # Non-vacuous: the occluder makes `ao_distance` move the centre pixel, so the parity check
        # below would catch a dropped `Distance` link (P1b review). Measured delta ~12/255.
        restore = self.render_settings()
        bpy.context.scene.cycles.samples = 64
        try:
            small = self.render_with(ao, 'ao_distance', ao, 0.2, 'prev_normal_ao_small.png')
            large = self.render_with(ao, 'ao_distance', ao, 4.0, 'prev_normal_ao_large.png')
            self.assert_distance_moves_the_pixel(small, large, 'AO layer (previous normal)')
        finally:
            restore()

        self.compare_nested_and_un_nested(ao, 'ao_layer')

    def test_02_ao_layer_with_previous_normal_off(self):
        noise = self.add_layer('NestedAOOffNoise', 'NOISE')
        noise.channels[0].enable = True
        self.enable_height_bump(noise)
        self.set_smooth_bump(True)

        ao = self.add_layer('NestedAOOff', 'AO')
        ao.hemi_use_prev_normal = False
        self.enable_height_bump(ao)

        tree = self.get_layer_tree(ao)
        group = tree.nodes.get(ao.source_group)
        self.assertIsNotNone(group, 'the AO layer did not enter the nested source path')
        # With the switch off the un-nested source still reads Geometry Normal; the nested one
        # must receive the same stream rather than an unlinked input.
        self.assert_normal_forwarded(group, group.node_tree.nodes.get(ao.source), 'AO layer off')
        geometry_normal = tree.nodes.get(common.GEOMETRY).outputs['Normal']
        self.assertEqual(group.inputs['Normal'].links[0].from_socket, geometry_normal)

        self.compare_nested_and_un_nested(ao, 'ao_layer_off')

    def test_03_baked_hemi_and_edge_detect_survive_smooth_bump(self):
        for layer_type in ('HEMI', 'EDGE_DETECT'):
            with self.subTest(layer_type=layer_type):
                layer = self.add_layer('NestedBaked' + layer_type, layer_type)
                layer.channels[0].enable = True
                layer.hemi_use_prev_normal = True
                layer.baked_uv_name = 'UVMap'

                tree = self.get_layer_tree(layer)
                baked = tree.nodes.new('ShaderNodeTexImage')
                baked.name = 'BakedSource' + layer_type
                baked.label = 'Baked Source'
                baked.image = self.make_constant_image(
                    'NestedBakedImage' + layer_type, (0.4, 0.5, 0.6, 1.0))
                layer.baked_source = baked.name
                layer.use_baked = True
                self.enable_height_bump(layer)

                self.set_smooth_bump(True)
                group = tree.nodes.get(layer.source_group)
                self.assertIsNotNone(group,
                                     'the baked %s layer did not nest' % layer_type)
                # The baked image is what the inner tree reads; the interface must still accept
                # the previous-normal stream instead of aborting.
                self.assert_normal_forwarded(
                    group, group.node_tree.nodes.get(layer.baked_source), 'baked ' + layer_type)

                self.compare_nested_and_un_nested(layer, 'baked_' + layer_type)

    def test_04_ao_mask_with_previous_normal_under_smooth_bump(self):
        self.add_occluder()
        # A dark layer below, so the AO mask changes the visible pixel: a white layer over white
        # hides the mask's alpha change.
        bpy.ops.wm.y_new_layer(name='NestedAOMaskBelow', type='COLOR',
                               solid_color=(0.02, 0.03, 0.04), uv_map='UVMap')
        below = self.get_active_layer()
        below.channels[0].enable = True

        layer = self.add_layer('NestedAOMaskLayer', 'COLOR')
        layer.channels[0].enable = True
        self.enable_height_bump(layer)

        mask = mask_common.add_new_mask(
            layer, 'NestedAOMask', 'AO', 'UV', 'UVMap',
            blend_type='MULTIPLY', hemi_use_prev_normal=True)
        layer.enable_masks = True
        mask.channels[self.height_index()].enable = True
        node_connections.reconnect_layer_nodes(layer)
        node_connections.reconnect_yp_nodes(self.get_yp().id_data)

        # The mask source nests and its previous-normal leg used to raise KeyError: 'Normal'.
        self.set_smooth_bump(True)

        tree = self.get_layer_tree(layer)
        group = tree.nodes.get(mask.group_node)
        self.assertIsNotNone(group, 'the AO mask did not enter the nested source path')
        self.assert_normal_forwarded(group, group.node_tree.nodes.get(mask.source), 'AO mask')

        bump = tree.nodes.get(layer.bump_process)
        self.assertIsNotNone(bump, 'the layer has no bump process for the mask')
        self.assertEqual(group.inputs['Normal'].links[0].from_socket, bump.outputs['Normal'])

        # P1b review: the mask's `ao_distance` tunnel must reach the nested mask tree too.
        self.assert_start_source_input(
            group, group.node_tree.nodes.get(mask.source), mask, 'ao_distance', 'Distance', 'AO mask')

        # The mask test used to assert wiring only; render it so `ao_distance` visibly matters.
        restore = self.render_settings()
        bpy.context.scene.cycles.samples = 64
        try:
            small = self.render_with(
                mask, 'ao_distance', layer, 0.2, 'prev_normal_ao_mask_small.png')
            large = self.render_with(
                mask, 'ao_distance', layer, 4.0, 'prev_normal_ao_mask_large.png')
            self.assert_distance_moves_the_pixel(small, large, 'AO mask (previous normal)')
        finally:
            restore()


class TestNestedSourceInputs(NestedSourceTestBase):
    """P1b review: nesting must forward every source input the flat path reads.

    `3ed235e` declared only `Vector`/`Normal` on the nested interface, so a nested AO layer or AO
    mask read `Distance`'s 1.0 default while the flat one read `ao_distance`. These tests render a
    scene where AO distance visibly moves the pixel, compare nested/un-nested at the same value,
    and pin the generic declaration (with pruning) rather than one AO special case.
    """

    def test_01_ao_layer_distance_is_forwarded_and_renders(self):
        self.add_occluder()
        noise = self.add_layer('NestedAODistNoise', 'NOISE')
        noise.channels[0].enable = True
        self.enable_height_bump(noise)

        ao = self.add_layer('NestedAODist', 'AO')
        ao.channels[0].enable = True
        self.enable_height_bump(ao)

        restore = self.render_settings()
        bpy.context.scene.cycles.samples = 64
        try:
            flat_small = self.render_with(ao, 'ao_distance', ao, 0.2, 'ao_dist_flat_small.png')
            flat_large = self.render_with(ao, 'ao_distance', ao, 4.0, 'ao_dist_flat_large.png')

            self.set_smooth_bump(True)
            tree = self.get_layer_tree(ao)
            group = tree.nodes.get(ao.source_group)
            self.assertIsNotNone(group, 'the AO layer did not nest')

            nested_small = self.render_with(ao, 'ao_distance', ao, 0.2, 'ao_dist_nested_small.png')
            nested_large = self.render_with(ao, 'ao_distance', ao, 4.0, 'ao_dist_nested_large.png')

            # The render is the point: with the input dropped both values render as the 1.0 default.
            self.assert_distance_moves_the_pixel(nested_small, nested_large, 'nested AO layer')

            self.assert_start_source_input(
                group, group.node_tree.nodes.get(ao.source), ao, 'ao_distance', 'Distance',
                'AO layer')

            # Declaration is stable: a second pass adds or removes nothing.
            before = [inp.name for inp in group.inputs]
            input_outputs.check_all_channel_ios(self.get_yp())
            group = self.get_layer_tree(ao).nodes.get(ao.source_group)
            self.assertEqual(before, [inp.name for inp in group.inputs],
                             're-syncing changed the nested input contract')
        finally:
            self.set_smooth_bump(False)
            restore()

        self.assert_pixels_close(nested_small, flat_small, 'nested == flat, ao_distance 0.2')
        self.assert_pixels_close(nested_large, flat_large, 'nested == flat, ao_distance 4.0')

    def test_02_ao_mask_distance_is_forwarded_and_renders(self):
        self.add_occluder()
        # A dark layer below, so the AO mask visibly changes the centre pixel: over white the
        # multiply saturates and the distance change disappears.
        bpy.ops.wm.y_new_layer(name='NestedAODistMaskBelow', type='COLOR',
                               solid_color=(0.02, 0.03, 0.04), uv_map='UVMap')
        below = self.get_active_layer()
        below.channels[0].enable = True

        layer = self.add_layer('NestedAODistMaskLayer', 'COLOR')
        layer.channels[0].enable = True
        self.enable_height_bump(layer)

        mask = mask_common.add_new_mask(
            layer, 'NestedAODistMask', 'AO', 'UV', 'UVMap',
            blend_type='MULTIPLY', hemi_use_prev_normal=True)
        layer.enable_masks = True
        mask.channels[self.height_index()].enable = True
        node_connections.reconnect_layer_nodes(layer)
        node_connections.reconnect_yp_nodes(self.get_yp().id_data)

        restore = self.render_settings()
        bpy.context.scene.cycles.samples = 64
        try:
            flat_small = self.render_with(mask, 'ao_distance', layer, 0.2, 'mask_dist_flat_small.png')
            flat_large = self.render_with(mask, 'ao_distance', layer, 4.0, 'mask_dist_flat_large.png')

            self.set_smooth_bump(True)
            tree = self.get_layer_tree(layer)
            group = tree.nodes.get(mask.group_node)
            self.assertIsNotNone(group, 'the AO mask did not nest')

            nested_small = self.render_with(mask, 'ao_distance', layer, 0.2, 'mask_dist_nested_small.png')
            nested_large = self.render_with(mask, 'ao_distance', layer, 4.0, 'mask_dist_nested_large.png')

            self.assert_distance_moves_the_pixel(nested_small, nested_large, 'nested AO mask')

            self.assert_start_source_input(
                group, group.node_tree.nodes.get(mask.source), mask, 'ao_distance', 'Distance',
                'AO mask')
        finally:
            self.set_smooth_bump(False)
            restore()

        self.assert_pixels_close(nested_small, flat_small, 'nested == flat mask, ao_distance 0.2')
        self.assert_pixels_close(nested_large, flat_large, 'nested == flat mask, ao_distance 4.0')

    def test_03_switching_to_a_baked_source_prunes_the_unread_input(self):
        noise = self.add_layer('NestedPruneNoise', 'NOISE')
        noise.channels[0].enable = True
        self.enable_height_bump(noise)

        ao = self.add_layer('NestedPruneAO', 'AO')
        ao.channels[0].enable = True
        self.enable_height_bump(ao)
        self.set_smooth_bump(True)

        group = self.get_layer_tree(ao).nodes.get(ao.source_group)
        self.assertIn('Distance', group.inputs, 'the nested AO layer should read Distance')

        # A baked AO layer reads an image source, which has no Distance input: the declaration is
        # derived from the source, so switching to it must drop the now-dead socket.
        nested = group.node_tree
        baked = nested.nodes.new('ShaderNodeTexImage')
        baked.name = 'NestedPruneBaked'
        baked.image = self.make_constant_image('NestedPruneBakedImage', (0.3, 0.4, 0.5, 1.0))
        ao.baked_source = baked.name
        ao.baked_uv_name = 'UVMap'
        ao.use_baked = True
        self.set_smooth_bump(True)

        group = self.get_layer_tree(ao).nodes.get(ao.source_group)
        self.assertIsNotNone(group, 'the baked AO layer did not stay nested')
        self.assertNotIn('Distance', group.inputs,
                         'the dead Distance socket survived the source change')
        self.assertNotIn(
            'Distance',
            [item.name for item in group.node_tree.interface.items_tree
             if item.item_type == 'SOCKET' and item.in_out == 'INPUT'],
            'the nested tree kept a dead Distance input')

        before = [inp.name for inp in group.inputs]
        input_outputs.check_all_channel_ios(self.get_yp())
        group = self.get_layer_tree(ao).nodes.get(ao.source_group)
        self.assertEqual(before, [inp.name for inp in group.inputs],
                         're-syncing changed the pruned input contract')

    def test_04_flat_layer_and_mask_link_start_inputs_from_the_table(self):
        """The flat path must derive from `source_start_inputs`, not its own hard-coded blocks.

        P1c review (d): the nested declaration read the table while the flat layer/mask code kept
        a second list, so a new Start-fed input could be declared for nesting and left unlinked
        flat. Check the AO `Distance` link on both flat paths against the tunnel the derivation
        names -- no render, the existing AO tests cover the pixels.
        """
        ao = self.add_layer('FlatTableAO', 'AO')
        ao.channels[0].enable = True
        input_outputs.check_all_channel_ios(self.get_yp())
        node_connections.reconnect_layer_nodes(ao)
        tree = self.get_layer_tree(ao)
        self.assert_flat_start_input(tree, self.get_layer_source(ao), ao, 'AO', 'AO layer')

        layer = self.add_layer('FlatTableMaskLayer', 'COLOR')
        layer.channels[0].enable = True
        mask = mask_common.add_new_mask(
            layer, 'FlatTableMask', 'AO', 'UV', 'UVMap', hemi_use_prev_normal=True)
        layer.enable_masks = True
        mask.channels[self.height_index()].enable = True
        input_outputs.check_all_channel_ios(self.get_yp())
        node_connections.reconnect_layer_nodes(layer)
        tree = self.get_layer_tree(layer)
        self.assert_flat_start_input(
            tree, tree.nodes.get(mask.source), mask, 'AO', 'AO mask')

    def assert_flat_start_input(self, tree, source, entity, entity_type, label):
        """Both flat paths must link AO `Distance` from the tunnel the derivation names."""
        specs = node_connections.get_source_start_input_sockets(source, entity_type, entity, tree)
        self.assertIn('Distance', [name for name, _ in specs],
                      '%s: get_source_start_input_sockets did not derive Distance' % label)
        prop_name = node_connections.source_start_inputs['Distance'][1]
        tunnel = common.get_entity_input_name(entity, prop_name)
        start = tree.nodes.get(common.TREE_START)
        self.assertIsNotNone(start, '%s: the flat tree has no Start' % label)
        outer = start.outputs.get(tunnel)
        self.assertIsNotNone(outer, '%s: Start has no %r tunnel' % (label, tunnel))
        self.assertIn('Distance', source.inputs, '%s: the source has no Distance input' % label)
        links = source.inputs['Distance'].links
        self.assertEqual(len(links), 1,
                         '%s: Distance has %d links, expected the Start tunnel'
                         % (label, len(links)))
        self.assertEqual(links[0].from_socket, outer,
                         '%s: Distance is not fed from Start[%r]' % (label, tunnel))

    def add_layer(self, name, layer_type):
        bpy.ops.wm.y_new_layer(name=name, type=layer_type, uv_map='UVMap')
        return self.get_active_layer()


class TestNestedCustomSource(NestedSourceTestBase):
    """P1c: a CUSTOM source nests, and its group inputs are forwarded (FR-27).

    The nested pass used to drop the user group's channel inputs, which is why CUSTOM was excluded
    from the nesting gate. The contract now reads one rule, `get_custom_source_input_names`: a group
    input named like a root channel (`X`) or its alpha (`X Alpha`) is declared on the nested
    interface and forwarded to the inner group, by name, on both sides, when the group and the
    outer `Start` expose it. Any other input (`UVMap UV`, bare `Alpha`) keeps the user's default.
    """

    def channel_index(self, name):
        return [root_ch.name for root_ch in self.get_yp().channels].index(name)

    def enable_channels(self, layer, *names):
        for name in names:
            layer.channels[self.channel_index(name)].enable = True

    def make_passthrough_group(self, name, inputs, outputs):
        """A group whose outputs are its own inputs, so a dropped input changes the render."""
        group = self.make_group(name, outputs, inputs=inputs)
        group_in = group.nodes.new('NodeGroupInput')
        group_out = group.nodes.new('NodeGroupOutput')
        for socket_name, _socket_type in outputs:
            if group_in.outputs.get(socket_name) is None: continue
            group.links.new(group_in.outputs[socket_name], group_out.inputs[socket_name])
        return group

    def assert_custom_inputs_forwarded(self, layer, names):
        tree = self.get_layer_tree(layer)
        group = tree.nodes.get(layer.source_group)
        self.assertIsNotNone(group, 'the custom layer did not nest')
        self.assertIsNotNone(group.node_tree, 'the nested instance has no tree')
        start = tree.nodes.get(common.TREE_START)
        inner = group.node_tree.nodes.get(layer.source)
        self.assertIsNotNone(inner, 'the custom source node is not in the nested tree')
        nested_start = group.node_tree.nodes.get(common.TREE_START)

        for name in names:
            self.assertIn(name, group.inputs,
                          'the nested instance has no %r input' % name)
            links = group.inputs[name].links
            self.assertEqual(len(links), 1,
                             'instance input %r has %d links' % (name, len(links)))
            self.assertEqual(links[0].from_socket, start.outputs.get(name),
                             'instance input %r is not fed from the outer Start' % name)

            self.assertIn(name, inner.inputs,
                          'the inner custom group has no %r input' % name)
            inner_links = inner.inputs[name].links
            self.assertEqual(len(inner_links), 1,
                             'inner input %r has %d links' % (name, len(inner_links)))
            self.assertEqual(inner_links[0].from_socket, nested_start.outputs.get(name),
                             'inner input %r is not fed from the nested Start' % name)

    def assert_enabled_channel_inputs_connected(self, layer):
        """Every enabled channel's below-layers stream reaches the inner group by name."""
        tree = self.get_layer_tree(layer)
        group = tree.nodes.get(layer.source_group)
        self.assertIsNotNone(group, 'the custom layer did not nest')
        inner = group.node_tree.nodes.get(layer.source)
        yp = self.get_yp()
        checked = 0
        for i, ch in enumerate(layer.channels):
            if not ch.enable: continue
            name = yp.channels[i].name
            inp = inner.inputs.get(name)
            if inp is None:
                continue
            self.assertEqual(len(inp.links), 1,
                             'enabled channel %r does not reach the inner group' % name)
            checked += 1
        self.assertGreater(checked, 0, 'no enabled channel crossed the nested boundary')

    def replace_source_with_constant(self, layer, color):
        """Swap a source's outgoing links for a constant, in whichever tree it lives."""
        source = self.get_layer_source(layer)
        tree = source.id_data
        targets = [link.to_socket for link in tree.links if link.from_node == source]
        for target in targets:
            for link in list(target.links):
                tree.links.remove(link)
        rgb = tree.nodes.new('ShaderNodeRGB')
        rgb.name = 'NestedParityConstant'
        rgb.outputs[0].default_value = color
        for target in targets:
            tree.links.new(rgb.outputs[0], target)

    def test_01_custom_channel_inputs_are_forwarded_and_render_unchanged(self):
        group = self.make_passthrough_group(
            'NestedCustomPass',
            inputs=[('Color', 'NodeSocketColor'), ('Roughness', 'NodeSocketFloat'),
                    ('Color Alpha', 'NodeSocketFloat')],
            outputs=[('Color', 'NodeSocketColor'), ('Roughness', 'NodeSocketFloat')])
        layer = self.new_custom_layer(group.name, name='NestedCustom')
        self.enable_channels(layer, 'Color', 'Roughness')
        # Give the `Color` root channel an alpha so the outer `Start` declares `Color Alpha`.
        self.get_yp().channels[self.channel_index('Color')].enable_alpha = True
        input_outputs.check_all_channel_ios(self.get_yp())
        self.enable_height_bump(layer)

        tree = self.get_layer_tree(layer)
        source = self.get_layer_source(layer)
        self.assertEqual(len(source.inputs['Color'].links), 1,
                         'the passthrough Color input is not wired before nesting')

        restore = self.render_settings()
        try:
            before = list(self.render_center_pixel('nested_custom_before.png'))
            self.set_smooth_bump(True)

            # `Color Alpha` is the positive case for `<channel> Alpha` forwarding.
            self.assert_custom_inputs_forwarded(layer, ('Color', 'Roughness', 'Color Alpha'))
            self.assert_layer_nested(layer)
            # The source node itself must have moved out of the layer tree.
            self.assertIsNone(tree.nodes.get(layer.source),
                              'the custom source stayed in the layer tree')

            # Declaration is idempotent: a second IO pass adds or removes nothing.
            group = tree.nodes.get(layer.source_group)
            counts = (len(tree.nodes), len(tree.links), len(group.node_tree.nodes),
                      len(group.node_tree.links), len(group.inputs))
            input_outputs.check_all_channel_ios(self.get_yp())
            group = self.get_layer_tree(layer).nodes.get(layer.source_group)
            self.assertEqual(counts,
                             (len(self.get_layer_tree(layer).nodes),
                              len(self.get_layer_tree(layer).links),
                              len(group.node_tree.nodes), len(group.node_tree.links),
                              len(group.inputs)),
                             'a second IO pass changed the nested custom graph')

            after = list(self.render_center_pixel('nested_custom_after.png'))
        finally:
            self.set_smooth_bump(False)
            restore()

        self.assert_pixels_close(before, after, 'custom smooth bump')

    def test_02_group_input_named_normal_gets_the_below_layers_stream(self):
        group = self.make_group('NestedCustomNormal',
                                outputs=[('Color', 'NodeSocketColor')],
                                inputs=[('Normal', 'NodeSocketVector')])
        rgb = group.nodes.new('ShaderNodeRGB')
        rgb.outputs[0].default_value = (0.1, 0.2, 0.3, 1.0)
        group_out = group.nodes.new('NodeGroupOutput')
        group.links.new(rgb.outputs[0], group_out.inputs['Color'])

        layer = self.new_custom_layer(group.name, name='NestedCustomNormalLayer')
        self.enable_channels(layer, 'Color', 'Normal')
        self.enable_height_bump(layer)
        root_height = common.get_root_height_channel(self.get_yp())
        try:
            root_height.enable_smooth_bump = True
            input_outputs.check_all_channel_ios(self.get_yp())

            tree = self.get_layer_tree(layer)
            group_node = tree.nodes.get(layer.source_group)
            self.assertIsNotNone(group_node, 'the custom layer did not nest')
            self.assert_custom_inputs_forwarded(layer, ('Normal',))

            # A custom `Normal` input is the below-layers normal stream, not the previous-normal
            # leg: it is fed by the outer `Start`, never by the bump output.
            normal_links = group_node.inputs['Normal'].links
            self.assertEqual(len(normal_links), 1)
            bump = tree.nodes.get(layer.bump_process)
            if bump is not None:
                self.assertNotEqual(normal_links[0].from_socket, bump.outputs['Normal'],
                                    'the custom Normal input took the previous-normal leg')
            self.assertEqual(normal_links[0].from_socket.name, 'Normal')
        finally:
            root_height.enable_smooth_bump = False
            input_outputs.check_all_channel_ios(self.get_yp())

    def test_03_group_input_named_alpha_stays_unlinked(self):
        group = self.make_group('NestedCustomAlpha',
                                outputs=[('Color', 'NodeSocketColor')],
                                inputs=[('Color', 'NodeSocketColor'), ('Alpha', 'NodeSocketFloat')])
        group_in = group.nodes.new('NodeGroupInput')
        group_out = group.nodes.new('NodeGroupOutput')
        group.links.new(group_in.outputs['Color'], group_out.inputs['Color'])

        layer = self.new_custom_layer(group.name, name='NestedCustomAlphaLayer')
        self.enable_channels(layer, 'Color')
        self.enable_height_bump(layer)
        self.set_smooth_bump(True)

        tree = self.get_layer_tree(layer)
        group_node = tree.nodes.get(layer.source_group)
        self.assertIsNotNone(group_node, 'the custom layer did not nest')
        # A real input is forwarded, so the negative assertion below cannot pass vacuously.
        self.assert_custom_inputs_forwarded(layer, ('Color',))
        self.assertNotIn('Alpha', [inp.name for inp in group_node.inputs])
        self.assertIsNone(group_node.node_tree.nodes.get(common.TREE_START).outputs.get('Alpha'))

        # On the inner group node every input is fed except the literal `Alpha`: the layer stream
        # is `Color Alpha`, so there is no source to invent for a bare `Alpha`.
        inner = group_node.node_tree.nodes.get(layer.source)
        self.assertIsNotNone(inner, 'the custom source node is not in the nested tree')
        self.assertIn('Alpha', inner.inputs)
        self.assertEqual(len(inner.inputs['Alpha'].links), 0,
                         'the bare Alpha input was linked into the nested tree')
        self.assertGreater(len(inner.inputs['Color'].links), 0,
                           'no other input was forwarded, so the Alpha test is vacuous')
        unlinked = [inp.name for inp in inner.inputs if not inp.links]
        self.assertEqual(unlinked, ['Alpha'],
                         'unlinked inner inputs should be exactly Alpha, got %r' % unlinked)

    def test_04_vector_input_keeps_the_mapping_leg_and_removes_it_when_undeclared(self):
        group = self.make_group('NestedCustomVector',
                                outputs=[('Color', 'NodeSocketColor')],
                                inputs=[('Color', 'NodeSocketColor'), ('Vector', 'NodeSocketVector')])
        group_in = group.nodes.new('NodeGroupInput')
        group_out = group.nodes.new('NodeGroupOutput')
        group.links.new(group_in.outputs['Color'], group_out.inputs['Color'])

        layer = self.new_custom_layer(group.name, name='NestedCustomVectorLayer')
        self.enable_channels(layer, 'Color')
        self.enable_height_bump(layer)
        self.set_smooth_bump(True)

        tree = self.get_layer_tree(layer)
        group_node = tree.nodes.get(layer.source_group)
        self.assertIsNotNone(group_node, 'the custom layer did not nest')
        mapping = tree.nodes.get(layer.mapping)
        self.assertIsNotNone(mapping, 'the Vector input did not create a mapping node')
        self.assertIn('Vector', group_node.inputs)
        vector_links = group_node.inputs['Vector'].links
        self.assertEqual(len(vector_links), 1)
        self.assertEqual(vector_links[0].from_socket, mapping.outputs[0],
                         'the custom Vector input did not take the mapping leg')
        # `Vector` is the one contract name the outer Start does not feed: the mapping leg does,
        # and the nested Start carries it inward (FR-7).
        inner = group_node.node_tree.nodes.get(layer.source)
        self.assertIn('Vector', inner.inputs)
        self.assertEqual(len(inner.inputs['Vector'].links), 1,
                         'the inner Vector input is not fed from the nested Start')
        self.assertEqual(
            inner.inputs['Vector'].links[0].from_socket,
            group_node.node_tree.nodes.get(common.TREE_START).outputs.get('Vector'))
        self.assert_custom_inputs_forwarded(layer, ('Color',))

        # Removing the group's Vector input (a live interface edit) must drop the mapping node and
        # the declared nested input; otherwise a dead mapping node is left behind.
        common.remove_tree_input(group, input_outputs.get_tree_input_by_name(group, 'Vector'))
        input_outputs.check_all_channel_ios(self.get_yp())

        tree = self.get_layer_tree(layer)
        self.assertIsNone(tree.nodes.get(layer.mapping),
                          'the dead mapping node survived the Vector input removal')
        group_node = tree.nodes.get(layer.source_group)
        self.assertNotIn('Vector', [inp.name for inp in group_node.inputs])
        self.assertIsNone(
            group_node.node_tree.nodes.get(common.TREE_START).outputs.get('Vector'),
            'the nested interface kept a dead Vector input')

    def test_05_group_swap_and_make_unique_while_nested(self):
        group_a = self.make_passthrough_group(
            'NestedSwapA',
            inputs=[('Color', 'NodeSocketColor')],
            outputs=[('Color', 'NodeSocketColor')])
        layer = self.new_custom_layer(group_a.name, name='NestedSwapLayer')
        self.enable_channels(layer, 'Color', 'Roughness')
        self.enable_height_bump(layer)
        self.set_smooth_bump(True)
        self.assert_custom_inputs_forwarded(layer, ('Color',))

        group_b = self.make_passthrough_group(
            'NestedSwapB',
            inputs=[('Color', 'NodeSocketColor'), ('Roughness', 'NodeSocketFloat')],
            outputs=[('Color', 'NodeSocketColor'), ('Roughness', 'NodeSocketFloat')])

        # The real Change Group path: it does not halt the reconnect, so the declaration and the
        # forward run in the same pass as the interface change.
        self.assertTrue(custom_node_common.set_custom_layer_group(layer, group_b),
                        'the group swap was rejected')
        self.assertIs(layer.custom_group, group_b)
        self.assertIsNotNone(self.get_layer_tree(layer).nodes.get(layer.source_group),
                             'the layer un-nested on the group swap')
        self.assert_custom_inputs_forwarded(layer, ('Color', 'Roughness'))
        self.assert_enabled_channel_inputs_connected(layer)

        unique = custom_node_common.make_group_unique(layer)
        self.assertIsNotNone(unique, 'Make Unique did not produce a copy')
        self.assertIs(layer.custom_group, unique)
        self.assert_custom_inputs_forwarded(layer, ('Color', 'Roughness'))
        self.assert_enabled_channel_inputs_connected(layer)

        restore = self.render_settings()
        try:
            nested = list(self.render_center_pixel('nested_swap_nested.png'))
            self.set_smooth_bump(False)
            flat = list(self.render_center_pixel('nested_swap_flat.png'))
        finally:
            self.set_smooth_bump(False)
            restore()

        self.assert_pixels_close(nested, flat, 'group swap + Make Unique parity')

    def test_06_smooth_bump_custom_matches_noise(self):
        color = (0.2, 0.6, 0.9, 1.0)
        group = self.make_group('NestedParityCustom',
                                outputs=[('Color', 'NodeSocketColor')],
                                inputs=[('Color', 'NodeSocketColor')])
        rgb = group.nodes.new('ShaderNodeRGB')
        rgb.outputs[0].default_value = color
        group_out = group.nodes.new('NodeGroupOutput')
        group.links.new(rgb.outputs[0], group_out.inputs['Color'])

        custom = self.new_custom_layer(group.name, name='NestedParityCustomLayer')
        custom.channels[0].enable = True
        bpy.ops.wm.y_new_layer(name='NestedParityNoise', type='NOISE', uv_map='UVMap')
        noise = self.get_active_layer()
        noise.channels[0].enable = True

        # Inserting the second layer can move a stored layer reference to another collection slot;
        # resolve both by name once they exist (same caveat as test_custom_parity).
        yp = self.get_yp()
        custom = next(lay for lay in yp.layers if lay.name == 'NestedParityCustomLayer')
        noise = next(lay for lay in yp.layers if lay.name == 'NestedParityNoise')
        for layer in (custom, noise):
            self.enable_height_bump(layer)

        restore = self.render_settings()
        try:
            self.set_smooth_bump(True)
            for layer in (custom, noise):
                self.assertIsNotNone(self.get_layer_tree(layer).nodes.get(layer.source_group),
                                     '%s did not nest' % layer.name)

            # FR-27: the passthrough input link survives the nesting toggle.
            self.assert_custom_inputs_forwarded(custom, ('Color',))

            def render_alone(layer, filename, normalize):
                for other in (custom, noise):
                    other.enable = (other == layer)
                node_connections.reconnect_yp_nodes(yp.id_data)
                if normalize:
                    self.replace_source_with_constant(layer, color)
                return list(self.render_center_pixel(filename))

            custom_pixel = render_alone(custom, 'nested_parity_custom.png', False)
            noise_pixel = render_alone(noise, 'nested_parity_noise.png', True)
        finally:
            custom.enable = True
            noise.enable = True
            self.set_smooth_bump(False)
            restore()

        self.assert_pixels_close(custom_pixel, noise_pixel, 'custom vs noise smooth bump')

    def test_07_group_input_matching_no_channel_stays_unlinked(self):
        """P1c review: nested and flat must read one rule.

        A group input named like the outer UV tunnel (`UVMap UV`) is not a root channel, so the flat
        FR-6 path leaves it unlinked. The nested declaration used to forward any outer `Start`
        output, which linked it there only: flat centre `[0.5490 …]` vs old nested `[0.5922 …]`, a
        delta of 11/255. The output below adds the UV stream to Color, so a wrongly linked input
        visibly changes the render.
        """
        group = self.make_group('NestedCustomUVMap',
                                outputs=[('Color', 'NodeSocketColor')],
                                inputs=[('Color', 'NodeSocketColor'),
                                        ('UVMap UV', 'NodeSocketVector')])
        group_in = group.nodes.new('NodeGroupInput')
        group_out = group.nodes.new('NodeGroupOutput')
        add = group.nodes.new('ShaderNodeMixRGB')
        add.blend_type = 'ADD'
        add.inputs['Fac'].default_value = 1.0
        group.links.new(group_in.outputs['Color'], add.inputs['Color1'])
        group.links.new(group_in.outputs['UVMap UV'], add.inputs['Color2'])
        group.links.new(add.outputs['Color'], group_out.inputs['Color'])

        layer = self.new_custom_layer(group.name, name='NestedCustomUVMapLayer')
        self.enable_channels(layer, 'Color')
        self.enable_height_bump(layer)

        restore = self.render_settings()
        try:
            # Smooth bump off: the layer stays flat, this is the reference render.
            self.set_smooth_bump(False)
            flat = list(self.render_center_pixel('nested_uvmap_flat.png'))

            self.set_smooth_bump(True)
            self.assert_layer_nested(layer)
            tree = self.get_layer_tree(layer)
            group_node = tree.nodes.get(layer.source_group)
            self.assertIsNotNone(group_node, 'the custom layer did not nest')
            # `UVMap UV` matches no channel: it must not be declared or linked in the nested tree.
            self.assertNotIn('UVMap UV', [inp.name for inp in group_node.inputs],
                             'the nested instance declared the non-channel UVMap UV input')
            inner = group_node.node_tree.nodes.get(layer.source)
            self.assertIn('UVMap UV', inner.inputs)
            self.assertEqual(len(inner.inputs['UVMap UV'].links), 0,
                             'the nested tree linked the non-channel UVMap UV input')
            # The real channel input is still forwarded, so the test would notice a dead contract.
            self.assert_custom_inputs_forwarded(layer, ('Color',))

            nested = list(self.render_center_pixel('nested_uvmap_nested.png'))
        finally:
            self.set_smooth_bump(False)
            restore()

        self.assert_pixels_close(flat, nested, 'non-channel input flat vs nested')


if __name__ == '__main__':
    unittest.main()
