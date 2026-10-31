# Tasks — 001 Custom node layer

Spec: [`spec.md`](spec.md) · Plan: [`plan.md`](plan.md) · System map: [`../../architecture.md`](../../architecture.md)

One task = one commit. IDs match the plan's §8 sequencing (sub-tasks added where a step is too big
for one reviewable diff: `T-3a`, `T-3b`, …).

**Standing rules for every task**

- Never open a PR or push to `upstream`. Local commits only (see `AGENTS.md`).
- No version bump; `bl_info` and `blender_manifest.toml` are untouched.
- The add-on must load and the existing tests must pass at the end of the task.
- New behaviour gets a test in `tests/test_custom_node.py` (created in T-4) unless the task says
  otherwise. Tests need `bpy`, so they run inside Blender (T-2 records the command).
- Touching a component boundary or an invariant means editing `docs/architecture.md` in the same
  commit.
- Every `layer.type in {…}` decision gets a one-line reason at the site (NFR-4).
- Commit subject: `custom node: <what> (T-x, FR-n)`. Body: what was verified and how.

**Dependency order**

```
T-1 ─ T-2 ─┬─ T-3a ─ T-3b ─┐
           └─ T-4 ─────────┼─ T-5 ─ T-6a ─ T-6b ─┐
                           ├─ T-7a ─ T-7b ────────┤
                           ├─ T-8 ────────────────┤
                           └─ T-10 ───────────────┴─ T-9 ─ T-11 ─ T-12 ─ T-13
```

`T-9` is deliberately late: it is the parity sweep that finds wrong type-set decisions, and it can
only be checked once everything else exists. `T-12` and `T-13` are post-acceptance additions, not
part of the original sequence.

---

## T-1 — Verify the system map against the source

**FR:** — (enables NFR-4) · **Depends on:** nothing

`docs/architecture.md` was written from a reading of the code before any change. Correct it before
it becomes the reference the rest of the work is judged against.

- Open every function and file it names and check each claim: the five tree kinds, `io_suffix`
  vocabulary, the two reconnect passes, `get_available_source_outputs`, `refresh_source_tree_ios`,
  the `Alpha` convention, `lib.blend` lifecycle, `versioning.py` handlers.
- Recount the `layer.type in {…}` sites (the doc says ~76 across 15 files) and fix the number and
  the file list if wrong.
- Fix anything vague or wrong. Do not add speculation; §7 is already marked as intent.

**Done when:** every statement in §1–§6 can be pointed at by file and function, the counts are
exact, and the commit body lists what was corrected.

---

## T-2 — Establish and record the test invocation

**FR:** — (enables every verification below) · **Depends on:** T-1

- Find an invocation that runs `tests/test_quicksetup.py` headlessly. The tests assume a scene
  with a material named `Material` and call `bpy.ops.wm.*`; record those assumptions.
- Verify on Blender 4.2 LTS (the floor, ADR-0006) and on the current 5.x; do not spend time on
  pre-4.2 builds. Record both versions in the commit body.
- Write the exact commands into `AGENTS.md` under **Running**, and the scene assumptions into
  `tests/` (a short `tests/README.md` is fine).

**Done when:** the recorded command runs the suite and its output is pasted in the commit body for
both verified builds.

---

## T-3a — Register the `CUSTOM` type

**FR:** FR-1 (partial) · **Depends on:** T-2

- `common.py`: add `('CUSTOM', 'Custom Node', '')` to `layer_type_items`; `layer_type_labels`;
  `layer_node_bl_idnames['CUSTOM'] = 'ShaderNodeGroup'`.
- `layer_common.check_layer_source()`: minimal branch that creates the group node and assigns
  `layer.custom_group` if set (the reference property arrives in T-7a; for now accept a group name
  via the operator's `group_name`).
- `Layer.py`: `YNewLayer` / `YReplaceLayerType` gain `group_name` so both are scriptable.

**Verify:** add-on loads; Add Layer menu shows *Custom Node*; replace-type lists it.

**Done when:** `bpy.ops.wm.y_new_layer(type='CUSTOM', group_name='G')` creates a layer with
`type == 'CUSTOM'`, a `ShaderNodeGroup` source whose `node_tree` is `G`, and the layer renders
(black/miswired is acceptable here — T-4 makes it correct). Note in the commit body that the
feature is visibly incomplete at this point.

---

## T-3b — Group candidate enumeration and picker

**FR:** FR-2, FR-3, FR-1 · **Depends on:** T-3a

- New module `custom_node_common.py`; register it in `__init__.py` (import list, reload list,
  `register()`).
- `get_custom_group_candidates()`: excludes `~yPL ` trees, `yp.is_ypaint_layer_node` trees,
  `yp.is_ypaint_node` trees, and trees with no compatible output (compatibility stub lands here,
  completed in T-4).
- `ui.py`: picker (menu or dialog) used by Add Layer and Replace Layer Type, showing the group name;
  empty-state message when there are no candidates.

**Verify:** scripted FR-2 scenario — one suitable group, one `~yPL` group, one layer tree, one
group whose only output is a `Shader` — returns exactly the suitable one. Manual: menus show only
valid groups.

**Done when:** FR-2's verification passes and `wm.y_replace_layer_type(type='CUSTOM')` on an IMAGE
layer with a mask keeps the mask count, channel enables and blend types (FR-3).

---

## T-4 — Source creation, socket filter, default binding

**FR:** FR-4, FR-5, FR-9, FR-30, FR-1 (complete) · **Depends on:** T-3a

- `common.get_available_source_outputs()`: `CUSTOM` branch filtering by socket type
  (`NodeSocketColor`, `NodeSocketFloat`, `NodeSocketFloatFactor`, `NodeSocketVector`,
  `NodeSocketInt`); shader sockets never returned. Existing branches untouched.
- `custom_node_common.get_custom_layer_warning()` + binding validity derived on demand — no new
  stored state.
- Default binding: same-named output first, else first compatible output, applied on layer creation
  and for channels added later (FR-9).
- `layer_common.replace_layer_type()`: `CUSTOM` never uses the per-type source cache (reason at the
  site).
- Create `tests/test_custom_node.py` with helpers for building a scratch yp + user group.

**Verify:** FR-4 enumeration with a shader output present; FR-5 with and without an `Alpha` output;
FR-9 for `Color`/`Roughness` and for a channel added afterwards; the channel-source menu matches
`get_available_source_outputs`; the layer blends over the layer below (FR-30).

**Done when:** those tests pass, and a hand-built group producing two named outputs renders
correctly in the viewport and in a render.

---

## T-5 — Input wiring

**FR:** FR-6, FR-7, FR-18 · **Depends on:** T-4

- `node_connections.reconnect_custom_source_inputs()` called from `reconnect_layer_nodes` right
  after the existing `Vector` wiring: link `Start[X]` → `source.inputs[X]` and
  `Start[X + ' Alpha']` → `source.inputs[X + ' Alpha']` when present; leave other inputs alone.
- `common.is_mapping_possible(entity_type, entity=None)` and `is_layer_using_vector()`: `CUSTOM`
  uses the vector path **only if** the group declares a `Vector` input. Audit call sites of the new
  signature.
- Skip cleanly when `node_tree` is `None` or a socket vanished mid-reconnect.

**Verify:** FR-6 link assertions including the unmatched `MyOwnThing` input staying unlinked; FR-7
with and without `Vector` (mapping node present/absent, no dead vector nodes); FR-18 node inventory
of a fresh custom layer.

**Done when:** those tests pass and toggling the group's `Vector` input off and on (via T-6a's
manual refresh) adds and removes the mapping node without leftovers.

---

## T-6a — Interface signature and manual refresh

**FR:** FR-14 · **Depends on:** T-4, T-5

- `custom_node_common.get_custom_interface_signature(group)`: ordered
  `(in_out, name, socket_type, enabled)` tuples, built through `input_outputs.py` helpers so it
  works both before 4.0 and after (NFR-1). `None`-safe.
- `sync_custom_layers(yp)` and a `wm.y_custom_sync` operator behind a debug flag.
- `Make Unique` is **not** here (T-10).

**Verify:** FR-14 idempotency (running twice changes no link); signature changes on add / remove /
rename / retype and not on `default_value` edits.

**Done when:** the operator repairs a deliberately mis-wired layer on both available builds.

---

## T-6b — Live re-sync handler, binding warning

**FR:** FR-10, FR-11, FR-12, FR-13, NFR-2 · **Depends on:** T-6a

- `@persistent` `depsgraph_update_post` handler registered in `__init__.py`: compare signatures
  only, and only for yps that contain a `CUSTOM` layer; on difference run `sync_custom_layers`,
  updating the cache **before** rewiring.
- Guard with `yp.halt_update` / `yp.halt_reconnect`; catch and report exceptions once per group per
  session, leaving the cache stale so the next update retries.
- `ui.py`: channel-row warning when the bound socket is gone (FR-10); layer-row warning for a
  missing group (shared with T-7a).

**Verify:** FR-11 (add/remove/rename, one depsgraph update, links correct, no exception);
FR-12 (zero re-wires while dragging a socket default and moving nodes); FR-13 (exactly one sync for
one rename, no console flood); NFR-2 timing printed and recorded (target < 0.2 ms for 5 layers ×
20 sockets).

**Done when:** all four pass and the timing is in the commit body. If the handler loops, stop and
fix it here — do not proceed to T-7 with a known loop.

---

## T-7a — Group reference and missing-group fallback

**FR:** FR-15, FR-16 · **Depends on:** T-4

- `Layer.py` `YLayer` (line ~6022, near the source props): `custom_group :
  PointerProperty(type=bpy.types.NodeTree)` (ADR-0002). Remove the `group_name` stopgap from T-3a.
- Missing group (`None`, deleted, or no compatible outputs): source node exists with no tree,
  channel falls through as if the layer were disabled, layer row shows the state, relink action
  available, no `print`, no traceback.
- Rename the group; save and reopen.

**Verify:** FR-15 (rename then save/reopen keeps the reference; no update handler involved) and
FR-16 (set `node_tree = None`, reconnect: no exception, output equals the below-layers value, UI
state shown).

**Done when:** both tests pass and the ADR-0002 divergence is noted in `docs/architecture.md` if the
map claims otherwise.

---

## T-7b — Duplicate, paste, undo

**FR:** FR-17, FR-15 · **Depends on:** T-7a

- Duplicate Layer and copy/paste between materials keep the reference (no deep copy); document that
  Make Unique is the explicit copy (implemented in T-10).
- Undo/redo of: create layer, change group, change binding, group swap.

**Verify:** FR-17 across materials; undo after a group swap restores the previous group **and** a
connected tree (assert every enabled channel's expected incoming link exists, or legitimately none).

**Done when:** the tests pass and no half-applied state is reachable by undoing each of the four
operations.

---

## T-8 — Baking

**FR:** FR-19, FR-20, FR-21, FR-22 · **Depends on:** T-4 (better after T-5)

- `bake_common.is_join_objects_problematic()`: `CUSTOM` is problematic, with the existing
  console-notice wording (ADR-0004).
- `ui.py`: `use_baked` on a custom layer states that the live graph is bypassed (FR-22).
- Tests: constant-output group, bake to an image target, compare pixels.

**Verify:** FR-19 `(0.25, 0.5, 0.75)` within ±1/255 inside the island, plus a `VALUE` channel at
`0.3`; FR-20 masked custom layer over a solid layer vs the equivalent `NOISE` reference, within
±2/255; FR-21 merged bake skipped with notice, per-object bake completes; FR-22 notice shown and
the baked image wins.

**Done when:** all four pass on one build and the pixel tolerances are in the commit body.

---

## T-9 — Parity sweep and source-tree nesting

**FR:** FR-23 … FR-30 (incl. FR-27), NFR-3, NFR-4 · **Depends on:** T-5, T-6b, T-7b, T-8, T-10

- `subtree.refresh_source_tree_ios()`: forward the custom group's wired inputs into the nested
  source tree instead of dropping them; prune only what this function added. If it proves unstable,
  take the documented fallback — skip nesting for `CUSTOM` at the `check_layer_source_tree` gate —
  and record the decision and reason in `plan.md` §2.5 in the same commit.
- Walk every `layer.type in {…}` site; apply the plan's rule (default = `NOISE` membership) and the
  deviation table; add the one-line reason at each site. Append the final audit list to this task's
  commit body: file, line, set, decision.
- Add parity tests: enable/disable, reorder, parent under a Group layer, masks + transition bump,
  channel modifiers, channel override + swizzle, gamma/linear, smooth bump + uv neighbour, layer and
  channel preview modes, channel add/remove/rename, blending over what is below.

**Verify:** each row a–h of spec §4.7 with a `CUSTOM` layer against an otherwise identical `NOISE`
layer — same links, same rendered result (image diff within tolerance). FR-27 specifically: toggle
smooth bump with one passthrough input, render unchanged, input link still present.

**Done when:** the table is filled in the commit body, no unexplained membership remains, and the
rendered parity holds for every row.

---

## T-10 — Starter group, Make Unique, panel polish

**FR:** FR-31, FR-32, FR-8 · **Depends on:** T-4

- `create_starter_group(yp, name)`: Start/End, one pass-through pair per root channel, `Vector` and
  `Color Alpha` inputs, `Alpha` output. Written exactly once.
- `make_group_unique(layer)`: copy the tree, repoint, re-sync.
- Panel: group name, *Make Unique*, relink, and the starter/existing choice in one menu.

**Verify:** FR-31 shape + renders as "below layers"; FR-32 (add and remove a root channel: the
group's socket list is identical in names, types and order); FR-8 (two layers on one group follow
one edit; after Make Unique exactly one follows the next edit).

**Done when:** all three pass and the generated group opens in the node editor as something a user
would not be embarrassed by (named sockets, sane layout).

---

## T-11 — Acceptance run

**FR:** all; NFR-1 · **Depends on:** everything

- Run the spec §6 acceptance checklist on Blender 4.2 LTS (the floor, ADR-0006) and on the current
  5.x. Record: Blender version, pass/fail per line, and a screenshot or the failing assertion for
  anything that fails.
- Write the results into the commit body (not into `spec.md`; the spec records requirements, not
  outcomes).
- Any failure that is a defect becomes a new task appended under **Follow-ups** below.

**Done when:** every checklist line has a verdict on both builds, and every failure is either
fixed or filed.

**Status:** §6 items 1–21 have verdicts on Blender 5.2.3 LTS, and the suite plus the acceptance
script also run green on 4.2.9 and 4.5.9 LTS (ADR-0006). Item 22 (cross-build: a 5.x-saved file
opened in 4.2, and the reverse) is NOT RUN. Within 1–21, item 13's save/reopen sub-step and item
15's Developer-Mode visibility are NOT RUN (see the acceptance table). Evidence:
[`acceptance-5.2.3.md`](acceptance-5.2.3.md) and `tests/README.md`. The interactive items (menu
clicks, link inspection, Ctrl+Z, viewport review) still need a human pass.

---

## T-12 — Editable dummy group instances (post-acceptance)

**FR:** FR-33 (added 2026-10-30), FR-8, FR-16 · **Depends on:** T-10, T-11

**Status:** done — commits `b4fd407` (dummy creation and panel row) and `6dbce80` (cleanup on
every transition).

The shader editor cannot reliably open a group that has no instance, and the earlier *Edit Group*
operator reported success without changing the editor. Replace it with one unconnected instance of
each referenced group inside the labelled frame in every material tree, so the user Tabs into it
and edits the same datablock the layer renders from.

- `ensure_custom_group_dummy` / `prune_custom_group_dummies` /
  `remove_custom_group_dummies_from_tree`; idempotent, name-independent (`yp_custom_dummy` plus
  `node_tree`), no links, no `node.label`, frame never moved.
- Call on creation, Change Group, Make Unique, paste into another material and conversion to
  CUSTOM; prune on layer removal, conversion away, live group deletion/usability flip and ucupaint
  node removal. Do not add anything on load.
- Remove `wm.y_edit_custom_group`, its button and its tests. Panel row is
  `Node Group: <name> | Make Unique | Change Group`.

**Verify:** `TestCustomDummyInstances` (14 tests) covers creation, one-per-group, Change Group,
Make Unique, last-layer removal, shared material trees, sync/reconnect leaving it untouched,
conversion away, paste, live deletion, rename, yp-node removal, and an edit through
`dummy.node_tree` changing the centre pixel.

**Done when:** the tests pass, no file is mutated on load, and the layer panel has no *Edit Group*
action. (Met.)

---

## T-13 — Starter group alpha is a constant 1.0

**FR:** FR-31 (amended 2026-10-30) · **Depends on:** T-10

**Status:** done — `c0be3b3` (implementation, tests, acceptance) + `82ea52b` (evidence and docs
corrections). 136 tests OK (4 skipped); acceptance 15/15 PASS, L2 `opacity alpha=1.000
pixel=[0.024, 0.024, 0.024, 1.000]`. The pre-fix run failed `test_02b` with alpha 0.0, so the
assertion is not vacuous.

As shipped, `create_starter_group` feeds the `Alpha` output from the `Color Alpha` input. A fresh
layer has nothing connected to that alpha stream, so it evaluates to 0: the starter layer shows the
layers below but contributes no alpha of its own, and editing its colour output can appear to do
nothing. A starter group must be opaque.

- In `custom_node_common.create_starter_group`: stop declaring the `Color Alpha` input. Add a
  `ShaderNodeValue` inside the starter frame with `outputs[0].default_value = 1.0`, and link it to
  the `Alpha` group output with `node_connections.create_link`. Every channel output stays a
  pass-through from its same-named input.
- Do not modify existing starter groups and add no `versioning.py` block: FR-32 makes a starter
  group user-owned after its one-time creation, so old groups keep their `Color Alpha` pass-through
  until a user edits them.
- Update `TestCustomStarterGroup.test_01`: inputs are the channel names plus `Vector` (no
  `Color Alpha`), and `Alpha` is fed by the value node rather than by a group input. Extend
  `test_02`, or add a test, to assert a fresh starter layer renders opaque — with
  `film_transparent`, the centre pixel's alpha is 1.0, where it is 0 before this task. Update the
  starter-inputs assertion in `acceptance_5_2_3.py` for the same reason.

**Verify:** the updated tests pass headlessly, and the §6 "fresh starter group is opaque by
default" line passes.

**Done when:** a newly created starter group has no `Color Alpha` input, its `Alpha` output is a
constant 1.0, a fresh starter layer contributes alpha, and existing starter groups are unchanged.

---

## Follow-ups

*Appended by T-11 and by any task that discovers out-of-scope work. Nothing here is promised.*

- [X] **[P1] Verify the new support floor: Blender 4.2 LTS and 4.5 LTS.** *Done: 4.2.9 and 4.5.9
      downloaded to `/tmp/opencode/blender-builds` and run against the untouched tree — each
      `Ran 159 tests … OK (skipped=4)`, acceptance 15/15, UI/undo suite `159 … OK`, add-on
      registers. One test-only difference fixed in `6ce4e43` (`NodeTreeInterface.new_socket()`
      rejects `NodeSocketMenu` before 5.0; `TestCustomSocketFilter` now probes the capability).
      `6c121e1` adds `BLENDER_BIN` to `tests/run_ui.sh` so a specific build can run the UI suite.
      Reviewer PASS; 5.2.3 remains green.*
- [X] **Metadata for the 4.2 floor (ADR-0006).** *Done in `1d2c16c`: `bl_info["blender"] =
      (4, 2, 0)` and the `blender_279` checkout/zip/release steps removed from
      `.github/workflows/main.yml`; guards and `lib_281`/`lib_282.blend` kept; no version bump.
      Reviewer PASS (159 tests on 5.2.3 and 4.2.9, YAML parses, step order intact). Caveat for the
      docs commit: `bl_info` only **warns** on a legacy install below the floor (`userpref.py`
      enables it anyway); only the extension manifest (`blender_version_min = 4.2.0`) refuses. Do
      not claim a clean refusal, or add a runtime `bpy.app.version` check separately if denial is
      wanted.*
- [X] **ADR-0006 and docs for the 4.2 floor.** *Done in `796fb82`: the decision record
      (`docs/decisions/0006-drop-pre-4-2-support.md`), NFR-1 and §6 item 22 in `spec.md`, the
      `AGENTS.md` Blender-versions rule, `README.md` support/install text, and `tests/README.md`
      "Verified" (4.2.9, 4.5.9, 5.2.3). Reviewer PASS.*

- [X] **docs (small):** `docs/architecture.md:232` says T-11 "passed §6 items 1–21", but items 13
      (save/reopen sub-step) and 15 (Developer-Mode visibility) are NOT RUN in the acceptance
      table; the caveat was added. Cosmetic: `:254-255` broke "Row e's smooth-bump / case" across
      lines in the middle of the sentence; joined. *Done in `796fb82`.*

- [X] **[P0, P1c review FAIL] Nested CUSTOM forwards inputs the flat path leaves alone.**
      `get_source_start_input_sockets` derived the CUSTOM contract from **any** outer `Start`
      output, while the flat FR-6 path feeds only root-channel names and `<channel> Alpha`. A group
      input named like the UV socket (`UVMap UV`) was therefore linked in the nested tree but not
      in the flat one: on the reviewer's probe scene flat `[0.0235 …]` vs nested `[0.5608 …]`, max
      delta 0.537 (on the committed `test_07` scene 11/255) — an FR-6 and FR-27 violation. *Fixed
      in `52f8ff8`: `get_custom_source_input_names` is now the one channel-name rule both the flat
      `reconnect_custom_source_inputs` and the nested derivation call; `600e7f8` corrected
      `architecture.md`/the test text. Reviewer PASS; `test_07` fails on `34c190f`, and the
      strengthened `Alpha` test fails when the derivation is emptied.*

- [X] **[P1, P1b review FAIL] Nested sources still drop built-in source inputs other than
      `Vector`/`Normal`.** The nested AO layer/mask group declared only `['Vector', 'Normal']`, so
      the inner AO node's `Distance` had 0 links (default 1.0) and a non-default `ao_distance`
      could not reach a nested AO layer or AO mask; the flat source had that link. `3ed235e` fixed
      the crash but not this, and the AO/mask tests were render-vacuous while the commit body
      claimed rendered parity. *Fixed in `63d4c75`; reviewer PASS (151 tests headless + UI,
      acceptance 15/15). `source_start_inputs` + `get_source_start_input_sockets` +
      `refresh_nested_source_ios` derive `AO Distance`, `EDGE_DETECT Radius` and `COLOR_ID Color ID`
      from the outer `Start` tunnels, prune unread inputs, and are shared by layer nesting, channel
      overrides and mask trees; `docs/architecture.md:99-120` corrected. Reviewer's measured
      deltas: nested AO layer centre 9/255 / max 43/255, AO mask centre 9/255 / max 42/255 (nested
      == flat, 0/255 full image); the commit body's 13/12/49/48 do not reproduce on the committed
      scene.*

- [X] **[P1a, Ad-Hoc Fix] Layer preview mode breaks when the active layer changes.** With layer
      preview on, making another layer active aborts `Reconnect` with `KeyError: '_Layer Viewer'`
      inside `Root.update_layer_index` → `preview_mode.update_preview_mode` →
      `check_all_channel_ios(specific_layer=…)` → `reconnect_yp_nodes` (`node_connections.py:476`),
      so the preview stays on the old layer or goes blank. Root cause found 2026-10-30:
      `update_preview_mode` resolves the layer with `ListItem.get_active_layer` (list-item index)
      while the reconnect uses `yp.layers[yp.active_layer_index]`; when the two disagree only the
      stale layer gets viewer sockets, and the newly active layer's yp node has none. Fix: while
      layer preview mode is on, build the two viewer outputs for **every** layer tree (they are
      yp-wide state), resolve the previewed layer from the same source of truth as the reconnect,
      and make `reconnect_yp_nodes` tolerate a viewer socket that vanished mid-rebuild instead of
      raising. Verify: two NOISE layers, preview on, switch active layer both ways, switch channel,
      preview off — no exception, the yp viewer link comes from the newly active layer node and the
      render matches that layer. Then restore the rendered §4.7 row f comparison in
      `tests/test_custom_parity.py` (it is single-layer only because of this bug). *Fixed in
      `5bf214b`; reviewer PASS (138 tests, acceptance 15/15).*
- [X] **[P0, P1b review FAIL] Nested wiring regresses AO / previous-normal layers.**
      `reconnect_layer_nodes` now binds `source` to the nested `*_group` instance
      (`node_connections.py:1106`), but the previous-normal leg still does
      `source.inputs['Normal']` unguarded (`:1163`), and `refresh_source_tree_ios` declares only
      `Vector` on the instance. Reproduced: NOISE layer + smooth bump, then add an Ambient
      Occlusion layer and enable its Height channel → `KeyError: 'Normal'` at `:1163`, aborting the
      graph rebuild; `5bf214b` does not crash. The sibling line and the mask path
      (`:1386-1389`, needs `mask.hemi_use_prev_normal`) are the same shape. Fix: forward the
      previous-normal stream through the nested `Start` where the outer `Start` has a `Normal`
      socket, guard both sites otherwise (a layer/mask must never abort a rebuild over an optional
      input), and test AO, baked `HEMI`/`EDGE_DETECT` (flag on and off) and an AO mask. Record in
      the commit body whenever a leg is deliberately left at the default normal. *Fixed in this
      commit: the nested interface declares `Normal` for `HEMI`/`EDGE_DETECT`/`AO` (layer and
      non-baked mask), `reconnect_layer_nodes` feeds that instance input from the bump output or
      Geometry, and both previous-normal sites are guarded. `tests/test_nested_source.py` gains
      `TestNestedPreviousNormal` (4 tests). Baked `HEMI`/`EDGE_DETECT` deliberately keep the
      default normal inside the baked image, which has no `Normal` input; their render matches the
      un-nested baked layer. Reviewer: pending.*
- [X] **[P1b, Ad-Hoc Fix] Nested source trees are never wired.** *Done: `da03772` (nested wiring),
      `3ed235e` (previous-normal crash + forwarding) and `63d4c75` (generic derived inputs); all
      reviewer-verified. `tests/test_nested_source.py` now has 9 tests: NOISE, IMAGE, channel
      override, mask source, idempotency, un-nesting, AO/HEMI/EDGE_DETECT previous normal, AO
      layer/mask `Distance`, baked-source pruning.* A NOISE/IMAGE layer with global
      smooth bump enters `check_layer_source_tree`'s nesting path, but the nested tree is created
      empty: `refresh_source_tree_ios` only edits the interface, so the nested `Group Output` and
      the nested source's inputs have 0 links and the outer `source_group` instance has 0 input
      links; the layer renders disconnected. Same shallow pass builds channel-override trees
      (`enable_channel_source_tree`) and mask source trees (`enable_mask_source_tree`). Fix the
      shared nested pass: declare the nested `Group Input` sockets it will need, wire
      `Start → source/linear/bump nodes → End` inside the nested tree, forward the outer layer-tree
      stream into the `source_group` instance's inputs, and feed the outer End from the instance's
      outputs. Verify each entry point (layer nesting, channel override, mask source) with a render,
      not only a link count. CUSTOM stays out of the nesting set in this task. Implementation in
      `da03772`: `node_connections.reconnect_nested_source_nodes` /
      `reconnect_nested_group_inputs`, wired from `check_layer_source_tree`,
      `enable_channel_source_tree`, `enable_mask_source_tree` and the reconnect passes;
      `tests/test_nested_source.py` (6 tests) covers NOISE, IMAGE, channel override, mask source,
      idempotency and un-nesting.
- [X] **[P1c, Ad-Hoc Fix] Re-enable nesting for CUSTOM.** *Done: `34c190f` (nesting +
      forwarding + reserved names + swap/Make Unique tests), `52f8ff8` (channel-only rule),
      `600e7f8` (docs/test accuracy), `86ed394` (flat path reads the same Start-input table).
      Reviewer PASS on all four; 159 tests headless + UI, acceptance 15/15. `TestNestedCustomSource`
      covers forwarding and render parity, literal `Normal`, literal `Alpha`, `Vector` mapping
      add/remove, group swap + Make Unique while nested, CUSTOM-vs-NOISE row e and idempotency.*
      Depends on P1b. Forward the custom
      group's wired inputs into the nested tree's `Start` (T-9's abandoned attempt), let CUSTOM
      enter `check_layer_source_tree`'s nesting set, and re-run §4.7 row e against an otherwise
      identical NOISE layer plus the FR-27 smooth-bump toggle. If the nested pass still cannot feed
      the custom group's inputs, keep the documented fallback and record why in `plan.md` §2.5.
      Review findings carried in and closed: (a) reserved names by purpose — `Normal` is the
      below-layers stream for CUSTOM and the previous-normal leg only for HEMI/EDGE_DETECT/AO,
      `Vector` stays on the mapping leg, literal `Alpha` stays unlinked; (b) the nested derivation
      owns the contract so nothing declares a socket the prune would delete; (c) group swap and
      Make Unique while nested re-declare before reconnect; (d) flat and nested read
      `source_start_inputs`/`get_custom_source_input_names` — one rule each.

- [X] **[T-13 review, docs only]** `acceptance_5_2_3.py check_02` prints only `opacity alpha=…`, so
      `acceptance-5.2.3.md` row 3's pixel claim `[0.0, 0.0, 0.0, 1.0]` is unsupported (the run's
      artifact is `(6, 6, 6, 255)`). Emit the full centre pixel in the evidence and quote it.
      Also fix the stale row references after the +1 renumbering (`acceptance-5.2.3.md:13`, `:55` →
      save/reopen is row 14; `:74`'s "§6 line 14 / FR-16" → the `node_tree=None` row is 15),
      `custom_node_common.py:109` ("two essential nodes" — the frame now holds three), and
      `docs/architecture.md`'s starter-group paragraph (still says `Color Alpha` and "not in this
      code yet"). `tests/test_custom_node.py::test_02b` should set/restore
      `image_settings.color_mode = 'RGBA'` explicitly. *Fixed in `82ea52b`; reviewer PASS.*
- [X] **docs (P1a/P1b review, `architecture.md` only):** `docs/architecture.md` still used the old
      acceptance numbering ("§6 lines 1–15 … line 16") and said the §4.7 row f comparisons were
      "each taken in a single-layer scene", although `TestParityRowFActiveLayer.test_02` is a
      two-layer comparison since P1a. *Fixed in `22d83e7`; reviewer PASS. The `TestParityRowF`
      docstring was already current (from `5bf214b`), so no test text needed changing.*
- [X] **docs (planner-owned):** `spec.md` §6 line 3 still says it "FAILS on this branch until T-13
      lands" and the `## Changes` note says T-13 is not implemented. The spec records requirements,
      so the status wording needs a spec-owning session. Same session: `acceptance-5.2.3.md`'s
      "§6 line" column indexes its own 17-row table while `spec.md` §6 now has 22 items
      (five post-T-11 items have no row), and `tasks.md:306`/`:492` still use the old 16-line
      numbering. Wire the acceptance table to the spec's numbering instead of renumbering prose.
      *Fixed in `c741b0a` (planner session): spec status/FR-27/R4 updated, §6 items numbered 1–22,
      acceptance table re-keyed to those numbers with evidence-backed rows 11–15 (13 and 15 marked
      NOT RUN where nothing covers them).*

- [X] [Ad-Hoc Fix] `docs/architecture.md` accuracy: mark `Vector Displacement` / `Alpha` as opt-in
      (`Root.py:339-345` sets all `enable_*` false by default), and add the `<channel> Background`
      suffix to the §3 `io_suffix` vocabulary (`input_outputs.py:855,865`). Found by T-1 review.
- [X] [Ad-Hoc Fix] Reconcile the "~76 across 15 files" figure in `spec.md` R1/§4.9 and
      `ADR-0001` with the verified 71 non-comment sites / 14 files (76 occurrences including
      5 commented out; 70 live). Do not change requirements text otherwise.
- [X] **[P0, T-11 FAIL]** FR-16's literal verification (set the *source's* `node_tree = None`, keep the
      pointer) leaves the layer "usable": spliced into the yp, renders grey, channel-binding warning
      instead of the missing-group row and below-layers fall-through. Treat a source node with no
      `node_tree` as unusable (and show the missing-group state), or narrow FR-16 in `spec.md` —
      code fix preferred. Also fix `acceptance_5_2_3.py` (`os._exit(0)` regardless of verdicts, dead
      assert at `check_06`) and `architecture.md:170` (Make Unique now preserves bindings).
- [X] [Ad-Hoc Fix] `make_group_unique` re-applies FR-9 defaults, destroying explicit channel bindings
      (a channel bound to `Blue` renders `Color` after Make Unique). Preserve `socket_input_name`
      (and `custom_fallback_binding`) when the copied interface still has that output. Found by T-10
      review; T-11 must not accept FR-8 without this.
- [X] [Ad-Hoc Fix, reverted] **Edit Group**: the panel shows `Node Group: <name>` as a dead label and
      the Shader Editor offers no way to open a group without an instance. A `wm.y_edit_custom_group`
      operator + button was added (`get_custom_group_editor_area`, `TestCustomEditGroup*`), but it
      reported success without changing the editor in real use, so it was removed. Replaced by the
      dummy-instance workflow: `ensure_custom_group_dummy` / `prune_custom_group_dummies` keep one
      unconnected group instance per referenced group in a labelled frame in the material tree, which
      the user Tabs into. Requested by the user after testing 5.2.3.
- [ ] **[P1, pre-existing]** Built-in smooth-bump/UV-neighbour nesting is broken independently of CUSTOM:
      `refresh_source_tree_ios` leaves the nested tree's Group Output unfed and `reconnect_layer_nodes`
      creates cross-tree links Blender drops, so any NOISE/IMAGE layer with global smooth bump renders
      disconnected. Fix the nested-source pass, then re-enable nesting for CUSTOM and re-test §4.7 row e
      against NOISE. Found by T-9.
- [ ] **[P1, pre-existing]** `preview_mode.update_preview_mode` raises `KeyError: '_Layer Viewer'` when the
      active layer is not the one holding the preview output (two NOISE layers reproduce). Blocks a
      rendered §4.7 row f comparison. Found by T-9 review.
- [X] **[P0, T-9 review FAIL]** (a) §4.7 row f tests are vacuous: channel preview asserts layer-tree links
      that are identical with preview off; layer preview asserts an always-present viewer socket. Assert
      the real preview wiring in the yp/material trees and a rendered single-layer comparison. (b)
      `docs/architecture.md` claims "T-7b–T-10 landed … and the starter group" — T-10 is not built;
      remove. (c) `plan.md:90` still says CUSTOM enters the nesting set and `:124` cites the wrong
      bake line. (d) `check_layer_source_tree` still nests a CUSTOM layer when `use_baked` is on; CUSTOM
      must never nest. (e) Audit counts: 5 commented sites (71 non-comment, 70 live —
      `modifier_common.py:785` is unreachable).
- [X] [Ad-Hoc Fix] T-7b's FR-9-on-paste branch calls `set_custom_channel_default_binding` before the
      new layer's group node exists, so it is a no-op; the test only passes because the property
      default happens to equal the expected value. Move the call after the node is created and make
      the test fail without the fix.
- [ ] [Ad-Hoc Fix] T-7b's undo tests synthesize the undo step (`ed.undo_push` after the operator);
      interactive Ctrl+Z remains unverified and must be on T-11's human checklist.
- [X] **[P0, T-7b prerequisite]** `_custom_usability_cache` is keyed by `layer.as_pointer()`, a slot
      address: inserting/removing a layer shifts every later layer's pointer, so a usability flip can
      be masked (a usable layer inherits a missing layer's cached state → 0 reconnects, layer stays
      spliced with a warning). Key by a stable identity (`yp` + `layer.group_node`) and make
      `is_custom_layer_group_usable` read the pointer first with the source fallback, so the pointer
      is the single source of truth. Found by T-7a re-review.
- [X] **[P0, T-7a review FAIL]** FR-16 is only half-built: the relink action and a live group
      deletion/emptying set the pointer but never re-run `reconnect_yp_nodes`, so the layer stays
      bypassed / renders gray instead of falling through. `set_custom_layer_group` must re-splice
      the yp, and the handler must detect a *usability* transition (missing/emptied/restored) and
      reconnect the yp too. Tests must assert the yp links and pixels, not just the warning.
- [X] **[P0, T-6b review FAIL]** (a) FR-10 warning is unreachable: the live handler auto-re-binds the
      channel before redraw, so the user never sees that the binding changed. Needs a remembered
      "auto-fallback" flag (per layer channel, additive, default false), cleared when the user
      re-picks the binding. (b) A failing group wedges healthy groups in the same yp and can leave a
      half-applied repair (binding written, tree not rewired → silent wrong render). Sync per
      group, roll back channel bindings on exception, retry on later updates (time-throttled, no
      storm), keep healthy groups progressing. (c) `architecture.md` §6/§7 must be updated in the
      same commit (new `depsgraph_update_post` handler).
- [X] **[P0, T-6a review FAIL]** Signature cache is keyed module-level by group *name*, so a group
      referenced by layers in two `yp`s is only re-synced for the first yp: the second keeps a
      dead binding / dead mapping node forever. Key by `(yp, group)` (pointer), prune entries for
      groups/yps no longer iterated, and restore the previous signature in `except` so a failed
      sync is retried by the next handler pass (T-6b depends on this). Add a two-material test.
- [X] [Ad-Hoc Fix] `Layer.py:885` (`YNewLayer.invoke`) calls `is_mapping_possible(self.type, self)`
      with the *operator*, not a layer → `AttributeError: 'WindowManager' object has no attribute
      'yp'` for `CUSTOM`. Pass a real layer or use `entity=None`. Found by T-5 review.
- [X] [Ad-Hoc Fix] FR-6 edge: a root channel renamed to exactly `Vector` hijacks the group's
      `Vector` input (FR-7 reserves that name). Skip `'Vector'` in the channel-input loop.
- [X] [Ad-Hoc Fix] FR-6 edge, handle with T-7a group swap: pre-existing links on inputs that stop
      matching a channel (`MyOwnThing`) are not broken; Blender remaps them by index on tree swap.
- [X] [Ad-Hoc Fix] `get_custom_group_candidates()` must also exclude ucupaint's internal `.yP `
      trees (source/mask/modifier groups — `subtree.enable_mask_source_tree`,
      `subtree.check_layer_source_tree`, `modifier_common.py:660`, `common.py:4244`). FR-2's three
      named exclusions miss them; only layer trees set `is_ypaint_layer_node`. Found by T-3b review.
- [X] [Ad-Hoc Fix] Changing the group of an already-`CUSTOM` layer from the Replace Layer Type menu
      is a silent `CANCELLED` (`execute` rejects same-type). Group re-pick belongs to T-7a's panel —
      make sure that panel action works and the menu either works or is hidden.
- [ ] [Ad-Hoc Fix] `wm.y_replace_layer_type` with a typo'd `layer_name` silently retargets the
      active layer; it should report instead of falling through.
- [X] [Ad-Hoc Fix] `spec.md` FR-3 says verify `layer.blend_type`; blends are per-channel
      (`layer.channels[i].blend_type`) plus `mask.blend_type`. Correct the verification wording when
      a spec-owning session next touches the file. *Fixed in the 2026-10-30 `## Changes` entry and
      in FR-3 itself.*
- [X] [Ad-Hoc Fix] `.gitignore` covers `ucupaint_updater/` but not `customnodes_updater/`, so loading
      the add-on from this worktree leaves an untracked folder. *Fixed in `0740995`: a generic
      `*_updater/` pattern plus `.opencode/`.*
- [X] [Ad-Hoc Fix] `docs/architecture.md` §6 still says "There is no runner script in the
      repository"; T-2 added `tests/run_tests.py`. Update that bullet when the AGENTS.md update
      task is done.
- [X] [Ad-Hoc Fix] T-2's `AGENTS.md` **Running** section is not yet updated: `AGENTS.md` is
      write-locked to `@coder` and to the orchestrator, so the verified command
      (`blender --background --factory-startup --python tests/run_tests.py`) is recorded only in
      `tests/README.md` and the T-2 commit body. Needs a `planner` session or the user.
- [X] **Remove the pre-4.2 guards (ADR-0006 cleanup).** *Done: every constant-true
      `is_bl_newer_than`/`is_bl_equal` guard folded to its 4.2+ branch, the pre-4.0
      `tree.inputs`/`tree.outputs` branches and the updater's `blender_279` branch removed,
      `is_bl_equal` and the 2.7x icon table deleted. Guards for 4.3+/5.x and the `lib_281`/
      `lib_282` group libraries stay (the latter are loaded by every supported build). Suite 159
      OK on 4.2.9/4.5.9/5.2.3, acceptance 15/15, UI/undo 159 OK on all three.*
- [ ] **Cross-build saved file** (NFR-1, §6 item 22). The suite and the acceptance script now run
      on 4.2.9, 4.5.9 and 5.2.3 LTS and each build reopens its own saved file (acceptance L13a),
      but no run has opened a **5.x-saved** file in 4.2 or the reverse. Re-run
      `acceptance_5_2_3.py` on 4.2.9, save there, and open the 5.2.3 save in 4.2.9. The
      interactive items listed in `acceptance-5.2.3.md` (menu clicks, node-editor link inspection,
      Ctrl+Z, viewport review) still need a human pass.
