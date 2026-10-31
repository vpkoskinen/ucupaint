# 0006 — Drop pre-4.2 Blender support in this fork

Date: 2026-10-31
Status: accepted
Spec: NFR-1 and §6 item 22 (amended 2026-10-31)

## Context

The add-on has claimed, and quietly carried, a much older floor than it tests:

- **The extension manifest already requires 4.2.** `blender_manifest.toml` has
  `blender_version_min = "4.2.0"`, so the Extension Platform has never served 2.7x–3.6 users; the
  manifest and the "compatibility" story disagree.
- **The other two claims are older still.** `bl_info["blender"]` is `(2, 80, 0)` and `README.md`
  said "all official versions of Blender starting from Blender 2.76", with a separate
  `blender_279` branch zipped into a `-blender_27x-legacy-` release artifact by
  `.github/workflows/main.yml`.
- **The old branches are unexecuted.** There are ~771 `is_bl_newer_than` guards across the
  package, and before this decision the test suite had only ever run on 5.2.3 LTS. The pre-4.0
  code paths (`tree.inputs`/`tree.outputs` instead of `tree.interface`) have no recent evidence
  behind them; they are dead weight that reads as a supported contract. (The sibling files
  `lib_281.blend` / `lib_282.blend` look similar but are *not* version-gated: they split the
  built-in groups by the API they were authored against, and every supported build loads them.)
- **The fork does not inherit the promise.** This is `vpkoskinen/ucupaint`, kept separate from
  `ucupaint/ucupaint` until upstream drops its own pre-4.x support. Upstream's compatibility
  promise is upstream's to make; a diverged fork that cannot test 2.8x–3.6 should not restate it.

The cost of keeping the claim is not the code — it is that every version-dependent decision has to
be reasoned about against builds nobody runs, and that a user on 3.6 can install a build that was
never verified there.

## Decision

The supported floor for this fork is **Blender 4.2 LTS**. Blender 2.7x, 2.8x and 3.x are not
supported.

The decision is policy; the metadata landed in its own change:

- `bl_info["blender"]` becomes `(4, 2, 0)`, in sync with `blender_version_min = "4.2.0"`.
- `.github/workflows/main.yml` stops checking out `blender_279` and stops publishing the
  `-blender_27x-legacy-` artifact.
- `README.md`, the spec (NFR-1, §6 item 22) and `AGENTS.md` state the 4.2 floor.

The two metadata bullets are `1d2c16c`; the documentation bullets are this change.

The metadata change alone is behaviour-neutral. The guard removal that follows from it is a
separate step, done once the floor was in place (see Consequences); `lib_281.blend` /
`lib_282.blend` are **not** touched, for the reason in the last Context bullet.

## Rejected alternatives

- **Keep 2.8x–3.6 supported.** The honest version of the current claim: actually run the suite on
  2.93 LTS and 3.6 LTS. Rejected because it costs a first pass of 3–4 weeks (finding and fixing
  4.x-isms that are currently invisible, plus the interface/asset splits) and then a permanent
  build matrix of 8–9 Blender versions, to maintain branches whose pre-4.0 halves are never
  executed in normal development. It also buys users a floor that the extension package cannot
  reach anyway.
- **Support 4.0/4.1 as best-effort.** Tempting as a hedge, but they are untested intermediate
  versions: not the LTS the manifest targets, not the current 5.x the suite runs on. "Best effort"
  here means "we think it works", which is the claim this ADR exists to stop making. The
  Extension Platform cannot serve them either, so the reachable population is small.
- **Drop the old builds from CI but keep the compatibility claim.** Zero work, but it leaves the
  docs promising 2.76 and `bl_info` accepting a 2.80 install, so users on 3.x get a build that
  was never run there — the silently-wrong outcome this change is meant to remove. *(Inferred
  alternative; not discussed in a commit.)*

## Consequences

- Users on 2.8x–3.6 keep whatever ucupaint build they already installed, and can still take
  upstream's builds; this fork simply stops claiming them. The README says so instead of burying
  it.
- **The floor is enforced by the manifest, not by `bl_info`.** `blender_version_min = "4.2.0"`
  makes the Extension Platform refuse an older Blender, but `bl_info["blender"]` is advisory:
  Blender warns about a below-minimum add-on and still enables it (Blender's own `userpref.py`, on
  a legacy zip install). So a 3.6 user can install by hand and get an unsupported build — the
  README is what tells them not to. Refusing outright would need a separate runtime
  `bpy.app.version` check in `register()`; deliberately not added here, because it changes
  behaviour on install rather than the support claim, and can come later if wanted.
- The pre-4.0 guards (~771 `is_bl_newer_than` calls, plus the `tree.inputs`/`tree.outputs`
  branches and the updater's `blender_279` branch) were removed in the cleanup commit that carries
  this paragraph: each guard was folded to the branch a 4.2+ build takes, and the dead branch was
  deleted. Guards that still matter inside the supported range (`4.3`, `4.5`, `5.x`) stay. The
  `lib_281.blend` / `lib_282.blend` files stay for the reason above — they are not legacy.
  - Two leftovers are deliberately kept and marked: `is_udim_supported()` (always `True`) and
    `is_tangent_sign_hacks_needed()` (always `False`, a 2.8x/2.9x feature whose node/vcol plumbing
    is still referenced from the source-tree and versioning code). Neither affects a supported
    build; removing the second is a feature removal, not a version-guard removal, and belongs to
    its own task.
- New work may assume 4.2+ APIs. Interface code should still go through the helpers in
  `input_outputs.py` until that cleanup lands, so the removal stays mechanical rather than
  spreading inline version checks.
- Because the floor is now tested, `NodeTreeInterface.new_socket` can be relied on for every
  supported build except the *type* differences that survive inside 4.2–5.2 (e.g.
  `NodeSocketMenu` is rejected before 5.0), which tests must probe rather than assume — see
  `6ce4e43`.
- The spec's cross-version acceptance line (item 22) is no longer "2.80 and 4.x" but "4.2 and the
  current 5.x", which is a requirement someone can actually run.

## Verification

Run 2026-10-31 from builds downloaded to `/tmp/opencode/blender-builds` (outside the repository):

| Build | Headless suite | Acceptance script | UI/undo (`./tests/run_ui.sh`) |
|---|---|---|---|
| 4.2.9 LTS | `Ran 159 tests … OK (skipped=4)`, exit 0 | 15/15 PASS | `Ran 159 tests … OK`, exit 0 |
| 4.5.9 LTS | `Ran 159 tests … OK (skipped=4)`, exit 0 | 15/15 PASS | `Ran 159 tests … OK`, exit 0 |
| 5.2.3 LTS (reference) | green | 15/15 PASS (recorded in `acceptance-5.2.3.md`) | green |

- No leftover Blender processes after any run.
- The add-on registers and builds its UI on 4.2.9 and 4.5.9: the suite's `addon_utils.enable` and
  `test_quicksetup.py` construct a real yp and its panels, so registration is exercised, not
  assumed.
- One 4.2/4.5-specific difference was found and fixed in a test, not in the add-on:
  `NodeTreeInterface.new_socket()` rejects `NodeSocketMenu` before 5.0, so
  `TestCustomSocketFilter` now probes the capability instead of assuming it (`6ce4e43`).
- The acceptance script's own save-and-reopen step (L13a) ran on each of the three builds.

**Not verified by this evidence:**

- GPU / EEVEE rendering — the suite and acceptance script render through the CPU path available
  headlessly.
- The separate undo acceptance script (`acceptance_5_2_3_undo.py`) on 4.2/4.5; the undo unit
  tests do run in the UI suite on both.
- Item 22's cross-build half (a file saved by 5.x opened in 4.2, and the reverse) — what ran is
  same-build save/reopen on each version. Item 22 therefore stays an open checklist requirement.
