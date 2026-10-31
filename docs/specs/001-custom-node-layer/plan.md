# Plan — 001 Custom node layer

Spec: [`spec.md`](spec.md) · System map: [`../../architecture.md`](../../architecture.md) ·
Decisions: [ADR-0001](../../decisions/0001-custom-node-is-a-layer-source.md),
[ADR-0002](../../decisions/0002-store-group-as-pointer.md),
[ADR-0003](../../decisions/0003-live-resync-by-signature.md),
[ADR-0004](../../decisions/0004-bake-policy-for-custom-layers.md)

## 1. Approach

Add a `CUSTOM` layer type whose source node is a `ShaderNodeGroup` referencing a user tree, and make
the existing source abstraction accept it. No new reconnect architecture: `reconnect_layer_nodes`
keeps owning the layer tree, `get_available_source_outputs` keeps owning "what may a channel bind
to", and channel names keep being the contract (architecture I1–I5).

Three things are genuinely new:

1. a **socket-type filter** on source outputs (shader sockets out, value sockets in),
2. **input wiring** from `Start[<channel>]` into same-named group inputs,
3. a **live re-sync** path driven by an interface signature (ADR-0003).

One new module, `custom_node_common.py`, holds everything specific to this type so the diff to
existing modules stays small and reviewable. That module is where the user will look when a socket
rename misbehaves.

## 2. Components

### 2.1 New module `custom_node_common.py`

| Function | Responsibility |
|---|---|
| `get_custom_group_candidates()` | Pure function for FR-2. Excludes `~yPL ` prefixed trees, `yp.is_ypaint_layer_node` trees, `yp.is_ypaint_node` trees, trees with no compatible output. |
| `is_custom_socket_compatible(socket)` | FR-4 socket-type test, one place. Uses the socket *type* enum, not names. |
| `get_custom_input_names(group)` | Names of inputs that match a channel or are `Vector` (FR-6/FR-7), used by wiring and by arrangements. |
| `get_custom_interface_signature(group)` | `((in_out, name, socket_type, enabled), …)`, version-safe across the pre-4.0 and 4.0+ interface APIs. `None`-safe: a missing group has a defined empty signature. |
| `sync_custom_layers(yp)` | FR-11 to FR-13 entry point: compare signatures, and for changed groups re-bind channels (`socket_input_name` fallback), then `reconnect_layer_nodes` + `rearrange_layer_nodes` per affected layer with `yp.halt_update`/`halt_reconnect` guarding. |
| `create_starter_group(yp, name)` | FR-31. Builds Start/End, one pass-through pair per root channel, `Vector` in, `Alpha` out fed by a constant 1.0 value node, `Normal` out fed by a constant neutral normal map `(0.5, 0.5, 1.0)`. Writes the tree exactly once. *(Amended 2026-10-30: no `Color Alpha` input — see spec `## Changes` and tasks T-13. Amended 2026-10-31: `Normal` is a neutral map, not a pass-through — see tasks T-14.)* |
| `make_group_unique(layer)` | FR-8/FR-17. Copies the tree, repoints the layer, re-syncs. |
| `get_custom_layer_warning(layer)` | Derived (not stored) state for the UI: missing group, no compatible outputs, invalid binding. |

Registered in `__init__.py` (module import list, reload list, `register()`).

### 2.2 `common.py`

- `layer_type_items`, `layer_type_labels` += `('CUSTOM', 'Custom Node', '')`.
- `layer_node_bl_idnames['CUSTOM'] = 'ShaderNodeGroup'`.
- `get_available_source_outputs()`: add a `CUSTOM` branch that filters by
  `is_custom_socket_compatible`. Existing branches unchanged — this function is the single funnel
  used by the channel menu, `refresh_source_tree_ios` and `get_mask_input_socket_name`, so it is
  also where a mistake would show up everywhere at once.
- `is_mapping_possible(entity_type, entity=None)`: CUSTOM returns `True` **only if** the group
  declares a `Vector` input (FR-7, FR-18). Signature grows an optional `entity`; audit call sites.
- `is_layer_using_vector()`: CUSTOM is vector using iff the `Vector` input exists (or a mask uses
  `Layer` texcoord, or a channel override is enabled — keep the existing tail logic).
- `has_previous_layer_channels` / `check_need_prev_normal`: unchanged; a custom layer blends over
  what is below like any other layer.

### 2.3 `layer_common.py`

- `check_layer_source()`: `CUSTOM` branch — create `ShaderNodeGroup`, assign
  `source.node_tree = layer.custom_group`, **no** `duplicate_lib_node_tree`, no lib lookup. If the
  group is `None`, still create the node with `node_tree = None` (FR-16 fallback) and let
  `get_available_source_outputs` return `[]`.
- `replace_layer_type()`: `CUSTOM` joins the "not cached" set (a per-type source cache is
  meaningless for a referenced group); retargeting to CUSTOM requires a group, and the dialog
  supplies it.
- `add_new_layer()`: accept `custom_group` and `create_new_group`; call
  `custom_node_common.create_starter_group` in the latter case before creating the layer.

### 2.4 `node_connections.py`

- New `reconnect_custom_source_inputs(tree, layer, source)` called from `reconnect_layer_nodes`
  immediately after the existing `Vector` wiring: for each root channel `X`, link
  `Start[X] → source.inputs[X]` and `Start[X + ' Alpha'] → source.inputs[X + ' Alpha']` when those
  exist (FR-6). Must skip cleanly when the source has no `node_tree` or the socket list changed
  mid-reconnect.
- No change to the channel-chain logic: `ch.socket_input_name` already selects the output, and the
  `Alpha` convention is already implemented there.
- `remove_all_prev_inputs`: ensure it does not tear down links into a *custom source* (it targets
  the layer group node, so this is a check, not a change — verify with a test).

### 2.5 `subtree.py`

- `refresh_source_tree_ios()`: forward the group's own inputs into the nested source tree instead
  of dropping them (FR-27, R4). The contract is derived, not listed per type: for `CUSTOM`,
  `get_source_start_input_sockets` returns the group inputs that the flat FR-6 path also links —
  the root channel names plus `<channel> Alpha` — taken from the shared
  `get_custom_source_input_names` predicate and intersecting the group's inputs with the outer
  `Start`; `refresh_nested_source_ios` declares exactly those plus the optional `Vector`, pruning
  only what it owns. `reconnect_nested_group_inputs` forwards the same names from the outer
  `Start`, and `reconnect_nested_source_nodes` forwards them from the nested `Start` into the inner
  group. Flat and nested paths therefore read one rule, so a group input matching no channel (for
  example `UVMap UV`) keeps its default in both.
- `check_layer_source_tree()`: CUSTOM nests like NOISE. A *baked* CUSTOM layer is the one exception
  (`use_baked` would otherwise open the gate for every type) and stays un-nested (FR-27).

**P1c decision (2026-10-31) — forwarding works; CUSTOM nests.**
The T-9 fallback was taken because the nested pipeline then left the nested tree and its outer
instance unfed. P1b repaired that (`reconnect_nested_source_nodes`, `reconnect_nested_group_inputs`,
a derived interface), so the remaining change was to declare the custom group's inputs on the
nested `Group Input` and forward them. Reserved names are matched by purpose, not by string:

- `Normal`: for `HEMI` / `EDGE_DETECT` / `AO` it is the previous-normal leg, fed from the bump
  output or Geometry, and `reconnect_nested_group_inputs` skips it. For `CUSTOM` it is the
  below-layers normal stream and is declared and forwarded like `Color` or `Roughness`.
- `Vector`: stays with the mapping leg (FR-7). The outer instance is fed by the vector path, the
  nested `Start` carries it inward, and both the declaration and the mapping node exist only while
  the user group declares a `Vector` input (removing it removes both).
- `Alpha`: a group input literally named `Alpha` has no same-named `Start` socket (the layer stream
  is `Color Alpha`), so it is left unlinked rather than inventing a source.

Group swap / Make Unique while nested: `set_custom_layer_group` assigns `source.node_tree` inside
the nested tree, then `check_all_layer_channel_io_and_nodes` runs the declaration before
`reconnect_layer_nodes` forwards, so the new group's sockets are declared in the same pass that
changes them and the outer links are restored after the interface change. Covered by
`tests/test_nested_source.py::TestNestedCustomSource` (forwarding, `Normal`/`Alpha`/`Vector`,
swap + Make Unique, and a rendered CUSTOM-vs-NOISE parity at the 2/255 tolerance).


### 2.6 `ui.py`, `Layer.py`, menus

- `YLayer` (`Layer.py:6022`): `custom_group : PointerProperty(type=bpy.types.NodeTree)` near the
  other source props (ADR-0002).
- `YNewLayer` / `YReplaceLayerType`: `group_name`, `create_new_group`; an `invoke` dialog offering
  "pick existing / generate starter" (both scriptable, FR-1/FR-3/FR-31).
- Add Layer menu + Replace Layer Type menu: direct entry, **no preference gate** (Q4).
- Layer panel: group name + a `Make Unique` button; starter-group creation in the same row.
- Channel row: warning icon when `get_custom_layer_warning` is non-empty (FR-10); channel-source
  menu already lists outputs through `get_available_source_outputs`.
- Missing-group state on the layer row with a relink action (FR-16).

### 2.7 `bake_common.py`

- `is_join_objects_problematic()`: `CUSTOM` returns problematic (FR-21, ADR-0004) with the existing
  console-notice style.
- No other change: emission baking and bake-target assignment are already type-agnostic.

### 2.8 Type-set rule

**Default membership for `CUSTOM` is "whatever `NOISE` has", applied site by site.** Deviations are
listed here and must be committed with a one-line reason at the call site:

| Site | CUSTOM | Why |
|---|---|---|
| `is_mapping_possible` | conditional on `Vector` input | FR-7, FR-18 |
| `is_layer_using_vector` | conditional on `Vector` input | FR-7 |
| `check_layer_source_tree` (nesting) | in, like NOISE | FR-27; the nested pass now declares and forwards the group's inputs (see §2.5). A *baked* CUSTOM layer stays out: the bake path is IMAGE-typed and has no custom input contract |
| `is_join_objects_problematic` | `True` | ADR-0004 |
| `replace_layer_type` source cache | never cached | referenced group, nothing to cache |
| `check_layer_divider_alpha` | out | IMAGE/VCOL only |
| `has_layer_input_options` | like NOISE (in) | per-channel gamma must behave like NOISE (FR-27) |
| `bake_common.py:3656` (bake-to-layer target) | out | destination must be IMAGE (non-goal) |

Every touched site gets an entry either in this table or in a `# CUSTOM:` comment, satisfying NFR-4.

## 3. Data flow

**Create:** menu → `add_new_layer(type='CUSTOM', custom_group=…)` → `check_layer_source` sets
`source.node_tree` → `reconnect_layer_nodes` wires `Vector` (if declared) and the channel inputs →
channel defaults bound by name → `reconnect_yp_nodes` splices the layer into each channel.

**Edit a channel binding:** menu → `ch.socket_input_name` → `reconnect_layer_nodes` for that layer.

**Edit the user's group:** depsgraph update → `get_custom_interface_signature` differs →
`sync_custom_layers` → re-bind (fallback if bound name gone) → reconnect + rearrange → cache
updated before rewiring, so the update the reconnect causes is a no-op.

**Bake:** unchanged path — channel end value → emission output → render into the target. The
custom layer is just part of the value.

## 4. Error handling and fallbacks

| Situation | Behaviour |
|---|---|
| `custom_group` is `None`, deleted, or empty | layer stays; source node exists with no tree; channels fall through as if the layer were disabled; layer row shows "missing group"; relink action available. No `print`, no traceback. |
| Group has no compatible outputs | same as above, warning names the reason (FR-2 picker already prevents creating it this way). |
| Bound socket removed | `socket_input_name` falls back to first compatible output; channel row warns until re-bound (FR-10). |
| Socket retyped to shader | treated as removed (the name no longer appears in the compatible set). |
| Group references the material's own yp node | excluded from the picker (`yp.is_ypaint_node`), and `sync_custom_layers` refuses to descend into it, so no recursion. |
| Nested source tree loses a forwarded input | reconnect skips the missing socket; no stale link is left (FR-11's assertion covers this). |
| Sync raises inside the depsgraph handler | caught, reported once per group per session through the report path, and the group's signature is left stale so the next update retries (never a silent permanent break). |

## 5. Guardrails

**No pull requests to the upstream project. This is absolute.**

- `origin` = the user's fork (`vpkoskinen/ucupaint`); `upstream` = `ucupumar/ucupaint`.
- Never run `gh pr create`, `gh pr merge`, `gh pr edit`, `gh repo fork`, `gh pr view --repo
  ucupumar/ucupaint`, or `git push upstream …` on this feature. **Only the user opens a PR, and
  only after saying so explicitly in that session.** Agreement to implement, to commit, or to test
  is not permission to open a PR.
- `gh` has `upstream` recorded as its resolved base (`gh-resolved = base` in `.git/config`), so a
  default `gh pr create` would target ucupumar/ucupaint with no further prompt. Treat `gh pr` as
  forbidden rather than relying on remembering to pass `--repo`.
- Pushes, if any, go to `origin` on the `customnodes` branch only. No force-push.
- The user tests in pieces, from this worktree, on their fork. Work arrives as local commits.

Other rules for the implementing session:

- One task = one reviewable commit; each task must leave Blender loadable and the existing tests
  green, so the feature can be tried incrementally.
- Never `git commit --amend` or rebase a commit the user may already have tested.
- No version bump in feature commits (`bl_info` and `blender_manifest.toml` stay at 3.0.0 until a
  release task says otherwise).
- No source edit outside the listed files without updating this plan first.

## 6. Documentation deliverables

| Artifact | Content | When |
|---|---|---|
| `docs/architecture.md` | system map **as it is before the feature** (§1–§6), plus design intent (§7) | **first**, before any source change, so the map is not written from the finished diff |
| `AGENTS.md` | ≤ ~100 lines: build/run/test, conventions, folder map, pointers into `docs/`, the no-PR rule | alongside, so detail stays in `docs/` and the contract stays short |
| ADR-0001…0004 | the four irreversible choices, each with rejected alternatives | with this plan |
| `README`/wiki | not in scope; note the feature in the release notes when the user releases | later, user-driven |

`AGENTS.md` must stay a contract, not a manual: anything longer than a rule goes into
`docs/architecture.md` and is linked.

## 7. Verification strategy

- **Scripted** (`tests/`, run inside Blender): socket filtering (FR-4), default binding (FR-9),
  fallback on rename (FR-10), live re-sync after add/remove/rename (FR-11), no re-wire on default
  value edits (FR-12), idempotent refresh (FR-14), missing group (FR-16), starter group shape
  (FR-31/FR-32), bake pixel values (FR-19).
- **Manual** (a reviewer who did not write it): the §6 acceptance checklist, including the two
  Blender-version rows.
- **Parity** (FR-23…FR-30): each row is checked against an otherwise identical `NOISE` layer in the
  same scene. This is the cheapest defence against the type-set risk (R1).
- Test invocation: the repository has no runner. Task T-2 establishes and records the exact command
  in `AGENTS.md` (candidate: `blender --background --python-expr` driving `unittest` over
  `tests/`), verified against the extension build (4.2+) and one legacy build. Until T-2 lands, the
  plan does not claim a command.

## 8. Task sequencing (detail in `tasks.md`)

| # | Task | Delivers |
|---|---|---|
| T-1 | `docs/architecture.md` as-is | system map before code |
| T-2 | `AGENTS.md` incl. verified test invocation | project contract |
| T-3 | `CUSTOM` type registration + picker (`get_custom_group_candidates`) + Add/Replace menus | FR-1, FR-2, FR-3 |
| T-4 | Source creation, socket filter, channel default binding | FR-4, FR-5, FR-9 |
| T-5 | Input wiring (`Vector`, channels, `Alpha`) | FR-6, FR-7 |
| T-6 | Live re-sync + Refresh fallback + warning UI | FR-10 to FR-14 |
| T-7 | Integrity: pointer, missing group, unique, paste, undo | FR-15 to FR-18 |
| T-8 | Bake: pixel tests + merged-bake policy + use_baked notice | FR-19 to FR-22 |
| T-9 | Parity sweep over the type sets (FR-23…FR-30) + nesting/`refresh_source_tree_ios` | FR-27 and the table |
| T-10 | Starter group generation + Make Unique + panel polish | FR-31, FR-32 |
| T-11 | Acceptance run on two Blender versions, checklist filed | §6 |

T-9 is deliberately late and broad: it is the task that will find the wrong type-set decisions, and
it needs everything else in place to be checkable.

## 9. Risks

- **R1 (dominant) — type sets.** Mitigated by the default-to-NOISE rule, the deviation table, the
  parity tests, and one task dedicated to sweeping them.
- **R2 — resync loop.** Mitigated by update-cache-before-rewire and FR-13's observable check.
- **R3 — nesting (`refresh_source_tree_ios`).** Forwarding inputs through a generated interface is
  the fiddliest part; the documented fallback (skip nesting for CUSTOM) is a deliberate downgrade.
- **R4 — perf.** Signature per depsgraph update; NFR-2 budget. Measure in T-6, not at the end.
- **R5 — user expectation.** A group that assumes per-object data will bake wrong; ADR-0004 accepts
  this and FR-21 keeps the failure mode visible rather than silent.
