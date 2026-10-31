# 0004 — Bake policy for custom layers

Date: 2026-10-30
Status: accepted
Spec: FR-19 to FR-22, Q1 and Q2

## Context

Ucupaint bakes by rendering the channel's emission output into a target image or colour attribute.
Baking is therefore *not* type-aware: whatever the graph evaluates to is what lands in the texture.
That is what makes a custom layer bakeable at all (FR-19) — and it is also why the add-on's
existing "is this safe?" checks matter, because they were written against a closed set of sources
whose behaviour under these checks was known.

Two specific checks are affected:

- `bake_common.is_join_objects_problematic` decides whether the merged (multi-object) bake can run.
  It whitelists layer types that carry no UV/object-space dependency.
- `layer.use_baked` substitutes a baked image for the live source.

A custom group may contain anything: `Texture Coordinate`, `Object Info`, geometry nodes, a
`Noise Texture` (object-agnostic), or a random-per-sample node. ucupaint cannot know which.

## Decision

1. **Channel baking is supported** for custom layers, `RGB`/`VECTOR` and `VALUE` targets, with the
   existing subchannel assignment.
2. **Merged bake is conservatively disabled** whenever an enabled custom layer exists in the stack:
   `is_join_objects_problematic` returns `True` for `CUSTOM`. Per-object bakes are unaffected; the
   existing console notice tells the user why.
3. **`use_baked` keeps working**, and the UI states that the live custom graph is bypassed while it
   is on.

## Rejected alternatives

- **Static whitelist of "safe" node types** (allow merged bake when the group has no
  `Texture Coordinate`, `Object Info`, geometry or noise nodes). More useful, and wrong in the
  interesting cases: a group can reach object identity indirectly through a nested group, a driver,
  or an attribute whose data type differs per object, and `is_join_objects_problematic` is also the
  guard for mismatched attribute data types. A silent wrong bake is much worse to debug than a
  slower bake.
- **Baking disabled for custom layers.** Rejected by decision: the user asked for it, and emission
  baking is exactly the right mechanism.
- **Hiding `use_baked` for `CUSTOM`.** Less surprising at first glance, but it removes a legitimate
  workflow (bake a heavy graph once, then use the texture) and leaves a second code path to
  maintain. A visible notice is cheaper and honest.
- **Auto-purging a stale baked image when the group changes.** No way to know whether the change
  affects the baked channel; would delete user data speculatively.

## Consequences

- FR-21 is a deliberate performance regression for multi-object materials with custom layers, with
  a console explanation. Revisit only with evidence from a real scene.
- Bake verification (FR-19/20) is by pixel tolerance, not by comparing node graphs, because the
  group's internals are opaque to the add-on.
- A custom layer cannot be the *destination* of "bake to layer": `bake_common.py:3656` requires an
  `IMAGE` target, which still holds.
