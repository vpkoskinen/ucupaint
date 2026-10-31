import time
import bpy
from bpy.app.handlers import persistent
from .common import *

# Socket ids that a channel may bind to (FR-4). Everything else — notably `NodeSocketShader` —
# is never offered as a channel source. Ids are the `NodeSocket*` names used both by group
# interface entries (`socket_type`) and by instantiated sockets (`bl_idname`).
COMPATIBLE_SOCKET_IDS = {
    'NodeSocketColor',
    'NodeSocketFloat',
    'NodeSocketFloatFactor',
    'NodeSocketVector',
    'NodeSocketInt',
}

# ucupaint's own generated trees, by the `.yP ` namespace they share. Only layer trees carry
# yp.is_ypaint_layer_node; nested source trees (subtree.check_layer_source_tree), mask trees
# (subtree.enable_mask_source_tree), modifier groups and the parallax iterate group do not, so the
# name is what tells them apart from user groups. Modifier groups have no prefix constant yet
# (modifier_common.py creates '.yP Modifiers <name>' inline).
INTERNAL_TREE_PREFIXES = (LAYERGROUP_PREFIX, MASKGROUP_PREFIX, '.yP Modifiers ', ITERATE_GROUP)

def get_custom_group_outputs(group):
    # Group output declarations, version-safe: pre-4.0 exposes them on tree.outputs, 4.0+ on
    # tree.interface. Interface entries are not instantiated sockets, so they carry socket_type
    # while real sockets carry bl_idname; get_custom_socket_id reads whichever exists.
    if group is None: return []

    return [item for item in group.interface.items_tree if item.item_type == 'SOCKET' and item.in_out == 'OUTPUT']

def get_custom_socket_id(socket):
    # One socket type id for both representations this module sees: interface entries carry
    # `socket_type` ('NodeSocketColor'), instantiated sockets carry `bl_idname` ('NodeSocketColor')
    # and `type` ('RGBA', 'VALUE', …). Never the socket name.
    #
    # `bl_socket_idname` / `bl_idname` are checked first because they are cheap RNA reads that
    # report the same id; `socket_type` is ~2 µs per item on 5.x, which would blow NFR-2's budget
    # when a signature check walks 100 sockets on every depsgraph update.
    if socket is None: return ''

    bl_socket_idname = getattr(socket, 'bl_socket_idname', '')
    if bl_socket_idname: return bl_socket_idname

    bl_idname = getattr(socket, 'bl_idname', '')
    if bl_idname: return bl_idname

    return getattr(socket, 'socket_type', '')

def is_custom_socket_compatible(socket):
    # FR-4 socket-type test, one place. The value types are the whitelist; shader sockets and
    # every other type (bool, menu, string, object, …) never reach a channel.
    return get_custom_socket_id(socket) in COMPATIBLE_SOCKET_IDS

def get_custom_compatible_outputs(group):
    # Compatible output declarations of a group, in interface order.
    return [outp for outp in get_custom_group_outputs(group) if is_custom_socket_compatible(outp)]

def get_custom_group_candidates():
    # FR-2: pure enumeration, no UI context and no mutation. Intent is to exclude ucupaint's own
    # trees (all internal `.yP ` trees, layer trees, the ypaint node tree) and trees that cannot
    # feed a channel.
    groups = []

    for group in bpy.data.node_groups:
        if group.name.startswith('~yPL '): continue
        if group.name.startswith(INTERNAL_TREE_PREFIXES): continue
        if not isinstance(group, bpy.types.ShaderNodeTree): continue

        yp = getattr(group, 'yp', None)
        if yp is not None:
            if yp.is_ypaint_layer_node: continue
            if yp.is_ypaint_node: continue

        if not get_custom_compatible_outputs(group): continue

        groups.append(group)

    return groups

def _starter_socket_type(root_ch, in_out):
    # The socket type a starter group uses for a root channel: the same dictionaries the layer
    # tree's own Start/End interface uses (`input_outputs.py`), so the starter group's names and
    # types mirror the channel contract instead of inventing a second convention.
    if in_out == 'INPUT':
        return channel_socket_input_bl_idnames.get(root_ch.type, 'NodeSocketColor')
    return channel_socket_output_bl_idnames.get(root_ch.type, 'NodeSocketColor')

def create_starter_group(yp, name):
    # FR-31/FR-32: the one place ucupaint writes into a *user* node tree, and it does so exactly
    # once. Nothing else in the add-on adds, removes or renames a socket in this tree — not on
    # channel add/remove/rename and not on a sync — so the user can freely edit it afterwards.
    #
    # Shape: Group Input / Group Output with one input+output pair per current root channel (names
    # exactly the channel names), plus a `Vector` input (FR-7), and an `Alpha` output (FR-5,
    # reserved). Every channel output is linked from the same-named input, so a layer created from
    # it renders whatever is below. `Alpha` and `Normal` are the exceptions: `Alpha` has no
    # same-named input and is fed from a constant `ShaderNodeValue` at 1.0, so a fresh layer is
    # opaque and its output actually contributes; `Normal` is fed from a constant neutral normal
    # map, because a CUSTOM layer's `Normal` output is a tangent-space normal map (see the wiring
    # below). No `Color Alpha` input is declared. (`Color Alpha` handling for *user* groups, FR-6,
    # is unaffected.)
    if yp is None: return None

    name = (name or '').strip() or 'Custom Node Layer'
    tree = bpy.data.node_groups.new(get_unique_name(name, bpy.data.node_groups), 'ShaderNodeTree')

    # Presentation: one frame holding the essential nodes (Group Input, Group Output and the two
    # constants), so opening the group in the node editor shows a labelled pass-through instead of
    # nodes floating at the origin.
    frame = tree.nodes.new('NodeFrame')
    frame.label = 'Starter Group (pass-through)'
    frame.location = (-600, 300)
    frame.use_custom_color = True
    frame.color = (0.16, 0.22, 0.16)

    group_input = tree.nodes.new('NodeGroupInput')
    group_input.parent = frame
    group_input.location = (-300, 100)
    group_output = tree.nodes.new('NodeGroupOutput')
    group_output.parent = frame
    group_output.location = (300, 100)

    def add_input(socket_name, socket_type):
        # A channel named like a reserved input would collide; the reserved one wins (FR-7's
        # `Vector` reservation, FR-5's `Alpha`), matching the rest of the add-on.
        if get_tree_input_by_name(tree, socket_name) is not None: return False
        new_tree_input(tree, socket_name, socket_type)
        return True

    def add_output(socket_name, socket_type):
        if get_tree_output_by_name(tree, socket_name) is not None: return False
        new_tree_output(tree, socket_name, socket_type)
        return True

    for root_ch in yp.channels:
        add_input(root_ch.name, _starter_socket_type(root_ch, 'INPUT'))
    add_input('Vector', 'NodeSocketVector')

    for root_ch in yp.channels:
        add_output(root_ch.name, _starter_socket_type(root_ch, 'OUTPUT'))
    add_output('Alpha', 'NodeSocketFloatFactor')

    # Pass-through: each channel output fed from the input of the same name, except `Normal`.
    # A CUSTOM layer's `Normal` output is a tangent-space normal map: the layer tree puts it
    # through a `ShaderNodeNormalMap` (subtree.py, like NOISE). Feeding the below-layers normal
    # stream through that node transforms it twice and visibly warps the shading, so the starter's
    # `Normal` output is a constant neutral map (0.5, 0.5, 1.0) instead. Its same-named input is
    # still declared and fed (FR-6), so a user can build on the below-layers stream themselves.
    # Wired through `node_connections.create_link`, the add-on's only link creator.
    from .node_connections import create_link
    normal_out_name = next((root_ch.name for root_ch in yp.channels
                            if root_ch.special_type == 'NORMAL'), None)
    alpha_output = group_output.inputs.get('Alpha')
    for outp in group_output.inputs:
        if outp.name in {'Alpha', normal_out_name}: continue
        inp = group_input.outputs.get(outp.name)
        if inp is not None:
            create_link(tree, inp, outp)

    # FR-31: `Alpha` is a constant 1.0, not a pass-through, so a fresh layer is opaque.
    if alpha_output is not None:
        value = tree.nodes.new('ShaderNodeValue')
        value.parent = frame
        value.location = (300, -100)
        value.outputs[0].default_value = 1.0
        create_link(tree, value.outputs[0], alpha_output)

    # FR-31: the neutral normal map that makes a fresh starter layer a no-op for normals.
    normal_output = group_output.inputs.get(normal_out_name) if normal_out_name else None
    if normal_output is not None:
        # `ShaderNodeCombineXYZ` rather than 5.x's `FunctionNodeInputVector`: the fork supports
        # Blender 4.2 LTS, and Combine XYZ exists in every supported build.
        neutral_normal = tree.nodes.new('ShaderNodeCombineXYZ')
        neutral_normal.parent = frame
        neutral_normal.label = 'Neutral Normal'
        neutral_normal.location = (100, -100)
        for socket_name, value in (('X', 0.5), ('Y', 0.5), ('Z', 1.0)):
            neutral_normal.inputs[socket_name].default_value = value
        create_link(tree, neutral_normal.outputs[0], normal_output)

    return tree

# Interface signature cache. Module-level and transient on purpose: T-6b owns its lifetime (its
# depsgraph handler is the only continuous reader and will prime, compare and eventually prune it).
# Nothing is written to the layer or to `yp` — a cache entry that survives an undo is merely stale,
# which can only cause one redundant, idempotent sync (ADR-0003), never a missed one.
#
# Keyed by `(yp_tree_pointer, group_pointer)`, not by group name: two materials can reference the
# same user group, and each `yp` must repair its own layers independently. Group names are not
# unique across a session once a datablock is removed (Blender may reuse the name), while
# `as_pointer()` is stable for the lifetime of the datablock. `yp.id_data` is the ucupaint node
# tree holding the `yp` PropertyGroup; comparing its pointer distinguishes the materials.
_CUSTOM_CACHE_MISSING = object()
_custom_interface_signature_cache = {}

# T-7a / FR-16 usability cache. Keyed by the stable per-layer identity from
# `get_custom_usability_key()` (the `yp` tree plus the layer's own group node name, never
# `layer.as_pointer()`) and holding the last observed `is_custom_layer_group_usable` value for that
# layer. The depsgraph handler compares it with the live value and re-splices the yp only when it
# flips (usable -> missing/emptied, or back). Without it a missing group would be indistinguishable
# from one that was never usable and every update would rebuild the channel chain. It is
# session-scoped like the signature cache, pruned with it, and reset by `clear_custom_sync_state`.
_custom_usability_cache = {}

# T-6b error state. All are session-scoped and keyed by `(yp_key, group_key)`, matching the
# signature cache; `clear_custom_sync_state()` resets them with it.
#
# `_custom_sync_throttle` records `(failed_signature, retry_after)` for a repair that raised.
# Retrying is bounded but not permanent: the next update retries once the delay has elapsed, an
# interface change (a different signature) retries immediately, and a manual Refresh calls
# `sync_custom_layers(yp)` directly, which ignores the throttle. That keeps `plan.md` §4's
# "the next update retries" true while a deterministic failure cannot turn every update into a
# failing reconnect (no per-frame storm).
_custom_sync_throttle = {}
# Delay between retries of a failed group's repair.
CUSTOM_SYNC_RETRY_DELAY = 0.5
# Groups whose failure has already been shown this session: report once, not once per update.
_custom_sync_reported = set()
# Latest error text per `(yp_key, group_key)`, read by the UI's report row; cleared when that
# group's sync succeeds.
_custom_sync_errors = {}


def clear_custom_sync_state():
    # T-6b cache lifetime: a new file/open must not reuse pointers (or stale signatures) from the
    # previous session. Called from `load_post` and from `unregister`.
    _custom_interface_signature_cache.clear()
    _custom_usability_cache.clear()
    _custom_sync_throttle.clear()
    _custom_sync_reported.clear()
    _custom_sync_errors.clear()


@persistent
def custom_sync_load_post(dummy):
    # A reopened file gets a silent cold-start repair on its first depsgraph update: an empty
    # cache differs from every live signature, so the handler runs the idempotent sync once.
    clear_custom_sync_state()


def get_custom_sync_error(yp):
    # T-6b report path for the UI. The handler cannot use `Operator.report`, so it leaves the
    # message here and the panel draws it; no console output (NFR-3). Errors are per group so a
    # healthy group completing in the same pass cannot erase a neighbour's report.
    if yp is None: return ''
    try: yp_key = yp.id_data.as_pointer()
    except Exception: return ''

    messages = []
    for key, message in _custom_sync_errors.items():
        if key[0] == yp_key and message not in messages:
            messages.append(message)
    return '; '.join(messages)

# What a missing group has: a real, empty signature, not `None`, so callers can compare tuples
# without a special case and `()` means both "no group" and "group with no sockets".
EMPTY_INTERFACE_SIGNATURE = ()

def get_custom_interface_signature(group):
    # FR-14 / ADR-0003: the ordered `((in_out, name, socket_type, enabled), …)` of every interface
    # socket of `group`, built through `input_outputs` so pre-4.0 (`tree.inputs` / `tree.outputs`)
    # and 4.0+ (`tree.interface`) give the same shape. Only declaration topology is included, so
    # `default_value` edits, node locations and node mute state can never change it (FR-12).
    if group is None: return EMPTY_INTERFACE_SIGNATURE

    # Imported lazily to keep this module's place in `__init__.py`'s import order (it is loaded
    # before `input_outputs`/`subtree`/`node_connections`).
    from .input_outputs import get_tree_interface_socket_entries

    signature = []
    for in_out, socket in get_tree_interface_socket_entries(group):
        # `enabled` fallback: 4.0+ interface entries have no `.enabled` (Blender exposes no
        # per-declaration enable flag, only `hide_value`), so a declaration that cannot report one
        # counts as enabled, which matches what a freshly instantiated socket reports. Pre-4.0
        # `tree.inputs` / `tree.outputs` entries are real sockets and give the honest value.
        enabled = getattr(socket, 'enabled', True)
        signature.append((in_out, socket.name, get_custom_socket_id(socket), enabled))

    return tuple(signature)

def get_custom_layer_group(layer):
    # The user group a custom layer points at. `layer.custom_group` is the single source of truth
    # (T-7a, ADR-0002); the source node's `node_tree` is only a defensive fallback for a layer that
    # was built before the pointer existed (an old file). Both can be None (FR-16).
    if layer is None: return None

    group = getattr(layer, 'custom_group', None)
    if group is not None: return group

    source = get_layer_source(layer)
    return getattr(source, 'node_tree', None) if source is not None else None

def is_custom_layer_source_missing(layer):
    # FR-16: an existing source node with no `node_tree` cannot instantiate anything, so the layer
    # contributes nothing even while `layer.custom_group` still names a valid tree. Only a *node
    # that exists* counts: no source node at all is not this state (a broken/never-built layer keeps
    # its previous behaviour, which the pointer-first predicate already covers).
    if layer is None: return False
    source = get_layer_source(layer)
    if source is None: return False
    return getattr(source, 'node_tree', None) is None

def is_custom_layer_group_usable(layer):
    # FR-16: a custom layer contributes only when its referenced group offers at least one
    # compatible output. False for a missing group (None or a deleted datablock), an emptied one and
    # a layer with no group. Non-custom layers always answer True, so call sites can ask
    # unconditionally.
    #
    # The pointer is read first (`get_custom_layer_group`: `custom_group`, with the source node's
    # tree only as the pre-pointer-file fallback), so this predicate, the layer row and the missing
    # group menu cannot disagree about which group the layer uses. Before T-7a this read the source
    # node directly, which let a stale `source.node_tree` contradict `layer.custom_group`.
    #
    # Precedence when pointer and source disagree: the pointer names the group and wins over a
    # *stale but present* source tree (T-7a `test_03`, the pointer is the source of truth). The one
    # exception is a source node that lost its tree entirely: `source.node_tree = None` is the
    # literal FR-16 action and makes the layer unusable even while the pointer is intact, because
    # nothing is instantiated in the graph. `set_custom_layer_group` sets both in one step, which is
    # why relinking restores usability in a single update.
    if layer is None or getattr(layer, 'type', '') != 'CUSTOM': return True
    if is_custom_layer_source_missing(layer): return False

    group = get_custom_layer_group(layer)
    if group is None: return False

    return bool(get_custom_compatible_outputs(group))

def get_custom_layer_source(layer):
    # Source node of a custom layer, or None. None-safe for a layer whose tree is gone.
    if layer is None: return None
    return get_layer_source(layer)


# Dummy-instance workflow (T-12). Blender's Shader Editor has no reliable Python API to open a node
# group that has no instance anywhere, and the previous *Edit Group* operator reported success
# without changing the editor in real use. Instead the material tree gets a visible, unconnected
# instance of every group a CUSTOM layer references, inside a labelled frame. The user Tabs into the
# instance and edits the same datablock the layer's source points at, so edits propagate live.
#
# Identification is a custom property plus the group pointer, never a name: the user may rename the
# node, and `node_tree` is the actual reference that matters. The frame is found by its property or
# its exact label, and is never moved or relabelled once it exists, so a hand-arranged layout
# survives every later sync.
CUSTOM_DUMMY_FRAME_LABEL = 'Custom Layers: edit here, do not connect'
CUSTOM_DUMMY_PROP = 'yp_custom_dummy'
CUSTOM_DUMMY_FRAME_PROP = 'yp_custom_dummy_frame'
# Cascade spacing for freshly added dummies; the slot scan avoids collisions with existing ones.
CUSTOM_DUMMY_STEP_X = 260.0
CUSTOM_DUMMY_STEP_Y = 220.0


def _find_custom_dummy_frame(tree):
    # The frame ours or a frame the user happened to label identically. Never re-label or move it.
    for node in tree.nodes:
        if node.type != 'FRAME': continue
        if node.get(CUSTOM_DUMMY_FRAME_PROP) or node.label == CUSTOM_DUMMY_FRAME_LABEL:
            return node
    return None


def _custom_dummy_nodes(tree):
    # Only nodes we created: a user group node is never touched even if it sits in the frame.
    return [node for node in tree.nodes
            if node.type == 'GROUP' and node.get(CUSTOM_DUMMY_PROP)]


def _referenced_custom_groups(yp):
    # One entry per referenced group, in first-reference order. Two layers on one group share a
    # dummy; a missing group (None) references nothing and is therefore pruned.
    groups = []
    seen = set()
    for layer in yp.layers:
        # CUSTOM: only a custom layer references a user group.
        if layer.type != 'CUSTOM': continue
        group = get_custom_layer_group(layer)
        if group is None: continue
        key = group.as_pointer()
        if key in seen: continue
        seen.add(key)
        groups.append(group)
    return groups


def _custom_dummy_frame_location(tree, yp_tree):
    # Clear of the ucupaint node: left and down, so the dummy frame does not cover the layer graph
    # the user actually works with. The material always has exactly one node instantiating the yp
    # tree; without one (a broken setup) fall back to a fixed left/down origin.
    yp_pointer = yp_tree.as_pointer()
    yp_node = next((node for node in tree.nodes
                    if node.type == 'GROUP' and node.node_tree is not None
                    and node.node_tree.as_pointer() == yp_pointer), None)
    if yp_node is None: return (-600.0, -400.0)
    return (yp_node.location.x - 500.0, yp_node.location.y - 350.0)


def _free_custom_dummy_slot(existing):
    # Grid scan: first slot not occupied by an existing dummy. Existing dummies keep their
    # location, so adding a layer never moves the user's arrangement.
    occupied = {(round(node.location.x), round(node.location.y)) for node in existing}
    index = 0
    while True:
        location = ((index % 3) * CUSTOM_DUMMY_STEP_X,
                    -(index // 3) * CUSTOM_DUMMY_STEP_Y)
        if (round(location[0]), round(location[1])) not in occupied:
            return location
        index += 1


def _remove_empty_custom_dummy_frame(tree, frame):
    # Only a frame we created is ours to delete, and only when no node at all is parented to it:
    # a user may have moved their own nodes into the frame, and those must survive.
    # `node.parent == frame` (not `is`): Blender returns a fresh RNA wrapper for the parent, so an
    # identity check is always false and would delete a frame that still has dummies in it.
    if frame is None or not frame.get(CUSTOM_DUMMY_FRAME_PROP): return False
    if any(node.parent == frame for node in tree.nodes): return False
    tree.nodes.remove(frame)
    return True


def _sync_custom_group_dummies_in_tree(tree, yp_tree, referenced):
    referenced_keys = {group.as_pointer() for group in referenced}
    frame = _find_custom_dummy_frame(tree)

    # Prune: a dummy whose group no layer references any more (or whose datablock is gone) goes.
    # No links were ever created, so removing the node cannot disturb the render or the yp tree.
    for node in _custom_dummy_nodes(tree):
        group = node.node_tree
        if group is None or group.as_pointer() not in referenced_keys:
            tree.nodes.remove(node)
            continue
        # The header must follow the group datablock name. Earlier versions copied the name into
        # `node.label`, which then froze across a rename; clear such a label so the live name shows.
        if node.label:
            node.label = ''

    existing = _custom_dummy_nodes(tree)
    present = {node.node_tree.as_pointer() for node in existing if node.node_tree is not None}
    missing = [group for group in referenced if group.as_pointer() not in present]

    if not missing:
        _remove_empty_custom_dummy_frame(tree, frame)
        return

    if frame is None:
        frame = tree.nodes.new('NodeFrame')
        frame.label = CUSTOM_DUMMY_FRAME_LABEL
        frame[CUSTOM_DUMMY_FRAME_PROP] = True
        frame.use_custom_color = True
        frame.color = (0.22, 0.16, 0.16)
        frame.location = _custom_dummy_frame_location(tree, yp_tree)

    for group in missing:
        node = tree.nodes.new('ShaderNodeGroup')
        node[CUSTOM_DUMMY_PROP] = True
        node.node_tree = group
        # No label: a group node shows its `node_tree` name until the user labels it, and a label
        # written here would freeze the old name across a group rename.
        node.parent = frame
        node.location = _free_custom_dummy_slot(existing)
        node.select = False
        existing.append(node)

    _remove_empty_custom_dummy_frame(tree, frame)


def _sync_custom_group_dummies(yp):
    # The material trees that actually use this yp. `get_materials_using_yp` is the existing scan;
    # do not hand-roll another one. `yp.id_data` is the ucupaint node tree, so a dummy always lands
    # in the *material* tree, never in ucupaint's own generated graph.
    if yp is None: return
    try:
        materials = get_materials_using_yp(yp)
    except Exception:
        return

    referenced = _referenced_custom_groups(yp)

    for mat in materials:
        tree = getattr(mat, 'node_tree', None)
        if tree is None: continue
        try:
            _sync_custom_group_dummies_in_tree(tree, yp.id_data, referenced)
        except Exception:
            # A file mid-edit can have a tree removed between the scan and the write. The dummy is
            # a convenience for the editor, never a rendering dependency, so a failure here must
            # not break layer creation, relinking or removal.
            continue


def ensure_custom_group_dummy(layer):
    # Called on creation, group change/relink and Make Unique: ensure every referenced group has
    # one unconnected instance in this material, and prune instances for groups no layer uses.
    # Idempotent: a second call adds nothing.
    if layer is None or getattr(layer, 'type', '') != 'CUSTOM': return
    _sync_custom_group_dummies(layer.id_data.yp)


def prune_custom_group_dummies(yp):
    # Called after removal and after a group change/Make Unique: same idempotent sync, so dummies
    # and the frame disappear with their last referencing layer, while another group's dummy stays.
    _sync_custom_group_dummies(yp)


def remove_custom_group_dummies_from_tree(tree):
    # Called when the ucupaint node is removed: the dummies live in the *material* tree, not in the
    # yp tree, so they must be pruned through an explicit tree while no yp instance is left to find
    # the material with `get_materials_using_yp`. An empty reference list removes every dummy and
    # the frame once it is empty; user nodes and links are never touched.
    if tree is None: return
    try:
        _sync_custom_group_dummies_in_tree(tree, None, [])
    except Exception:
        # A material tree mid-removal is not worth failing the operator for; the dummy is only an
        # editor convenience.
        pass


def reconnect_custom_yp(yp, layers=None):
    # T-7a / FR-16: rebuild the whole yp channel chain after a CUSTOM layer's *usability* changed.
    # Layer-local passes cannot move a layer into or out of the blend chain; only
    # `reconnect_yp_nodes` does that (it treats an unusable CUSTOM layer exactly like a disabled
    # one). `rearrange_yp_nodes` then restores the layout. Both are the existing entry points; this
    # helper only owns the guard so every caller re-splices the same way.
    #
    # `layers` are the layers whose usability flipped in this update. A layer that became usable
    # again also needs its own tree rebuilt (`reconnect_layer_nodes`): clearing the source node's
    # `node_tree` drops the links from its outputs, and restoring the same tree does not bring those
    # links back by itself. Rebuilding only the flipped layers keeps the transition at one update
    # without touching unrelated healthy layers. Callers that already ran the layer pass
    # (`set_custom_layer_group`) pass nothing.
    if yp is None: return

    from .node_connections import reconnect_yp_nodes, reconnect_layer_nodes
    from .node_arrangements import rearrange_yp_nodes, rearrange_layer_nodes

    tree = yp.id_data
    ori_halt_update = yp.halt_update
    ori_halt_reconnect = yp.halt_reconnect
    try:
        yp.halt_update = True
        # The reconnect passes are no-ops while their own guard is set; lift it for the repair.
        yp.halt_reconnect = False
        for layer in (layers or []):
            # Only a usable layer has a source tree to rebuild; a layer going missing is bypassed
            # at the yp level and its own broken tree must not be walked.
            if not is_custom_layer_group_usable(layer): continue
            reconnect_layer_nodes(layer)
            rearrange_layer_nodes(layer)
        reconnect_yp_nodes(tree)
        rearrange_yp_nodes(tree)
    finally:
        yp.halt_reconnect = ori_halt_reconnect
        yp.halt_update = ori_halt_update


def get_custom_usability_key(layer):
    # T-7a follow-up: stable identity for the FR-16 usability cache, `(yp tree, layer marker)`.
    #
    # Never `layer.as_pointer()`: that is a collection slot address. Blender reuses a freed slot,
    # so removing a layer hands its address to the next layer in the list, and a cached value for
    # the removed layer would be read as the neighbour's. The layer's group node name is per-layer
    # (a node lives in exactly one tree and its name is unique there), survives list insertion and
    # removal, and is already the cross-tree reference (`layer.group_node`).
    #
    # A hidden layer (disabled or with a hidden parent) moves its node to the yp trash tree and
    # leaves `group_node == ''`; `trash_group_node` names it there and is unique in that tree, so it
    # carries the identity. A layer with no node at all yet — created but not built, or a broken
    # tree — falls back to its own name, which `get_unique_name` keeps unique in `yp.layers`. The
    # `g:`/`t:`/`l:` namespaces keep those three sources from colliding; each only changes when the
    # layer itself is rebuilt (an enable toggle or a new layer tree), which reconnects the yp anyway,
    # so a fresh key there costs at most one idempotent repair.
    if layer is None: return None
    try: yp_key = layer.id_data.as_pointer()
    except Exception: return None

    group_node = getattr(layer, 'group_node', '')
    if group_node: return (yp_key, 'g:' + group_node)

    trash_node = getattr(layer, 'trash_group_node', '')
    if trash_node: return (yp_key, 't:' + trash_node)

    return (yp_key, 'l:' + layer.name)

def _set_custom_usability(layer, usable):
    # Record the live usability so the handler does not reconnect a second time for a change this
    # synchronous path already applied (relink through `set_custom_layer_group`).
    if layer is None: return
    key = get_custom_usability_key(layer)
    if key is None: return
    _custom_usability_cache[key] = bool(usable)

def is_custom_channel_binding_valid(layer, ch, source=None):
    # FR-9/FR-10 derived state: is the bound output one a channel may actually use? A binding is
    # invalid when the socket vanished, was retyped to an incompatible type, or is empty.
    if layer is None or ch is None: return False

    if not source: source = get_custom_layer_source(layer)
    if source is None: return False

    name = ch.socket_input_name
    if not name: return False

    return any(outp.name == name for outp in get_available_source_outputs(source, layer.type))

def get_custom_channel_warning(layer, ch, source=None):
    # FR-10 derived state for one channel. Shared by `get_custom_layer_warning` and the layers
    # panel's per-channel row, so the predicate the tests exercise is the one the UI actually
    # ships. Empty string means healthy.
    #
    # Disabled channels are intentionally skipped: a disabled channel feeds nothing, so a stale
    # binding on it is not a warning. An overridden channel is skipped too: the override pick
    # (`wm.y_set_layer_channel_input` with an empty socket name) makes the channel ignore the
    # group output, so a fallback flag left over from the group binding is stale.
    if layer is None or ch is None or layer.type != 'CUSTOM': return ''
    if not ch.enable or ch.override: return ''

    if ch.custom_fallback_binding:
        return 'Channel binding was re-pointed after its group output changed'
    if not is_custom_channel_binding_valid(layer, ch, source):
        return 'Channel is not bound to a group output'

    return ''

def get_custom_layer_warning(layer):
    # FR-4/FR-9/FR-10/FR-16 derived state for the UI; nothing is stored except the channel's
    # fallback flag. Empty string means healthy. The missing-group and no-compatible-output cases
    # are the FR-16 fallback state; a channel that was automatically re-pointed after its output
    # changed is FR-10's warning that stays until the user re-chooses.
    if layer is None or layer.type != 'CUSTOM': return ''

    # FR-16: the source node exists but no longer instantiates a tree. The pointer can still name a
    # valid group (the reviewer's probe), yet the layer cannot contribute, so the row's missing-group
    # state and the bypass agree with `is_custom_layer_group_usable`.
    if is_custom_layer_source_missing(layer): return 'Missing node group'

    group = get_custom_layer_group(layer)
    if group is None: return 'Missing node group'

    if not get_custom_compatible_outputs(group): return 'Node group has no compatible outputs'

    source = get_custom_layer_source(layer)
    for ch in layer.channels:
        message = get_custom_channel_warning(layer, ch, source)
        if message:
            return message

    return ''

def get_default_custom_output_name(layer, root_ch, source=None):
    # FR-9: the output whose name equals the root channel's name, else the first compatible
    # output in socket order. Empty string when the group offers nothing compatible.
    if layer is None or root_ch is None: return ''

    if not source: source = get_custom_layer_source(layer)
    if source is None: return ''

    outputs = get_available_source_outputs(source, layer.type)
    if not outputs: return ''

    for outp in outputs:
        if outp.name == root_ch.name: return outp.name

    return outputs[0].name

def set_custom_channel_default_binding(layer, ch, root_ch):
    # FR-9 default binding, called on layer creation and when a root channel is added later.
    # CUSTOM only: every other layer type keeps its existing per-type binding behaviour.
    if layer is None or ch is None or layer.type != 'CUSTOM': return

    name = get_default_custom_output_name(layer, root_ch)
    if not name: return

    yp = layer.id_data.yp
    if ch.socket_input_name == name: return

    # halt_update so the property's update callback does not reconnect a half-built layer; the
    # callers reconnect right after and the channel's linear node is checked there.
    ori_halt_update = yp.halt_update
    yp.halt_update = True
    ch.socket_input_name = name
    yp.halt_update = ori_halt_update

def _preserve_custom_channel_bindings(layer, yp):
    # Make Unique / copy case (FR-8). The copied interface is the same as the original's, so an
    # explicit channel binding is part of the layer's behaviour and must survive the repoint. Only
    # a bound name that the copy no longer offers falls back to FR-9/FR-10 — the same automatic
    # re-point (and warning flag) `_rebind_custom_channels` applies when a group's interface changes.
    # A change-group action must not use this: a genuinely different tree is supposed to be rebound
    # per FR-9/FR-10, which is why `set_custom_layer_group` defaults to that path.
    source = get_custom_layer_source(layer)
    if source is None: return

    available = {outp.name for outp in get_available_source_outputs(source, layer.type)}

    for i, ch in enumerate(layer.channels):
        if i >= len(yp.channels): break
        name = ch.socket_input_name
        if name and name in available:
            # The copy still offers this output: keep the binding and its flag untouched.
            continue
        before = ch.socket_input_name
        set_custom_channel_default_binding(layer, ch, yp.channels[i])
        if ch.socket_input_name != before:
            ch.custom_fallback_binding = True


def set_custom_layer_group(layer, group, preserve_bindings=False):
    # FR-15/FR-16: point an existing custom layer at `group` (or at nothing, which is the FR-16
    # fallback state) and repair the graph. This is the relink path behind the Replace Layer Type
    # picker: one operator step, so one undo step, and the previous group plus a connected tree come
    # back together.
    #
    # `preserve_bindings=False` (a *change-group* action) re-applies the FR-9 defaults to every
    # channel, because the new tree is a different group and its outputs need binding from scratch
    # (FR-10 on a name that vanished). `preserve_bindings=True` is the *copy* case behind Make
    # Unique (FR-8): the interface is the same, so each channel keeps its `socket_input_name` and
    # `custom_fallback_binding` while the copy still offers that output name; only a name missing
    # from the copy falls back per FR-9/FR-10.
    #
    # Blender remaps a group node's instance links *by socket index* when `node_tree` is assigned, so
    # a link into an input that no longer exists on the new group would silently move to a
    # different input (the `MyOwnThing` follow-up). Clearing the source's input links before the
    # swap is what keeps FR-6's "an input matching no channel stays unlinked" true across a swap.
    if layer is None or getattr(layer, 'type', '') != 'CUSTOM': return False

    yp = layer.id_data.yp
    source = get_custom_layer_source(layer)
    if source is None: return False

    from .input_outputs import check_all_layer_channel_io_and_nodes
    from .node_connections import break_input_link, reconnect_layer_nodes
    from .node_arrangements import rearrange_layer_nodes

    source_tree = source.id_data

    ori_halt_update = yp.halt_update
    ori_halt_reconnect = yp.halt_reconnect
    try:
        yp.halt_update = True
        yp.halt_reconnect = True

        for inp in source.inputs:
            break_input_link(source_tree, inp)

        layer.custom_group = group
        source.node_tree = group

        if preserve_bindings:
            # FR-8: a copy has the same interface, so keep each explicit binding (and its flag).
            # Only a bound name missing from the copy falls back per FR-9/FR-10.
            _preserve_custom_channel_bindings(layer, yp)
        else:
            # FR-9 bindings for the new group; an explicit re-pick is not the FR-10 automatic
            # fallback, so the warning flags start clear.
            for i, ch in enumerate(layer.channels):
                ch.custom_fallback_binding = False
                if i < len(yp.channels):
                    set_custom_channel_default_binding(layer, ch, yp.channels[i])

        # The `Vector` input decides whether a mapping node exists; the IO pass creates/prunes it.
        check_all_layer_channel_io_and_nodes(layer)

        yp.halt_reconnect = False
        reconnect_layer_nodes(layer)
        rearrange_layer_nodes(layer)

        # FR-16: a relink can change usability (missing -> usable or the reverse), which only the
        # yp-level pass can express: it re-splices this layer into the channel chain or bypasses it
        # like a disabled layer. Without this the pointer and warning update but the render keeps
        # the previous graph until an unrelated `layer.enable` toggle.
        reconnect_custom_yp(yp)
    finally:
        yp.halt_reconnect = ori_halt_reconnect
        yp.halt_update = ori_halt_update

    # The synchronous path has already spliced the graph; record the new usability so the handler
    # does not treat it as a fresh transition and reconnect again.
    _set_custom_usability(layer, is_custom_layer_group_usable(layer))

    # Dummy instances: Make Unique and Change Group both land here, so the new group gets its
    # editable instance and the old group's dummy is pruned when no layer references it any more.
    ensure_custom_group_dummy(layer)

    return True

def make_group_unique(layer):
    # FR-8/FR-17: the explicit deep copy. `group.copy()` gives an independent tree; the layer is
    # repointed through `set_custom_layer_group` with `preserve_bindings=True`, so the copied
    # interface keeps every explicit channel binding (and its FR-10 flag) instead of re-applying
    # the FR-9 defaults — the binding is part of the layer's behaviour, not of the group datablock.
    # The relink path also clears the stale input links, re-splices the yp and records the new
    # usability. Two layers on one group keep following the original until this runs; afterwards
    # exactly the copied layer follows the copy.
    #
    # The copy must not inherit identity that belongs to the original: a `~yPL ` name would make
    # `lib.clean_unused_libraries` treat it as a library tree (and prune it when this layer is the
    # last user), and the `yp` flags would make the picker/versioning treat it as ucupaint's own.
    # A user group usually has neither, but a copied library group does.
    if layer is None or getattr(layer, 'type', '') != 'CUSTOM': return None

    group = get_custom_layer_group(layer)
    if group is None: return None

    unique = group.copy()

    if unique.name.startswith('~yPL '):
        unique.name = unique.name[len('~yPL '):] or 'Custom Node Layer'
    unique.use_fake_user = False
    try:
        yp = getattr(unique, 'yp', None)
        if yp is not None:
            yp.is_ypaint_layer_node = False
            yp.is_ypaint_node = False
    except Exception:
        pass

    if not set_custom_layer_group(layer, unique, preserve_bindings=True):
        # The layer has no source node to repoint: leave no orphan copy behind.
        bpy.data.node_groups.remove(unique)
        return None
    return unique

def _count_custom_layer_links(layer):
    # Link count of one CUSTOM layer tree, for the "did the repair do anything" report. A missing
    # tree counts as zero; the sync then has nothing to repair there.
    tree = get_tree(layer)
    return len(tree.links) if tree else 0

def _rebind_custom_channels(layer, yp):
    # FR-10 fallback: a channel whose bound output vanished (or is no longer compatible) binds to
    # the FR-9 default again — the same-named output if it exists, else the first compatible one.
    # Marks the channel so the UI keeps warning until the user re-chooses the binding explicitly;
    # an automatic fallback is not a silent change (FR-10).
    # Returns how many bindings actually changed.
    source = get_custom_layer_source(layer)
    if source is None: return 0

    changed = 0
    for i, ch in enumerate(layer.channels):
        if i >= len(yp.channels): break  # bindings are positional against the root channel list
        if is_custom_channel_binding_valid(layer, ch, source): continue
        before = ch.socket_input_name
        set_custom_channel_default_binding(layer, ch, yp.channels[i])
        if ch.socket_input_name != before:
            ch.custom_fallback_binding = True
            changed += 1

    return changed

def _iter_yps_with_custom_layers():
    # T-6b yp discovery. `yp` is a PointerProperty on every node tree, so this walks the
    # `bpy.data.node_groups` datablocks and skips anything that is not a ucupaint node tree; it does
    # not descend into materials or into any node tree's nodes. The inner loop stops at the first
    # custom layer. Cost is therefore the datablock count, not the scene size, and the signature
    # check — the budgeted part — only runs for trees that actually have a custom layer. Measured
    # against NFR-2's 5 layers × 20 sockets case (see the T-6b commit body).
    for tree in bpy.data.node_groups:
        yp = getattr(tree, 'yp', None)
        if yp is None or not yp.is_ypaint_node: continue
        for layer in yp.layers:
            # CUSTOM: only a custom layer references a user group whose interface can change.
            if layer.type == 'CUSTOM':
                yield yp
                break


def _custom_sync_group_name(group_key):
    # Resolve a group pointer back to its datablock name for the report text. Group pointers are
    # what the cache keys use; the name is only needed when a failure is shown, so this walks
    # `bpy.data.node_groups` on the error path and never on the update path.
    if not isinstance(group_key, int): return None
    for group in bpy.data.node_groups:
        if group.as_pointer() == group_key: return group.name
    return None

def _handle_custom_sync_error(yp, exception, signatures, causes=None):
    # T-6b exception policy. Never let the exception reach Blender's handler loop; throttle every
    # failed group at the signature it tried, so the next update retries after a bounded delay
    # (or immediately on an interface change). The message is shown once per group per session
    # through the UI report path, not printed. Each message names its group and keeps that group's
    # own cause, so two failing groups in one yp cannot be mistaken for each other.
    try:
        yp_key = yp.id_data.as_pointer()
    except Exception:
        return

    causes = causes or {}
    cause = str(exception)
    for key, signature in signatures.items():
        _custom_sync_throttle[key] = (signature, time.monotonic() + CUSTOM_SYNC_RETRY_DELAY)
        if key in _custom_sync_reported: continue
        _custom_sync_reported.add(key)
        group_name = _custom_sync_group_name(key[1])
        group_cause = str(causes.get(key, exception))
        message = 'Custom layer sync failed'
        if group_name: message += ' (' + group_name + ')'
        _custom_sync_errors[key] = message + ': ' + group_cause

    if not signatures:
        # The failure happened before a group signature could be read; report it per yp once.
        marker = (yp_key, 'yp')
        if marker not in _custom_sync_reported:
            _custom_sync_reported.add(marker)
            _custom_sync_errors[marker] = 'Custom layer sync failed: ' + cause


class CustomSyncError(RuntimeError):
    # Carries the groups that failed, so the handler reports only them even though healthy groups
    # in the same yp already completed and must not be blamed (Defect B). `causes` keeps each
    # group's own exception for the report text.
    def __init__(self, cause, signatures, causes=None):
        super().__init__(str(cause))
        self.cause = cause
        self.signatures = signatures
        self.causes = causes or {}


def _prune_custom_handler_caches(yp_key, live_group_keys, live_usability_keys):
    # The handler is the only continuous reader, so it also owns cache lifetime for a yp (T-6a).
    # Signature/error entries belong to a *group*; usability entries belong to a *layer*. Only
    # integer keys are group pointers — `(yp_key, 'yp')` is the whole-yp failure marker and must
    # survive until a successful sync clears it. A usability key is `(yp_key, marker)` with a
    # string marker (see `get_custom_usability_key`), so it never looks like a group pointer.
    for key in list(_custom_interface_signature_cache):
        if key[0] == yp_key and key[1] not in live_group_keys:
            _custom_interface_signature_cache.pop(key, None)

    for key in list(_custom_usability_cache):
        if key[0] == yp_key and key not in live_usability_keys:
            _custom_usability_cache.pop(key, None)

    for key in list(_custom_sync_throttle):
        if key[0] == yp_key and isinstance(key[1], int) and key[1] not in live_group_keys:
            _custom_sync_throttle.pop(key, None)

    for key in list(_custom_sync_reported):
        if key[0] == yp_key and isinstance(key[1], int) and key[1] not in live_group_keys:
            _custom_sync_reported.discard(key)

    for key in list(_custom_sync_errors):
        if key[0] == yp_key and isinstance(key[1], int) and key[1] not in live_group_keys:
            _custom_sync_errors.pop(key, None)


@persistent
def custom_layer_update_handler(scene, depsgraph=None):
    # T-6b / FR-11–FR-13 / ADR-0003. Signature-gated live re-sync on depsgraph update.
    #
    # FR-12: a default_value edit, a node move or a mute changes no declaration, so every cached
    # signature still matches and `sync_custom_layers` is never called. FR-13: `sync_custom_layers`
    # writes the new signature *before* rewiring, so the update caused by the rewire sees a match
    # and takes this early path too.
    #
    # T-7a / FR-16: usability is a second, per-layer gate. A group that is deleted (live) or loses
    # its last compatible output leaves the signature unchanged — or has no group at all — so the
    # signature pass cannot see it. The usability flag is cached per layer (keyed by the stable
    # `get_custom_usability_key`, never a collection slot pointer) and a yp is re-spliced only when
    # it flips, which is exactly one rebuild per transition (deleting a group is silent afterwards;
    # restoring it flips once).
    #
    # Each yp is handled on its own and each group inside it is repaired with its own try/except
    # (in `sync_custom_layers`): one failing group cannot skip a healthy group in the same yp.
    #
    # The whole body is guarded: an exception inside a depsgraph handler would otherwise surface as
    # a broken frame rather than a report (ADR-0003).
    try:
        now = time.monotonic()
        for yp in _iter_yps_with_custom_layers():
            signatures = {}
            candidates = set()
            usability_changed = False
            flipped_layers = []
            yp_key = None

            # CUSTOM: only a custom layer has a group to watch or a usability to compare.
            # Resolve the pointer once per layer; `live_group_keys` is computed here so the prune in
            # `finally` is safe even if the repair raises part way through. The usability key is the
            # layer's stable identity, not its collection slot (T-7a follow-up).
            layer_groups = [(layer, get_custom_layer_group(layer),
                             get_custom_usability_key(layer)) for layer in yp.layers
                            if layer.type == 'CUSTOM']
            live_usability_keys = {key for _, _, key in layer_groups}
            live_group_keys = {group.as_pointer() for _, group, _ in layer_groups
                               if group is not None}

            try:
                yp_key = yp.id_data.as_pointer()
                # One signature read per group per update, shared by the usability gate and the
                # signature gate. This is the NFR-2-budgeted work; never walk an interface twice.
                signature_by_pointer = {}
                for layer, group, usability_key in layer_groups:
                    # FR-16 usability from the referenced group's own signature, the same pointer
                    # `is_custom_layer_group_usable` reads, so predicate, row and graph cannot
                    # disagree about which group the layer uses.
                    signature = None
                    if group is not None:
                        group_pointer = group.as_pointer()
                        signature = signature_by_pointer.get(group_pointer)
                        if signature is None:
                            signature = get_custom_interface_signature(group)
                            signature_by_pointer[group_pointer] = signature
                    # FR-16: the source node's live tree is the graph truth. A source that lost its
                    # tree makes the layer unusable even when the pointer still names a valid group
                    # (the literal `source.node_tree = None` probe), so the usability gate flips and
                    # this update re-splices the yp exactly once.
                    usable = not is_custom_layer_source_missing(layer) and signature is not None and any(
                        in_out == 'OUTPUT' and socket_type in COMPATIBLE_SOCKET_IDS
                        for in_out, _name, socket_type, _enabled in signature)

                    cached_usable = _custom_usability_cache.get(usability_key, _CUSTOM_CACHE_MISSING)
                    if cached_usable is _CUSTOM_CACHE_MISSING:
                        _custom_usability_cache[usability_key] = usable
                        # A cold start with an unusable layer still needs one splice: a file saved
                        # while missing may carry a stale chain.
                        if not usable:
                            usability_changed = True
                            flipped_layers.append(layer)
                    elif cached_usable != usable:
                        _custom_usability_cache[usability_key] = usable
                        usability_changed = True
                        flipped_layers.append(layer)

                    if group is None: continue  # missing group: usability handles it, no signature
                    if group is yp.id_data: continue  # cycle guard: never resync the yp's own tree
                    key = (yp_key, group.as_pointer())
                    if key in signatures: continue
                    group_pointer = key[1]
                    signature = signature_by_pointer.get(group_pointer)
                    if signature is None:
                        signature = get_custom_interface_signature(group)
                        signature_by_pointer[group_pointer] = signature
                    signatures[key] = signature
                    if _custom_interface_signature_cache.get(key, _CUSTOM_CACHE_MISSING) == signature:
                        continue
                    throttled = _custom_sync_throttle.get(key)
                    if throttled is not None:
                        failed_signature, retry_after = throttled
                        # Same failing interface and still inside the retry window: skip. A changed
                        # signature retries immediately; an elapsed window retries too.
                        if signature == failed_signature and now < retry_after:
                            continue
                    candidates.add(key[1])

                # FR-16: one yp-level re-splice per usability transition, independent of whether
                # a group signature also changed (the two can happen in the same update).
                if usability_changed:
                    reconnect_custom_yp(yp, flipped_layers)
                    # A group deleted live takes the dummy's `node_tree` with it, leaving a blank
                    # instance. The usability flip is the only handler event that deletion produces,
                    # so prune here while the yp is already being repaired.
                    prune_custom_group_dummies(yp)
                if candidates:
                    sync_custom_layers(yp, group_keys=candidates)
            except CustomSyncError as e:
                _handle_custom_sync_error(yp, e.cause, e.signatures, e.causes)
            except Exception as e:
                _handle_custom_sync_error(yp, e, signatures)
            finally:
                if yp_key is not None:
                    _prune_custom_handler_caches(yp_key, live_group_keys, live_usability_keys)
    except Exception as e:
        # The discovery walk itself failed (for example a datablock being removed mid-iteration).
        # There is no group to blame; swallow it so Blender's handler loop stays intact.
        try: _handle_custom_sync_error(None, e, {})
        except Exception: pass


def sync_custom_layers(yp, group_keys=None):
    # T-6a/T-6b: the single repair entry point for CUSTOM layers (FR-14). Idempotent: called on a
    # healthy tree it leaves every link, node and binding exactly as it was and returns ''.
    #
    # `group_keys` narrows the repair to the given group pointers (the live handler passes the
    # groups whose signature changed). `None` means a manual Refresh: every group, ignoring the
    # retry throttle. Each group is repaired in isolation: on failure its cache entry, bindings
    # and fallback flag are restored, the failure is throttled, and the next group still runs.
    # Failures are re-raised together as `CustomSyncError` after all groups were attempted.
    #
    # Returns a short report string for `wm.y_custom_sync`, '' when nothing needed repair.
    if yp is None: return ''

    from .input_outputs import check_all_layer_channel_io_and_nodes
    from .node_connections import reconnect_layer_nodes
    from .node_arrangements import rearrange_layer_nodes

    cache = _custom_interface_signature_cache
    # Identity of this material's ucupaint tree: the `yp` PropertyGroup lives on that node tree,
    # and `as_pointer()` is stable for the session, unlike a name.
    yp_key = yp.id_data.as_pointer()
    manual = group_keys is None

    # CUSTOM: only a referenced user group has an interface signature; every other layer type is
    # rebuilt by its own property updates and has no group to watch.
    #
    # Collect the live group keys across *all* custom layers (not just the filtered ones) so the
    # prune below is correct even when the handler passes a subset.
    group_layers = {}
    group_objects = {}
    live_group_keys = set()
    for layer in yp.layers:
        if layer.type != 'CUSTOM': continue
        group = get_custom_layer_group(layer)
        if group is None: continue
        group_key = group.as_pointer()
        live_group_keys.add(group_key)
        if group is yp.id_data: continue  # cycle guard: never resync the yp's own tree
        if not manual and group_key not in group_keys: continue
        key = (yp_key, group_key)
        group_layers.setdefault(key, []).append(layer)
        group_objects[key] = group

    changes = []  # (key, group, layers, signature, known)
    for key, layers in group_layers.items():
        group = group_objects[key]
        signature = get_custom_interface_signature(group)
        cached = cache.get(key, _CUSTOM_CACHE_MISSING)
        if cached == signature:
            # A manual Refresh always reruns the reconnect passes (FR-14: a broken link is not
            # necessarily a signature change); the handler only visits groups whose signature changed.
            if not manual: continue
            changes.append((key, group, layers, signature, False))
            continue
        # A first sighting (cold cache) establishes the baseline; it is not a reported change.
        known = cached is not _CUSTOM_CACHE_MISSING
        changes.append((key, group, layers, signature, known))

    groups_with_known_change = set()
    rebound_total = 0
    repaired_links = False
    failures = []
    failure_causes = {}
    first_error = None

    ori_halt_update = yp.halt_update
    ori_halt_reconnect = yp.halt_reconnect
    try:
        for key, group, layers, signature, known in changes:
            if known: groups_with_known_change.add(group.name)

            # Cache the new signature *before* any rewiring, so a reconnect that dirties the tree
            # cannot make the next comparison see the old interface again (ADR-0003). Removed on
            # failure so the next pass still sees a change and retries.
            cache[key] = signature

            # Snapshot every channel's binding and fallback flag before the repair. A failure after
            # re-binding but before reconnect must not leave a half-applied state (Defect B(c)).
            snapshot = [(layer, ch, ch.socket_input_name, ch.custom_fallback_binding)
                        for layer in layers for ch in layer.channels]

            links_before = sum(_count_custom_layer_links(layer) for layer in layers)
            rebound = 0
            try:
                yp.halt_update = True
                yp.halt_reconnect = True
                for layer in layers:
                    rebound += _rebind_custom_channels(layer, yp)
                    # Adding or removing the group's `Vector` input changes whether this layer
                    # needs a mapping node; that node is created/pruned by the tree IO pass.
                    check_all_layer_channel_io_and_nodes(layer)

                # The reconnect passes are no-ops while their own guard is set, so lift it for the
                # repair only; the caller's value is restored in `finally`.
                yp.halt_reconnect = False
                for layer in layers:
                    reconnect_layer_nodes(layer)
                    rearrange_layer_nodes(layer)
            except Exception as e:
                # Drop the entry (never restore it): a missing cache differs from every live
                # signature, so the next update retries even for a manual pass whose signature
                # already matched.
                cache.pop(key, None)

                # Restore the bindings under the update guard, so the property callbacks do not
                # try to reconnect a tree that is mid-rollback.
                yp.halt_update = True
                try:
                    for layer, ch, name, fallback in snapshot:
                        if ch.socket_input_name != name:
                            ch.socket_input_name = name
                        ch.custom_fallback_binding = fallback
                finally:
                    yp.halt_update = ori_halt_update
                    yp.halt_reconnect = ori_halt_reconnect

                _custom_sync_throttle[key] = (signature, time.monotonic() + CUSTOM_SYNC_RETRY_DELAY)
                failures.append((key, signature))
                failure_causes[key] = e
                if first_error is None: first_error = e
                continue
            finally:
                yp.halt_update = ori_halt_update
                yp.halt_reconnect = ori_halt_reconnect

            # T-6b: a completed group repair clears its failure throttle and report, so a later
            # manual Refresh ends the throttle even if nothing else changed.
            rebound_total += rebound
            links_after = sum(_count_custom_layer_links(layer) for layer in layers)
            if links_after != links_before: repaired_links = True
            _custom_sync_throttle.pop(key, None)
            _custom_sync_reported.discard(key)
            _custom_sync_errors.pop(key, None)
    finally:
        yp.halt_reconnect = ori_halt_reconnect
        yp.halt_update = ori_halt_update
        # Prune this yp's entries for groups its layers no longer reference (or that are gone).
        # Other yps' entries are left alone.
        #
        # Every error map is pruned, not only the signature cache: a failed repair already popped
        # its cache entry (so the next pass retries), so a stale throttle/report/error would
        # otherwise outlive the layer that referenced the group. That is the "red sync row
        # survives a deleted layer" case; a manual Refresh reaches this same `finally`.
        stale_keys = {key for mapping in (cache, _custom_sync_throttle,
                                          _custom_sync_reported, _custom_sync_errors)
                      for key in mapping
                      if key[0] == yp_key and key[1] not in live_group_keys}
        for key in stale_keys:
            cache.pop(key, None)
            _custom_sync_throttle.pop(key, None)
            _custom_sync_reported.discard(key)
            _custom_sync_errors.pop(key, None)

        # T-7a: the usability cache is keyed per layer, not per group, so it is pruned against the
        # layers that still exist. Same lifetime as the rest of this yp's cache entries.
        live_usability_keys = {get_custom_usability_key(layer) for layer in yp.layers
                               if layer.type == 'CUSTOM'}
        for key in list(_custom_usability_cache):
            if key[0] == yp_key and key not in live_usability_keys:
                _custom_usability_cache.pop(key, None)

    if failures:
        raise CustomSyncError(first_error, dict(failures), failure_causes)

    if not (groups_with_known_change or rebound_total or repaired_links): return ''

    parts = []
    if groups_with_known_change:
        parts.append('group interface changed: ' + ', '.join(sorted(groups_with_known_change)))
    if rebound_total:
        parts.append(str(rebound_total) + ' channel binding(s) re-bound')
    if repaired_links:
        parts.append('layer links repaired')

    return 'Custom layers synced (' + '; '.join(parts) + ')'
