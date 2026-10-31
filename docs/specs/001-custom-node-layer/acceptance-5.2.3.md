# Acceptance run — spec 001 §6 on Blender 5.2.3 LTS (T-11)

Build: **Blender 5.2.3 LTS**, build date **2026-10-26**, build hash `e13b728c6880`, branch
`makepkg (modified)`, Linux x86-64 release build, `/usr/bin/blender`. No other Blender build is
installed (checked: `which -a blender` → only `/usr/bin/blender`); none was downloaded.

This file is evidence. The requirements stay in [`spec.md`](spec.md); outcomes belong here and in
the T-11 commit body.

## Runner commands

```sh
# acceptance, headless checks (all §6 items except the undo half of item 19)
blender --background --factory-startup --python-exit-code 1 --python \
    docs/specs/001-custom-node-layer/acceptance_5_2_3.py

# acceptance, undo half (real window: Blender has no undo stack in --background)
./tests/run_ui.sh docs/specs/001-custom-node-layer/acceptance_5_2_3_undo.py

# required suites, before and after the run
blender --background --factory-startup --python-exit-code 1 --python tests/run_tests.py
./tests/run_ui.sh
```

`--python-exit-code 1` makes Blender return non-zero on any Python exception in the script, so an
import-time crash or a failure before `main()` is not masked as success; `main()` additionally exits
non-zero for any failing check. Both suites were green before the run and after it:
`Ran 121 tests ... OK (skipped=4)` headless, `Ran 121 tests ... OK` through `./tests/run_ui.sh`.

The scripts build their own scratch object/material/ucupaint node per line and drive the public
operators and predicates; they do not import `tests/test_custom_node.py`. Renders are Cycles CPU,
32×32, 8 samples, centre pixel.

## §6 checklist

| §6 | Checklist item | Verdict | Evidence |
|---|---|---|---|
| 1 | Add Layer → Custom Node offers a group picker; internal `~yPL` and layer trees absent | **PASS** | `get_custom_group_candidates()` with one suitable, one `~yPL `, one `.yP Layer ` and one shader-only group returned exactly `['AccSuitable']`; the real picker draw (`ui.draw_custom_group_picker`) offered `['Generate Starter Group', 'AccSuitable']` and none of the excluded trees. |
| 2 | Same menu generates a starter group; pass-through; adding a root channel leaves its sockets untouched (FR-31/32) | **PASS** | Starter inputs `[Color, Metallic, Roughness, Height, Normal, Vector]` (no `Color Alpha`), outputs `[Color, Metallic, Roughness, Height, Normal, Alpha]`; every channel output fed from its same-named input, `Alpha` fed from a `ShaderNodeValue` at 1.0; render on/off `[0.102, 0.455, 0.0]` both; interface signature unchanged after `y_add_new_ypaint_channel`. *(The `Normal` output was amended on 2026-10-31, T-14; see the re-run note below.)* |
| 3 | A fresh starter group is opaque by default: no alpha input, `Alpha` a constant 1.0 (FR-31 as amended) | **PASS** | Over a transparent custom layer below, film-transparent render with the yp alpha wired to the BSDF: centre pixel `[0.024, 0.024, 0.024, 1.000]` (RGB stable within 2/255 between runs; the layer is black over a transparent below stream, so only `A` matters), `A = 1.000` (a `ShaderNodeValue` at 1.0 feeds the group's `Alpha`; pre-T-13 this pixel was `A = 0`). |
| 4 | Color + Roughness group renders; each channel binds to the same-named output | **PASS** | `channels[Color].socket_input_name == 'Color'`, `channels[Roughness] == 'Roughness'`; centre pixel `[0.573, 0.035, 0.0]` (the group's red constant). |
| 5 | Channel source menu lists the group's outputs and nothing shader-typed | **PASS** | Group with `Color`, `Rough`, `Shader`: `get_available_source_outputs` → `['Color', 'Rough']`; the real `YLayerChannelInputMenu.draw` produced menu entries `['Color', 'Rough']`. |
| 6 | Rename `Roughness` → `Rough`: live re-wire, fallback warning until re-bound | **PASS** | One `view_layer.update()` re-pointed the binding to a live output (`Color`, the FR-9 default), set `custom_fallback_binding`, warning `'Channel binding was re-pointed after its group output changed'`; explicit re-bind to `Rough` cleared the flag and warning. |
| 7 | Delete the bound output: falls back to the first output, renders, no traceback | **PASS** | Deleting `Roughness` left live outputs `['Color']`; binding became `'Color'`, fallback flagged, `get_custom_sync_error == ''`; rendered `[0.569, 0.039, 0.0]`. No exception. |
| 8 | Vector group gets mapping controls; non-Vector does not | **PASS** | With `Vector`: `layer.mapping` names a `ShaderNodeMapping` and the source `Vector` input is linked from it. Without: `layer.mapping == ''`, no mapping node, no `ShaderNodeMapping`/`TexCoord`/`UVMap` node, no `Vector` input. |
| 9 | Group with `Color` + `Color Alpha` + `Roughness` inputs receives the below-layers streams | **PASS** | All three source inputs each receive exactly one link from the layer tree's `Start` group-input socket of the same name; `MyOwnThing` stays unlinked. |
| 10 | Two layers on one group follow one edit; Make Unique separates them | **PASS** | Renaming `Color` → `Colour` re-bound both layers; `y_make_custom_group_unique(A)` repointed only A to a copy; renaming `Colour` → `Tint` then moved B only (A stayed `Colour`, B became `Tint`). |
| 11 | Replace Layer Type → Custom Node re-picks the group instead of cancelling (FR-3) | **PASS** (automated) | `tests/test_custom_node.py::TestCustomGroupSwap.test_01_replace_layer_type_repicks_the_group`: `wm.y_replace_layer_type(type='CUSTOM', group_name='SwapB', layer_name=…)` returned `FINISHED`, `layer.custom_group` and the source `node_tree` became `SwapB`, bindings re-pointed by FR-9, the stale non-channel input link was dropped, and swapping back restored the initial graph snapshot. `TestCustomDefaultBinding.test_05_replace_layer_type_binds_and_requires_a_group` refuses the conversion when no group is given (returns False, type unchanged) and retargets with one; `TestCustomGroupSwap.test_02` asserts the same operator returns `CANCELLED` and keeps the existing group. Not clicked in the UI. |
| 12 | A custom layer puts an unconnected instance in the frame `Custom Layers: edit here, do not connect`; an edit there changes the render (FR-33) | **PASS** (automated) | `TestCustomDummyInstances.test_01_creation_adds_one_unlinked_dummy_in_the_labeled_frame`: one `ShaderNodeGroup` with `yp_custom_dummy`, `node_tree is group`, parent label exactly `Custom Layers: edit here, do not connect`, zero links on the node and on every socket, in the material tree and not the yp tree, left/below the ucupaint node, unchanged by a second `ensure_custom_group_dummy`. `test_14_editing_through_the_dummy_changes_the_render`: editing the group through `dummy.node_tree` flipped the centre pixel red → blue. Tab-in was scripted, not performed by hand. |
| 13 | Two layers share one dummy; Change Group, Make Unique, paste, conversion away and removal prune correctly; removed dummies stay removed after reopening (FR-33) | **PASS** (automated), except the save/reopen sub-step **NOT RUN** | `TestCustomDummyInstances` covers every mutation: `test_02` (one dummy for two layers, two for two groups), `test_03` (Change Group), `test_04` (Make Unique), `test_05`/`test_06` (last-layer removal; another group's dummy survives), `test_07` (sync/reconnect leave it untouched and unlinked), `test_08`/`test_09` (conversion to NOISE/COLOR), `test_10` (paste into another material), `test_11` (group datablock deleted), `test_12` (rename follows), `test_13` (ucupaint node removed). No test deletes the dummies, saves and reopens; that sub-step needs a manual pass. |
| 14 | Two groups, one unusable: the healthy group still re-syncs, the broken one reports and retries without a per-frame storm (FR-11/FR-13) | **PASS** (automated) | `TestCustomFailureIsolation.test_01_failure_rolls_back_isolates_and_retries_without_a_storm`: with group A raising and group B renamed, both were attempted in the same update (1 each), B repaired and re-wired, A's binding rolled back, `get_custom_sync_error(yp)` names A, and 20 further updates made no extra A attempt; expiring the throttle retried and repaired A. `TestCustomSyncErrorNamesGroups.test_01` names both failing groups. The layers-panel drawing of that error is not exercised — the read is scripted. |
| 15 | Refresh operator visible only with Developer Mode on; reports nothing on a healthy tree (FR-14) | **NOT RUN** (manual visibility check); the no-report half is **PASS** (automated) | `TestCustomSyncOperator.test_02_reports_nothing_on_a_healthy_tree`: `wm.y_custom_sync()` returns `FINISHED` and reports nothing after a healthy sync. Visibility is a `poll` on `developer_mode` (`ui.py:9405-9407`) that no test calls, and the row was not looked at in a running UI, so the checklist item is not green. |
| 16 | Bake a constant `(0.25, 0.5, 0.75)` custom colour channel; pixels match | **PASS** | 128² HDR image bake: every texel within 1/255 of `(0.25, 0.5, 0.75)`. |
| 17 | Bake a `VALUE` channel from a float output; pixels match | **PASS** | 128² bake of `Roughness` from a `0.3` float output: every texel within 1/255 of `0.3`. |
| 18 | Two objects sharing the material: merged bake skipped with notice; bake works | **PASS** | `is_join_objects_problematic` True; notice `"INFO: Merged bake is not happening because there's a custom node layer"`; `prepare_objs_before_baking` returned 2 objects; per-object bake uniform at `(0.25, 0.5, 0.75)` ± 1/255. |
| 19 | Save, reopen: layer intact. Undo after switching groups: previous graph back and connected | **PASS** | Save/open of `acc_save_reopen.blend`: layer still CUSTOM, `custom_group` and source `node_tree` are `AccSaveGroup`, binding `Color`, render before/after `[0.573, 0.035, 0.0]`. Undo (real window, `bpy.ops.ed.undo()` after `wm.y_replace_layer_type` from `AccUndoA` to `AccUndoB`): group back to `AccUndoA`, binding `Color`, both enabled channels (`Color`, `Roughness`) connected in the yp. |
| 20 | Set the group's node tree to None: layer stays, no traceback, UI shows missing group | **PASS** | `source(layer).node_tree = None` with `layer.custom_group` left pointing at the group (the literal item/FR-16 action); one `view_layer.update()` → layer stays in `yp.layers`, pointer unchanged, `is_custom_layer_group_usable` False, layer node carries no yp links (bypassed exactly like a disabled layer), warning `'Missing node group'`, `get_custom_sync_error == ''`; render shows the below green layer `[0.169, 0.573, 0.0]`. `test_05` also confirms this equals an identical disabled layer's graph and pixel, that the row shows the ERROR state with the relink menu, and that there is no traceback. Restoring the same tree repairs in one update: render red `[0.573, 0.035, 0.0]`. |
| 21 | Toggle smooth bump, preview modes, masks, modifiers: no visual change versus before | **PASS** (see note) | Identity toggles left the render bit-identical (tolerance 2/255), baseline `[0.549, 0.545, 0.545]`: `enable_smooth_bump` on the height channel with a pass-through input, a full-white MULTIPLY mask (`enable_masks`), an identity MATH modifier on then off. Preview is *meant* to change what is displayed, so for preview the check is the viewer wiring (`Emission Viewer` present on, absent off); pixel parity with an equivalent NOISE layer is covered by the parity suite (row f). |
| 22 | Blender 2.80 (or oldest supported target) and 4.x both open a saved file with a custom layer | **NOT RUN** | No legacy/4.x Blender is installed on this machine (`which -a blender` → only 5.2.3 LTS) and none was downloaded. Only 5.2.3 opening its own saved file was verified (item 19). This is the reason the line is not green. |

Row numbers are the item numbers in [`spec.md`](spec.md) §6. Items 11–15 were added to §6 after
this run (T-12/T-13 and the P1 fixes); their verdicts rest on `tests/test_custom_node.py`, not on
this run, and each row names the test rather than inventing a manual observation.

**2026-10-31 re-run (T-14, FR-31 normal amendment).** `check_02` was updated for the neutral
`Normal` output and the full script was run again on the same build: **L2 PASS**, inputs
`[Color, Metallic, Roughness, Height, Normal, Vector]`, outputs `[Color, Metallic, Roughness,
Height, Normal, Alpha]`, `Normal` fed by a constant vector `(0.5, 0.5, 1.0)`, `Alpha` by a
`ShaderNodeValue` at 1.0, render on/off `[0.102, 0.455, 0.0]` both, interface signature unchanged.
The required suites were green: `Ran 161 tests ... OK (skipped=4)`.

### Scope notes (what a human must still click)

Everything above was scripted. The following were **not** performed interactively and should be
part of a human pass:

- Clicking the Add Layer / Replace Layer Type / channel-source menus in Blender's UI. The scripts
  drove the real menu `draw` bodies with a recording layout; they did not click the entries.
- Opening the custom layer's node editor and clicking through the `Color` / `Color Alpha` /
  `Roughness` input links. The links were asserted on the tree, not inspected visually.
- Pressing **Ctrl+Z** in the UI. The undo check used `bpy.ops.ed.undo()` in a real window after an
  explicit `undo_push` (the same limitation recorded in the T-7b follow-up).
- Visual viewport inspection; renders were compared by centre pixel.

## Defects found

One defect, found during this acceptance run and fixed afterwards in `b4d29a3` (the T-11 fix):

- **§6 item 20 / FR-16 — a source node with no `node_tree` was treated as usable.** Clearing only
  the source node's `node_tree` while `layer.custom_group` still named the group left the layer
  spliced into the yp and rendering grey, with a channel-binding warning instead of the
  missing-group row and the below-layers fall-through. Usability now also reads the source node: an
  existing source node with no `node_tree` is the missing-group state. The checklist above records
  the fixed behaviour.

No other checklist line failed. The remaining outstanding item is environmental: the cross-version
line (item 22) needs a machine with a 2.80/4.x build; it is recorded under Follow-ups.

## Post-acceptance addendum (2026-10-30)

This run predates two later changes and should be read with them in mind:

- **Dummy group instances** (`b4fd407`, `6dbce80`) replaced the short-lived *Edit Group* operator.
  They are covered by `tests/test_custom_node.py::TestCustomDummyInstances`, not by this checklist;
  spec FR-33 and §6 record the manual items.
- **Starter-group alpha (T-13, re-run 2026-10-30).** This file's L2/L3 rows and line 3 were
  regenerated after T-13, which amended FR-31: the starter group no longer declares a `Color Alpha`
  input, and its `Alpha` output is fed from a `ShaderNodeValue` at 1.0. On a transparent below
  stream, a film-transparent render now gives `A = 1.000`; before T-13 the same pixel was `A = 0`.
  Line 2 still passes because a pass-through layer renders identically whether it is enabled or
  disabled. Existing starter groups are deliberately not migrated (FR-32).
