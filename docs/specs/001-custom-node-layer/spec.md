# 001 — Custom node layer

Status: implemented through T-13 and the P1 fixes (preview layer switch, nested-source wiring, CUSTOM
nesting); 4.2+ floor since 2026-10-31; suite and acceptance run on 4.2.9 / 4.5.9 / 5.2.3, checklist
item 22 (cross-version file) still open — see `## Changes`
Issue: [ucupaint#90](https://github.com/ucupumar/ucupaint/issues/90)
Date: 2026-10-30

## 1. Problem

Ucupaint builds each layer from a fixed catalogue of source nodes (`IMAGE`, `NOISE`,
`VORONOI`, `HEMI`, … — see `layer_node_bl_idnames` in `common.py`). A user who wants a
channel value that no catalogue entry produces has to leave ucupaint, hand-wire nodes
outside the layer stack, and lose masks, blending, baking and the channel contract.

Issue #90 proposes letting a **user-authored node group** act as a layer's source:

- it must be a node group,
- it must have at least one output,
- a `Vector` input and an `Alpha` output are optional,
- its outputs can be assigned to layer channel inputs,
- shader/BSDF socket types are not supported.

This spec adds one more capability on top of the issue: the group's **inputs** receive the
channel streams arriving from the layers below, so a user can combine, remap or post-process
the existing stack instead of only adding to it.

## 2. Users

- **Technical artist / shader author**: writes a node group once (triplanar blend, procedural
  wear curves, custom colour logic) and drives roughness/metallic/colour from it, per layer,
  with masks and baking working as usual.
- **Add-on integrator**: ships a Blender library of node groups that ucupaint users drop in as
  layers, without patching ucupaint.
- **Maintainer**: needs the source abstraction to stay single, so the catalogue stays tenable.

## 3. User stories

- **US-1** As a shader author I pick one of my node groups as a new layer, and its outputs appear
  as selectable sources for each channel.
- **US-2** As a shader author I rename or add an output socket in my group and the layer follows
  without me hunting for a refresh button.
- **US-3** As a shader author I feed the roughness and metallic streams from below into my group,
  remix them, and send them back out.
- **US-4** As a shader author I bake my channels as usual and the custom layer is in the bake.
- **US-5** As a user I can save, reopen, duplicate and undo without the layer losing its group.

## 4. Requirements

Each requirement is verifiable by a second person using the add-on in Blender, or by a script in
`tests/`. "Verification" states the check, not the implementation.

### 4.1 Creating and targeting a custom layer

**FR-1** A new layer type `CUSTOM` ("Custom Node") exists in `layer_type_items`,
`layer_type_labels` and the Add Layer / Replace Layer Type menus. Creating one produces a layer
whose source node is a node group instance pointing at a user-authored `ShaderNodeTree`.
*Verification:* `bpy.ops.wm.y_new_layer(type='CUSTOM', group_name=<name>)` creates a layer with
`type == 'CUSTOM'`; its source node is a `ShaderNodeGroup` whose `node_tree` is the named tree;
the layer is listed in the ucupaint layer list and renders.

**FR-2** Candidate groups for the picker are enumerable by a pure function. Candidates exclude
ucupaint's own trees: names beginning `~yPL `; every generated `.yP ` tree (layer trees, nested
source trees, mask trees, modifier trees and the parallax iterate group); trees where
`yp.is_ypaint_layer_node` is set; trees with `yp.is_ypaint_node`; and non-`ShaderNodeTree`
datablocks. Trees with no compatible output socket are excluded. *(amended 2026-10-30 — see
[`## Changes`](#changes))*
*Verification:* helper returns exactly the expected set for a scene containing one suitable group,
one `~yPL` group, one layer tree, one `.yP Mask` or `.yP Modifiers` tree, and one group whose only
output is a `Shader`.

**FR-3** `wm.y_replace_layer_type(type='CUSTOM')` switches an existing layer to a custom source,
prompting for a group, and preserves the layer's masks, channel enables, per-channel blends
(`layer.channels[i].blend_type`), mask blend and modifiers. `wm.y_new_layer` and
`wm.y_replace_layer_type` accept a `group_name` string property so both are drivable from scripts.
*(verification wording corrected 2026-10-30: blends are per channel and per mask, not on the
layer — see [`## Changes`](#changes))*
*Verification:* an IMAGE layer with one mask converted to CUSTOM keeps mask count, channel enable
flags, every channel's `blend_type`, `mask.blend_type`, modifier count, and renders.

### 4.2 The socket contract

**FR-4 (outputs)** Every enabled output of the group whose socket type is one of
`NodeSocketColor`, `NodeSocketFloat`, `NodeSocketFloatFactor`, `NodeSocketVector`, `NodeSocketInt`
is offered as a channel source. Sockets of every other type (notably `NodeSocketShader`) are never
offered, in the UI or in `get_available_source_outputs`.
*Verification:* a group with outputs `Color` (Color), `Rough` (Float) and a BSDF `Shader` yields
exactly `['Color', 'Rough']` from the enumerator, and the channel-source menu shows those two.

**FR-5 (alpha)** An output named exactly `Alpha` supplies the alpha of every channel that binds to
the group. Without it, alpha is `1.0`, matching the existing convention in
`reconnect_layer_nodes`. The name `Alpha` is therefore reserved and documented as such.
*Verification:* with an `Alpha` output, the channel's alpha link comes from that socket; without
it, alpha comes from the one-value node.

**FR-6 (inputs)** After reconnecting, for each root channel named `X`, if the group has an input
socket named `X`, the layer's incoming (below-layers) channel stream is linked into it; likewise
for `X + ' Alpha'`. Inputs whose names match no channel and are not `Vector` are left unlinked so
the user's own defaults apply.
*Verification:* a group with inputs `Color`, `Color Alpha`, `Roughness`, `MyOwnThing` gets links on
the first three only, and the `Color` link originates from the tree's `Start` group-input socket,
not from the source itself.

**FR-7 (vector)** If the group declares an input named `Vector`, the layer is treated as vector
using: mapping/UV/texcoord nodes are created and wired exactly as for a texture layer, and the
`Vector` socket receives that output. If it does not, no mapping nodes are created for the layer.
*Verification:* group with `Vector` → `layer.mapping` node exists and the source's `Vector` input is
linked; group without `Vector` → no mapping node, no vector input link.

**FR-8 (one group, many layers)** Several layers may reference the same group; editing the group
affects all of them. A per-layer *Make Unique* action duplicates the tree and repoints only that
layer.
*Verification:* two layers on one group change together when a node inside the group changes;
after Make Unique exactly one of them follows the next edit.

### 4.3 Channel binding

**FR-9** Each enabled channel binds to one output through the existing
`ch.socket_input_name`, set from the existing channel-source menu. Default binding on layer
creation (and for channels added later) is the output whose name equals the root channel's name,
else the first compatible output in socket order.
*Verification:* a group with `Color` and `Roughness` outputs gives
`channels[Color].socket_input_name == 'Color'`, `channels[Roughness] == 'Roughness'`; a channel
with no same-named output binds to the first output; adding a root channel afterwards binds it
without touching the others.

**FR-10** When the bound socket disappears, the channel falls back to the first compatible output
and the channel row shows a warning (not a silent change).
*Verification:* rename the bound output; the channel still renders, `socket_input_name` is a
socket that exists, and the warning indicator is present until the binding is re-chosen.

### 4.4 Live re-sync

**FR-11** Adding, removing, renaming or retyping a socket in a referenced group re-establishes all
layer links without any manual refresh: by the next depsgraph update the tree is fully connected,
and in the UI the change is perceived as immediate.
*Verification:* script: create a custom layer, add an output, remove an output, rename an output,
then trigger one depsgraph update; assert every enabled channel's expected incoming link exists,
no exception is raised, and no stale links point at removed sockets.

**FR-12** Only interface *topology* changes re-wire. Editing a socket's `default_value`, a node's
location, or a node's mute state must not trigger a re-wire or a tree rebuild.
*Verification:* count reconnects (a counter in the sync entry point, or measure via a debug flag)
while dragging a socket default and moving a node: zero. Changing a socket name: one.

**FR-13** The live re-sync must not loop: a re-wire performed from within a depsgraph update does
not schedule another update that re-triggers the sync.
*Verification:* edit a socket name with the *Sync* debug flag on; the update count for the sync
entry point is 1, not unbounded, and Blender stays responsive (no console flood).

**FR-14** A manual *Refresh* operator exists as a fallback and as the tool for scripted repair. It
must be idempotent.
*Verification:* running Refresh twice on a healthy layer changes no links and reports nothing.

### 4.5 Integrity

**FR-15** The group reference survives: renaming the group, duplicating it, saving and reopening
the .blend, and undo/redo. No update handler may be required for the rename case.
*Verification:* rename, save, reopen, and assert the layer still points at the same data-block and
still renders; undo after a group swap restores the previous group and a connected tree.

**FR-16** Deleted or emptied group: if the referenced tree no longer exists, its `node_tree` is
`None`, or it has no compatible output, the layer keeps its place in the stack, renders a defined
fallback (channel falls through as if disabled), logs nothing to the console, and the UI marks the
layer as missing its group. The `custom_group` pointer decides usability, except that an existing
source node with no `node_tree` is unusable even while the pointer names a valid tree. A picker
action lets the user relink another group. *(clarified 2026-10-30 — see
[`## Changes`](#changes))*
*Verification:* set the source's `node_tree = None` while the pointer still names the group and
reconnect; no exception, no traceback, channel output equals the below-layers value, and the layer
row shows the missing-group state. Restoring the tree repairs the graph in one update.

**FR-17** Copy/paste of layers between materials and `Duplicate Layer` preserve the reference (no
accidental deep copy); Make Unique is the explicit deep copy.
*Verification:* paste a custom layer into another material's yp; both now reference the same group;
Make Unique separates them.

**FR-18** The tree created by any of the above contains no orphan nodes: no leftover
divider-alpha, flip-Y or linear nodes for a type that does not use them, no unused essential
nodes (existing `clean_essential_nodes` behaviour is the baseline).
*Verification:* node-type inventory of the layer tree for a fresh custom layer equals the expected
minimal set.

### 4.6 Baking

**FR-19** A channel whose stack includes a custom layer bakes the same value it renders. Baking to a
bake target (image or vertex colour) is supported for both `RGB`/`VECTOR` and `VALUE` target
channels, including the existing subchannel assignment UI.
*Verification:* custom layer bound to `Color` with a constant `(0.25, 0.5, 0.75)` output; bake the
`Color` channel into a 512² image; every pixel inside the UV island is within ±1/255 of that value.
Repeat with a `VALUE` channel reading a constant `0.3` float output.

**FR-20** Baking a stack is correct with the custom layer in the middle: values below and above
the layer, plus masks and blend modes, are respected.
*Verification:* custom layer with a 50 % mask over a solid colour layer: baked pixel ≈ blend of
the two constants, matching the equivalent NOISE-layer reference scene within ±2/255.

**FR-21** Merged (multi-object) bake conservatively disables itself when a custom layer is present,
because ucupaint cannot know whether the group depends on per-object data. The user is informed by
the existing console message channel.
*Verification:* two objects sharing the material, one custom layer → `is_join_objects_problematic`
returns True, merged bake is skipped, bake still completes per object.

**FR-22** A custom layer's own *Use Baked* substitution (replacing the live graph with a baked
image) is **not** silently enabled; if the layer is switched to baked mode the UI must state that
the custom graph is being bypassed. *(See open question Q1.)*
*Verification:* toggling `use_baked` on a custom layer shows the bypass notice; the rendered result
matches the baked image rather than the live graph.

### 4.7 Integration with existing per-layer features

For each row, the custom layer must behave like a texture-generator layer (`NOISE`), not like a
special case. Verification for every row: perform the action on a CUSTOM layer and on an otherwise
identical NOISE layer; the resulting links and rendered output must be equivalent.

| # | Feature | FR |
|---|---------|----|
| a | enable/disable layer, layer reordering, parenting under a Group layer | FR-23 |
| b | masks (layer mask, mask blend, transition bump, mask modifiers) | FR-24 |
| c | channel modifiers (invert, curve, math, colour ramp …) | FR-25 |
| d | channel override and swizzle | FR-26 |
| e | per-channel gamma/linear, `enable_smooth_bump`, `uv_neighbor` | FR-27 |
| f | layer preview mode and channel preview mode | FR-28 |
| g | channel add/remove/rename in the yp after the layer exists | FR-29 |
| h | `Background`-style behaviour is *not* implied: the layer blends over what is below | FR-30 |

**FR-27 note:** smooth bump nests the source into a generated sub-tree, and that sub-tree's
interface must reproduce every input the source consumes: for CUSTOM the entity's channel inputs
plus `<channel> Alpha`, `Vector` only when the source declares one, a previous-normal input for
`HEMI`/`EDGE_DETECT`/`AO`, and the Start-tunnelled source inputs (`AO Distance`,
`EDGE_DETECT Radius`, `COLOR_ID Color ID`). Each such input must be fed from the nested interface
and forwarded to the inner source node, so nesting neither invents a mapping leg nor leaves a
stream at its default; an input the flat source leaves at its default must stay at its default
when nested. After toggling `enable_smooth_bump` the layer must still render identically.
*Verification:* toggle smooth bump on a custom layer with one passthrough input and assert the
render is unchanged and the input link still exists.

### 4.8 Starter groups (added 2026-10-30, see `## Changes`)

**FR-31** *New Custom Node Layer* offers two paths: pick an existing group, or generate a starter
group. A starter group is a new `ShaderNodeTree` containing one input and one output socket per
current root channel (names exactly the channel names, plus a `Vector` input), wired pass-through
(each channel output fed from the same-named input), so a fresh custom layer initially shows what
is below. `Alpha` and `Normal` are the exceptions:

- `Alpha` is fed from a constant value node at **1.0**, never from an input, so a fresh layer is
  opaque and its output actually contributes.
- `Normal` is fed from a constant neutral tangent-space normal map `(0.5, 0.5, 1.0)`, never from
  the `Normal` input. A custom layer's `Normal` output is interpreted as a tangent-space normal map
  (the layer tree puts it through a `Normal Map` node), so passing the below-layers normal stream
  through would transform it twice and warp the shading. The `Normal` input is still declared and
  fed with the below-layers stream (FR-6), so the user can build on it.

The group declares **no** `Color Alpha` input. *(amended 2026-10-30 and 2026-10-31 — see
[`## Changes`](#changes). Existing starter groups are not migrated: FR-32 makes the tree user-owned
after creation.)*
*Verification:* `wm.y_new_layer(type='CUSTOM', create_new_group=True, group_name='X')` produces a
tree whose inputs are exactly one per `yp.channels` entry plus `Vector`, whose outputs are exactly
one per channel plus `Alpha`, where each channel output has one link from its same-named input
except `Normal` (one link from a constant vector `(0.5, 0.5, 1.0)`) and `Alpha` (one link from a
value node whose value is 1.0); every channel binds to the same-named output, and a fresh layer
renders its colour at alpha 1.0 (film-transparent render, `A` channel) without changing the
shading normals.

**FR-32** A starter group is written exactly once, at creation. Afterwards it is a user tree:
ucupaint never adds, removes or renames sockets in it, on channel add/remove/rename or on any sync.
*Verification:* add and remove a root channel after the starter group exists; the group's socket
list is byte-identical to before (compare names and types in order), and the affected channels
report the binding fallback from FR-10 instead of the group being modified.

### 4.9 Non-functional

**NFR-1** Supported on **Blender 4.2 LTS and every later version the add-on supports** — the floor
is `bl_info["blender"] = (4, 2, 0)`, matching `blender_version_min = "4.2.0"` in
`blender_manifest.toml`. Pre-4.2 Blender is not supported by this fork. The interface API split
(`tree.inputs/outputs` before 4.0 vs `tree.interface` after) predates the floor: the pre-4.0 helpers
in `input_outputs.py` stay in the code and interface work must still go through those helpers, never
inline, but no supported build takes that branch.
*(amended 2026-10-31 — floor changed from `(2, 80, 0)` with 2.7x guards to 4.2+; see
[`## Changes`](#changes) and [ADR-0006](../../decisions/0006-drop-pre-4-2-support.md).)*

**NFR-2** Reconnect cost for a custom layer must stay within 1.5× of an equivalent NOISE layer, and
the live re-sync signature check must be cheap enough to run on every depsgraph update (target:
< 0.2 ms for a yp with 5 custom layers, 20 sockets each).

**NFR-3** No new console noise in the normal case; errors are reported through the add-on's existing
report path, not `print`.

**NFR-4** Every type-set decision this feature touches is recorded, so the next reviewer can see
*why* CUSTOM is in or out of each of the ~71 `layer.type in {…}` sites.

### 4.10 Editable group instances (added 2026-10-30, see [`## Changes`](#changes))

**FR-33** After any layer creation, group change, Make Unique, paste into another material or
conversion to `CUSTOM`, every material tree using a yp with at least one `CUSTOM` layer contains one
editable instance of each group those layers reference. The instance is an unconnected
`ShaderNodeGroup` whose `node_tree` is the same datablock as the layer's source, marked with the
`yp_custom_dummy` property, and placed inside a single frame labelled exactly
`Custom Layers: edit here, do not connect`. Two layers on one group share one instance; two groups
get two. The instances are created on layer creation, group change, Make Unique, paste into another
material and conversion to `CUSTOM`; they are **not** added merely by opening a file. They are
removed when no `CUSTOM` layer references their group any more (layer removal, group change,
Make Unique on the last reference, conversion away from `CUSTOM`, deletion of the group datablock,
removal of the ucupaint node), and the frame is removed only when no node remains parented to it.
A dummy's node label is empty, so its header follows the group datablock name across a rename.
Editing through `dummy.node_tree` is editing the layer's group: the render changes. User-authored
nodes and links are never touched. *(Added after the original approval; ADR-0005 records why.)*
*Verification:* create a custom layer and assert one node with `yp_custom_dummy` sits in the
labelled frame with zero links and `node_tree is layer.custom_group`; edit a node in
`dummy.node_tree` and assert the centre pixel changes; rename the group and assert the dummy has
no `label` and points at the renamed tree; remove the layer and assert the dummy and empty frame
are gone. Repeat with two layers on one group (one dummy) and two groups (two dummies). Convert to
`NOISE`/`COLOR`, change group, Make Unique, paste into a second material, delete the group
datablock and remove the ucupaint node, asserting the expected dummy/frame count each time. Remove
the dummy nodes, save and reopen, and assert no dummy is added on load.

## 5. Non-goals

- **Custom masks.** `mask.socket_input_name` is the same mechanism and this is the natural phase 2,
  but it is out of scope here.
- **Custom channel overrides.** `ch.override_type` gets no custom entry.
- **Authoring inside ucupaint.** The user edits the group in Blender's node editor. Ucupaint only
  creates a starter group and reads its sockets; it never edits a user group's contents.
- **Shader/BSDF sockets**, per the issue. No surface or volume semantics.
- **Arbitrary property tunnels.** Exposing ucupaint layer properties (colour, blur, scale …) as
  inputs of the user's group is not included; only channel streams and `Vector`.
- **Automatic translation of a custom group into bakeable "pure" nodes**, or validation that the
  group is bake-safe. Baking is emission-render based; a group that depends on per-object or
  per-sample data bakes to whatever it evaluates to, and that is the user's responsibility.
- **Migration of existing materials.** No existing layer type changes; `CUSTOM` is additive, so no
  `versioning.py` block is required beyond registering the new enum value.
- **Presets / group library management** (browsing, versioning or shipping groups).

## 6. Acceptance checklist

Manual, in a scratch .blend, one reviewer who did not write the code. Items are numbered so
[`acceptance-5.2.3.md`](acceptance-5.2.3.md) and the task list can cite them:

1. [ ] Add Layer → Custom Node offers a group picker; internal `~yPL`, layer and other `.yP `
      generated trees are absent. *(FR-2)*
2. [ ] The same menu can generate a starter group; it renders as "below layers", and adding a root
      channel afterwards leaves the group's sockets untouched. *(FR-31/FR-32)*
3. [ ] A fresh starter group is opaque by default: it has no alpha input and its `Alpha` output is
      a constant 1.0, so the layer actually contributes when its colour is changed. *(FR-31 as
      amended)*
4. [ ] A layer made from a group with `Color` + `Roughness` outputs renders, and each channel binds
      to the same-named output by default.
5. [ ] Channel source menu lists the group's outputs and nothing shader-typed.
6. [ ] Rename `Roughness` → `Rough` inside the group: the layer re-wires without any refresh, and
      the channel shows the fallback warning until re-bound.
7. [ ] Delete the bound output: falls back to the first output, renders, no traceback.
8. [ ] Group with `Vector` input gets mapping controls; group without one shows no mapping controls.
9. [ ] Group with `Color` + `Color Alpha` + `Roughness` inputs receives the below-layers streams;
      clicking through the node editor shows those links.
10. [ ] Two layers on one group follow one edit; Make Unique separates them and keeps each channel's
      explicit binding when the copied group still has that output. *(FR-8)*
11. [ ] Replace Layer Type → Custom Node on an already-custom layer re-picks the group instead of
      silently cancelling. *(FR-3)*
12. [ ] Creating a custom layer puts an unconnected instance of its group in the frame
      `Custom Layers: edit here, do not connect`; Tab into it, edit a node, and the layer's render
      changes. *(FR-33)*
13. [ ] Two layers on one group share one dummy; Change Group, Make Unique, paste into another
      material, conversion away from CUSTOM and layer removal add/prune dummies and the frame
      correctly; removing the dummy nodes and reopening the file does not add them back. *(FR-33)*
14. [ ] Two groups in one yp, one made unusable: the healthy group still re-syncs, the broken one
      reports in the layers panel and retries without a per-frame storm. *(FR-11/FR-13)*
15. [ ] The manual Refresh operator is visible only with Developer Mode on, and reports nothing on a
      healthy tree. *(FR-14)*
16. [ ] Bake a constant `(0.25, 0.5, 0.75)` custom colour channel to a bake target; pixels match.
17. [ ] Bake a `VALUE` channel from a float output; pixels match.
18. [ ] Two objects sharing the material: merged bake is skipped with the console notice, bake works.
19. [ ] Save, reopen: layer intact. Undo after switching groups: previous graph back and connected.
20. [ ] Set the group's node tree to None: layer stays, no console traceback, UI shows missing group.
21. [ ] Toggle smooth bump, preview modes, masks, modifiers on the custom layer: no visual change
      versus before toggling.
22. [ ] Blender 4.2 (oldest supported) and the current 5.x both open a saved file with a custom
      layer. *(amended 2026-10-31: was "2.80 (or the oldest supported target) and 4.x", per
      ADR-0006; a requirement, not yet a recorded result.)*

## 7. Open questions

*All four resolved on 2026-10-30 — see `## Changes`.*

- **Q1 — *Use Baked* on a custom layer.** FR-22 assumes the toggle still works but warns that the
  graph is bypassed. Alternative: hide `use_baked` entirely for CUSTOM. Which?
  *(resolved: option A, FR-22 as written)*
- **Q2 — Merged-bake conservatism.** FR-21 disables merged bake for any custom layer. Alternative:
  allow it when the group contains no `Texture Coordinate`/`Object Info`/geometry nodes (a static
  whitelist), which is more useful but can silently bake wrong. Confirm conservative default.
  *(resolved: FR-21 as written)*
- **Q3 — Starter group.** Should *New Custom Node Layer* be able to generate a group whose sockets
  are pre-named after the material's channels? Recommended yes, with "pick existing" as the other
  half of the same menu.
  *(resolved: yes — promoted to FR-31/FR-32)*
- **Q4 — Feature gate.** Behind the existing developer/preference flag for one release, or live in
  the Add Layer menu immediately?
  *(resolved: visible immediately, no preference gate — this overrides the stated default)*

## 8. Risks

- **R1 — The ~71 hard-coded type sets.** `layer.type in {…}` / `not in {…}` appear across 14 files
  (`common.py`, `subtree.py`, `node_connections.py`, `ui.py`, `Modifier.py`, `bake_common.py`,
  `input_outputs.py`, `channel_common.py`, `layer_common.py`, `Root.py`,
  `ListItem.py`, `versioning.py`, `modifier_common.py`, `Layer.py`). Five further occurrences are
  commented out.

  Each is a silent-failure site:
  wrong membership shows up as a miswired layer, not a crash.
- **R2 — Live re-sync loop.** Reconnecting inside a depsgraph handler can re-trigger updates. FR-13
  exists because this is the most likely way the feature ships stable in a test and hangs in use.
- **R3 — Socket-name coupling.** Bindings and input matching are name-based by design. Renames are
  handled (FR-10/FR-11) but the model must never silently do something surprising.
- **R4 — Nested source sub-tree.** A source nested for smooth bump or UV neighbour renders from a
  generated tree, and that tree's interface must carry the source's whole input contract: channel
  inputs plus `<channel> Alpha` for CUSTOM, `Vector` only when declared, the previous-normal leg for
  `HEMI`/`EDGE_DETECT`/`AO`, and the Start-tunnelled inputs (`AO Distance`, `EDGE_DETECT Radius`,
  `COLOR_ID Color ID`). A contract derived from outputs alone drops all of them, and an input
  declared on one path but not the other changes the render silently. FR-27.
- **R5 — Bake assumptions.** `bake_common.py:156` and the merged-bake check encode "which layer
  types are safe"; CUSTOM lands in a policy nobody has reasoned about before.

## Changes

### 2026-10-30 — approved; Q1–Q4 answered; starter groups added

Spec approved as written. The four open questions were answered, and one of them overrides the
default recommended in §7:

- **Q1** — *Use Baked* on a custom layer keeps working and warns that the live graph is bypassed.
  FR-22 stands as written.
- **Q2** — Merged bake is conservatively disabled when a custom layer exists. FR-21 stands as
  written. The whitelist alternative is recorded and rejected in `ADR-0004`.
- **Q3** — Starter groups are in scope. This adds **FR-31** and **FR-32** (§4.8) and two lines to
  the acceptance checklist. FR-32 exists because FR-31 is the only place ucupaint writes into a
  user node tree, and it must stay that way.
- **Q4** — **Overrides the stated default:** the feature is visible in the Add Layer and Replace
  Layer Type menus immediately, with no preference or developer-mode gate. No FR changes; FR-1 was
  already written without a gate.

Not changed by these answers: non-goals, the socket contract, live re-sync requirements, and the
bake verification tolerances.

### 2026-10-31 — starter group normal is a neutral map (FR-31, amended)

As shipped, the starter group fed its `Normal` output from the same-named input. A custom layer's
`Normal` output is a tangent-space normal map — `subtree.py` creates a `ShaderNodeNormalMap` for a
`CUSTOM` normal channel, like `NOISE` — so that pass-through fed the below-layers *world-space*
normal stream into the `Normal Map` node and transformed it twice. A fresh, otherwise empty custom
layer therefore warped the shading; setting the normal blend to 0 removed it.

Amended at the user's report: the starter group's `Normal` output is now fed from a constant
neutral tangent-space normal map `(0.5, 0.5, 1.0)`, which is the identity for a normal map. The
`Normal` input is still declared and receives the below-layers stream (FR-6), so a user can wire
it deliberately (adding their own `Normal Map` node where needed). Existing starter groups are not
migrated for the same FR-32 reason as the alpha amendment: the tree is user-owned after creation,
so a user edits an old starter by hand.

### 2026-10-30 — implementation record (branch `customnodes`)

Built through T-11 and accepted on Blender 5.2.3 LTS; the cross-version line of §6 is still **NOT
RUN**. This entry records observable behaviour that differs from §1–§4 as approved. Amended
requirement text is also marked in place with a dated note.

**Added — editable group instances (FR-33, §4.10).** Creating a `CUSTOM` layer, changing its group,
making the group unique, pasting a custom layer into another material, or converting a layer to
`CUSTOM` adds one unconnected `ShaderNodeGroup` per referenced group to every material tree that
uses the yp, inside the frame labelled exactly `Custom Layers: edit here, do not connect`. Two
layers on one group share one instance; two groups get two. The node carries the `yp_custom_dummy`
property, has no links, and has no `label`, so its header follows the group datablock name. Its
`node_tree` is the same datablock as the layer's source: Tab into the instance, edit a node, and
the layer's render changes. Instances (and the frame when empty) are pruned on layer removal, group
change, Make Unique, conversion away from `CUSTOM`, deletion of the group datablock and removal of
the ucupaint node. They are **not** added by opening a file. User nodes and links are never
modified. Rationale and rejected alternatives: [`ADR-0005`](../../decisions/0005-edit-custom-groups-through-dummy-instances.md).

**Starter group and alpha (FR-31, amended).** As shipped, the starter group adds an output named
`Alpha` beside the approved per-channel outputs and feeds it from the `Color Alpha` input. On a
fresh layer that alpha stream has no connected value, so its constant is **0**: a starter layer
renders as the layers below but contributes no alpha of its own, and editing its colour output can
appear to do nothing. Amended on 2026-10-30, at the user's request: the group declares no
`Color Alpha` input, and the `Alpha` output is fed from a constant value node at **1.0**, so a
fresh layer is opaque. FR-6's rule that a *user* group's `Color Alpha` input receives the
below-layers stream is unaffected; it simply no longer applies to starter groups. Existing starter
groups are not migrated, because FR-32 makes the tree user-owned after its one-time creation — the
add-on may not add or remove its sockets, so a user edits an old starter by hand. Implemented in
`c0be3b3` as [`tasks.md`](tasks.md) T-13 and reviewer-verified in `82ea52b`: §6 item 3 now passes
on this branch.

**Clarifications from implementation and review**

- **FR-2** — the picker also excludes every generated `.yP ` tree: layer and nested source trees,
  `.yP Mask` trees, `.yP Modifiers` trees and the parallax iterate group. Only `ShaderNodeTree`
  datablocks are candidates. Without these exclusions ucupaint's own trees appeared in the list.
- **FR-3** — the verification text wrongly said `layer.blend_type`; blends are per channel
  (`layer.channels[i].blend_type`) and per mask (`mask.blend_type`). The requirement itself is
  unchanged.
- **FR-8** — Make Unique preserves each channel's explicit `socket_input_name` and
  `custom_fallback_binding` while the copied interface still offers that output; a missing name
  falls back by FR-9/FR-10 and warns. Without this a channel explicitly bound to `Blue` rendered
  `Color` after Make Unique.
- **FR-10** — the automatic re-point sets a stored per-channel flag (`custom_fallback_binding`).
  The channel row warns until the user explicitly re-picks the binding; an override clears the
  flag. Disabled and overridden channels do not warn, because they feed nothing.
- **FR-11/FR-13** — sync failures are isolated per group: one broken group no longer blocks a
  healthy group in the same yp. A failed group is retried after a bounded 0.5 s delay (or
  immediately if its interface changes), its channel bindings are rolled back, and its error is
  shown in the layers panel rather than the console.
- **FR-14** — the manual *Refresh Custom Node Layers* operator (`wm.y_custom_sync`) exists but is
  visible only while Developer Mode is on. It visits every group, ignores the retry throttle, and
  reports nothing on a healthy tree.
- **FR-16** — a group with no compatible output is treated exactly like a deleted group. The
  `custom_group` pointer is the source of truth, except that an existing source node whose
  `node_tree` is `None` makes the layer unusable even while the pointer names a valid tree.
  Relinking through *Change Group* re-splices the yp in the same operator step, so one undo restores
  the previous group and a connected tree.
- **Replace Layer Type** — choosing `CUSTOM` on an already-custom layer re-picks the group instead
  of returning a silent `CANCELLED`.

**Removed — Edit Group.** An `wm.y_edit_custom_group` operator and panel button briefly existed.
They were removed because they reported success without changing the Shader Editor in real use.
The shipped panel row is `Node Group: <name> | Make Unique | Change Group`; it has no Edit Group
action. The dummy instance is the edit affordance.

**Inferred, then confirmed on 2026-10-30.** The branch does not record why dummies are omitted on
load; the documented rule is “opening a file does not mutate it”. The frame location and exact
label are deliberate but their rejected variants are not in the commit bodies; they are recorded in
ADR-0005 and marked there as inferred.

**Remaining gaps** (not acceptance passes): the legacy/4.x build line (§6 item 22) and interactive
Ctrl+Z (undo was exercised with `bpy.ops.ed.undo()` in a real window). The former P1s
(built-in smooth-bump/UV-neighbour nesting, `preview_mode` with two layers) are fixed in
`5bf214b`/`da03772`-`86ed394` and the starter-group alpha in `c0be3b3`; the
`wm.y_replace_layer_type` typo fall-through is still an open follow-up in [`tasks.md`](tasks.md).

### 2026-10-31 — supported floor raised to Blender 4.2 LTS

The user decided to drop pre-4.x support for this fork. Recorded as
[ADR-0006](../../decisions/0006-drop-pre-4-2-support.md); this entry amends two approved lines:

- **NFR-1** (§4.9) — the floor is `bl_info["blender"] = (4, 2, 0)`, matching the manifest's
  `blender_version_min = "4.2.0"`, instead of `(2, 80, 0)` with 2.7x guards. Pre-4.2 Blender is
  unsupported here. The pre-4.0 `input_outputs.py` helpers stay and interface work still goes
  through them; no supported build takes that branch.
- **§6 item 22** — now "Blender 4.2 (oldest supported) and the current 5.x both open a saved file
  with a custom layer", instead of 2.80 + 4.x. It remains an **unchecked requirement**; the rest of
  §6 is unchanged, and no run has yet opened a 5.x-saved file in 4.2 or the reverse.

Verification added by this decision (builds from `/tmp/opencode/blender-builds`, not in the repo):
4.2.9 LTS and 4.5.9 LTS each ran the headless suite (`Ran 159 tests … OK (skipped=4)`, exit 0), the
acceptance script (15/15 PASS) and the UI/undo suite through `./tests/run_ui.sh` (`Ran 159 tests …
OK`, exit 0); the 5.2.3 LTS reference build stays green. One 4.2/4.5 difference was found in a test
only — `NodeTreeInterface.new_socket()` rejects `NodeSocketMenu` before 5.0, so
`TestCustomSocketFilter` probes the capability (`6ce4e43`). The "legacy/4.x build line" gap noted in
the 2026-10-30 entry above is therefore narrowed to its cross-build half; item 22 stays unticked.

This narrows the 2026-10-30 entry's remaining-gap note; it does not change any requirement's
behaviour on 4.2+. The metadata half landed in `1d2c16c` (`bl_info["blender"] = (4, 2, 0)`, the
`blender_279` release-workflow steps removed); the cleanup half — all ~771 `is_bl_newer_than`
guards folded to the branch a 4.2+ build takes, the pre-4.0 `tree.inputs`/`tree.outputs` branches
deleted, the updater's `blender_279` branch removed — landed with this entry. Guards that still
matter inside the supported range (4.3, 4.5, 5.x) stay. `lib_281.blend` / `lib_282.blend` stay too:
they are not legacy, they hold the groups every supported build loads. Both walks were re-verified
on 4.2.9, 4.5.9 and 5.2.3. Note that only the extension manifest refuses a pre-4.2 Blender;
`bl_info` is advisory, so a hand-installed legacy zip on 3.x is unsupported rather than blocked
(ADR-0006).
