# 0002 — Store the custom group as a PointerProperty, not a name

Date: 2026-10-30
Status: accepted
Spec: FR-15, FR-16, FR-17

## Context

Every existing cross-reference in ucupaint is a **string name**: `layer.source`, `layer.mapping`,
`layer.source_group`, `mod.group_tree`, `ch.bake_target_name`. Names are convenient (Blender keeps
them unique per data-block type) but they are resolved lazily every time, and they break on rename:
Blender renames the *new* owner of a name to `Name.001`, so a stale string silently points at the
wrong node, or at nothing.

A custom layer references a `ShaderNodeTree` — a data-block, not a node in the same tree. Spec
FR-15 requires the reference to survive renaming and save/reload *without an update handler*, and
FR-17 requires paste-between-materials to preserve it.

## Decision

`layer.custom_group` is a `PointerProperty(type=bpy.types.NodeTree)` on the layer, assigned when
the layer is created or retargeted. No name lookup, no rename handler.

## Rejected alternatives

- **String name + `bpy.data.node_groups.get(name)`.** Consistent with the rest of the codebase and
  simple, but: rename breaks it (FR-15 forbids the handler workaround), two materials can point at
  different trees with the same name after a partial copy, and copy/paste between materials needs
  custom remapping logic.
- **Name on the source node only (`source.node_tree` and nothing stored on the layer).** Tempting
  since the pointer already exists on the node, but the layer's source node is *recreated* on type
  changes, on nesting into a source tree, and on baked-source substitution — the reference must
  outlive the node, and the UI must be able to describe a layer whose group is missing.
- **Duplicating the tree per layer, always.** Removes the sharing question but makes "one library
  group used by twenty layers" impossible and silently multiplies a 200-node tree per layer.
  Rejected; *Make Unique* covers the case where independence is wanted.
- **Using the node group's `users` count as ownership.** Cannot distinguish "shared by two layers"
  from "used by the tree's own nested group instances", and gives no UI handle.

## Consequences

- Renaming the group is a no-op for ucupaint; the pointer follows.
- The pointer keeps the tree alive (users count), so a referenced group is never purged by
  `clean_unused_libraries` or on save. A layer that is deleted releases it.
- Reading `custom_group` can be `None` (deleted, unlinked, or an old file). All code paths must
  handle `None` before dereferencing: FR-16 defines the fallback.
- This is the one place where ucupaint's storage model diverges from every other reference. Record
  it here so the divergence is not "fixed" back to a string later.
