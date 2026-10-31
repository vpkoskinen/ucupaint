from .common import *
from . import ListItem, custom_node_common

def create_link(tree, out, inp):
    node = inp.node
    if not any(l for l in out.links if l.to_socket == inp):
        tree.links.new(out, inp)
        #print(out, 'is connected to', inp)
    if node: return node.outputs
    return []

def break_link(tree, out, inp):
    for link in out.links:
        if link.to_socket == inp:
            tree.links.remove(link)
            return True
    return False

def break_input_link(tree, inp):
    for link in inp.links:
        tree.links.remove(link)

def break_output_link(tree, outp):
    for link in outp.links:
        tree.links.remove(link)

def reconnect_mask_modifier_nodes(tree, mod, start_value):
    
    value = start_value

    if mod.type == 'INVERT':
        invert = tree.nodes.get(mod.invert)
        create_link(tree, value, invert.inputs[1])
        value = invert.outputs[0]

    elif mod.type == 'RAMP':
        ramp = tree.nodes.get(mod.ramp)
        ramp_mix = tree.nodes.get(mod.ramp_mix)
        mixcol0, mixcol1, mixout = get_mix_color_indices(ramp_mix)

        create_link(tree, value, ramp.inputs[0])
        create_link(tree, value, ramp_mix.inputs[mixcol0])
        create_link(tree, ramp.outputs[0], ramp_mix.inputs[mixcol1])

        value = ramp_mix.outputs[mixout]

    elif mod.type == 'CURVE':
        curve = tree.nodes.get(mod.curve)
        create_link(tree, value, curve.inputs[1])
        value = curve.outputs[0]

    return value

def reconnect_modifier_nodes(tree, mod, start_rgb, start_alpha):

    if not mod.enable:
        return start_rgb, start_alpha

    used_by_paired_alpha = is_modifier_used_by_paired_alpha_channel(mod)

    rgb = start_rgb
    alpha = start_alpha

    if mod.type == 'INVERT':

        invert = tree.nodes.get(mod.invert)
        if invert:
            rgb = create_link(tree, rgb, invert.inputs[0])[0]
            create_link(tree, alpha, invert.inputs[1])
            if len(invert.outputs) > 1: alpha = invert.outputs[1]

    elif mod.type == 'RGB_TO_INTENSITY':

        rgb2i = tree.nodes.get(mod.rgb2i)
        if rgb2i:
            rgb = create_link(tree, rgb, rgb2i.inputs[0])[0]
            alpha = create_link(tree, alpha, rgb2i.inputs[1])[1]

    elif mod.type == 'INTENSITY_TO_RGB':

        i2rgb = tree.nodes.get(mod.i2rgb)
        if i2rgb:
            rgb = create_link(tree, rgb, i2rgb.inputs[0])[0]
            alpha = create_link(tree, alpha, i2rgb.inputs[1])[1]

    elif mod.type == 'OVERRIDE_COLOR':

        oc = tree.nodes.get(mod.oc)
        if oc:
            rgb = create_link(tree, rgb, oc.inputs[0])[0]
            alpha = create_link(tree, alpha, oc.inputs[1])[1]

    elif mod.type == 'COLOR_RAMP':

        color_ramp = tree.nodes.get(mod.color_ramp)
        if color_ramp and (mod.affect_alpha or mod.affect_color or used_by_paired_alpha):

            color_ramp_alpha_multiply = tree.nodes.get(mod.color_ramp_alpha_multiply)
            if color_ramp_alpha_multiply:
                am_mixcol0, am_mixcol1, am_mixout = get_mix_color_indices(color_ramp_alpha_multiply)
                rgb = create_link(tree, rgb, color_ramp_alpha_multiply.inputs[am_mixcol0])[am_mixout]
                create_link(tree, alpha, color_ramp_alpha_multiply.inputs[am_mixcol1])

            if mod.affect_alpha and not mod.affect_color and not used_by_paired_alpha:
                alpha = create_link(tree, alpha, color_ramp.inputs[0])[0]
            else:
                color_ramp_linear_start = tree.nodes.get(mod.color_ramp_linear_start)
                if color_ramp_linear_start:
                    rgb = create_link(tree, rgb, color_ramp_linear_start.inputs[0])[0]

                rgb = create_link(tree, rgb, color_ramp.inputs[0])[0]

                if mod.affect_alpha and mod.affect_color:
                    alpha = color_ramp.outputs[1]

                color_ramp_linear = tree.nodes.get(mod.color_ramp_linear)
                if color_ramp_linear:
                    rgb  = create_link(tree, rgb, color_ramp_linear.inputs[0])[0]

    elif mod.type == 'RGB_CURVE':

        rgb_curve = tree.nodes.get(mod.rgb_curve)
        if rgb_curve:
            rgb = create_link(tree, rgb, rgb_curve.inputs[1])[0]

    elif mod.type == 'HUE_SATURATION':

        huesat = tree.nodes.get(mod.huesat)
        if huesat:
            rgb = create_link(tree, rgb, huesat.inputs[4])[0]

    elif mod.type == 'BRIGHT_CONTRAST':

        brightcon = tree.nodes.get(mod.brightcon)
        if brightcon:
            rgb = create_link(tree, rgb, brightcon.inputs[0])[0]

    elif mod.type == 'MULTIPLIER':

        multiplier = tree.nodes.get(mod.multiplier)
        if multiplier:
            rgb = create_link(tree, rgb, multiplier.inputs[0])[0]
            alpha = create_link(tree, alpha, multiplier.inputs[1])[1]

    elif mod.type == 'MATH':

        mmath = tree.nodes.get(mod.math)
        if mmath:
            rgb = create_link(tree, rgb, mmath.inputs[0])[0]
            alpha = create_link(tree, alpha, mmath.inputs[1])[1]

    return rgb, alpha

def reconnect_all_modifier_nodes(tree, parent, start_rgb, start_alpha, mod_group=None, use_modifier_1=False):

    rgb = start_rgb
    alpha = start_alpha

    if mod_group:
        # Connect modifier group node
        create_link(tree, rgb, mod_group.inputs[0])
        create_link(tree, alpha, mod_group.inputs[1])

        # Get nodes inside modifier group tree and repoint it
        mod_tree = mod_group.node_tree
        start = mod_tree.nodes.get(MOD_TREE_START)
        if start:
            rgb = start.outputs[0]
            alpha = start.outputs[1]
    else:
        mod_tree = tree

    modifiers = parent.modifiers
    if use_modifier_1:
        modifiers = parent.modifiers_1

    # Connect all the nodes
    for mod in reversed(modifiers):
        rgb, alpha = reconnect_modifier_nodes(mod_tree, mod, rgb, alpha)

    if mod_group:

        # Connect to end node
        end = mod_tree.nodes.get(MOD_TREE_END)
        if end:
            create_link(mod_tree, rgb, end.inputs[0])
            create_link(mod_tree, alpha, end.inputs[1])

        # Repoint rgb and alpha to mod group
        rgb = mod_group.outputs[0]
        alpha = mod_group.outputs[1]

    return rgb, alpha

def remove_all_prev_inputs(tree, layer, node): #, height_only=False):

    yp = layer.id_data.yp

    if layer.parent_idx == -1: 
        return

    for i, ch in enumerate(layer.channels):
        root_ch = yp.channels[i]
        if has_previous_layer_channels(layer, root_ch): continue

        if root_ch.special_type == 'HEIGHT':
            io_name = root_ch.name + io_suffix['SCALE']
            if io_name in node.inputs:
                break_input_link(tree, node.inputs[io_name])

        #if height_only: continue

        io_name = root_ch.name
        if io_name in node.inputs:
            # Should always fill normal input
            if root_ch.special_type == 'NORMAL':
                create_link(tree, get_essential_node(tree, GEOMETRY)['Normal'], node.inputs[io_name])
            else:
                break_input_link(tree, node.inputs[io_name])
            
        io_name = root_ch.name + io_suffix['ALPHA']
        if io_name in node.inputs:
            break_input_link(tree, node.inputs[io_name])

def remove_unused_group_node_connections(tree, layer, node): #, height_only=False):

    yp = layer.id_data.yp
    #node = tree.nodes.get(layer.group_node)

    if layer.type != 'GROUP':
        return

    for i, ch in enumerate(layer.channels):
        root_ch = yp.channels[i]
        if has_channel_children(layer, root_ch): continue

        io_name = root_ch.name + io_suffix['HEIGHT'] + io_suffix['GROUP']
        if io_name in node.inputs:
            break_input_link(tree, node.inputs[io_name])

        io_name = root_ch.name + io_suffix['HEIGHT'] + io_suffix['ALPHA'] + io_suffix['GROUP']
        if io_name in node.inputs:
            break_input_link(tree, node.inputs[io_name])

        io_name = root_ch.name + io_suffix['SCALE']
        if io_name in node.inputs:
            break_input_link(tree, node.inputs[io_name])

        #if height_only: continue

        io_name = root_ch.name + io_suffix['GROUP']
        if io_name in node.inputs:
            # Should always fill normal input
            #geometry = tree.nodes.get(GEOMETRY)
            #if root_ch.special_type == 'NORMAL' and geometry:
            #    create_link(tree, geometry.outputs['Normal'], node.inputs[io_name])
            #else:
            break_input_link(tree, node.inputs[io_name])

        io_name = root_ch.name + io_suffix['ALPHA'] + io_suffix['GROUP']
        if io_name in node.inputs:
            break_input_link(tree, node.inputs[io_name])

''' Get essential node and if not found, create one '''
def get_essential_node(tree, name):
    node = tree.nodes.get(name)
    if not node:
        if name == TREE_START:
            node = tree.nodes.new('NodeGroupInput')
            node.name = TREE_START
            node.label = 'Start'

        elif name == TREE_END:
            node = tree.nodes.new('NodeGroupOutput')
            node.name = TREE_END
            node.label = 'End'

        elif name == ONE_VALUE:
            node = tree.nodes.new('ShaderNodeValue')
            node.name = ONE_VALUE
            node.label = 'One Value'
            node.outputs[0].default_value = 1.0

        elif name == HALF_VALUE:
            node = tree.nodes.new('ShaderNodeValue')
            node.name = HALF_VALUE
            node.label = 'Half Value'
            node.outputs[0].default_value = 0.5

        elif name == ZERO_VALUE:
            node = tree.nodes.new('ShaderNodeValue')
            node.name = ZERO_VALUE
            node.label = 'Zero Value'
            node.outputs[0].default_value = 0.0

        elif name == GEOMETRY:
            node = tree.nodes.new('ShaderNodeNewGeometry')
            node.name = GEOMETRY

        elif name == TEXCOORD:
            node = tree.nodes.new('ShaderNodeTexCoord')
            node.name = TEXCOORD

    if name == TREE_END:
        return node.inputs

    return node.outputs

''' Check for all essential nodes and delete them if no links found '''
def clean_essential_nodes(tree, exclude_texcoord=False, exclude_geometry=False):
    for name in [ONE_VALUE, HALF_VALUE, ZERO_VALUE, GEOMETRY, TEXCOORD, TREE_START, TREE_END]:
        if exclude_texcoord and name == TEXCOORD: continue
        if exclude_geometry and name == GEOMETRY: continue
        node = tree.nodes.get(name)
        if node:
            link_found = False
            if len(node.outputs) > 0:
                for outp in node.outputs:
                    if len(outp.links) > 0:
                        link_found = True
                        break
            elif len(node.inputs) > 0:
                for inp in node.inputs:
                    if len(inp.links) > 0:
                        link_found = True
                        break
            if not link_found:
                tree.nodes.remove(node)

def reconnect_yp_nodes(tree, merged_layer_ids = []):
    yp = tree.yp
    nodes = tree.nodes
    ypup = get_user_preferences()

    # Get color and alpha channel
    color_ch, alpha_ch = get_color_alpha_ch_pairs(yp)

    # UVs
    uv_maps = {}
    tangents = {}
    bitangents = {}

    for uv in yp.uvs:
        uv_map = nodes.get(uv.uv_map)
        if uv_map:
            uv_maps[uv.name] = uv_map.outputs[0]

        tangent_process = nodes.get(uv.tangent_process)
        if tangent_process:
            tangents[uv.name] = tangent_process.outputs['Tangent']
            bitangents[uv.name] = tangent_process.outputs['Bitangent']

    # Get normal and height channel
    root_normal_ch = get_root_normal_channel(yp)
    root_height_ch = get_root_height_channel(yp)

    # Get main UV
    main_uv = None
    if root_normal_ch and root_normal_ch.main_uv != '':
        main_uv = yp.uvs.get(root_normal_ch.main_uv)

    if not main_uv and len(yp.uvs) > 0:
        main_uv = yp.uvs[0]

    # Get main tangent and bitangent
    if main_uv and main_uv.name in tangents and main_uv.name in bitangents:
        tangent = tangents[main_uv.name]
        bitangent = bitangents[main_uv.name]
    else:
        tangent = None
        bitangent = None

    baked_uv = yp.uvs.get(yp.baked_uv_name)
    baked_uv_map = nodes.get(baked_uv.uv_map) if baked_uv else None
    if baked_uv_map: baked_uv_map = baked_uv_map.outputs[0]

    for i, ch in enumerate(yp.channels):
        #if ch_idx != -1 and i != ch_idx: continue

        start_linear = nodes.get(ch.start_linear)
        end_linear = nodes.get(ch.end_linear)
        end_normal_engine_filter = nodes.get(ch.end_normal_engine_filter)
        end_backface = nodes.get(ch.end_backface)
        clamp = nodes.get(ch.clamp)
        end_max_height = nodes.get(ch.end_max_height)
        end_max_height_tweak = nodes.get(ch.end_max_height_tweak)
        start_normal_filter = nodes.get(ch.start_normal_filter)
        start_bump_process = nodes.get(ch.start_bump_process)
        start_height_process = nodes.get(ch.start_height_process)

        io_name = ch.name
        io_alpha_name = ch.name + io_suffix['ALPHA']
        io_max_height_name = ch.name + io_suffix['SCALE']
        io_midlevel_name = ch.name + io_suffix['MIDLEVEL']

        rgb = get_essential_node(tree, TREE_START)[io_name]
        #if ch.enable_alpha and ch.type == 'RGB':
        if ch.enable_alpha:
            alpha = get_essential_node(tree, TREE_START)[io_alpha_name]
        else: alpha = get_essential_node(tree, ONE_VALUE)[0]

        # Base layer preview mode
        active_layer = ListItem.get_active_layer(yp)
        if is_layer_preview_mode_enabled(yp) and ch == yp.channels[yp.preview_mode_channel_index]:
            if not active_layer:
                col_preview = get_essential_node(tree, TREE_END).get(LAYER_VIEWER)
                alpha_preview = get_essential_node(tree, TREE_END).get(LAYER_ALPHA_VIEWER)
                if col_preview:
                    if ch.special_type == 'NORMAL' and start_normal_filter:
                        create_link(tree, start_normal_filter.outputs[0], col_preview)
                    else: create_link(tree, rgb, col_preview)
                if alpha_preview:
                    if alpha_ch and color_ch == ch:
                        alpha_ch_io = get_essential_node(tree, TREE_START).get(alpha_ch.name)
                        if alpha_ch_io: create_link(tree, alpha_ch_io, alpha_preview)
                    else:
                        create_link(tree, alpha, alpha_preview)

        midlevel = None
        max_height = None

        if ch.special_type == 'HEIGHT':
            if io_max_height_name in get_essential_node(tree, TREE_START):
                max_height = get_essential_node(tree, TREE_START)[io_max_height_name]
            else: max_height = get_essential_node(tree, ONE_VALUE)[0]

            if io_midlevel_name in get_essential_node(tree, TREE_START):
                midlevel = get_essential_node(tree, TREE_START)[io_midlevel_name]
            else: midlevel = get_essential_node(tree, ZERO_VALUE)[0]

            # Input height process
            if start_height_process:
                rgb = create_link(tree, rgb, start_height_process.inputs[0])[0]
                if max_height and 'Value Max Height' in start_height_process.inputs:
                    create_link(tree, max_height, start_height_process.inputs['Value Max Height'])
                if midlevel and 'Midlevel' in start_height_process.inputs:
                    create_link(tree, midlevel, start_height_process.inputs['Midlevel'])

        if start_linear:
            rgb = create_link(tree, rgb, start_linear.inputs[0])[0]
        elif start_normal_filter:
            rgb = create_link(tree, rgb, start_normal_filter.inputs[0])[0]

        # Layers loop
        for j, layer in reversed(list(enumerate(yp.layers))):

            node = nodes.get(layer.group_node)
            if not node: continue
            layer_ch = layer.channels[i]

            # Get layer channel pairs
            layer_color_ch, layer_alpha_ch = get_layer_color_alpha_ch_pairs(layer)
            layer_normal_ch, layer_height_ch = get_layer_normal_height_ch_pairs(layer)

            if layer_ch == layer_normal_ch and layer_height_ch.enable and layer_height_ch.use_height_as_normal:
                layer_ch_enable = True
            elif layer_ch != layer_alpha_ch:
                layer_ch_enable = layer_ch.enable
            else: layer_ch_enable = layer_color_ch.enable or layer_alpha_ch.enable

            #is_hidden = not layer.enable or is_parent_hidden(layer)

            if is_layer_preview_mode_enabled(yp) and active_layer: # and yp.preview_mode_type == 'LAYER':

                if ch == yp.channels[yp.preview_mode_channel_index] and layer == yp.layers[yp.active_layer_index]:

                    col_preview = get_essential_node(tree, TREE_END).get(LAYER_VIEWER)
                    alpha_preview = get_essential_node(tree, TREE_END).get(LAYER_ALPHA_VIEWER)
                    # The layer's viewer outputs are yp-wide state, created for every layer tree
                    # while layer preview mode is on. A socket can still be missing mid-rebuild
                    # (the tree was just rebuilt and this pass runs before the owner is refreshed),
                    # so tolerate its absence instead of raising (P1a).
                    col_preview_soc = node.outputs.get(LAYER_VIEWER)
                    alpha_preview_soc = node.outputs.get(LAYER_ALPHA_VIEWER)
                    # CUSTOM: a missing group previews like a disabled layer (nothing to show).
                    layer_hidden = not layer.enable or (
                        layer.type == 'CUSTOM' and not custom_node_common.is_custom_layer_group_usable(layer))
                    if col_preview:
                        #create_link(tree, rgb, col_preview)
                        if layer_hidden:
                            create_link(tree, get_essential_node(tree, ZERO_VALUE)[0], col_preview)
                        elif col_preview_soc: create_link(tree, col_preview_soc, col_preview)
                    if alpha_preview:
                        if layer_hidden:
                            create_link(tree, get_essential_node(tree, ZERO_VALUE)[0], alpha_preview)
                        elif alpha_preview_soc: create_link(tree, alpha_preview_soc, alpha_preview)

            if (
                #(merged_layer_ids and j not in merged_layer_ids and not is_hidden)
                (merged_layer_ids and j not in merged_layer_ids) or
                not layer.enable or
                # CUSTOM: a layer whose group is missing or unusable has nothing to contribute, so
                # it falls through exactly like a disabled layer (FR-16) — the below-layers value
                # reaches the layer above unchanged.
                (layer.type == 'CUSTOM' and not custom_node_common.is_custom_layer_group_usable(layer))
                ):

                if node:
                    for inp in node.inputs:
                        break_input_link(tree, inp)
                    for outp in node.outputs:
                        break_input_link(tree, outp)

                continue

            #if is_hidden:
            #    continue

            need_prev_normal = check_need_prev_normal(layer)

            if not (ch.special_type in {'NORMAL', 'HEIGHT'} and need_prev_normal) and not layer_ch_enable:
                continue

            # UV inputs
            uv_names = []

            if root_height_ch and root_height_ch.main_uv != '':
                uv_names.append(root_height_ch.main_uv)

            if layer.texcoord_type == 'UV' and layer.uv_name not in uv_names:
                uv_names.append(layer.uv_name)

            if layer.use_baked and layer.baked_uv_name != '' and layer.baked_uv_name not in uv_names:
                uv_names.append(layer.baked_uv_name)

            for mask in layer.masks:
                if mask.texcoord_type == 'UV' and mask.uv_name not in uv_names:
                    uv_names.append(mask.uv_name)

                if mask.use_baked and mask.baked_uv_name != '' and mask.baked_uv_name not in uv_names:
                    uv_names.append(mask.baked_uv_name)

            for uv_name in uv_names:
                uv = yp.uvs.get(uv_name)
                if not uv: continue
                inp = node.inputs.get(uv_name + io_suffix['UV'])
                if inp:
                    if uv_name in uv_maps:
                        create_link(tree, uv_maps[uv_name], inp)

                inp = node.inputs.get(uv_name + io_suffix['TANGENT'])
                if inp and uv_name in tangents: 
                    create_link(tree, tangents[uv_name], inp)

                inp = node.inputs.get(uv_name + io_suffix['BITANGENT'])
                if inp and uv_name in bitangents: 
                    create_link(tree, bitangents[uv_name], inp)

            # Texcoord inputs
            texcoords = []
            if layer.texcoord_type not in {'UV', 'Decal'}:
                texcoords.append(layer.texcoord_type)

            for mask in layer.masks:
                if mask.texcoord_type not in {'UV', 'Decal', 'Layer'} and mask.texcoord_type not in texcoords:
                    texcoords.append(mask.texcoord_type)

            for tc in texcoords:
                inp = node.inputs.get(io_names[tc])
                if inp: 
                    create_link(tree, get_essential_node(tree, TEXCOORD)[tc], inp)

            # Merge process doesn't care with parents
            if not merged_layer_ids and layer.parent_idx != -1: continue

            if io_name in node.inputs: 
                outputs = create_link(tree, rgb, node.inputs[io_name])
                if io_name in outputs: rgb = outputs[io_name]

            if ch.enable_alpha and io_alpha_name in node.inputs:
                outputs = create_link(tree, alpha, node.inputs[io_alpha_name])
                if io_alpha_name in outputs: alpha = outputs[io_alpha_name]

            if max_height and io_max_height_name in node.inputs:
                outps = create_link(tree, max_height, node.inputs[io_max_height_name])
                if io_max_height_name in outps:
                    max_height = outps[io_max_height_name]

        rgb, alpha = reconnect_all_modifier_nodes(tree, ch, rgb, alpha)

        if end_linear and (end_linear.type != 'GROUP' or end_linear.node_tree):
            rgb = create_link(tree, rgb, end_linear.inputs[0])[0]

        if ch.special_type == 'HEIGHT':

            end_height_normalize = nodes.get(ch.end_height_normalize)
            if end_height_normalize:
                if 'Height' in end_height_normalize.inputs:
                    rgb = create_link(tree, rgb, end_height_normalize.inputs['Height'])[0]

                if max_height and 'Max Height' in end_height_normalize.inputs:
                    create_link(tree, max_height, end_height_normalize.inputs['Max Height'])

            end_bump_process = nodes.get(ch.end_bump_process)
            if end_bump_process:
                if 'Height' in end_bump_process.inputs:
                    #rgb = create_link(tree, rgb, end_bump_process.inputs['Height'])[0]
                    create_link(tree, rgb, end_bump_process.inputs['Height'])

                if ch.use_height_normalize and max_height and 'Distance' in end_bump_process.inputs:
                    create_link(tree, max_height, end_bump_process.inputs['Distance'])

        if clamp:
            mixcol0, mixcol1, mixout = get_mix_color_indices(clamp)
            rgb = create_link(tree, rgb, clamp.inputs[mixcol0])[mixout]

        # Check if height channel use bump only
        if ch.special_type in {'NORMAL', 'HEIGHT'}:
            normal_ch, height_ch = get_normal_height_ch_pairs(yp)
            if height_ch and height_ch.use_height_as_bump:
                height_end_bump_process = nodes.get(height_ch.end_bump_process)
                if ch == normal_ch:
                    if height_end_bump_process and 'Normal' in height_end_bump_process.inputs:
                        rgb = create_link(tree, rgb, height_end_bump_process.inputs['Normal'])[0]

                elif ch == height_ch and not is_channel_preview_mode_enabled(yp):
                    if ch.use_height_normalize:
                        rgb = get_essential_node(tree, HALF_VALUE)[0]
                    else: rgb = get_essential_node(tree, ZERO_VALUE)[0]
        
        if yp.use_baked and not ch.disable_global_baked:

            baked_soc = None

            bt = yp.bake_targets.get(ch.bake_target_name)

            if bt:
                baked_node = nodes.get(bt.baked_node)

                if ch.special_type == 'HEIGHT':
                    if bt.height_normalize:
                        max_value_node = nodes.get(bt.max_value_node)
                        if max_value_node:
                            max_height = max_value_node.outputs[0]

                if baked_node:
                    # Separate XYZ
                    separate_xyz = nodes.get(bt.separate_xyz)
                    if separate_xyz: create_link(tree, baked_node.outputs[0], separate_xyz.inputs[0])

                    # Invert values
                    invert_r = nodes.get(bt.invert_r)
                    invert_g = nodes.get(bt.invert_g)
                    invert_b = nodes.get(bt.invert_b)
                    invert_a = nodes.get(bt.invert_a)

                    # Connect invert nodes
                    if separate_xyz:
                        if invert_r: create_link(tree, separate_xyz.outputs[0], invert_r.inputs[1])
                        if invert_g: create_link(tree, separate_xyz.outputs[1], invert_g.inputs[1])
                        if invert_b: create_link(tree, separate_xyz.outputs[2], invert_b.inputs[1])
                    if invert_a:
                        if baked_node.type == 'TEX_IMAGE': create_link(tree, baked_node.outputs[1], invert_a.inputs[1])
                        elif baked_node.type == 'ATTRIBUTE': create_link(tree, baked_node.outputs['Alpha'], invert_a.inputs[1])

                    if is_bake_target_using_exact_channel(bt, ch):
                        if baked_node.type == 'TEX_IMAGE': baked_soc = baked_node.outputs[0]
                        elif baked_node.type == 'ATTRIBUTE': baked_soc = baked_node.outputs['Color']

                    elif ch.type == 'VALUE' or get_bake_target_subchannel_ids_of_rgb_to_bw_channel(bt, ch) != -1:
                        if ch.type == 'VALUE': index = get_bake_target_subchannel_ids_of_value_channel(bt, ch) 
                        else: index = get_bake_target_subchannel_ids_of_rgb_to_bw_channel(bt, ch)
                        if index != -1:
                            if index == 3:
                                if bt.a.invert_value and invert_a: baked_soc = invert_a.outputs[0]
                                elif baked_node.type == 'TEX_IMAGE': baked_soc = baked_node.outputs[1]
                                elif baked_node.type == 'ATTRIBUTE': baked_soc = baked_node.outputs['Alpha']
                            else: 
                                if index == 0 and bt.r.invert_value and invert_r: baked_soc = invert_r.outputs[0]
                                elif index == 1 and bt.g.invert_value and invert_g: baked_soc = invert_g.outputs[0]
                                elif index == 2 and bt.b.invert_value and invert_b: baked_soc = invert_b.outputs[0]
                                elif separate_xyz: baked_soc = separate_xyz.outputs[index]
                    else:
                        ids = get_bake_target_subchannel_ids_of_rgb_channel(bt, ch)
                        if -1 not in ids:
                            baked_combine_xyz = nodes.get(ch.baked_combine_xyz)
                            if separate_xyz and baked_combine_xyz:
                                # Get base socket
                                socs = []
                                for i in range(len(ids)):
                                    if ids[i] == 3:
                                        if baked_node.type == 'TEX_IMAGE': socs.append(baked_node.outputs[1])
                                        elif baked_node.type == 'ATTRIBUTE': socs.append(baked_node.outputs['Alpha'])
                                    else: socs.append(separate_xyz.outputs[ids[i]])

                                # Check for inverted value
                                for i, index in enumerate(ids):
                                    if index == 0 and bt.r.invert_value and invert_r: socs[i] = invert_r.outputs[0]
                                    elif index == 1 and bt.g.invert_value and invert_g: socs[i] = invert_g.outputs[0]
                                    elif index == 2 and bt.b.invert_value and invert_b: socs[i] = invert_b.outputs[0]
                                    elif index == 3 and bt.a.invert_value and invert_a: socs[i] = invert_a.outputs[0]

                                # Connect to combine xyz
                                for i, soc in enumerate(socs):
                                    create_link(tree, soc, baked_combine_xyz.inputs[i])

                                baked_soc = baked_combine_xyz.outputs[0]

            if baked_soc:
                rgb = baked_soc

                if ch.special_type == 'NORMAL':

                    #baked_normal_no_disp = nodes.get(ch.baked_normal_no_disp)
                    #if baked_normal_no_disp and height_ch and not height_ch.use_height_as_bump:
                    #    rgb = baked_normal_no_disp.outputs[0]

                    baked_normal_prep = nodes.get(ch.baked_normal_prep)
                    if baked_normal_prep:
                        if rgb:
                            rgb = create_link(tree, rgb, baked_normal_prep.inputs[0])[0]
                        else:
                            rgb = baked_normal_prep.outputs[0]
                            break_input_link(tree, baked_normal_prep.inputs[0])

                        #HACK: Some earlier nodes have wrong default colot input
                        baked_normal_prep.inputs[0].default_value = (0.5, 0.5, 1.0, 1.0)

                    baked_normal = nodes.get(ch.baked_normal)
                    if baked_normal:
                        rgb = create_link(tree, rgb, baked_normal.inputs[1])[0]

        if end_backface:
            if alpha_ch and alpha_ch == ch:
                rgb = create_link(tree, rgb, end_backface.inputs[0])[0]
            else: alpha = create_link(tree, alpha, end_backface.inputs[0])[0]
            create_link(tree, get_essential_node(tree, GEOMETRY)['Backfacing'], end_backface.inputs[1])

        if yp.use_baked and (
            (ch.use_baked_vcol and not ch.disable_global_baked) or
            (alpha_ch == ch and color_ch.use_baked_vcol and not color_ch.disable_global_baked)
            ):

            if ch == alpha_ch: baked_vcol = nodes.get(color_ch.baked_vcol)
            else: baked_vcol = nodes.get(ch.baked_vcol)

            if baked_vcol:
                if ch.bake_to_vcol_alpha or ch == alpha_ch:
                    rgb = baked_vcol.outputs['Alpha']
                else:
                    rgb = baked_vcol.outputs['Color']
                if is_channel_alpha_enabled(ch):
                    alpha = baked_vcol.outputs['Alpha']

        if io_name in get_essential_node(tree, TREE_END): 
            create_link(tree, rgb, get_essential_node(tree, TREE_END)[io_name])

        #if ch.type == 'RGB' and ch.enable_alpha:
        if ch.enable_alpha:
            create_link(tree, alpha, get_essential_node(tree, TREE_END)[io_alpha_name])
        if ch.special_type == 'HEIGHT':
            if max_height and io_max_height_name in get_essential_node(tree, TREE_END): create_link(tree, max_height, get_essential_node(tree, TREE_END)[io_max_height_name])
            if io_midlevel_name in get_essential_node(tree, TREE_END): 
                create_link(tree, get_essential_node(tree, HALF_VALUE)[0], get_essential_node(tree, TREE_END)[io_midlevel_name])

    # Bake target image nodes
    for bt in yp.bake_targets:
        baked_node = nodes.get(bt.baked_node)
        if baked_node:
            from . import BakeTarget
            uv_name = BakeTarget.get_bake_target_uv_name(bt)
            uv = yp.uvs.get(uv_name)
            bt_uv_map = nodes.get(uv.uv_map) if uv else None
            if bt_uv_map and baked_node.type == 'TEX_IMAGE': 
                create_link(tree, bt_uv_map.outputs[0], baked_node.inputs[0])

    # Merge process doesn't care with parents
    if merged_layer_ids: return

    # List of last members
    last_members = []
    for layer in yp.layers:
        # CUSTOM: a missing group is treated as disabled here too, or it could become the start of
        # a group-connection chain it does not belong to (FR-16).
        if not layer.enable or (layer.type == 'CUSTOM' and not custom_node_common.is_custom_layer_group_usable(layer)):
            continue
        if is_bottom_member(layer, True):
            last_members.append(layer)

        # Remove unused input links
        node = tree.nodes.get(layer.group_node)
        if layer.type == 'GROUP':
            remove_unused_group_node_connections(tree, layer, node)
        remove_all_prev_inputs(tree, layer, node)

    # Group stuff
    for layer in last_members:

        node = nodes.get(layer.group_node)

        cur_layer = layer
        cur_node = node

        # Dictionary of Outputs
        outs = {}
        for outp in node.outputs:
            outs[outp.name] = outp

        while True:
            # Get upper layer
            upper_idx, upper_layer = get_upper_neighbor(cur_layer)
            upper_node = nodes.get(upper_layer.group_node)

            # Connect
            if upper_layer.parent_idx == cur_layer.parent_idx:
                if upper_layer.enable:
                    for inp in upper_node.inputs:
                        if inp.name in outs:
                            o = create_link(tree, outs[inp.name], inp)
                            if inp.name in o:
                                outs[inp.name] = o[inp.name]
                        elif inp.name in upper_node.outputs: 
                            outs[inp.name] = upper_node.outputs[inp.name]

                cur_layer = upper_layer
                cur_node = upper_node
            else:

                for output_name, outp in outs.items():
                    io_name =  output_name + io_suffix['GROUP']
                    if io_name in upper_node.inputs:
                        create_link(tree, outp, upper_node.inputs[io_name])

                break

    # Clean unused essential nodes
    clean_essential_nodes(tree)

def reconnect_mask_source_nodes(mask, layer_tree):

    # A mask source tree is nested for smooth bump: its nodes live in `mask.group_node` and must
    # be wired inside that tree (P1b). The outer chain reads the group instance.
    group_node = layer_tree.nodes.get(mask.group_node)
    if group_node:
        tree = group_node.node_tree
        start = tree.nodes.get(TREE_START)
        end = tree.nodes.get(TREE_END)
    else:
        tree = layer_tree
        start = end = None

    swizzle_enabled = False
    baked_source = tree.nodes.get(mask.baked_source)
    source = None

    if mask.type == 'BACKFACE':
        val = get_essential_node(tree, GEOMETRY)['Backfacing']
        source = tree.nodes.get(GEOMETRY)
    elif baked_source and mask.use_baked:
        source = baked_source
        val = source.outputs[0]
    else: 
        source = tree.nodes.get(mask.source)

        # Get mask input socket
        soc = get_mask_input_socket(mask, source) if source else None
        val = soc if soc else get_essential_node(tree, ZERO_VALUE)[0]

        if val.type in {'RGBA', 'RGB', 'VECTOR'}:
            swizzle_enabled = True

    # Forward the generated `Start` inputs the mask source consumes (typically `Vector`).
    if start and source:
        # Re-sync the nested interface from what the flat mask source actually consumes (P1b
        # review): the tree-kind input plus every `Start`-fed source input (AO `Distance`, …). This
        # runs on every reconnect, so a source/type change prunes sockets that are no longer read.
        contract_source = baked_source if (baked_source and mask.use_baked) else source
        base_inputs = [('Value', 'NodeSocketFloat')] if mask.type == 'MODIFIER' else [('Vector', 'NodeSocketVector')]
        refresh_nested_source_ios(
            tree, contract_source, mask.type, entity=mask, outer_tree=layer_tree,
            prev_normal=(mask.type in {'HEMI', 'EDGE_DETECT', 'AO'} and not mask.use_baked),
            base_inputs=base_inputs
        )

        for inp in source.inputs:
            outp = start.outputs.get(inp.name)
            if outp is not None:
                _link_single(tree, outp, inp)

    # Swizzle
    separate_color_channels = tree.nodes.get(mask.separate_color_channels)
    if swizzle_enabled and mask.swizzle_input_mode in {'R', 'G', 'B'}:
        separate_color_channels_outputs = create_link(tree, val, separate_color_channels.inputs[0])
        if mask.swizzle_input_mode == 'R': val = separate_color_channels_outputs[0]
        elif mask.swizzle_input_mode == 'G': val = separate_color_channels_outputs[1]
        elif mask.swizzle_input_mode == 'B': val = separate_color_channels_outputs[2]

    # Linear
    linear = tree.nodes.get(mask.linear)
    if linear:
        val = create_link(tree, val, linear.inputs[0])[0]

    # Modifiers
    for mod in mask.modifiers:
        val = reconnect_mask_modifier_nodes(tree, mod, val)

    # Feed the nested mask's `Value` output and read the instance from the outer tree.
    if end:
        end_inp = end.inputs.get('Value')
        if end_inp is None and len(end.inputs) > 0: end_inp = end.inputs[0]
        _link_single(tree, val, end_inp)

        instance_out = group_node.outputs.get('Value')
        if instance_out is None and len(group_node.outputs) > 0:
            instance_out = group_node.outputs[0]
        return group_node, instance_out

    return source, val

def do_height_mask_loops(tree, layer, ch_idx, chain, alpha):
    yp = layer.id_data.yp

    nodes = tree.nodes
    root_ch = yp.channels[ch_idx]
    ch = layer.channels[ch_idx]
    trans_bump_ch = get_transition_bump_channel(layer)

    # NOTE: Probably needed if use height as bump is enabled
    #if write_height:
    chain_local = len(layer.masks)
    #else: chain_local = min(len(layer.masks), ch.transition_bump_chain)

    end_chain = alpha
    end_chain_crease = alpha

    pure = alpha
    remains = get_essential_node(tree, ONE_VALUE)[0]

    tb_falloff = nodes.get(ch.tb_falloff)
    if tb_falloff:
        tb_emulated_curve_fac = get_essential_node(tree, TREE_START).get(get_entity_input_name(ch, 'transition_bump_falloff_emulated_curve_fac'))
        if tb_emulated_curve_fac:
            if 'Fac' in tb_falloff.inputs:
                create_link(tree, tb_emulated_curve_fac, tb_falloff.inputs['Fac'])

    if chain == 0 or len(layer.masks) == 0:
        if tb_falloff:
            end_chain = pure = create_link(tree, end_chain, tb_falloff.inputs[0])[0]

    for j, mask in enumerate(layer.masks):
        if not mask.enable: continue

        c = mask.channels[ch_idx]
        mask_mix = nodes.get(c.mix)
        mix_pure = nodes.get(c.mix_pure)
        mix_remains = nodes.get(c.mix_remains)
        #mix_normal = nodes.get(c.mix_normal)
        #mix_limit_normal = nodes.get(c.mix_limit_normal)

        mmixcol0, mmixcol1, mmixout = get_mix_color_indices(mask_mix)
        mp_mixcol0, mp_mixcol1, mp_mixout = get_mix_color_indices(mix_pure)
        mr_mixcol0, mr_mixcol1, mr_mixout = get_mix_color_indices(mix_remains)
        #mn_mixcol0, mn_mixcol1, mn_mixout = get_mix_color_indices(mix_normal)

        if tb_falloff and (j == chain-1 or (j == chain_local-1 and not trans_bump_ch)):
            pure = tb_falloff.outputs[0]
        elif j < chain:
            if mask_mix: pure = mask_mix.outputs[mmixout]
        else:
            if mix_pure: pure = create_link(tree, pure, mix_pure.inputs[mp_mixcol0])[mp_mixout]

        if j >= chain:
            if mix_remains: remains = create_link(tree, remains, mix_remains.inputs[mr_mixcol0])[mr_mixout]

        # NOTE: Probably needed if use height as bump is enabled
        #if normal_alpha:
        #    if mix_normal:
        #        normal_alpha = create_link(tree, normal_alpha, mix_normal.inputs[mn_mixcol0])[mn_mixout]
        #    if mix_limit_normal and group_alpha:
        #        normal_alpha = create_link(tree, normal_alpha, mix_limit_normal.inputs[0])[0]
        #        create_link(tree, group_alpha, mix_limit_normal.inputs[1])

        if j == chain-1 or (j == chain_local-1 and not trans_bump_ch):
            
            if mask_mix:
                end_chain_crease = mask_mix.outputs[mmixout]
            #else: end_chain_crease = alpha

            if tb_falloff:
                if mask_mix: create_link(tree, mask_mix.outputs[mmixout], tb_falloff.inputs[0])[0]
                end_chain = tb_falloff.outputs[0]
            elif mask_mix: 
                end_chain = mask_mix.outputs[mmixout]

    return end_chain, end_chain_crease, pure, remains

def get_custom_source_input_names(layer, source, start_outputs):
    """Names the flat FR-6 path feeds into a CUSTOM source: `<channel>` and `<channel> Alpha`.

    One rule for both paths (P1c review): `reconnect_custom_source_inputs` (flat) and
    `get_source_start_input_sockets` (nested declaration) call this, so a group input that matches
    no channel (e.g. `UVMap UV`) keeps its default in both trees. An input qualifies only when the
    outer `Start` exposes the same-named output (which is how a channel declares alpha, see
    `input_outputs`), so a literal `Alpha` has no source. `Vector` stays on the mapping leg (FR-7).
    """
    names = []
    if layer is None or source is None or start_outputs is None: return names
    yp = getattr(layer.id_data, 'yp', None)
    if yp is None: return names

    for root_ch in yp.channels:
        for name in (root_ch.name, root_ch.name + io_suffix['ALPHA']):
            # CUSTOM: only the literal `Vector` input is reserved for the vector path (FR-7).
            # Skipping the whole root channel here would also drop `<channel> Alpha`, so a group
            # input literally named `Vector Alpha` could never be fed.
            if name == 'Vector': continue
            if name in names: continue
            # Sockets are looked up by name on every pass: a group interface can change while a
            # reconnect is running (FR-11), so a cached socket or an index would dangle.
            if start_outputs.get(name) is None or source.inputs.get(name) is None: continue
            names.append(name)
    return names

def reconnect_custom_source_inputs(tree, layer, source):
    # FR-6: every input of the user's group named like a root channel (`X`) or like its alpha
    # (`X Alpha`) receives the layer's incoming (below-layers) stream. Every other input keeps the
    # user's default, and `Vector` is not touched here — the caller's vector path owns it (FR-7).
    if tree is None or layer is None or source is None: return
    # FR-16: an empty source has no group and therefore no inputs to wire.
    if getattr(source, 'node_tree', None) is None: return

    start_outputs = get_essential_node(tree, TREE_START)

    for name in get_custom_source_input_names(layer, source, start_outputs):
        outp = start_outputs.get(name)
        inp = source.inputs.get(name)

        # A stale link from another socket would otherwise sit next to the new one.
        if inp.links and not any(link.from_socket == outp for link in inp.links):
            break_input_link(tree, inp)

        create_link(tree, outp, inp)

def _link_single(tree, out, inp):
    """Link `out` to `inp`, dropping a stale link from another socket first."""
    if out is None or inp is None: return
    for link in list(inp.links):
        if link.from_socket != out:
            tree.links.remove(link)
    if not inp.links:
        tree.links.new(out, inp)

# Source inputs the flat reconnect path feeds from the layer-tree `Start` (an entity property
# tunnel) rather than from the source node's own settings. Key: source input socket name; value:
# (layer/mask type, entity property). The flat path (`reconnect_layer_nodes`, through
# `link_source_start_inputs`), the nested declaration (`get_source_start_input_sockets`) and the
# inner forwarding all read this table, so a source input is declared, linked and pruned the same
# way whether or not its tree is nested (P1c review: before the shared loop the flat layer/mask
# blocks were a second, hard-coded list that could drift from this one).
source_start_inputs = {
    'Distance': ('AO', 'ao_distance'),
    'Radius': ('EDGE_DETECT', 'edge_detect_radius'),
    'Color ID': ('COLOR_ID', 'color_id'),
}

def link_source_start_inputs(tree, entity, entity_type, source):
    """Feed one source's Start-sourced inputs from the outer `Start`.

    The flat path and `get_source_start_input_sockets` (nested declaration) read the same table,
    so a new Start-fed input cannot be declared on the nested side and left unlinked on the flat
    side. `source` is the flat source node or, when nested, its `source_group`/`group_node`
    instance: both expose the same input names. A missing property, tunnel or socket skips the
    entry instead of raising.
    """
    if tree is None or entity is None or source is None: return
    # `get_essential_node` returns the node's output sockets (like the old inline blocks used).
    start_outputs = get_essential_node(tree, TREE_START)
    for name, (type_name, prop_name) in source_start_inputs.items():
        if type_name != entity_type: continue
        if not hasattr(entity, prop_name): continue
        tunnel = get_entity_input_name(entity, prop_name)
        if not tunnel: continue
        outp = start_outputs.get(tunnel)
        inp = source.inputs.get(name)
        if outp and inp: create_link(tree, outp, inp)

source_input_socket_bl_idnames = {
    'VALUE': 'NodeSocketFloat',
    'INT': 'NodeSocketInt',
    'VECTOR': 'NodeSocketVector',
    'RGBA': 'NodeSocketColor',
    'BOOLEAN': 'NodeSocketBool',
}

def get_source_start_input_sockets(source, layer_type, entity, outer_tree):
    """`(name, socket_type)` for every source input fed from the outer tree's `Start`.

    Derived rather than hard-coded: an input qualifies when the source has it, `source_start_inputs`
    names its entity property for this type, and the outer `Start` actually exposes that tunnel (no
    tunnel means the flat path would not feed it either). `Vector` and `Normal` are owned by the
    callers: `Vector` rides the vector/mapping leg and `Normal` the bump/Geometry leg.

    CUSTOM reads one rule instead of a table, and it is the same rule the flat path links: the root
    channel names plus `<channel> Alpha` (P1c review). A group input matching no channel (`UVMap
    UV`) is therefore left at its default in both trees. `Normal` is fed when it is a channel name;
    `Vector` stays with the mapping leg (FR-7) and a literal `Alpha` has no same-named `Start`
    output (the layer stream is `Color Alpha`).
    """
    sockets = []
    if source is None or entity is None or outer_tree is None: return sockets
    start = outer_tree.nodes.get(TREE_START)
    if start is None: return sockets

    if layer_type == 'CUSTOM':
        for name in get_custom_source_input_names(entity, source, start.outputs):
            inp = source.inputs.get(name)
            sockets.append((name, source_input_socket_bl_idnames.get(inp.type, 'NodeSocketFloat')))
        return sockets

    for name, (type_name, prop_name) in source_start_inputs.items():
        if type_name != layer_type: continue
        inp = source.inputs.get(name)
        if inp is None: continue
        if not hasattr(entity, prop_name): continue
        tunnel = get_entity_input_name(entity, prop_name)
        if not tunnel or start.outputs.get(tunnel) is None: continue
        sockets.append((name, source_input_socket_bl_idnames.get(inp.type, 'NodeSocketFloat')))

    return sockets

def refresh_nested_source_ios(source_tree, source, layer_type, entity=None, outer_tree=None,
        prev_normal=False, base_inputs=(('Vector', 'NodeSocketVector'),)):
    """Declare a nested source tree's inputs from what its flat source actually consumes.

    `base_inputs` is the always-present contract of the tree kind (`Vector` for a source tree,
    `Value` for a modifier mask); the rest is derived by `get_source_start_input_sockets`, and
    `Normal` is added when the entity reads a previous normal. Inputs that are no longer needed are
    removed, so re-syncing after a source/type change does not accumulate dead sockets, and two
    consecutive passes add or remove nothing.
    """
    specs = list(base_inputs) if base_inputs else []
    if prev_normal: specs.append(('Normal', 'NodeSocketVector'))
    specs += get_source_start_input_sockets(source, layer_type, entity, outer_tree)

    valid_names = []
    for name, socket_type in specs:
        if name in valid_names: continue
        valid_names.append(name)
        if get_tree_input_by_name(source_tree, name) is None:
            new_tree_input(source_tree, name, socket_type)

    for inp in reversed(get_tree_inputs(source_tree)):
        if inp.name not in valid_names:
            remove_tree_input(source_tree, inp)

def reconnect_nested_group_inputs(tree, group_node, prev_normal=False):
    """Feed a nested source/mask/channel `*_group` instance from the outer tree's `Start`.

    Sockets are matched by name. `Vector` has no same-named `Start` socket (the layer tree calls
    it `<uv> UV`), so the caller's vector path feeds that one; inputs whose `Start` tunnel has a
    different name (`Distance` from `.ao_distance`) are fed by `reconnect_layer_nodes` from the
    same table the nested declaration uses. Everything else, including the generated channel
    inputs, is forwarded here.

    `prev_normal` marks the `Normal` input as the previous-normal leg (`HEMI` / `EDGE_DETECT` /
    `AO`), which `reconnect_layer_nodes` feeds from the bump output or Geometry. For every other
    source — notably a CUSTOM group input literally named `Normal` — that name is the below-layers
    normal stream and is forwarded like any other.
    """
    if tree is None or group_node is None: return
    start = tree.nodes.get(TREE_START)
    if start is None: return

    for inp in group_node.inputs:
        if inp.name == 'Normal' and prev_normal: continue
        outp = start.outputs.get(inp.name)
        if outp is not None:
            _link_single(tree, outp, inp)

def reconnect_nested_source_nodes(source_tree, source_node, layer_type, linear=None,
        divider_alpha=None, flip_y=None, parent=None, used_output_names=None,
        start=None, end=None):
    """Wire the inside of a generated nested source tree (P1b).

    `Start[name]` feeds the source input of the same name (at least `Vector`); the source's
    available outputs run through divider-alpha/linear/flip-Y (the first colour stream) and, for
    the outputs a channel actually binds, the layer's modifier groups, into `End[name]` and
    `End[name + ' Alpha']`. Every End input is fed exactly once and running it twice adds nothing.
    """
    if source_tree is None or source_node is None: return

    start = start or source_tree.nodes.get(TREE_START)
    end = end or source_tree.nodes.get(TREE_END)
    if start is None or end is None: return

    # Forward the generated inputs the inner source consumes, by name.
    for inp in source_node.inputs:
        outp = start.outputs.get(inp.name)
        if outp is not None:
            _link_single(source_tree, outp, inp)

    if parent is not None:
        if linear is None: linear = source_tree.nodes.get(parent.linear)
        if divider_alpha is None: divider_alpha = source_tree.nodes.get(parent.divider_alpha)
        if flip_y is None: flip_y = source_tree.nodes.get(parent.flip_y)

    used = used_output_names if used_output_names is not None else []
    use_modifiers = parent is not None and used_output_names is not None
    used_output_idx = 0
    vec3_found = False

    for outp in get_available_source_outputs(source_node, layer_type):
        rgb = outp
        if 'Alpha' in source_node.outputs and outp.name != 'Alpha':
            alpha = source_node.outputs['Alpha']
        else: alpha = get_essential_node(source_tree, ONE_VALUE)[0]

        # Divider-alpha/linear/flip-Y apply to the first colour stream only, like the outer chain.
        if not vec3_found and outp.type in {'RGBA', 'RGB', 'VECTOR'}:
            vec3_found = True

            if divider_alpha:
                mixcol0, mixcol1, mixout = get_mix_color_indices(divider_alpha)
                rgb = create_link(source_tree, rgb, divider_alpha.inputs[mixcol0])[mixout]
                create_link(source_tree, alpha, divider_alpha.inputs[mixcol1])

            if linear:
                rgb = create_link(source_tree, rgb, linear.inputs[0])[0]

            if flip_y:
                rgb = create_link(source_tree, rgb, flip_y.inputs[0])[0]

        # Modifier groups that moved into the nested tree apply only to bound outputs.
        if use_modifiers and outp.name in used:
            mod_group = None
            if used_output_idx < len(parent.mod_groups):
                mod_group = source_tree.nodes.get(parent.mod_groups[used_output_idx].name)
            used_output_idx += 1
            rgb, alpha = reconnect_all_modifier_nodes(source_tree, parent, rgb, alpha, mod_group)

        _link_single(source_tree, rgb, end.inputs.get(outp.name))
        _link_single(source_tree, alpha, end.inputs.get(outp.name + ' Alpha'))

def reconnect_layer_nodes(layer, ch_idx=-1, merge_mask=False):
    yp = layer.id_data.yp

    #print('Reconnect layer ' + layer.name)
    if yp.halt_reconnect: return

    tree = get_tree(layer)
    if not tree: return
    nodes = tree.nodes

    # Get layer source. When the source is nested (smooth bump/UV neighbour), the outer channel
    # chain must read the `source_group` instance: the inner node lives in another tree and links
    # across trees are silently dropped by Blender (P1b).
    source_group = nodes.get(layer.source_group)
    if source_group:
        source = source_group
    else:
        source = get_layer_source(layer, tree)

    texcoord = nodes.get(layer.texcoord)
    blur_vector = nodes.get(layer.blur_vector)
    mapping = nodes.get(layer.mapping)
    linear = nodes.get(layer.linear)
    divider_alpha = nodes.get(layer.divider_alpha)
    flip_y = nodes.get(layer.flip_y)
    decal_process = nodes.get(layer.decal_process)

    # Get tangent and bitangent
    layer_tangent = get_essential_node(tree, TREE_START).get(layer.uv_name + io_suffix['TANGENT'])
    layer_bitangent = get_essential_node(tree, TREE_START).get(layer.uv_name + io_suffix['BITANGENT'])

    normal_root_ch = get_root_normal_channel(yp)
    height_root_ch = get_root_height_channel(yp)
    if height_root_ch and height_root_ch.main_uv != '':
        tangent = get_essential_node(tree, TREE_START).get(height_root_ch.main_uv + io_suffix['TANGENT'])
        bitangent = get_essential_node(tree, TREE_START).get(height_root_ch.main_uv + io_suffix['BITANGENT'])
    else:
        tangent = layer_tangent
        bitangent = layer_bitangent

    # Fake lighting stuff
    bump_process = nodes.get(layer.bump_process)
    if bump_process and height_root_ch:

        prev_normal = get_essential_node(tree, TREE_START).get(normal_root_ch.name) if normal_root_ch else None
        prev_height = get_essential_node(tree, TREE_START).get(height_root_ch.name)
        prev_max_height = get_essential_node(tree, TREE_START).get(height_root_ch.name + io_suffix['SCALE'])

        if prev_height and 'Height' in bump_process.inputs: create_link(tree, prev_height, bump_process.inputs['Height'])
        if prev_max_height and 'Max Height' in bump_process.inputs: create_link(tree, prev_max_height, bump_process.inputs['Max Height'])

        if prev_normal and 'Normal' in bump_process.inputs: create_link(tree, prev_normal, bump_process.inputs['Normal'])
        if tangent and 'Tangent' in bump_process.inputs: create_link(tree, tangent, bump_process.inputs['Tangent'])
        if bitangent and 'Bitangent' in bump_process.inputs: create_link(tree, bitangent, bump_process.inputs['Bitangent'])

    # Start-fed source inputs (P1c review): one table for the flat and nested paths. `source` is
    # the source node or, when nested, its `source_group` instance, whose inputs carry the same
    # names.
    link_source_start_inputs(tree, layer, layer.type, source)

    # Use previous normal
    # CUSTOM: only HEMI/EDGE_DETECT/AO read the previous normal into their source; CUSTOM has no
    # such input contract (out, like NOISE).
    if layer.type in {'HEMI', 'EDGE_DETECT', 'AO'}:
        # The input is optional (a baked nested source has no consumer for it): never abort a
        # rebuild over it (P1b review).
        if layer.hemi_use_prev_normal and bump_process and 'Normal' in source.inputs:
            create_link(tree, bump_process.outputs['Normal'], source.inputs['Normal'])
        elif 'Normal' in source.inputs: create_link(tree, get_essential_node(tree, GEOMETRY)['Normal'], source.inputs['Normal'])

    # Baked source (nested trees keep it inside `source_group`, so the instance stays the source)
    baked_source = nodes.get(layer.baked_source)
    if not source_group and layer.use_baked and baked_source:
        source = baked_source

    # Texcoord
    vector = None
    if layer.use_baked:
        vector = get_essential_node(tree, TREE_START).get(layer.baked_uv_name + io_suffix['UV'])
    elif is_layer_using_vector(layer, exclude_baked=True):
        if layer.texcoord_type == 'UV':
            vector = get_essential_node(tree, TREE_START).get(layer.uv_name + io_suffix['UV'])
        elif layer.texcoord_type == 'Decal':
            if texcoord:
                vector = texcoord.outputs['Object']
                if decal_process: 
                    layer_decal_distance = get_essential_node(tree, TREE_START).get(get_entity_input_name(layer, 'decal_distance_value'))
                    vector = create_link(tree, vector, decal_process.inputs[0])[0]
                    if layer_decal_distance: create_link(tree, layer_decal_distance, decal_process.inputs[1])
                    if layer.decal_projection_type != 'FLAT':    
                        layer_decal_scale = get_essential_node(tree, TREE_START).get(get_entity_input_name(layer, 'decal_scale'))
                        if layer_decal_scale: create_link(tree, layer_decal_scale, decal_process.inputs[2])
        else: vector = get_essential_node(tree, TREE_START).get(io_names[layer.texcoord_type])

        if vector and blur_vector:
            vector = create_link(tree, vector, blur_vector.inputs[1])[0]

            layer_blur_factor = get_essential_node(tree, TREE_START).get(get_entity_input_name(layer, 'blur_vector_factor'))
            if layer_blur_factor: create_link(tree, layer_blur_factor, blur_vector.inputs[0])

        if vector and mapping and layer.texcoord_type != 'Decal':
            vector = create_link(tree, vector, mapping.inputs[0])[0]
        
        # Layer UV uniform scale value
        uniform_scale_value = get_essential_node(tree, TREE_START).get(get_entity_input_name(layer, 'uniform_scale_value'))
        if uniform_scale_value:
            if layer.enable_uniform_scale:
                create_link(tree, uniform_scale_value, mapping.inputs[3])
            else:
                break_link(tree, uniform_scale_value, mapping.inputs[3])

    if vector and 'Vector' in source.inputs:
        create_link(tree, vector, source.inputs['Vector'])

    # CUSTOM: the group's channel-named inputs get the below-layers streams (FR-6). Runs after the
    # vector path so `Vector` keeps that wiring and is never linked here.
    if layer.type == 'CUSTOM':
        reconnect_custom_source_inputs(tree, layer, source)

    # Get all available source outputs
    available_outputs = get_available_source_outputs(source, layer.type)
    used_output_names = []

    # Get channel pairs
    color_ch, alpha_ch = get_layer_color_alpha_ch_pairs(layer)
    root_color_ch, root_alpha_ch = get_color_alpha_ch_pairs(yp)
    normal_ch, height_ch = get_layer_normal_height_ch_pairs(layer)

    # To store if the layer channel is enabled or not
    ch_enableds = {}

    # Get pair of source output name with layer channel
    ch_output_names = {}
    for i, ch in enumerate(layer.channels):

        # Alpha channel will get ignored if color channel is also enabled
        channel_enabled = get_channel_enabled(ch, layer) or (ch == alpha_ch and get_channel_enabled(color_ch, layer) and layer.type != 'PREV_LAYERS') or (ch == normal_ch and height_ch.use_height_as_normal and get_channel_enabled(height_ch, layer))
        ch_enableds[yp.channels[i].name] = channel_enabled

        # Only create channel socket dictionary for enabled channels
        if not channel_enabled: continue

        root_ch = yp.channels[i]

        # Get main socket
        # NOTE: Always use color socket if override is enabled and the layer is an image or color attribute
        # This is to avoid solid alpha value if 'Alpha' socket is used.
        # CUSTOM: the solid-alpha shortcut is IMAGE/VCOL only; a custom layer's override is out of
        # scope (non-goal), so it binds normally like NOISE.
        if layer.type in {'IMAGE', 'VCOL'} and ch.override:
            outp = source.outputs.get('Color')
        elif layer.type == 'PREV_LAYERS':
            outp = source.outputs.get(root_ch.name)
        else: outp = source.outputs.get(ch.socket_input_name)
        if outp not in available_outputs:
            outp = None

        # If not, use whatever in the first index
        if not outp and len(available_outputs) > 0:
            outp = available_outputs[0]

        # Pair the output name to the layer channel
        ch_output_names[root_ch.name] = outp.name if outp else None

        # Set the output as used output
        if outp and outp.name not in used_output_names:
            used_output_names.append(outp.name)

    # Wire the inside of a nested source tree and forward the outer instance's inputs (P1b).
    if source_group and source_group.node_tree:
        nested_tree = source_group.node_tree
        nested_prop = 'baked_source' if layer.use_baked else 'source'
        nested_source = nested_tree.nodes.get(getattr(layer, nested_prop))
        if nested_source:
            reconnect_nested_source_nodes(
                nested_tree, nested_source,
                'IMAGE' if layer.use_baked else layer.type,
                linear=nested_tree.nodes.get(layer.linear),
                divider_alpha=nested_tree.nodes.get(layer.divider_alpha),
                flip_y=nested_tree.nodes.get(layer.flip_y),
                parent=layer, used_output_names=used_output_names
            )
        reconnect_nested_group_inputs(
            tree, source_group,
            # HEMI/EDGE_DETECT/AO keep the previous-normal leg; CUSTOM's `Normal` is a stream.
            prev_normal=layer.type in {'HEMI', 'EDGE_DETECT', 'AO'}
        )

    # Dictionary to trace rgb and alpha connections of source socket
    rgb_connections = {}
    alpha_connections = {}

    for i, name in enumerate(used_output_names):
        rgb_connections[name] = source.outputs.get(name)

        # Alpha will use socket called 'Alpha' otherwise alpha will be considered have one in value
        if 'Alpha' not in source.outputs or name == 'Alpha':
            alpha_connections[name] = get_essential_node(tree, ONE_VALUE)[0]
        else: alpha_connections[name] = source.outputs.get('Alpha')

        #if layer.type in {'IMAGE', 'VCOL'}:
        if name == 'Color':
            if divider_alpha: 
                mixcol0, mixcol1, mixout = get_mix_color_indices(divider_alpha)
                rgb_connections[name] = create_link(tree, rgb_connections[name], divider_alpha.inputs[mixcol0])[mixout]
                create_link(tree, alpha_connections[name], divider_alpha.inputs[mixcol1])
            if linear: rgb_connections[name] = create_link(tree, rgb_connections[name], linear.inputs[0])[0]
            if flip_y: rgb_connections[name] = create_link(tree, rgb_connections[name], flip_y.inputs[0])[0]

        mod_group = None
        if i < len(layer.mod_groups):
            mod_group = nodes.get(layer.mod_groups[i].name)
        
        rgb_connections[name], alpha_connections[name] = reconnect_all_modifier_nodes(
            tree, layer, rgb_connections[name], alpha_connections[name], mod_group
        )

    alpha_preview = get_essential_node(tree, TREE_END).get(LAYER_ALPHA_VIEWER)

    # Get normal/height channel
    layer_height_ch = get_height_channel(layer)

    # Get transition bump channel
    trans_bump_flip = False
    trans_bump_crease = False
    trans_bump_ch = get_transition_bump_channel(layer)
    if trans_bump_ch:
        trans_bump_flip = trans_bump_ch.transition_bump_flip
        trans_bump_crease = trans_bump_ch.transition_bump_crease and not trans_bump_flip

    compare_alpha = None
    if layer_height_ch:
        #if layer_height_ch.normal_blend_type == 'COMPARE':
        if layer_height_ch.height_blend_type == 'COMPARE':
            #height_blend = nodes.get(layer_height_ch.height_blend)
            height_blend = nodes.get(layer_height_ch.blend)
            if height_blend: compare_alpha = height_blend.outputs.get('Normal Alpha')

    chain = -1
    tb_value = None
    tb_second_value = None
    if trans_bump_ch:
        # Get the earliest enabled mask
        for i, mask in enumerate(layer.masks):
            if mask.enable: chain = i+1

        chain = min(chain, trans_bump_ch.transition_bump_chain)

        tb_value = get_essential_node(tree, TREE_START).get(get_entity_input_name(trans_bump_ch, 'transition_bump_value'))
        tb_second_value = get_essential_node(tree, TREE_START).get(get_entity_input_name(trans_bump_ch, 'transition_bump_second_edge_value'))

    # Root mask value for merging mask
    root_mask_val = get_essential_node(tree, ONE_VALUE)[0]

    # Layer Masks
    for i, mask in enumerate(layer.masks):

        # Mask source
        mask_source, mask_val = reconnect_mask_source_nodes(mask, tree)

        mask_blur_vector = nodes.get(mask.blur_vector)
        mask_mapping = nodes.get(mask.mapping)
        mask_decal_process = nodes.get(mask.decal_process)
        mask_decal_alpha = nodes.get(mask.decal_alpha)
        mask_texcoord = nodes.get(mask.texcoord)

        if mask_decal_alpha and mask_decal_process:
            mask_val = create_link(tree, mask_val, mask_decal_alpha.inputs[0])[0]
            create_link(tree, mask_decal_process.outputs[1], mask_decal_alpha.inputs[1])

        if is_layer_preview_mode_enabled(yp) and yp.preview_mode_type == 'SPECIFIC_MASK' and mask.active_edit == True:
            if alpha_preview:
                create_link(tree, mask_val, alpha_preview)

        # Start-fed source inputs (P1c review): one table for the flat and nested paths.
        # `mask_source` is the source node or the nested `group_node` instance.
        link_source_start_inputs(tree, mask, mask.type, mask_source)

        # Hemi related
        if mask.type in {'HEMI', 'EDGE_DETECT', 'AO'} and not mask.use_baked:
            # Optional input: a nested mask source whose interface lacks it must fall back, not
            # abort the rebuild (P1b review).
            if mask.hemi_use_prev_normal and bump_process and 'Normal' in mask_source.inputs:
                create_link(tree, bump_process.outputs['Normal'], mask_source.inputs['Normal'])
            elif 'Normal' in mask_source.inputs: create_link(tree, get_essential_node(tree, GEOMETRY)['Normal'], mask_source.inputs['Normal'])

        # Mask start
        mask_vector = None
        mask_uv_name = mask.uv_name if not mask.use_baked or mask.baked_uv_name == '' else mask.baked_uv_name
        if mask.use_baked or mask.type not in {'VCOL', 'HEMI', 'OBJECT_INDEX', 'COLOR_ID', 'BACKFACE', 'EDGE_DETECT', 'AO', 'MODIFIER'}:
            if mask.use_baked or mask.texcoord_type == 'UV':
                mask_vector = get_essential_node(tree, TREE_START).get(mask_uv_name + io_suffix['UV'])
            elif mask.texcoord_type == 'Decal':
                if mask_texcoord:
                    mask_vector = mask_texcoord.outputs['Object']
                    if mask_decal_process: 
                        mask_decal_distance = get_essential_node(tree, TREE_START).get(get_entity_input_name(mask, 'decal_distance_value'))
                        mask_vector = create_link(tree, mask_vector, mask_decal_process.inputs[0])[0]
                        if mask_decal_distance: create_link(tree, mask_decal_distance, mask_decal_process.inputs[1])
                        if mask.decal_projection_type != 'FLAT':
                            mask_decal_scale = get_essential_node(tree, TREE_START).get(get_entity_input_name(mask, 'decal_scale'))
                            if mask_decal_scale: create_link(tree, mask_decal_scale, mask_decal_process.inputs[2])
            elif mask.texcoord_type == 'Layer':
                mask_vector = vector
            else: 
                mask_vector = get_essential_node(tree, TREE_START).get(io_names[mask.texcoord_type])

            if mask_vector:

                if mask.use_baked:
                    mask_baked_mapping = nodes.get(mask.baked_mapping)
                    if mask_baked_mapping:
                        mask_vector = create_link(tree, mask_vector, mask_baked_mapping.inputs[0])[0]

                elif mask.texcoord_type != 'Layer':

                    mask_blur_factor = get_essential_node(tree, TREE_START).get(get_entity_input_name(mask, 'blur_vector_factor'))
                    if mask_blur_factor: create_link(tree, mask_blur_factor, mask_blur_vector.inputs[0])

                    if mask_blur_vector:
                        mask_vector = create_link(tree, mask_vector, mask_blur_vector.inputs[1])[0]

                    if mask_mapping and mask.texcoord_type != 'Decal':
                        mask_vector = create_link(tree, mask_vector, mask_mapping.inputs[0])[0]

                # Bind by name: the nested interface may also declare Start-fed source inputs
                # (AO `Distance`), so the control input is not reliably at index 0 (P1b review).
                mask_vector_inp = mask_source.inputs.get('Vector') or mask_source.inputs[0]
                create_link(tree, mask_vector, mask_vector_inp)

                # Mask UV uniform scale value
                uniform_scale_value = get_essential_node(tree, TREE_START).get(get_entity_input_name(mask, 'uniform_scale_value'))
                if uniform_scale_value:
                    if mask.enable_uniform_scale:
                        create_link(tree, uniform_scale_value, mask_mapping.inputs[3])
                    else:
                        break_link(tree, uniform_scale_value, mask_mapping.inputs[3])

        # Mask root mix
        mmix = nodes.get(mask.mix)
        if mmix:
            mixcol0, mixcol1, mixout = get_mix_color_indices(mmix)
            root_mask_val = create_link(tree, root_mask_val, mmix.inputs[mixcol0])[mixout]
            create_link(tree, mask_val, mmix.inputs[mixcol1])

        # Mask intensity
        mask_intensity = get_essential_node(tree, TREE_START).get(get_entity_input_name(mask, 'intensity_value'))

        # Mask channels
        for j, c in enumerate(mask.channels):
            root_ch = yp.channels[j]
            ch = layer.channels[j]

            mask_mix = nodes.get(c.mix)
            mix_pure = nodes.get(c.mix_pure)
            mix_remains = nodes.get(c.mix_remains)
            mix_normal = nodes.get(c.mix_normal)
            mix_vdisp = nodes.get(c.mix_vdisp)

            mmixcol0, mmixcol1, mmixout = get_mix_color_indices(mask_mix)
            mp_mixcol0, mp_mixcol1, mp_mixout = get_mix_color_indices(mix_pure)
            mr_mixcol0, mr_mixcol1, mr_mixout = get_mix_color_indices(mix_remains)
            mn_mixcol0, mn_mixcol1, mn_mixout = get_mix_color_indices(mix_normal)
            mv_mixcol0, mv_mixcol1, mv_mixout = get_mix_color_indices(mix_vdisp)

            if mix_pure:
                create_link(tree, mask_val, mix_pure.inputs[mp_mixcol1])
                if mask_intensity: create_link(tree, mask_intensity, mix_pure.inputs[0])

            if mix_remains:
                create_link(tree, mask_val, mix_remains.inputs[mr_mixcol1])
                if mask_intensity: create_link(tree, mask_intensity, mix_remains.inputs[0])

            if mix_normal:
                create_link(tree, mask_val, mix_normal.inputs[mn_mixcol1])
                if mask_intensity: create_link(tree, mask_intensity, mix_normal.inputs[0])

            if mix_vdisp:
                create_link(tree, mask_val, mix_vdisp.inputs[mv_mixcol1])
                if mask_intensity: create_link(tree, mask_intensity, mix_vdisp.inputs[0])

            if mask_mix:

                if mask_intensity: create_link(tree, mask_intensity, mask_mix.inputs[0])

                create_link(tree, mask_val, mask_mix.inputs[mmixcol1])

    if merge_mask and is_layer_preview_mode_enabled(yp):
        if alpha_preview:
            create_link(tree, root_mask_val, alpha_preview)
        return

    # Layer intensity input
    layer_intensity_value = get_essential_node(tree, TREE_START).get(get_entity_input_name(layer, 'intensity_value'))
    
    # Parent flag
    has_parent = layer.parent_idx != -1

    # Alpha channel rgb connection stream
    alpha_ch_rgb = None
    alpha_has_blend = False

    # Height channel rgb connection stream
    height_ch_rgb = None
    height_ch_alpha = None

    # For ordered layer channels
    layer_channels = []

    # Make sure alpha channel in earlier list so the output can be used with color channel
    if color_ch and alpha_ch:
        layer_channels.append(alpha_ch)
        layer_channels.append(color_ch)

    # Height channel should be earlier than normal channel
    if normal_ch and height_ch:
        layer_channels.append(height_ch)
        layer_channels.append(normal_ch)

    # Remaining layer channels
    for ch in layer.channels:
        if ch not in layer_channels:
            layer_channels.append(ch)

    # Get relevant, non skippable layer channels
    if ch_idx != -1 and ch_idx < len(layer.channels):
        ch = layer.channels[ch_idx]
        relevant_chs = [ch]
        if ch == color_ch:
            relevant_chs.append(alpha_ch)
        if ch == height_ch:
            relevant_chs.append(normal_ch)
    else:
        relevant_chs = [ch for ch in layer_channels]

    # Layer Channels
    for ch in layer_channels:

        i = get_layer_channel_index(layer, ch)
        root_ch = yp.channels[i]

        channel_enabled = ch_enableds[root_ch.name]
        channel_converted = root_ch.special_type == 'HEIGHT' and ch.use_height_as_normal

        # Disabled channel layer preview
        if is_layer_preview_mode_enabled(yp) and (not channel_enabled or channel_converted):
            if yp.preview_mode_type == 'SPECIFIC_MASK' and ch.override and ch.active_edit == True:
                if alpha_preview:
                    create_link(tree, get_essential_node(tree, ZERO_VALUE)[0], alpha_preview)
            elif root_ch == yp.channels[yp.preview_mode_channel_index]:
                col_preview = get_essential_node(tree, TREE_END).get(LAYER_VIEWER)
                if col_preview:
                    create_link(tree, get_essential_node(tree, ZERO_VALUE)[0], col_preview)
                if alpha_preview:
                    create_link(tree, get_essential_node(tree, ZERO_VALUE)[0], alpha_preview)

        if not channel_enabled:
            continue

        # Rgb and alpha start
        rgb = None
        alpha = None

        # Use alpha of color channel if color channel is enabled
        # CUSTOM: an alpha channel takes the colour channel's alpha like NOISE; only container
        # (group/previous-layers) types are excluded.
        if ch == alpha_ch and get_channel_enabled(color_ch, layer) and not color_ch.unpair_alpha and layer.type not in {'GROUP', 'PREV_LAYERS'}:
            if ch_output_names[root_color_ch.name] != None:
                rgb = alpha_connections[ch_output_names[root_color_ch.name]]
                alpha = get_essential_node(tree, ONE_VALUE)[0]

        if rgb == None:
            if ch_output_names[root_ch.name] != None:
                rgb = rgb_connections[ch_output_names[root_ch.name]]
                alpha = alpha_connections[ch_output_names[root_ch.name]]
            else:
                rgb = get_essential_node(tree, ONE_VALUE)[0]
                alpha = get_essential_node(tree, ONE_VALUE)[0]

        # Use alpha channel output as alpha of all other channels if color channel is also enabled
        if alpha_ch_rgb and get_channel_enabled(color_ch, layer):
            alpha = alpha_ch_rgb

        if height_ch_alpha and ch == normal_ch and height_ch.enable and height_ch.use_height_as_normal:
            alpha = height_ch_alpha
        
        prev_alpha_alpha = None
        next_alpha_alpha = None

        ch_intensity = get_essential_node(tree, TREE_START).get(get_entity_input_name(ch, 'intensity_value'))
        prev_rgb = get_essential_node(tree, TREE_START).get(root_ch.name)
        if alpha_ch and ch == color_ch:
            prev_alpha = get_essential_node(tree, TREE_START).get(root_alpha_ch.name)
            prev_alpha_alpha = get_essential_node(tree, TREE_START).get(root_alpha_ch.name + io_suffix['ALPHA'])
            next_alpha_alpha = get_essential_node(tree, TREE_END).get(root_alpha_ch.name + io_suffix['ALPHA'])
        else:
            prev_alpha = get_essential_node(tree, TREE_START).get(root_ch.name + io_suffix['ALPHA'])

        group_alpha = None

        if layer.type == 'GROUP':

            # Channel Group RGB
            soc_name = root_ch.name + io_suffix['GROUP']

            group_channel = source.outputs.get(soc_name)
            if group_channel: rgb = group_channel
            elif root_ch.special_type == 'NORMAL':
                # Get Geometry normal if normal from group doesn't exist
                rgb = get_essential_node(tree, GEOMETRY).get('Normal')

            # Channel Group Alpha
            soc_name = root_ch.name + io_suffix['ALPHA'] + io_suffix['GROUP']

            group_channel_alpha = source.outputs.get(soc_name)
            if group_channel_alpha: alpha = group_channel_alpha

            group_alpha = alpha

        rgb_before_override = rgb

        # Channel Override 
        ch_source = None
        if ch.override:

            if ch.override_type == 'DEFAULT':
                if root_ch.type == 'VALUE':
                    ch_override_value = get_essential_node(tree, TREE_START).get(get_entity_input_name(ch, 'override_value'))
                    if ch_override_value: rgb = ch_override_value
                else: 
                    ch_override_color = get_essential_node(tree, TREE_START).get(get_entity_input_name(ch, 'override_color'))
                    if ch_override_color: rgb = ch_override_color
            else:
                # A nested override source is read through its `source_group` instance (P1b); the
                # inner node is in another tree and cannot be linked from the layer tree.
                ch_source_group = nodes.get(ch.source_group)
                if ch_source_group:
                    ch_source = ch_source_group
                    ch_tree = ch_source_group.node_tree
                    if ch_tree:
                        reconnect_nested_source_nodes(
                            ch_tree, ch_tree.nodes.get(ch.source), ch.override_type,
                            linear=ch_tree.nodes.get(ch.linear)
                        )
                    reconnect_nested_group_inputs(tree, ch_source_group)
                else:
                    ch_source = nodes.get(ch.source)

            if ch_source:
                if ch.override_type == 'VORONOI' and ch.voronoi_feature == 'N_SPHERE_RADIUS':
                    rgb = ch_source.outputs['Radius']
                else: rgb = ch_source.outputs[0]

            if vector and ch_source and ch.override_type != 'DEFAULT' and 'Vector' in ch_source.inputs:
                create_link(tree, vector, ch_source.inputs['Vector'])

            if is_layer_preview_mode_enabled(yp) and yp.preview_mode_type == 'SPECIFIC_MASK' and ch.active_edit == True:
                if alpha_preview:
                    create_link(tree, rgb, alpha_preview)

        if ch not in relevant_chs: continue

        intensity = nodes.get(ch.intensity)
        layer_intensity = nodes.get(ch.layer_intensity)
        intensity_multiplier = nodes.get(ch.intensity_multiplier)
        extra_alpha = nodes.get(ch.extra_alpha)
        decal_alpha = nodes.get(ch.decal_alpha)
        blend = nodes.get(ch.blend)

        ch_tb_fac = get_essential_node(tree, TREE_START).get(get_entity_input_name(ch, 'transition_bump_fac'))

        if intensity_multiplier and ch != trans_bump_ch:
            if trans_bump_flip:
                if tb_second_value: create_link(tree, tb_second_value, intensity_multiplier.inputs['Multiplier'])
            elif tb_value: create_link(tree, tb_value, intensity_multiplier.inputs['Multiplier'])

            if ch_tb_fac: create_link(tree, ch_tb_fac, intensity_multiplier.inputs['Factor'])

        ch_linear = nodes.get(ch.linear)
        if ch_linear:
            create_link(tree, rgb, ch_linear.inputs[0])
            rgb = ch_linear.outputs[0]

        # NOTE: Swizzle currently only works with non custom layer channel source
        if ch.swizzle_input_mode != 'RGB' and not ch.override:
            src = source #ch_source if ch_source else source
            soc = get_channel_input_socket(layer, ch, src)
            if soc.type in {'RGBA', 'RGB', 'VECTOR'}:
                separate_color_channels = tree.nodes.get(ch.separate_color_channels)
                if separate_color_channels:
                    create_link(tree, rgb, separate_color_channels.inputs[0])
                    if ch.swizzle_input_mode == 'R':
                        rgb = separate_color_channels.outputs[0]
                    elif ch.swizzle_input_mode == 'G':
                        rgb = separate_color_channels.outputs[1]
                    elif ch.swizzle_input_mode == 'B':
                        rgb = separate_color_channels.outputs[2]

        mod_group = nodes.get(ch.mod_group)

        rgb_before_mod = rgb
        alpha_before_mod = alpha

        # Reconnect modifier nodes
        rgb, alpha = reconnect_all_modifier_nodes(tree, ch, rgb, alpha, mod_group)

        rgb_after_mod = rgb
        alpha_after_mod = alpha

        # For transition input
        transition_input = alpha
        if chain == 0 and intensity_multiplier:
            alpha = create_link(tree, alpha, intensity_multiplier.inputs[0])[0]

        # Mask multiplies
        for j, mask in enumerate(layer.masks):

            # Modifier mask need previous alpha
            if mask.type == 'MODIFIER':
                if mask.group_node != '':
                    mask_source = nodes.get(mask.group_node)
                    if mask_source: create_link(tree, alpha, mask_source.inputs[0])
                else:
                    mask_source = nodes.get(mask.source)
                    if mask_source:
                        if mask.modifier_type in {'CURVE', 'INVERT'}:
                            create_link(tree, alpha, mask_source.inputs[1])
                        else: create_link(tree, alpha, mask_source.inputs[0])

            mask_mix = nodes.get(mask.channels[i].mix)
            mmixcol0, mmixcol1, mmixout = get_mix_color_indices(mask_mix)
            if mask_mix:
                alpha = create_link(tree, alpha, mask_mix.inputs[mmixcol0])[mmixout]

            mix_limit = nodes.get(mask.channels[i].mix_limit)
            if mix_limit and group_alpha:
                alpha = create_link(tree, alpha, mix_limit.inputs[0])[0]
                create_link(tree, group_alpha, mix_limit.inputs[1])

            # Transition input uses the alpha at the chain end
            if j == chain-1 and intensity_multiplier:
                transition_input = alpha
                alpha = create_link(tree, alpha, intensity_multiplier.inputs[0])[0]

        # Decal alpha
        if decal_alpha and decal_process:
            alpha = create_link(tree, alpha, decal_alpha.inputs[0])[0]
            create_link(tree, decal_process.outputs[1], decal_alpha.inputs[1])[0]

        # If transition bump is not found, use last alpha as input
        if not trans_bump_ch:
            transition_input = alpha

        # Pass alpha to layer intensity
        if layer_intensity and layer_intensity_value:
            if ch_intensity:
                # NOTE: Layer group with height as normal enabled will use height channel intensity rather than it's own
                if layer.type == 'GROUP' and ch == normal_ch and height_ch.enable and height_ch.use_height_as_normal:
                    height_ch_intensity = get_essential_node(tree, TREE_START).get(get_entity_input_name(height_ch, 'intensity_value'))
                    ch_intensity = create_link(tree, height_ch_intensity, layer_intensity.inputs[0])[0]
                else:
                    ch_intensity = create_link(tree, ch_intensity, layer_intensity.inputs[0])[0]
            create_link(tree, layer_intensity_value, layer_intensity.inputs[1])

        # Bookmark alpha before intensity because it can be useful
        alpha_before_intensity = alpha

        height_proc = nodes.get(ch.height_proc)
        max_height_calc = nodes.get(ch.max_height_calc)
        normal_proc = nodes.get(ch.normal_proc)
        vdisp_proc = nodes.get(ch.vdisp_proc)

        # Pass alpha to intensity
        if intensity:
            alpha = create_link(tree, alpha, intensity.inputs[0])[0]

            if ch_intensity:
                create_link(tree, ch_intensity, intensity.inputs[1])

        if root_ch.special_type == 'NORMAL':

            if normal_proc:
                ch_normal_strength = get_essential_node(tree, TREE_START).get(get_entity_input_name(ch, 'normal_strength'))
                if ch == normal_ch and height_ch.enable and height_ch.use_height_as_normal:
                    # Height channel as bump
                    if height_ch_rgb and 'Height' in normal_proc.inputs:
                        create_link(tree, height_ch_rgb, normal_proc.inputs['Height'])

                    #if ch_normal_strength and 'Strength' in normal_proc.inputs:
                    #    create_link(tree, ch_normal_strength, normal_proc.inputs['Strength'])

                    #height_ch_bump_distance = get_essential_node(tree, TREE_START).get(get_entity_input_name(height_ch, 'bump_distance'))
                    #if height_ch_bump_distance and 'Max Height' in normal_proc.inputs:
                    #    create_link(tree, height_ch_bump_distance, normal_proc.inputs['Max Height'])

                    #if prev_rgb and 'Normal' in normal_proc.inputs:
                    #    create_link(tree, prev_rgb, normal_proc.inputs['Normal'])

                    rgb_original = rgb
                    rgb = normal_proc.outputs[0]

                    normal_overlay = nodes.get(ch.normal_overlay)
                    if normal_overlay and height_ch_alpha:
                        create_link(tree, rgb, normal_overlay.inputs[0])
                        create_link(tree, height_ch_alpha, normal_overlay.inputs[1])
                        create_link(tree, rgb_original, normal_overlay.inputs[2])
                        create_link(tree, alpha, normal_overlay.inputs[3])

                        if layer_tangent and 'Tangent' in normal_overlay.inputs:
                            create_link(tree, layer_tangent, normal_overlay.inputs['Tangent'])
                        if layer_bitangent and 'Bitangent' in normal_overlay.inputs:
                            create_link(tree, layer_bitangent, normal_overlay.inputs['Bitangent'])

                        rgb = normal_overlay.outputs[0]
                        alpha = normal_overlay.outputs[1]
                else:
                    # Normal map
                    if 'Strength' in normal_proc.inputs and ch_normal_strength:
                        create_link(tree, ch_normal_strength, normal_proc.inputs['Strength'])

                    if 'Color' in normal_proc.inputs:
                        rgb = create_link(tree, rgb, normal_proc.inputs['Color'])[0]

            # Connect tangent if overlay blend is used
            if blend:
                if ch.normal_blend_type == 'OVERLAY':
                    if tangent and 'Tangent' in blend.inputs: create_link(tree, tangent, blend.inputs['Tangent'])
                    if bitangent and 'Bitangent' in blend.inputs: create_link(tree, bitangent, blend.inputs['Bitangent'])

        # Special height channel
        if root_ch.special_type == 'HEIGHT':
            prev_max_height = get_essential_node(tree, TREE_START).get(root_ch.name + io_suffix['SCALE'])
            next_max_height = get_essential_node(tree, TREE_END).get(root_ch.name + io_suffix['SCALE'])

            ch_bump_distance = get_essential_node(tree, TREE_START).get(get_entity_input_name(ch, 'bump_distance'))
            ch_bump_midlevel = get_essential_node(tree, TREE_START).get(get_entity_input_name(ch, 'bump_midlevel'))

            bump_distance_ignorer = nodes.get(ch.bump_distance_ignorer)
            if bump_distance_ignorer:
                ch_bump_distance = create_link(tree, ch_bump_distance, bump_distance_ignorer.inputs[0])[0]

            # Get various alpha variations from mask loop
            end_chain, end_chain_crease, pure, remains = do_height_mask_loops(tree, layer, i, chain, alpha_after_mod)

            # Transition bump
            tb_distance = None
            tb_intensity_multiplier = None
            if ch.enable_transition_bump: # and ch.enable:
                tb_distance = get_essential_node(tree, TREE_START).get(get_entity_input_name(ch, 'transition_bump_distance'))
                tb_intensity_multiplier = nodes.get(ch.tb_intensity_multiplier)

                if tb_distance:
                    tb_distance_flipper = nodes.get(ch.tb_distance_flipper)
                    if tb_distance_flipper:
                        tb_distance = create_link(tree, tb_distance, tb_distance_flipper.inputs[0])[0]

                if tb_intensity_multiplier:
                    tb_inverse = nodes.get(ch.tb_inverse)
                    if tb_inverse:
                        create_link(tree, transition_input, tb_inverse.inputs[1])
                        create_link(tree, tb_inverse.outputs[0], tb_intensity_multiplier.inputs[0])

                    if tb_second_value:
                        create_link(tree, tb_second_value, tb_intensity_multiplier.inputs[1])

                if tb_value:
                    create_link(tree, tb_value, intensity_multiplier.inputs[1])

            # Transition bump crease
            tb_crease_factor = get_essential_node(tree, TREE_START).get(get_entity_input_name(ch, 'transition_bump_crease_factor')) if trans_bump_crease else None
            tb_crease_power = get_essential_node(tree, TREE_START).get(get_entity_input_name(ch, 'transition_bump_crease_power')) if trans_bump_crease else None
                
            if height_proc or max_height_calc:

                # Group layer uses child max height for bump distance
                if layer.type == 'GROUP' and (root_ch.use_height_normalize or ch.enable_transition_bump):
                    ch_bump_distance = source.outputs.get(root_ch.name + io_suffix['SCALE'] + io_suffix['GROUP'])

                # Use default value if some sockets are not found
                if not ch_bump_distance: ch_bump_distance = get_essential_node(tree, ZERO_VALUE)[0]
                if not ch_bump_midlevel: ch_bump_midlevel = get_essential_node(tree, HALF_VALUE)[0]
                
            # Connect height process
            if height_proc: 
                if 'Value' in height_proc.inputs: rgb = create_link(tree, rgb, height_proc.inputs['Value'])[0]
                if 'Alpha' in height_proc.inputs: alpha = create_link(tree, alpha, height_proc.inputs['Alpha'])[1]
                if 'Value Max Height' in height_proc.inputs: create_link(tree, ch_bump_distance, height_proc.inputs['Value Max Height'])
                if 'Midlevel' in height_proc.inputs: create_link(tree, ch_bump_midlevel, height_proc.inputs['Midlevel'])

                # Transition bump related
                if tb_distance:
                    if 'Transition Max Height' in height_proc.inputs: 
                        create_link(tree, tb_distance, height_proc.inputs['Transition Max Height'])

                if 'Delta' in height_proc.inputs and ch_bump_distance:
                    tb_delta_calc = nodes.get(ch.tb_delta_calc)
                    if tb_delta_calc:
                        create_link(tree, tb_distance, tb_delta_calc.inputs[0])
                        create_link(tree, ch_bump_distance, tb_delta_calc.inputs[1])
                        create_link(tree, tb_delta_calc.outputs[0], height_proc.inputs['Delta'])

                if 'Edge 1 Alpha' in height_proc.inputs:
                    if trans_bump_crease:
                        create_link(tree, intensity_multiplier.outputs[0], height_proc.inputs['Edge 1 Alpha'])
                    else: create_link(tree, alpha_before_intensity, height_proc.inputs['Edge 1 Alpha'])

                if 'Edge 2 Alpha' in height_proc.inputs and tb_intensity_multiplier:
                    create_link(tree, tb_intensity_multiplier.outputs[0], height_proc.inputs['Edge 2 Alpha'])

                if 'Transition' in height_proc.inputs: 
                    if trans_bump_crease:
                        create_link(tree, end_chain, height_proc.inputs['Transition'])
                    else: create_link(tree, pure, height_proc.inputs['Transition'])

                if 'Remaining Alpha' in height_proc.inputs: 
                    create_link(tree, remains, height_proc.inputs['Remaining Alpha'])

                # Transition bump crease
                if tb_crease_factor:
                    if 'Crease Factor' in height_proc.inputs:
                        create_link(tree, tb_crease_factor, height_proc.inputs['Crease Factor'])

                if tb_crease_power and 'Crease Power' in height_proc.inputs:
                    create_link(tree, tb_crease_power, height_proc.inputs['Crease Power'])

                if 'Transition Crease' in height_proc.inputs:
                    create_link(tree, end_chain_crease, height_proc.inputs['Transition Crease'])

                if trans_bump_crease:
                    if ch.use_height_as_normal:
                        alpha = height_proc.outputs['Filtered Alpha']
                    else: alpha = height_proc.outputs['Combined Alpha']

                # Transition bump crease sometimes need intensity input
                if ch_intensity and 'Intensity' in height_proc.inputs:
                    create_link(tree, ch_intensity, height_proc.inputs['Intensity'])

            # Connect max height calculation
            if max_height_calc:

                if prev_max_height and 'Prev Bump Distance' in max_height_calc.inputs: 
                    create_link(tree, prev_max_height, max_height_calc.inputs['Prev Bump Distance'])
                if next_max_height: create_link(tree, max_height_calc.outputs[0], next_max_height)

                if ch_bump_distance and 'Bump Distance' in max_height_calc.inputs: create_link(tree, ch_bump_distance, max_height_calc.inputs['Bump Distance'])
                if ch_bump_midlevel and 'Midlevel' in max_height_calc.inputs: create_link(tree, ch_bump_midlevel, max_height_calc.inputs['Midlevel'])
                if ch_intensity and 'Intensity' in max_height_calc.inputs: create_link(tree, ch_intensity, max_height_calc.inputs['Intensity'])

                # Transition bump
                if tb_distance and 'Transition Bump Distance' in max_height_calc.inputs:
                    create_link(tree, tb_distance, max_height_calc.inputs['Transition Bump Distance'])

                # Transition bump crease
                if tb_crease_factor and 'Crease Factor' in max_height_calc.inputs:
                    create_link(tree, tb_crease_factor, max_height_calc.inputs['Crease Factor'])

        if root_ch.special_type == 'VDISP':

            vdisp_flip_yz = tree.nodes.get(ch.vdisp_flip_yz)
            if vdisp_flip_yz:
                rgb = create_link(tree, rgb, vdisp_flip_yz.inputs[0])[0]

            if vdisp_proc:
                inp0, inp1, outp0 = get_mix_color_indices(vdisp_proc)
                ch_vdisp_strength = get_essential_node(tree, TREE_START).get(get_entity_input_name(ch, 'vdisp_strength'))
                
                rgb = create_link(tree, rgb, vdisp_proc.inputs[inp0])[outp0]
                if ch_vdisp_strength: create_link(tree, ch_vdisp_strength, vdisp_proc.inputs[inp1])

        # Transition AO
        tao = nodes.get(ch.tao)
        if tao and root_ch.type in {'RGB', 'VALUE'} and trans_bump_ch and ch.enable_transition_ao:

            if ch_intensity:
                create_link(tree, ch_intensity, tao.inputs['Intensity Channel'])

            if layer_intensity_value and 'Intensity Layer' in tao.inputs:
                create_link(tree, layer_intensity_value, tao.inputs['Intensity Layer'])

            tao_intensity = get_essential_node(tree, TREE_START).get(get_entity_input_name(ch, 'transition_ao_intensity'))
            if tao_intensity:
                create_link(tree, tao_intensity, tao.inputs['Intensity'])

            tao_power = get_essential_node(tree, TREE_START).get(get_entity_input_name(ch, 'transition_ao_power'))
            if tao_power:
                create_link(tree, tao_power, tao.inputs['Power'])

            tao_color = get_essential_node(tree, TREE_START).get(get_entity_input_name(ch, 'transition_ao_color'))
            if tao_color:
                create_link(tree, tao_color, tao.inputs['AO Color'])

            tao_inside_intensity = get_essential_node(tree, TREE_START).get(get_entity_input_name(ch, 'transition_ao_inside_intensity'))
            if tao_inside_intensity:
                create_link(tree, tao_inside_intensity, tao.inputs['Inside Intensity'])

            if trans_bump_flip:
                create_link(tree, rgb, tao.inputs[0])
                rgb = tao.outputs[0]

                trans_im = nodes.get(trans_bump_ch.tb_intensity_multiplier)

                if trans_im: create_link(tree, trans_im.outputs[0], tao.inputs['Multiplied Alpha'])

            else: 
                if prev_rgb: create_link(tree, prev_rgb, tao.inputs[0])

                # Get intensity multiplier of transition bump
                trans_im = nodes.get(trans_bump_ch.intensity_multiplier)
                if trans_im: create_link(tree, trans_im.outputs[0], tao.inputs['Multiplied Alpha'])

                # Dealing with chain
                remaining_alpha = get_essential_node(tree, ONE_VALUE)[0]
                for j, mask in enumerate(layer.masks):
                    if j >= chain:
                        mix_remains = nodes.get(mask.channels[i].mix_remains)
                        mr_mixcol0, mr_mixcol1, mr_mixout = get_mix_color_indices(mix_remains)
                        if mix_remains:
                            remaining_alpha = create_link(tree, remaining_alpha, mix_remains.inputs[mr_mixcol0])[mr_mixout]

                prev_rgb = tao.outputs[0]
                if 'Remaining Alpha' in tao.inputs:
                    create_link(tree, remaining_alpha, tao.inputs['Remaining Alpha'])

                if 'Input Alpha' in tao.inputs:
                    if prev_alpha: create_link(tree, prev_alpha, tao.inputs['Input Alpha'])
                    prev_alpha = tao.outputs['Input Alpha']

                # Extra alpha
                if 'Extra Alpha' in tao.inputs:
                    #if layer_height_ch and layer_height_ch.normal_blend_type == 'COMPARE' and compare_alpha:
                    if layer_height_ch and layer_height_ch.height_blend_type == 'COMPARE' and compare_alpha:
                        create_link(tree, compare_alpha, tao.inputs['Extra Alpha'])
                    else:
                        break_input_link(tree, tao.inputs['Extra Alpha'])

            create_link(tree, transition_input, tao.inputs['Transition'])

        # Transition Ramp
        tr_ramp = nodes.get(ch.tr_ramp)
        if tr_ramp and root_ch.type in {'RGB', 'VALUE'} and ch.enable_transition_ramp:

            tr_ramp_blend = nodes.get(ch.tr_ramp_blend)
            tr_intensity_value = get_essential_node(tree, TREE_START).get(get_entity_input_name(ch, 'transition_ramp_intensity_value'))
            tb_second_fac = get_essential_node(tree, TREE_START).get(get_entity_input_name(ch, 'transition_bump_second_fac'))

            create_link(tree, transition_input, tr_ramp.inputs['Transition'])

            if tb_second_fac:
                create_link(tree, tb_second_fac, tr_ramp.inputs['Factor'])

            if tr_intensity_value:
                if 'Intensity' in tr_ramp.inputs:
                    create_link(tree, tr_intensity_value, tr_ramp.inputs['Intensity'])

            if trans_bump_flip:

                # Connect intensity
                if ch_intensity:
                    create_link(tree, ch_intensity, tr_ramp_blend.inputs['Intensity Channel'])

                if layer_intensity_value and 'Intensity Layer' in tr_ramp_blend.inputs:
                    create_link(tree, layer_intensity_value, tr_ramp_blend.inputs['Intensity Layer'])

                if tr_intensity_value:
                    if 'Intensity' in tr_ramp_blend.inputs:
                        create_link(tree, tr_intensity_value, tr_ramp_blend.inputs['Intensity'])

                if tb_value:
                    create_link(tree, tb_value, tr_ramp.inputs['Multiplier'])

                if prev_rgb: create_link(tree, prev_rgb, tr_ramp_blend.inputs['Input RGB'])
                create_link(tree, intensity_multiplier.outputs[0], tr_ramp_blend.inputs['Multiplied Alpha'])

                create_link(tree, tr_ramp.outputs[0], tr_ramp_blend.inputs['Ramp RGB'])

                trans_ramp_input = tr_ramp.outputs['Ramp Alpha']

                for j, mask in enumerate(layer.masks):
                    if j >= chain:
                        mix_remains = nodes.get(mask.channels[i].mix_remains)
                        mr_mixcol0, mr_mixcol1, mr_mixout = get_mix_color_indices(mix_remains)
                        if mix_remains:
                            trans_ramp_input = create_link(tree, trans_ramp_input, mix_remains.inputs[mr_mixcol0])[mr_mixout]

                create_link(tree, trans_ramp_input, tr_ramp_blend.inputs['Ramp Alpha'])
                prev_rgb = tr_ramp_blend.outputs[0]

                if 'Input Alpha' in tr_ramp_blend.inputs:
                    if prev_alpha: create_link(tree, prev_alpha, tr_ramp_blend.inputs['Input Alpha'])
                    prev_alpha = tr_ramp_blend.outputs['Input Alpha']

                if 'Input Alpha Alpha' in tr_ramp_blend.inputs:
                    if prev_alpha_alpha: create_link(tree, prev_alpha_alpha, tr_ramp_blend.inputs['Input Alpha Alpha'])
                    prev_alpha_alpha = tr_ramp_blend.outputs['Input Alpha Alpha']

                #break_input_link(tree, tr_ramp_blend.inputs['Intensity'])

            elif not trans_bump_flip:
                if 'RGB' in tr_ramp.inputs:
                    create_link(tree, rgb, tr_ramp.inputs['RGB'])
                rgb = tr_ramp.outputs[0]

                if tb_second_value:
                    create_link(tree, tb_second_value, tr_ramp.inputs['Multiplier'])

                elif ch.transition_ramp_intensity_unlink and ch.transition_ramp_blend_type == 'MIX':
                    if 'Remaining Alpha' in tr_ramp.inputs:
                        create_link(tree, alpha_before_intensity, tr_ramp.inputs['Remaining Alpha'])
                    if 'Channel Intensity' in tr_ramp.inputs:
                        create_link(tree, alpha, tr_ramp.inputs['Channel Intensity'])

                    alpha = tr_ramp.outputs[1]

        # Extra alpha
        if extra_alpha and compare_alpha:
            alpha = create_link(tree, alpha, extra_alpha.inputs[0])[0]
            create_link(tree, compare_alpha, extra_alpha.inputs[1])

        # End node
        next_rgb = get_essential_node(tree, TREE_END).get(root_ch.name)
        if alpha_ch and ch == color_ch:
            # Do not connect color's next alpha if alpha is unpaired or layer is a group and alpha channel has blend node
            if color_ch.unpair_alpha or (layer.type == 'GROUP' and alpha_has_blend):
                next_alpha = None
            else: next_alpha = get_essential_node(tree, TREE_END).get(root_alpha_ch.name)
        else: next_alpha = get_essential_node(tree, TREE_END).get(root_ch.name + io_suffix['ALPHA'])

        if root_ch.special_type == 'NORMAL':
            blend_type = ch.normal_blend_type
        elif root_ch.special_type == 'HEIGHT':
            blend_type = ch.height_blend_type
        else: blend_type = ch.blend_type

        # Get output of alpha channel before blend node
        if ch == alpha_ch and not color_ch.unpair_alpha:
            alpha_ch_rgb = rgb

            # Check if alpha has blend node
            if blend: alpha_has_blend = True

            group_alpha_multiply = tree.nodes.get(ch.group_alpha_multiply) 
            if alpha and group_alpha_multiply:
                alpha_ch_rgb = create_link(tree, alpha_ch_rgb, group_alpha_multiply.inputs[0])[0]
                create_link(tree, alpha, group_alpha_multiply.inputs[1])

        if blend:
            bcol0, bcol1, bout = get_mix_color_indices(blend)

            # NOTE: Normal channel from height channel with transition bump will skip usual alpha process
            if ch == normal_ch and height_ch.enable and height_ch.use_height_as_normal and height_ch == trans_bump_ch:
                alpha = height_ch_alpha

            # Pass rgb to blend
            blended_rgb = create_link(tree, rgb, blend.inputs[bcol1])[bout]

            if (
                    #(blend_type == 'MIX' and (has_parent or (root_ch.type == 'RGB' and root_ch.enable_alpha)))
                    (blend_type == 'MIX' and (has_parent or is_channel_alpha_enabled(root_ch)) and (ch != height_ch or not ch.use_height_as_normal))
                ):

                if prev_rgb:
                    if 'Color1' in blend.inputs: create_link(tree, prev_rgb, blend.inputs['Color1'])
                    elif 'Value1' in blend.inputs: create_link(tree, prev_rgb, blend.inputs['Value1'])
                    elif 'Vector1' in blend.inputs: create_link(tree, prev_rgb, blend.inputs['Vector1'])
                if prev_alpha and 'Alpha1' in blend.inputs: create_link(tree, prev_alpha, blend.inputs['Alpha1'])

                if prev_alpha_alpha and 'Alpha1 Alpha' in blend.inputs: 
                    create_link(tree, prev_alpha_alpha, blend.inputs['Alpha1 Alpha'])
                if not ch.unpair_alpha:
                    if next_alpha_alpha and 'Alpha Alpha' in blend.outputs: 
                        create_link(tree, blend.outputs['Alpha Alpha'], next_alpha_alpha)

                if 'Alpha2' in blend.inputs: create_link(tree, alpha, blend.inputs['Alpha2'])

            else:
                create_link(tree, alpha, blend.inputs[0])

                if prev_rgb: create_link(tree, prev_rgb, blend.inputs[bcol0])

            # Armory can't recognize mute node, so reconnect input to output directly
            #if layer.enable and ch.enable:
            #    create_link(tree, blend.outputs[0], next_rgb)
            #else: create_link(tree, prev_rgb, next_rgb)

            if next_rgb: create_link(tree, blend.outputs[bout], next_rgb)

            # Get height channel value after blend node
            if ch == height_ch:
                height_ch_rgb = blended_rgb
                height_ch_alpha = alpha
                
                if ch.use_height_as_normal:
                    if prev_rgb and next_rgb:
                        create_link(tree, prev_rgb, next_rgb)
                    if prev_max_height and next_max_height:
                        create_link(tree, prev_max_height, next_max_height)

        elif prev_rgb and next_rgb: 
            create_link(tree, prev_rgb, next_rgb)

        if next_alpha:
            if not blend or (blend and len(blend.outputs) < 2) or (
                (blend_type != 'MIX' and (has_parent or is_channel_alpha_enabled(root_ch)))
                ) or (
                ch == height_ch and ch.use_height_as_normal
                ):
                if prev_alpha: create_link(tree, prev_alpha, next_alpha)
            else:
                if blend: create_link(tree, blend.outputs[1], next_alpha)

        # Layer preview
        if is_layer_preview_mode_enabled(yp):

            # If previewing specific mask with any mask or override channel active
            if yp.preview_mode_type == 'SPECIFIC_MASK':
                active_found = False

                for mask in layer.masks:
                    if mask.active_edit:
                        active_found = True
                        break

                for ch in layer.channels:
                    if ch.override and ch.override_type != 'DEFAULT' and ch.active_edit:
                        active_found = True
                        break

                    if ch.override_1 and ch.override_1_type != 'DEFAULT' and ch.active_edit_1:
                        active_found = True
                        break
                
                if not active_found and alpha_preview:
                    create_link(tree, source.outputs[0], alpha_preview)

            elif root_ch == yp.channels[yp.preview_mode_channel_index] and not channel_converted:
                col_preview = get_essential_node(tree, TREE_END).get(LAYER_VIEWER)
                if col_preview:
                    if root_ch.special_type == 'NORMAL' and normal_proc: 
                        create_link(tree, normal_proc.outputs[0], col_preview)
                    elif root_ch.special_type == 'HEIGHT' and height_proc: 
                        create_link(tree, height_proc.outputs[0], col_preview)
                    elif root_ch.special_type == 'VDISP' and vdisp_proc: 
                        _, _, mixout = get_mix_color_indices(vdisp_proc)
                        create_link(tree, vdisp_proc.outputs[mixout], col_preview)
                    else: create_link(tree, rgb, col_preview)
                if alpha_preview and yp.preview_mode_type != 'SPECIFIC_MASK':
                    create_link(tree, alpha, alpha_preview)
                
    # Clean unused essential nodes
    clean_essential_nodes(tree, exclude_texcoord=True)
