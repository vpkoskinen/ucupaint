# Architecture

Ucupaint is a Blender add-on that turns a stack of *layers* into a material's channels. This
document maps how that is expressed in node trees. It describes the code as it is; proposals live
in `docs/specs/`.

## 1. Data model

A material holds one *ucupaint node*: a node group instance whose `node_tree.yp` exists. `yp` is
where everything lives:

| `yp.*` | meaning |
|---|---|
| `channels` | root channels of the material. The default root channels are Color, Metallic, Roughness, Normal and Height; Alpha, Ambient Occlusion, Emission and Vector Displacement are opt-in (`Root.py:337-345` defaults their `enable_*` to `False`; they are created at `Root.py:637-641,648-649,651-652,667-668`). User-added channels also live here. Each is `RGB`, `VALUE` or `VECTOR`, and some have a `special_type` (`NORMAL`, `HEIGHT`, `VDISP`) |
| `layers` | the stack, flat, ordered, with `parent_idx` for Group layers |
| `uvs` | UV maps and their tangent/bitangent process nodes |
| `bake_targets` | images/vertex colours a channel can be baked into |
| `version` | schema version for `versioning.py` migrations |
| `halt_reconnect`, `halt_update` | re-entrancy guards, set while a multi-step edit is half-built |

Properties are the source of truth. Node trees are a *projection* of them, rebuilt by the
`reconnect_*` functions; nothing about the graph is authoritative.

## 2. The five kinds of node tree

1. **Material tree** — the material's own tree. Holds the ucupaint node, one UV/tangent chain per
   UV map, and per root channel a pipeline around the layer stack: `start_linear`,
   `start_normal_filter`, `start_bump_process`, `end_linear`, `clamp`, `end_backface`,
   `end_normal_engine_filter`, `end_max_height`, baked-target nodes, and the viewer/emission output
   used by preview and bake.
2. **Layer tree** — one per layer, `LAYERGROUP_PREFIX + name`, marked
   `tree.yp.is_ypaint_layer_node`. `layer.group_node` names its instance in the tree above it —
   the material tree, or the parent layer's tree for a Group layer. It
   contains the layer's *source* node, `mapping`, `texcoord`, `divider_alpha`, `flip_y`, channel
   modifier groups, mask groups, and the pair `Start` (`NodeGroupInput`) / `End` (`NodeGroupOutput`).
3. **Source tree** — optional nesting *inside* a layer tree (`layer.source_group`), used when
   smooth bump or UV neighbour work needs the source evaluated per neighbour direction. Its
   interface is *generated*: see §4.
4. **Channel source tree / modifier trees / mask trees** — per-channel override sources
   (`ch.source_group` on a layer channel), modifier group trees (`get_mod_tree`), and mask group
   trees (`MASKGROUP_PREFIX`, `mask.group_node`).
5. **Library groups** — `lib.blend`, plus `lib_281.blend` / `lib_282.blend`, which carry the groups
   authored against the 2.81 / 2.82 APIs (Edge Detect and friends); every supported build loads
   all three, so none of them is legacy. Names
   prefixed `~yPL `. Created lazily by `common.get_node_tree_lib`
   and `lib.get_smooth_mix_node`, never edited in place, and pruned by `lib.clean_unused_libraries`
   when they lose all users. A layer that needs to edit one must copy it
   (`duplicate_lib_node_tree`) — the Hemi source does exactly this.

## 3. The channel contract (the central invariant)

Layers never talk to each other directly. They talk through **named sockets on the layer group
node**, and the names are the API. `io_suffix` (`common.py`) fixes the vocabulary:

- `<channel>` — the value of that channel at this point in the stack
- `<channel> Alpha`, `<channel> Scale` (height max), `<channel> Midlevel`
- `<channel> Group` for group-layer variants, with `Alpha`/`Height`/`Scale` forms such as
  `<channel> Alpha Group`, `<channel> Height Group`, `<channel> Height Alpha Group`,
  `<channel> Scale Group`
- `<channel> Background` (`<channel> Alpha Background` for the alpha form) for background-layer
  variants (`io_suffix['BACKGROUND']`, built at `input_outputs.py:843-865`)
- `<channel> Height`, `<channel> Max Height`, `<channel> Vector Displacement` for the
  normal/height and displacement outputs
- `<uv> UV`, `<uv> Tangent`, `<uv> Bitangent`
- plus property tunnels named `path.prop` (`get_entity_input_name`), which let a layer read its own
  Blender properties from inside its tree.

`reconnect_yp_nodes` walks channels outer, layers inner: it takes `Start[<channel>]`, pushes it
through every layer bottom-up, then the channel's modifier stack, `end_linear`, clamp, baked-target
substitution, backface, and finally `End[<channel>]`. `reconnect_layer_nodes` builds one layer:
source → per-channel modifier stacks → the layer tree's `End[<channel>]`.

Consequences that any new layer type must respect:

- **I1** Channel names are the only cross-layer contract; renaming a socket is a breaking change.
- **I2** Binding is by socket *name*, never by index. `ch.socket_input_name` holds the chosen
  source output; `get_channel_input_socket_name` falls back to the first compatible output when it
  no longer exists.
- **I3** No hand wiring. Links are made only through `create_link` / `break_input_link` in
  `node_connections.py`, and only from a `reconnect_*` pass.
- **I4** Type-dependent behaviour is expressed as literal `layer.type in {…}` / `not in {…}` sets —
  71 non-comment sites (49 affirmative `in`, 22 `not in`) across 14 files (`ui.py` 26, `common.py` 15,
  `subtree.py` 10, `node_connections.py` 3,
  `layer_common.py` 4, `Modifier.py` 3, `Root.py` 2, `versioning.py` 2, and one each in
  `bake_common.py`, `channel_common.py`, `input_outputs.py`, `Layer.py`, `ListItem.py`,
  `modifier_common.py`); five further sites are commented out (one in `node_connections.py`, four in
  `ui.py`). Of the 71, 70 are live: `modifier_common.py:785` is unreachable
  (`check_layer_modifier_tree(...); return` at `modifier_common.py:783-784`), so its membership is
  dead code, not a design decision. Membership of each set is a design decision about that type, and
  getting one wrong fails silently (a miswired layer renders, just wrongly).
- **I5** A tree is only edited by the code that created it. Library groups are copied before edit;
  a user-authored group is never edited at all.

## 4. The source abstraction

Every layer type is a *source node* inside the layer tree, chosen by `layer_node_bl_idnames`.
Two functions define what a source may offer:

- `get_available_source_outputs(source, entity_type)` — the funnel that decides which of a source's
  enabled outputs a channel may bind to. It already special-cases `VCOL`, `BACKFACE`, `AO`.
- `refresh_source_tree_ios(source_tree, layer_type, source, prev_normal=False, entity=None,
  outer_tree=None)` — regenerates a nested source tree's interface: a `Vector` input when the
  source consumes one, optionally a `Normal` input when the entity's previous-normal switch is
  meaningful (`HEMI` / `EDGE_DETECT` / `AO`), every source input the flat path feeds from a `Start`
  socket, plus `<name>` and `<name> Alpha` outputs per available output. The Start-fed inputs are
  derived, not listed at each call site: `get_source_start_input_sockets` walks `source_start_inputs`
  (AO `Distance` ← `ao_distance`, EDGE_DETECT `Radius` ← `edge_detect_radius`, COLOR_ID `Color ID`
  ← `color_id`) and keeps only entries the source has, the entity exposes and the outer `Start`
  carries. `link_source_start_inputs` feeds the flat layer and mask sources from that same table,
  so the two paths can no longer drift: an input the nested tree declares is linked in the flat
  tree too. `CUSTOM` reads one rule instead of the table: a group input belongs to the contract when
  its name is a root channel name or `<channel> Alpha` (`get_custom_source_input_names`), intersected
  with the group's inputs and the outer `Start` outputs. `Normal` qualifies only because it is a
  root channel name (there it names the below-layers normal stream, not the previous-normal leg);
  a `<uv> UV` or any other non-channel `Start` socket keeps the user's default, and `Vector` stays
  with the mapping leg. Inputs outside the derived contract are pruned, so a source/type change
  cannot leave a dead socket and a second pass adds or removes nothing. Mask trees
  (`reconnect_mask_source_nodes`) and channel-override trees (`subtree.enable_channel_source_tree`)
  use the same function.
- `reconnect_nested_source_nodes(source_tree, source_node, layer_type, …)` — wires the inside of a
  generated nested tree: `Start[name] → source.inputs[name]` for every source input the nested
  interface declares (not only `Vector`), the source's outputs through
  divider-alpha/linear/flip-Y and the layer's modifier groups into `End[name]` /
  `End[name + ' Alpha']`. `reconnect_nested_group_inputs` feeds a nested layer/override source
  instance (`source_group`, `ch.source_group`) from the containing tree's `Start` by socket name,
  while the vector path feeds its `Vector`. Its `Normal` is the previous-normal leg only for
  `HEMI` / `EDGE_DETECT` / `AO`, where `reconnect_layer_nodes` feeds it from the bump output or
  Geometry and the forward skips it; for `CUSTOM` the name is the below-layers stream and is
  forwarded. A nested mask instance (`mask.group_node`) is fed by `reconnect_layer_nodes` too, not
  by `reconnect_nested_group_inputs`. Both are idempotent; a nested tree is never wired with
  cross-tree links.

`Alpha` is a reserved output name: an `Alpha` output feeds every channel's alpha, and its absence
means alpha is 1.0 (`reconnect_layer_nodes`).

## 5. Extension points

| Concept | Enum | Node factory | Instance creator |
|---|---|---|---|
| Layer type | `layer_type_items` + `layer_type_labels` + `layer_node_bl_idnames` | `layer_common.check_layer_source` | `add_new_layer`, `replace_layer_type` |
| Mask type | `mask_type_items` | `mask_common.add_new_mask` | `YNewLayerMask` |
| Modifier type | `modifier_type_items` | `modifier_common.check_modifier_nodes` | `YNewYPaintModifier` |
| Channel override | `channel_override_type_items` | `subtree.enable_channel_source_tree` | `YReplaceLayerChannelSource` |
| Bake target | — | `BakeTarget.py` | `YNewBakeTarget` |

Adding a layer type touches all of: the three enum/label maps, `check_layer_source`,
`replace_layer_type`'s cache logic, `is_mapping_possible`, `is_layer_using_vector`,
`has_layer_input_options`, `subtree.check_layer_source_tree`, `bake_common.is_join_objects_problematic`,
the `ui.py` panels and menus, and node arrangements.

## 6. Versioning and lifecycle

- `yp.version` gates migrations in `versioning.py::update_routine`, plus
  `update_node_tree_libs` for `~yPL` trees; both are `load_post` handlers. Anything that changes
  existing materials needs a block there. A purely additive type does not: `layer.custom_group`
  (T-7a) is additive, so an older file opens with the pointer `None` while its source node still
  points at the user group. `get_custom_layer_group` falls back to `source.node_tree`, so the layer
  keeps working unchanged; the pointer is filled the next time the group is chosen. The pointer and
  the source node's tree can still diverge: the pointer decides whether the layer is usable, the
  source tree decides what it renders, and every add-on path (`set_custom_layer_group`) writes both.
  An existing source node with no `node_tree` is therefore unusable — the FR-16 missing-group state
  and below-layers fall-through — even when `custom_group` names a valid tree. The pre-pointer
  `source.node_tree` fallback still applies when the pointer itself is `None`.
- `depsgraph_update_post` carries one continuous subscriber,
  `custom_node_common.custom_layer_update_handler`: it walks the node-tree datablocks, compares
  each `CUSTOM` layer's group interface signature and its group usability, and runs the idempotent
  repair when an interface changed. A signature change repairs the layer; a *usability flip*
  (usable → missing/emptied, or back) re-splices the whole yp, because only that pass can bypass
  the layer like a disabled one. Each flip rebuilds once: a group that stays missing is silent.
  These gates keep every other edit (default values, node moves, mute, non-custom layers) out of
  the repair path. Failures are reported through the layers panel, never the console, and retried
  after a bounded per-group delay. A `load_post` subscriber (`custom_sync_load_post`) clears the
  signature, usability, throttle and report caches so a reopened file gets a cold-start repair
  instead of inheriting pointers from the previous session. The `Decal.py` constraint sync and the
  `Root.py` paint-slot patch (skipped on 5.1+) remain narrow jobs. `bpy.msgbus` drives the
  node-slider UI cache
  (`ui.py::yp_load_ui_msgbus_subscription`) and object/mode/active-material change detection
  (`Root.py::yp_load_msgbus_subscription`).
- Tests are `unittest` modules under `tests/` that import `bpy`, so they run inside Blender via
  `tests/run_tests.py`.

## 7. Where 001 lands (built and accepted)

`docs/specs/001-custom-node-layer/` adds a `CUSTOM` layer type whose source is a `ShaderNodeGroup`
pointing at a user tree. The **group** reference is a `PointerProperty` on the layer
(`layer.custom_group`, ADR-0002) — the one deliberate divergence from the name-based references
described in ADR-0002, so a rename and a save/reopen keep it without a handler. Socket **binding**
stays name-based in both directions: outputs → `ch.socket_input_name`, inputs ← `Start[<channel>]`.
Built: the type itself, the compatible-output filter on
`get_available_source_outputs`, the socket-name binding, the channel input wiring, the live
re-sync handler above (signature-gated repair, per-group failure isolation, the FR-10 fallback
flag), and the group pointer with the FR-16 missing-group state (a missing or unusable group makes
the layer fall through exactly like a disabled one; the layer row shows it, the Replace Layer Type
picker relinks in one step, and a live deletion/emptying re-splices the yp on the next depsgraph
update). It lives in `custom_node_common.py` plus the handler rather than scattering logic, so the
rest of §3 is unchanged, which is the point.

T-10 adds the two write-side helpers that complete the layer type's UX without widening §3:
`create_starter_group` is the only place the add-on writes into a *user* node tree, and it does so
exactly once (FR-31/FR-32) — the tree is then never modified, so a channel added later reports the
FR-10 binding fallback instead of growing a socket. The starter group is a pass-through
`NodeGroupInput`/`NodeGroupOutput` pair, one named input/output pair per root channel plus a
`Vector` input and an `Alpha` output, so a fresh layer's channels follow whatever is below. `Alpha`
has no same-named input: it is fed by a constant `ShaderNodeValue` at 1.0, so a fresh layer is
opaque instead of forwarding a transparent below-layers stream, and no `Color Alpha` input is
declared. `Normal` is the other exception: a custom layer's `Normal` output is a tangent-space
normal map (the layer tree adds a `Normal Map` node), so the output is a constant neutral map
`(0.5, 0.5, 1.0)` rather than a pass-through of the world-space below-layers stream, which would be
transformed twice. The `Normal` input is still declared and fed (FR-6). Spec FR-31 was amended on
2026-10-30 (alpha) and 2026-10-31 (normal) to this shape; those corrections are T-13 and T-14 in
the spec's `tasks.md`. Existing starter groups are deliberately not migrated (FR-32).
`make_group_unique` is the explicit deep copy behind the layer panel's *Make Unique* (FR-8/FR-17):
it copies the referenced tree, repoints `layer.custom_group` and the source node through the same
`set_custom_layer_group` relink path (stale input links cleared, channel bindings preserved, yp re-spliced),
and strips `~yPL ` naming and ucupaint `yp` flags from the copy. The layers panel shows the group
name, *Make Unique*, and a picker that offers "generate starter" and "pick existing" in one menu.

A group that has no instance cannot be opened by a reliable Python API, so the layer's material
carries a dummy instance: `ensure_custom_group_dummy` (called on creation, Change Group, Make
Unique, paste into another material and conversion to CUSTOM) puts one unconnected
`ShaderNodeGroup` per referenced group inside a frame labelled
**"Custom Layers: edit here, do not connect"** in every
`mat.node_tree` returned by `get_materials_using_yp`. The instances are identified by the
`yp_custom_dummy` property plus their `node_tree`, are placed left/down of the ucupaint node and
cascaded, and never receive a link. The user Tabs into an instance and edits the same datablock
the layer's source points at, so edits propagate to the layer. The dummy sets no `node.label`, so
its header follows the group datablock name across a rename (a label written by an earlier
version is cleared). `prune_custom_group_dummies` (layer removal, Change Group, Make Unique,
converting away from CUSTOM, and a live group deletion or usability flip) drops an instance when
no CUSTOM layer references its group any more, and the frame when it is empty; removing the
ucupaint node prunes its material trees through `remove_custom_group_dummies_from_tree` before the
node (whose pointer finds those materials) goes away. An existing frame is never moved, and user
nodes are never removed. Files are not mutated on load: the nodes appear only on creation or
group-change paths. The previous *Edit Group* operator and its button were removed because they
reported success without changing the Shader Editor in real use; ADR-0005 records the choice and
its rejected alternatives.

Acceptance (T-11) passed §6 items 1–21 on Blender 5.2.3; item 22 (cross-version)
remains unverified, and within that pass **item 13's save/reopen sub-step and item 15's
Developer-Mode visibility were NOT RUN** — they are not covered by the dummy-instance unit tests,
which exercise the creation and prune paths inside one session. The interactive checklist items
(menu clicks, link inspection, Ctrl+Z, viewport review) still need a human pass. Since ADR-0006 the
supported floor is 4.2: the suite and the acceptance script also run on 4.2.9 and 4.5.9 LTS, so
item 22 now means "4.2 and the current 5.x". T-7–T-10 landed duplicate/paste/undo of the reference,
baking, parity with built-in sources, and the starter group / Make Unique / panel. The
dummy-instance UX above landed after that acceptance run and is covered by
`tests/test_custom_node.py::TestCustomDummyInstances`, not by the T-11 checklist. The parity
sweep (T-9) leaves §4 true by construction. P1b fixed the built-in nested pipeline:
`reconnect_nested_source_nodes` wires the nested tree and `reconnect_nested_group_inputs` feeds the
outer instance, so the source stays connected; `refresh_source_tree_ios` creates `Vector` and,
for `HEMI` / `EDGE_DETECT` / `AO`, a `Normal` input (masks likewise), and
`tests/test_nested_source.py` covers NOISE, IMAGE, channel-override and mask source trees with a
rendered before/after pixel plus the AO / baked HEMI / EDGE_DETECT previous-normal cases. P1c then
let `CUSTOM` nest too: its group inputs are declared on the nested interface by the same derived
rule and forwarded on both sides, with `Normal` treated as the below-layers stream for CUSTOM,
`Vector` kept on the mapping leg and a bare `Alpha` left unlinked; only a *baked* CUSTOM layer stays
un-nested. `tests/test_nested_source.py::TestNestedCustomSource` covers the forwarding, the
reserved names, a group swap plus Make Unique while nested, and a rendered CUSTOM-vs-NOISE parity.
`tests/test_custom_parity.py` covers spec §4.7 rows a–h against an otherwise identical NOISE layer,
with one documented exception: row f asserts the material-tree and yp-tree preview wiring (which
exists only while preview is on) plus a rendered CUSTOM-vs-NOISE comparison in normal,
layer-preview and channel-preview mode. NORMAL and CHANNEL each use a fresh single-layer yp per
layer type; LAYER preview also compares two layers in one yp via the active-layer switch (P1a).
Row e's smooth-bump case now nests CUSTOM, so its passthrough-input assertion exercises the nested
instance.
