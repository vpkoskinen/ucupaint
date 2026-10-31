# 0003 — Live re-sync by interface signature on depsgraph update

Date: 2026-10-30
Status: accepted
Spec: FR-11 to FR-14

## Context

Channel bindings and input wiring are derived from the user group's sockets. When the user adds,
removes, renames or retypes a socket, the layer graph must be rebuilt. The requirement (FR-11) is
that this happens without a manual refresh and is perceived as immediate, which means it must be
driven by a Blender notification, not by a UI redraw of the ucupaint panel.

Blender gives add-ons three relevant hooks, and ucupaint already uses two of them:

- `bpy.app.handlers.depsgraph_update_post` — coarse, fires often, used by `Decal.py` for a narrow job.
- `bpy.msgbus.subscribe_rna` — fine-grained, but keyed on `(RNA type, property)`; ucupaint uses it
  only for node-socket `default_value` (`ui.py::yp_load_ui_msgbus_subscription`).
- `load_post` — file lifecycle only.

## Decision

A `depsgraph_update_post` handler compares a cheap **interface signature** per referenced group:
the ordered tuple of `(in_out, name, socket_type, enabled)`. Only when it differs from the cached
value does the handler run the sync (re-bind channels, rewire inputs, refresh nested source IO),
and it updates the cache *before* rewiring.

The sync is idempotent, so an extra run is harmless; the guard exists to keep it out of the update
path in the normal case and to make the loop impossible rather than unlikely.

## Rejected alternatives

- **`bpy.msgbus` on the node tree interface.** The precise tool, but notification behaviour for
  interface item add/remove/rename is not something we can rely on across the add-on's whole
  version range (2.80 → 4.x, including the pre-4.0 `tree.inputs`/`tree.outputs` model), and a
  missed notification means a silently wrong render. `depsgraph_update_post` plus a signature is
  version-independent and observable.
- **Manual refresh only.** Simplest and already specified as a fallback (FR-14), but it fails
  US-2: rename an output, see a wrong render, then discover a button.
- **Reacting to every depsgraph update unconditionally.** Correct but wasteful; with several
  custom layers it reconnects on every mouse move, and each reconnect dirties the tree.
- **Watching socket `default_value` too.** Explicitly rejected by FR-12: dragging a slider inside
  the user's group must not rebuild the layer graph.

## Consequences

- Cost is a signature tuple per referenced group per depsgraph update; budgeted in NFR-2.
- The signature cache is in-memory, keyed per `yp`. Undo can leave it stale, which at worst causes
  one redundant, idempotent sync — never a missed one, because a stale cache can only differ from
  the live interface, and a difference triggers the sync.
- The handler must be `@persistent` and registered on `register()`, and must never raise: an
  exception inside a depsgraph handler is visible as a broken frame, not a traceback the user can
  act on.
- Implementation cost lives in `custom_node_common.py`, not in `node_connections.py`, so the
  reconnect functions stay as they are.
