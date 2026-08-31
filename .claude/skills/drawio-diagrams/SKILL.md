---
name: drawio-diagrams
description: >-
  Create editable draw.io / diagrams.net (.drawio) diagrams, either from a
  codebase or from a written description. Use this whenever someone wants a
  picture of how something works — "diagram this repo", "draw the data flow",
  "make a flowchart", "architecture diagram", "architecture picture",
  "visualize this codebase", "map out the services", "show how X connects to
  Y", "chart the request path" — and for any named diagram type: sequence
  diagram, ER diagram, class diagram, state machine, C4 diagram, network
  diagram, data pipeline, swimlane diagram, org chart, dependency graph.
  Also use it for explicit draw.io work: .drawio or .xml diagram files,
  diagrams.net, mxfile / mxGraph XML, and for editing, fixing, decompressing,
  or validating an existing .drawio file. Produces uncompressed XML the user
  can open and rearrange by hand.
---

# draw.io diagrams

Produces `.drawio` files that a person can open in diagrams.net and edit —
real shapes with real geometry, not an image. Output is always **uncompressed
XML** so it diffs in git and can be inspected.

Two scripts do the work that breaks hand-written diagrams: coordinate math and
XML escaping. Do not hand-write `.drawio` XML for anything past a couple of
boxes — use the builder.

## Workflow

**1. Decide the diagram type and confirm scope.**
Which question does this diagram answer? "How does a request become an order?"
is a diagram; "the system" is not. If the user asked for something broad, name
the one or two pages you plan to draw and check before building.

**2. Gather the content.**
- *From a codebase:* read `references/codebase-discovery.md` first. Deployment
  descriptors and entrypoints, then outbound calls — **not** the folder tree.
  Confirm the node list with the user before generating; a wrong service name
  is the first thing they will notice.
- *From a description:* extract the nouns (nodes) and verbs (edges). Ask about
  anything you would otherwise invent. Never draw an edge you cannot justify.

**3. Pick conventions.** `references/diagram-types.md` has the shape vocabulary,
direction, and edge-labelling rules per type. Follow the convention for the
type — readers already know it.

**4. Write a JSON spec and build.**

```bash
python .claude/skills/drawio-diagrams/scripts/build_drawio.py spec.json \
    -o diagram.drawio --geometry
```

**5. Validate. Always.**

```bash
python .claude/skills/drawio-diagrams/scripts/validate_drawio.py diagram.drawio
```

Nonzero exit means the file is broken — fix it before handing it over. Use
`--strict` to treat warnings (overlaps, dangling edges) as failures too.

**6. Read the `--geometry` output** before declaring victory: layers, sizes, and
group membership. A node in a surprising layer means an edge is wrong.

**7. Hand it over** with a one-line summary of what each page shows, plus any
edges you inferred rather than verified.

## Spec format

```json
{
  "pages": [{
    "name": "Order path",
    "direction": "vertical",
    "nodes": [
      {"id": "gw",  "label": "API gateway",  "shape": "service",   "color": "blue"},
      {"id": "svc", "label": "orders-svc\n(Go)", "shape": "component", "color": "green"},
      {"id": "pg",  "label": "PostgreSQL",   "shape": "database",  "color": "purple"},
      {"id": "key", "label": "Dashed = async", "shape": "note", "color": "yellow",
       "x": 900, "y": 40}
    ],
    "edges": [
      {"from": "gw",  "to": "svc", "label": "POST /orders"},
      {"from": "svc", "to": "pg",  "label": "read/write"},
      {"from": "svc", "to": "gw",  "label": "202 accepted", "dashed": true}
    ],
    "groups": [
      {"id": "core", "label": "EKS: prod-1", "members": ["gw", "svc"], "color": "gray"}
    ]
  }]
}
```

A single page can be the top-level object — `pages` is only needed for several.

- **shapes**: `process` `component` `service` `start` `end` `decision`
  `database` `queue` `external` `cloud` `actor` `note` `document` `package`
- **colors**: `blue` `green` `yellow` `orange` `red` `purple` `gray` `white`
  `none` — draw.io's own palette, so output looks native
- **node overrides**: `layer` (pin the rank), `x`/`y` (absolute, skips layout —
  for legends and notes), `width`/`height`, `style` (raw draw.io style string,
  replaces the preset entirely)
- **edges**: `label`, `dashed`, `color`, `style`
- **groups**: become real swimlane containers; members are reparented, so
  dragging the lane in the app moves everything inside it. One group per node.
- `\n` in a label becomes a line break; `&`, `<`, `>` are escaped for you.

Unknown shapes and colors, and edges pointing at missing nodes, fail the build
with a message naming the valid options — the spec is wrong, not the diagram.

Also available: `--decompress in.drawio -o out.drawio` inflates a file saved in
draw.io's default compressed format so it can be read and edited.

## Scope

**8–20 nodes per page.** Below 8 a diagram rarely earns its place; above 20 it
stops being readable. **Above 25, split into pages** — by deployment boundary,
by subsystem, or by zoom level (C4 context → containers). Multiple focused
pages beat one wall chart every time.

Cut before you draw: collapse every instance of a thing into one node, leave
out infrastructure that touches everything (logging, metrics, secrets) unless
the diagram is *about* it, and drop anything the reader's question does not
depend on. A node that could be deleted without changing the answer should be.

## Quality bar

Before handing a diagram over:

- Validator passes.
- Every node's label names something real in the system — a service, a
  datastore, an actor. No boxes labelled "Services" or "Business Logic".
- Every non-obvious edge is labelled with what actually crosses it: protocol,
  operation, format, cadence. Every edge out of a `decision` is labelled.
- Colour means one thing on the page, and a `note` says what if it is not
  obvious.
- Groups match deployment boundaries, not source folders.
- No node sits inside a group it does not belong to (the builder pushes them
  clear; the validator fails if one slipped through).
- Nothing is inferred silently — inferred edges are dashed, noted, and called
  out to the user.
- The page reads in one direction, top-to-bottom or left-to-right.

## Reference files

Read the relevant one before building; do not work from memory on style strings.

| File | Read it when |
| --- | --- |
| `references/diagram-types.md` | choosing shapes, direction, and edge labels for a given type — architecture, C4, flowchart, sequence, ER, state machine, network, data pipeline, class, org chart |
| `references/codebase-discovery.md` | the diagram comes from a repo: what to read, in what order, and the finding→element mapping |
| `references/layout.md` | the layout looks wrong, or you need `layer`/pin overrides, spacing, and group behaviour |
| `references/xml-format.md` | hand-editing XML, custom styles, cloud provider icons (AWS/Azure/GCP), UML class and sequence styles, escaping, waypoints, compressed files |
| `assets/template.drawio` | a hand-written starting point showing a swimlane, containers, a note, waypoints, and fixed connection points across two pages |
