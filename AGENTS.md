# AGENTS.md

Ucupaint: a Blender add-on (Python, `bpy`) that manages texture layers for Eevee and Cycles.
System map: [`docs/architecture.md`](docs/architecture.md). Specs: `docs/specs/`. Decisions:
`docs/decisions/`.

## This fork

This checkout is `vpkoskinen/ucupaint`, a personal fork of `ucupumar/ucupaint`. Nothing here is a
contribution vehicle for upstream, and nothing is ever sent to upstream:

- **Never push to `upstream` (`ucupumar/ucupaint`) and never open a pull request against it.** Not
  for a feature, not for a typo, not "while I'm here". `gh` resolves its PR base to `upstream` in
  this checkout, so treat every `gh pr` command as forbidden rather than passing `--repo` and
  hoping.
- **Only the user's own fork is a push target**: `origin` is `vpkoskinen/ucupaint` and is pushed
  only when the user asks for a push in that turn. Local commits are the default. Never
  force-push.
- **Pre-4.2 Blender is out of scope.** The fork targets Blender 4.2 LTS and newer (ADR-0006).
  Keeping 2.7x–3.6 working is not a goal and no work goes into it; upstream may keep its own older
  support, but that promise is not inherited here.

## Hard rules

- The user tests the feature in pieces from this checkout. One task = one reviewable commit, each
  leaving Blender loadable and the tests green.
- Never amend or rebase a commit the user may have already tested.
- No version bump in feature work: `bl_info` in `__init__.py` and `blender_manifest.toml` stay in
  sync and move only in a release task.

## Layout

| Path | Contents |
|---|---|
| `__init__.py` | `bl_info`, module import/reload list, `register()`/`unregister()`; a new module must be added to both lists |
| `common.py` | shared helpers; enums (`layer_type_items`, `mask_type_items`, `io_suffix`), socket/tree utilities, channel queries |
| `node_connections.py` | all wiring: `create_link`, `reconnect_yp_nodes` (per channel), `reconnect_layer_nodes` (per layer) |
| `layer_common.py`, `mask_common.py`, `modifier_common.py`, `channel_common.py` | creating and editing entities |
| `subtree.py`, `input_outputs.py` | per-entity subtree construction; the group-node interface (property tunnels, channel I/O) |
| `custom_node_common.py` | the `CUSTOM` layer source: starter group, group candidates/usability, dummy edit instances, live re-sync handler (signature cache, per-group throttle) |
| `ui.py`, `Layer.py`, `Mask.py`, `Root.py`, `Modifier.py`, `BakeTarget.py` | panels, menus, operators, `PropertyGroup`s |
| `bake_common.py`, `image_ops.py`, `UDIM.py`, `ImageAtlas.py` | baking and image plumbing |
| `versioning.py` | schema migrations, gated on `yp.version`, run from `load_post` |
| `lib.py`, `lib.blend` | built-in node groups, `~yPL ` prefix, created lazily, pruned when unused |
| `tests/` | `unittest` modules that import `bpy` |
| `docs/` | architecture, specs, ADRs |

## Running

The repository *is* the add-on directory. For development, link it into a Blender add-ons path —
`~/.config/blender/<version>/scripts/addons/ucupaint` — or install it as an extension (4.2+,
`blender_manifest.toml`). Edit in place; do not copy.

Tests import `bpy`, so they run inside Blender, not with a system Python. Run them from the
repository root:

```sh
blender --background --factory-startup --python tests/run_tests.py
```

`tests/run_tests.py` adds the repository's parent to `sys.path`, enables the package through
`addon_utils`, runs every `tests/test_*.py` module with `unittest` and exits 0 on success, 1 on
failure. `--factory-startup` is required: without it the user's enabled add-ons load first and
collide. The tests use the startup scene (active object `Cube`, material `Material`) and mutate it,
so do not point Blender at another file. Undo tests need a real window and are skipped headlessly;
run `tests/run_ui.sh` for those (`tests/run_ui.sh <script>` runs another UI script). UI suites
must go through that wrapper: a bare `xvfb-run blender` still opens a window on a Wayland desktop
and leaves it open on error. Never run `blender` without `--background` unless it is through
`tests/run_ui.sh`. See `tests/README.md`.

## Conventions

- **Node trees are a projection.** Properties are the source of truth; graphs are rebuilt by the
  `reconnect_*` passes. Never hand-wire nodes outside `node_connections.py`.
- **Names are the API.** Channel I/O is bound by socket name via `io_suffix` (`Alpha`, `Scale`,
  `Midlevel`, `UV`, `Tangent`, `Bitangent`, `Group`). No index-based binding.
- **`Alpha` is reserved.** A source output named `Alpha` feeds every channel's alpha; its absence
  means 1.0.
- **Type-dependent behaviour is a decision.** `layer.type in {…}` / `not in {…}` sets appear ~76
  times; each membership is a design statement about that type. Add a one-line reason at the site
  and a row in the plan's table.
- **Guard multi-step edits** with `yp.halt_reconnect` / `yp.halt_update`, and restore them in the
  same function.
- **Only edit trees you created.** Library groups are copied (`duplicate_lib_node_tree`) before
  edit; user-authored groups are never modified.
- **User data is written in exactly two places.** `create_starter_group` fills a newly created
  starter group once, and `yp_custom_dummy` nodes plus their frame are the only nodes added to a
  user material tree (ADR-0005). Never rewire user nodes or links.
- **Blender versions.** Support **4.2 LTS → current** (ADR-0006). Pre-4.2 is not supported by this
  fork, and nothing may reintroduce a claim for it. The pre-4.0 `is_bl_newer_than` guards and the
  `tree.inputs`/`tree.outputs` branches were removed in the ADR-0006 cleanup: assume 4.2+ APIs, and
  do not add version checks for versions the fork does not support. Interface work still goes
  through the helpers in `input_outputs.py`, never inline. `lib.blend`, `lib_281.blend` and
  `lib_282.blend` all stay: they split the built-in groups by the Blender API they were authored
  against (2.81 / 2.82), not by supported version, and every supported build loads all three.
- **Errors** go through the add-on's report path; no stray `print` in normal operation.
- Reference storage: prefer a `PointerProperty` for cross-tree references (see ADR-0002); do not
  convert existing name-based references.

## Docs

`docs/architecture.md` describes the system as it is — update it in the same commit as a change to
a component boundary or an invariant. Feature work gets a numbered folder in `docs/specs/`
(`spec.md`, `plan.md`, `tasks.md`); irreversible choices get an ADR with its rejected alternatives.
Keep this file short: if a rule needs a paragraph, it belongs in `docs/`, linked from here.
