# 0005 — Edit custom groups through dummy group instances

Date: 2026-10-30
Status: accepted
Spec: FR-33 (added 2026-10-30), FR-8, FR-16

## Context

A `CUSTOM` layer's source is a `ShaderNodeGroup` inside its layer tree. The user has to edit
that group — that is the point of the feature — but Blender's Shader Editor has no reliable
Python API for opening a node group that has no instance anywhere in a tree. A group referenced
only from a node that the user cannot see or reach is effectively uneditable.

The branch first shipped a `wm.y_edit_custom_group` operator and an *Edit Group* button. In real
use it reported success without changing the Shader Editor: `SpaceNodeEditor.node_tree` accepts a
tree of the wrong type without raising, assignment inside a `temp_override` whose `area` is the
target is silently discarded, and the available node-editor/window search is a best-effort
screen scan. It was removed.

The layer stores its group as a pointer (`ADR-0002`), so the group datablock survives, but the
pointer gives the user no editing entry point.

## Decision

Each material tree using a yp with at least one `CUSTOM` layer carries one **unconnected group
instance per referenced group**, inside a frame labelled exactly
`Custom Layers: edit here, do not connect`.

- Nodes are identified by the `yp_custom_dummy` property plus their `node_tree`, never by name;
  the frame by its property or its exact label.
- Two layers on one group share one instance; two groups get two.
- The instance has no links and never receives any. Its `node_tree` is the same datablock the
  layer's source points at, so Tabbing into it and editing a node changes the layer.
- Instances are created on layer creation, group change/relink, Make Unique, paste into another
  material and conversion to `CUSTOM`; they are pruned when no `CUSTOM` layer references the
  group any more (including conversion away from `CUSTOM`, live group deletion and removal of the
  ucupaint node). The frame is removed only when no node is parented to it.
- Nothing is added on file load. Opening an existing file never mutates it; a file gains its
  instances on the next creation or group-change path.
- The node carries no `label`, so its header follows the group datablock name across a rename.
- User nodes and links are never touched. The dummy is a convenience, never a rendering
  dependency.

## Rejected alternatives

- **`wm.y_edit_custom_group` operator that points an existing Shader Editor at the group.**
  Implemented and tried first. It can choose an editor and assign `space.node_tree`, but the
  success is unreliable in real use (overridden area, pinned editors, tree-type mismatch, multiple
  windows) and, worst case, reports `FINISHED` while the editor still shows another tree. A UI
  action that silently does nothing is worse than a visible node. Removed.
  *(Recorded in commits `7cbb52a` and `b4fd407`.)*
- **A dead `Node Group: <name>` label, leaving the user to add an instance manually.** Zero code
  and no API risk, but it makes the main workflow undiscoverable and every user builds a different
  workaround. The add-on can create the instance itself on the paths it already owns.
  *(Inferred design alternative; not recorded in a commit.)*
- **No edit affordance: require the user to keep an instance of the group in the tree.** Simpler,
  but a layer created from the picker has no instance, and deleting the last instance silently
  removes editing. It also breaks the "pick a library group and use it as a layer" story.
  *(Inferred design alternative; not recorded in a commit.)*
- **Put the dummy instances in the ucupaint `yp` tree.** The `yp` tree is a generated projection,
  rebuilt by the reconnect passes; user-visible nodes there would be cleaned or rewired, and it is
  not the tree the user edits when working on the material. The material tree is the correct
  boundary. *(Inferred design alternative; not recorded in a commit.)*

## Consequences

- User material files gain nodes that ucupaint owns. Every transition that can drop the last
  reference must prune them (`layer_common.add_new_layer`, `replace_layer_type`, `remove_layer`;
  `custom_node_common.set_custom_layer_group`, `make_group_unique`; the live handler on a group
  usability flip; `Root.YRemoveYPaintNode` through `remove_custom_group_dummies_from_tree`).
- The dummy is UI state stored in the scene. A user may move, rename, hide or delete it; a later
  creation/group-change path recreates a missing instance, and a sync never moves an existing one.
  The frame's hand-arranged position survives.
- Files saved by the briefly-shipped version may carry a `node.label`; the next dummy sync
  (creation/group-change path or prune) clears it so the header follows the group name again.
- Removing the workflow later requires deleting the dummy nodes and the frame from user files.
  This is why the choice is recorded: it is not a graph node that can be hidden behind a
  preference without a cleanup path.
- The alternative rejected in `ADR-0002` still holds: the pointer, not the dummy, is the layer's
  reference. Deleting a dummy never changes what the layer renders.
