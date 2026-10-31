# 0001 — A custom node is a layer source, bound by socket name

Date: 2026-10-30
Status: accepted
Spec: `docs/specs/001-custom-node-layer/spec.md`

## Context

Issue #90 asks for user-authored node groups to drive ucupaint channels. Ucupaint's layer is
already an abstraction: a *source node* inside a layer tree whose named outputs the layer's
channels bind to (`ch.socket_input_name`), with masks, blending, modifiers, preview and baking
built around that. The question is which layer of the system a custom node attaches to.

## Decision

A custom node group is a **new layer type** (`CUSTOM`), instantiated as the layer's source node.
Its outputs are bound per channel through the existing `ch.socket_input_name` mechanism, and its
inputs are matched by name to the incoming channel streams (`Start[<channel>]`) and `Vector`.

Binding is by socket name in both directions. `Alpha` and `Colors Alpha`-style names are reserved
by the existing convention.

## Rejected alternatives

- **A modifier type (`mod.type = 'CUSTOM'`).** Cheap, but a modifier transforms one rgb+alpha pair
  at a time; it cannot introduce a normal, a height or a second channel. The issue's premise —
  colour, roughness and metallic driven by one graph — is impossible.
- **A channel override (`ch.override_type = 'CUSTOM'`).** Channel-scoped by construction, so the
  user would have to duplicate the graph per channel. Kept as a possible phase 2 for the narrow
  "replace this one channel" case.
- **Free-form nodes around the layer group node.** Maximum freedom, but it breaks the invariant
  that channels are the only contract between layers (architecture I1): masks, blending, baked
  substitution and the preview/bake emission path all assume the layer group node is the boundary.
  It would also make bake correctness unverifiable.
- **A separate "custom" node outside the stack, wired into the material.** Loses masks, stack
  order, and every per-channel feature; users can already do this by hand, which is the status quo
  the issue complains about.
- **Explicit per-socket mapping UI instead of name matching.** More robust to renames, but it
  doubles the UI and contradicts how every other source already works (`socket_input_name` is
  already name-based, with a documented fallback). Robustness is instead bought with live re-sync
  (ADR-0003) and a visible fallback warning.

## Consequences

- The ~71 `layer.type in {…}` sets must each take a position on `CUSTOM` (spec NFR-4). This is the
  bulk of the work and the main source of silent bugs.
- Users get all layer features for free, including baking (with the caveats in ADR-0004).
- Socket names become a user-facing API for the first time: renaming an output in the user's group
  is a supported, non-destructive operation thanks to live re-sync.
