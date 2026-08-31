# Layout

How `build_drawio.py` places things, and how to steer it when the default is
wrong. Layout is what separates a diagram someone reads from one they squint
at and give up on.

## The algorithm, in order

1. **Drop back edges.** A DFS marks edges that close a cycle. They are still
   drawn, but they do not participate in layering — otherwise a retry loop
   pointing at an earlier service pushes its own target a layer deeper on every
   relaxation pass, and everything downstream inherits the inflation. A
   six-node flowchart with one loop comes out as a 26-layer staircase.
2. **Layer by longest path.** Every node starts at layer 0; relaxation enforces
   `layer(target) >= layer(source) + 1` until nothing changes. Longest path —
   not shortest — so a node sits below *every* one of its inputs, not just the
   first. The pass count is capped, so a cycle the DFS ordering missed
   degrades to a stable stack instead of hanging.
3. **Order within each layer** by the mean position of already-placed
   predecessors (barycenter). Cheap, and enough to stop fan-out/fan-in shapes
   from crossing themselves.
4. **Place** each layer as a centred row (vertical) or column (horizontal).
5. **Fit groups**, push non-members clear, then pull everything back on-canvas.

## Direction

| Diagram | Direction | Why |
| --- | --- | --- |
| Architecture, C4 | `vertical` | client at the top, storage at the bottom, the way people describe a stack |
| Flowchart, state machine | `vertical` | reading order matches control flow |
| Data pipeline, ETL | `horizontal` | sources → transforms → sinks reads left-to-right |
| Sequence | n/a | lifelines across the top, time down the page; hand-place |
| ER, class | `horizontal` | entities are peers, not stages |
| Org chart | `vertical` | reporting lines are a tree |

Deep-and-narrow graphs (a long pipeline) go `horizontal`; wide-and-shallow ones
(one gateway fanning out to twelve services) go `vertical`. Pick the direction
that makes the drawing closer to square — a 4000px-wide strip is unreadable on
any screen and unprintable on any page.

## Spacing

The defaults are tuned so edge labels have room and arrowheads do not collide
with borders:

| Constant | Value | Meaning |
| --- | --- | --- |
| `MARGIN` | 40 | page edge to first shape |
| `LAYER_GAP` | 90 | between layers — where edge labels live |
| `NODE_GAP` | 50 | between neighbours in a layer |
| `GROUP_PAD` | 24 | group border to its members |
| `GROUP_HDR` | 34 | swimlane title bar |
| `GROUP_CLEAR` | 30 | forced gap between a group box and an outsider |

Shrinking `LAYER_GAP` below ~70 makes labelled edges overlap the boxes they
connect. If a diagram feels cramped, cut nodes rather than gaps.

## Sizing

Box width comes from the longest label line (≈8px per character at the default
12px font) plus padding, clamped to 120–320px and rounded to the 10px grid so
shapes align. Height grows with line count, accounting for wrap inside the
clamped width. Set `width`/`height` explicitly only when you need shapes to
match exactly — a row of same-size boxes reads as a set of peers, which is
sometimes worth the manual override.

Labels over ~40 characters get clamped to 320px and wrap to three or more
lines, which throws the row's vertical rhythm off. Shorten the label instead:
a node is a name, not a sentence. Detail belongs in a `note` shape.

## Groups (swimlanes)

A group is a real draw.io container — members become **child cells**, so
dragging the lane in the app moves everything inside it. That is the point:
grouped output stays grouped when a human edits it.

Two consequences the builder handles for you:

- **Children are reparented to relative coordinates**, offset from the lane's
  top-left corner and below its title bar. Absolute coordinates on a child
  place it far off-canvas.
- **Non-members get pushed clear.** A group spanning three layers is a tall
  rectangle; any unrelated node that happens to land in those layers is
  visually swallowed by it and reads as a member. Such nodes are shoved
  sideways, away from the group's centre, carrying everything further out in
  that direction with them so the shove cannot create a fresh overlap.

Rules of thumb: keep members in adjacent layers (a group spanning layers 1 and
7 is a huge box mostly containing other people's nodes); one group per
deployment boundary, not per naming convention; no more than three or four
groups per page. A node can be in exactly one group — a draw.io cell has one
parent, so overlapping membership is rejected at spec time rather than
producing a mangled file.

## Escape hatches

| Field | Effect | Use when |
| --- | --- | --- |
| `layer: N` | pins the node to layer N, never relaxed | the algorithm ranks something wrong — e.g. a cache that should sit beside its service, not below it |
| `x` / `y` | absolute coordinates, layout skipped | legends, notes, titles — content that is not part of the graph |
| `width` / `height` | fixed size | matching a row of peers |
| `style` | replaces the generated style entirely | cloud-provider icons, custom shapes; you own the whole string, presets no longer apply |

Pinned nodes are excluded from the group-push pass — you asked for that
position, so nothing shoves them. If pushes drive the drawing past the page
margin, everything (pins included) shifts back on-canvas together; a pin fixes
a position *within* the drawing, so moving all but the pins would break the
very relationship you pinned it to hold.

## When the layout still looks wrong

Read the geometry rather than guessing: `--geometry` prints every node's layer,
position, size, and group membership.

| Symptom | Cause | Fix |
| --- | --- | --- |
| One layer far wider than the rest | a hub node fanning out to everything | split into pages, or group the fan-out |
| Node in a surprising layer | an edge you did not mean to draw | check the edge list; unverified edges are the usual culprit |
| Long edges crossing many layers | a shortcut edge (client → database) | keep it, but consider `dashed` so it reads as "bypass" |
| Everything in one layer | no edges | a diagram with no edges is a list; add the relationships or use a table |
| A staircase | a cycle plus pinned layers fighting | remove the `layer` pins and let back-edge detection work |
