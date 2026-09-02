# draw.io XML format

Everything here describes **uncompressed** `.drawio` XML — the format
`build_drawio.py` emits and the only one you can edit by hand.

## 1. File skeleton

```xml
<mxfile host="app.diagrams.net" agent="drawio-diagrams" version="24.0.0" type="device">
  <diagram id="page-1" name="Architecture">
    <mxGraphModel dx="1024" dy="768" grid="1" gridSize="10" guides="1" tooltips="1"
                  connect="1" arrows="1" fold="1" page="1" pageScale="1"
                  pageWidth="850" pageHeight="1100" math="0" shadow="0">
      <root>
        <mxCell id="0" />
        <mxCell id="1" parent="0" />
        <!-- every shape and connector goes here -->
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
```

`<mxCell id="0">` is the model root and `<mxCell id="1" parent="0">` is the
default layer. **Both are mandatory.** Omit either and draw.io opens a blank
canvas with no error — the single most common way a generated file "silently
fails". Every top-level shape sets `parent="1"`.

`id` values must be unique **within a page**. Across pages they may repeat, but
namespacing them (`p0-api`, `p1-api`) keeps copy-paste between pages safe;
`build_drawio.py` does this automatically.

## 2. Vertices

```xml
<mxCell id="api" value="api-gateway" style="rounded=1;whiteSpace=wrap;html=1;"
        vertex="1" parent="1">
  <mxGeometry x="280" y="160" width="170" height="60" as="geometry" />
</mxCell>
```

- `value` — the label (HTML when the style sets `html=1`, which it should).
- `style` — semicolon-separated `key=value` pairs; a bare token like `ellipse`
  or `rhombus` selects a built-in shape.
- `as="geometry"` on `mxGeometry` is required. Without it the shape has no size
  and does not render.
- Width/height must both be > 0.

## 3. Edges

```xml
<mxCell id="e1" value="POST /orders"
        style="edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;"
        edge="1" parent="1" source="gw" target="orders">
  <mxGeometry relative="1" as="geometry" />
</mxCell>
```

- `source` / `target` hold the **id of a cell**, not its label. An id that does
  not exist yields an edge dangling in space at that end.
- `parent="1"` — keep edges on the default layer even when both endpoints live
  inside a container. Parenting an edge to a swimlane makes its geometry
  relative to that lane and it drifts.
- `<mxGeometry relative="1" as="geometry" />` is the standard empty geometry;
  the router computes the path.

Useful edge style keys:

| Key | Effect |
| --- | --- |
| `edgeStyle=orthogonalEdgeStyle` | right-angle routing (default choice) |
| `edgeStyle=elbowEdgeStyle` | single elbow |
| `edgeStyle=entityRelationEdgeStyle` | ER-style stepped routing |
| `curved=1` | curved path |
| `rounded=1` | rounded corners on right angles |
| `dashed=1` | dashed line (async, external, optional) |
| `startArrow=none` / `endArrow=none` | suppress an arrowhead |
| `endArrow=block;endFill=0` | hollow triangle (UML inheritance) |
| `endArrow=open` | thin open arrow (UML return / dependency) |
| `endArrow=diamondThin;endFill=1;endSize=24` | filled diamond (composition) |
| `startArrow=diamondThin;startFill=0` | hollow diamond (aggregation) |
| `strokeColor=#b85450` | line colour |
| `strokeWidth=2` | line weight |
| `labelBackgroundColor=#ffffff` | keeps a label legible over a crossing line |

## 4. Containers (swimlanes) and the relative-coordinate gotcha

A container is a vertex with `swimlane` in its style; children set
`parent="<container id>"`.

```xml
<mxCell id="core" value="Core services" style="swimlane;startSize=34;html=1;"
        vertex="1" parent="1">
  <mxGeometry x="140" y="500" width="460" height="150" as="geometry" />
</mxCell>
<mxCell id="orders" value="orders-svc" style="rounded=0;html=1;"
        vertex="1" parent="core">
  <mxGeometry x="24" y="58" width="180" height="70" as="geometry" />
</mxCell>
```

**A child's `x`/`y` are relative to its parent's top-left corner, not to the
page.** `orders` above sits at absolute `(164, 558)`. Two consequences:

1. Reparenting a node into a lane means *subtracting* the lane's origin from
   its coordinates. Leaving absolute coordinates in place flings the shape far
   off into the canvas — often outside the visible page, which reads as "the
   shape vanished".
2. The origin includes the title bar. `startSize=34` means a child with `y=0`
   is hidden **behind** the header; children need `y >= startSize` plus padding.

`build_drawio.py` handles both; `validate_drawio.py` resolves the parent chain
before checking overlaps, precisely because raw x/y from two different
coordinate spaces compare as nonsense.

Related container keys: `startSize=0` (no title bar), `horizontal=0` (vertical
lane, title down the left edge), `collapsible=0`, `container=1` (allow drops).

## 5. Escaping

`value` is an XML attribute that draw.io then interprets as HTML (`html=1`).
Text therefore passes through **two** decoders, so it needs two rounds of
escaping. To display `a & b <tag>`:

| You want to display | Put this in the file | Why |
| --- | --- | --- |
| `&` | `&amp;amp;` | XML decode → `&amp;` → HTML decode → `&` |
| `<` | `&amp;lt;` | same chain |
| `>` | `&amp;gt;` | same chain |
| `"` inside an attribute | `&quot;` | closes the attribute otherwise |
| line break | `&lt;br&gt;` | XML decode → `<br>` → HTML break |
| literal `<br>` as text | `&amp;lt;br&amp;gt;` | |
| non-breaking space | `&amp;nbsp;` | |

Single-escaped `&lt;` in `value` becomes a real `<` at the HTML stage, so
`&lt;edge&gt;` renders as an unknown empty tag and the text disappears.

**Newlines**: `html=1` collapses raw newlines to spaces. A multi-line label
must use `&lt;br&gt;`. This is why the builder converts `\n` for you.

`style` attribute values are escaped once (plain XML) — they are never parsed
as HTML.

## 6. Shape presets used by `build_drawio.py`

| `shape` | Style fragment | Default w×h |
| --- | --- | --- |
| `process` | `rounded=0;whiteSpace=wrap;html=1;` | 160×60 |
| `component` | `html=1;shape=module;align=left;spacingLeft=24;whiteSpace=wrap;` | 180×70 |
| `service` | `rounded=1;arcSize=12;whiteSpace=wrap;html=1;` | 170×60 |
| `start` | `ellipse;whiteSpace=wrap;html=1;` | 120×60 |
| `end` | `ellipse;whiteSpace=wrap;html=1;strokeWidth=3;` | 120×60 |
| `decision` | `rhombus;whiteSpace=wrap;html=1;` | 160×90 |
| `database` | `shape=cylinder3;boundedLbl=1;backgroundOutline=1;size=15;` | 150×90 |
| `queue` | `shape=process;backgroundOutline=1;size=0.1;` | 170×60 |
| `external` | `rounded=1;dashed=1;whiteSpace=wrap;html=1;` | 170×60 |
| `cloud` | `ellipse;shape=cloud;whiteSpace=wrap;html=1;` | 180×110 |
| `actor` | `shape=umlActor;verticalLabelPosition=bottom;verticalAlign=top;` | 40×70 |
| `note` | `shape=note;size=18;whiteSpace=wrap;html=1;` | 160×80 |
| `document` | `shape=document;boundedLbl=1;whiteSpace=wrap;html=1;` | 160×80 |
| `package` | `shape=folder;tabWidth=70;tabHeight=20;tabPosition=left;` | 180×100 |

## 7. Colour presets

These are draw.io's own default swatches — the pairs its Style panel offers —
so generated files look like someone drew them in the app rather than picking
arbitrary hexes.

| `color` | fill | stroke | font |
| --- | --- | --- | --- |
| `blue` | `#dae8fc` | `#6c8ebf` | `#000000` |
| `green` | `#d5e8d4` | `#82b366` | `#000000` |
| `yellow` | `#fff2cc` | `#d6b656` | `#000000` |
| `orange` | `#ffe6cc` | `#d79b00` | `#000000` |
| `red` | `#f8cecc` | `#b85450` | `#000000` |
| `purple` | `#e1d5e7` | `#9673a6` | `#000000` |
| `gray` | `#f5f5f5` | `#666666` | `#333333` |
| `white` | `#ffffff` | `#000000` | `#000000` |
| `none` | `none` | `#000000` | `#000000` |

Fill and stroke are a matched pair; mixing one preset's fill with another's
stroke is what makes a diagram look hand-tinted.

## 8. Waypoints and fixed connection points

Waypoints force a route through specific coordinates (absolute, page space):

```xml
<mxCell id="e9" style="edgeStyle=orthogonalEdgeStyle;html=1;" edge="1" parent="1"
        source="reject" target="validate">
  <mxGeometry relative="1" as="geometry">
    <Array as="points">
      <mxPoint x="180" y="200" />
    </Array>
  </mxGeometry>
</mxCell>
```

Use them sparingly — one waypoint to steer a feedback edge around a column of
boxes is good; a hand-plotted path for every edge is unmaintainable, and any
later move of a node leaves the route stale.

Fixed connection points pin *where* on the shape an edge attaches, as a
fraction of width/height:

```
exitX=1;exitY=0.5;exitDx=0;exitDy=0;   /* leave at right edge, mid-height */
entryX=0;entryY=0.5;entryDx=0;entryDy=0; /* arrive at left edge, mid-height */
```

`exitDx`/`exitDy` must be present (both `0`) or draw.io ignores the constraint.
Fixed points matter for decision diamonds — pin *yes* to one side and *no* to
the other so the branches never swap on a re-route.

## 9. AWS / Azure / GCP shape keys

Cloud icons live in stencil libraries addressed through `shape=mxgraph.<lib>.<name>`.
Enable the library in the app's shape panel (More Shapes ▸ Networking) before
expecting the icons to appear in the UI; the XML renders regardless.

**AWS (aws4 — the current set).** Two forms. Resource icons:

```
sketch=0;outlineConnect=0;fontColor=#232F3E;gradientColor=#F78E04;
gradientDirection=north;fillColor=#D05C17;strokeColor=#ffffff;dashed=0;
verticalLabelPosition=bottom;verticalAlign=top;align=center;html=1;fontSize=12;
aspect=fixed;shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.lambda;
```

Swap `resIcon` for the service: `mxgraph.aws4.ec2`, `.s3`, `.rds`, `.lambda`,
`.sqs`, `.sns`, `.dynamodb`, `.api_gateway`, `.cloudfront`, `.elastic_load_balancing`,
`.ecs`, `.eks`, `.fargate`, `.kinesis`, `.step_functions`, `.secrets_manager`.
The gradient/fill pair encodes the service *category* colour (compute orange
`#D05C17`, storage green `#7AA116`, database blue `#3334B9`, networking purple
`#8C4FFF`, integration pink `#E7157B`) — keep icons in one category consistent.

Group/boundary boxes (VPC, subnet, account) are containers:

```
sketch=0;points=[[0,0],[0.25,0],[0.5,0],[0.75,0],[1,0],[1,0.25],[1,0.5],[1,0.75],
[1,1],[0.75,1],[0.5,1],[0.25,1],[0,1],[0,0.75],[0,0.5],[0,0.25]];outlineConnect=0;
gradientColor=none;html=1;whiteSpace=wrap;fontSize=12;fontStyle=0;container=1;
collapsible=0;pointerEvents=0;fillColor=none;dashed=0;verticalAlign=top;
align=left;spacingLeft=30;shape=mxgraph.aws4.group;
grIcon=mxgraph.aws4.group_vpc;strokeColor=#8C4FFF;fontColor=#8C4FFF;
```

`grIcon` variants: `group_vpc`, `group_aws_cloud`, `group_region`,
`group_security_group`, `group_auto_scaling_group`, `group_account`.

**Azure (azure2).** `shape=mxgraph.azure2.<category>.<service>`, e.g.
`mxgraph.azure2.compute.function_apps`, `mxgraph.azure2.databases.sql_database`,
`mxgraph.azure2.integration.service_bus`, `mxgraph.azure2.storage.storage_accounts`,
`mxgraph.azure2.networking.application_gateways`. Typical wrapper:

```
sketch=0;points=[[0,0,0],[0.25,0,0],[0.5,0,0],[0.75,0,0],[1,0,0]];
aspect=fixed;html=1;align=center;verticalLabelPosition=bottom;verticalAlign=top;
shape=mxgraph.azure2.compute.function_apps;
```

**GCP (gcp2).** `shape=mxgraph.gcp2.<name>` for icons —
`mxgraph.gcp2.cloud_run`, `.cloud_functions`, `.pubsub`, `.cloud_sql`,
`.bigquery`, `.gke`, `.cloud_storage`, `.cloud_load_balancing` — with
`fillColor=#4284F3` (or the product's colour) and the same
`verticalLabelPosition=bottom;verticalAlign=top;aspect=fixed` wrapper. Project
and zone boundaries use `shape=mxgraph.gcp2.<something>_card` containers, or a
plain dashed rectangle, which is usually cleaner.

Stencil names drift between draw.io releases. If an icon renders as a blank
box, draw the shape once in the app, then **right-click ▸ Edit Style** and copy
the exact string — that is the authoritative source, not memory. When in doubt,
a labelled `service` rectangle in the right colour communicates fine; a diagram
full of missing-icon squares does not.

## 10. UML class and sequence styles

**Class box** — a stack-layout swimlane whose children are the rows:

```xml
<mxCell id="cls" value="OrderService"
        style="swimlane;fontStyle=1;childLayout=stackLayout;horizontal=1;
               startSize=26;horizontalStack=0;resizeParent=1;resizeParentMax=0;
               html=1;whiteSpace=wrap;collapsible=0;marginBottom=0;"
        vertex="1" parent="1">
  <mxGeometry x="80" y="80" width="200" height="112" as="geometry" />
</mxCell>
<mxCell id="cls-f1" value="- repo: OrderRepo"
        style="text;strokeColor=none;fillColor=none;align=left;verticalAlign=top;
               spacingLeft=4;spacingRight=4;overflow=hidden;
               points=[[0,0.5],[1,0.5]];portConstraint=eastwest;rotatable=0;"
        vertex="1" parent="cls">
  <mxGeometry y="26" width="200" height="26" as="geometry" />
</mxCell>
<mxCell id="cls-div"
        style="line;strokeWidth=1;fillColor=none;align=left;verticalAlign=middle;
               spacingTop=-1;spacingLeft=3;spacingRight=3;rotatable=0;
               labelPosition=right;points=[];portConstraint=eastwest;"
        vertex="1" parent="cls">
  <mxGeometry y="52" width="200" height="8" as="geometry" />
</mxCell>
<mxCell id="cls-m1" value="+ place(o: Order): Receipt"
        style="text;strokeColor=none;fillColor=none;align=left;verticalAlign=top;
               spacingLeft=4;spacingRight=4;overflow=hidden;
               points=[[0,0.5],[1,0.5]];portConstraint=eastwest;rotatable=0;"
        vertex="1" parent="cls">
  <mxGeometry y="60" width="200" height="26" as="geometry" />
</mxCell>
```

Rows carry only `y`/`width`/`height` — the stack layout owns `x`. The parent's
height must equal the sum of its rows (26 header + 26 per row + 8 divider) or
the box shows a gap.

Relationship arrows: inheritance `endArrow=block;endSize=16;endFill=0;html=1;`,
implementation the same plus `dashed=1`, composition
`endArrow=diamondThin;endFill=1;endSize=24;html=1;`, aggregation the same with
`endFill=0`, dependency `endArrow=open;endSize=12;dashed=1;html=1;`.
Multiplicities go on the edge's child labels or in the edge `value`.

**Sequence lifeline** — a container whose dashed stem is drawn by the perimeter:

```xml
<mxCell id="ll" value="orders-svc"
        style="shape=umlLifeline;perimeter=lifelinePerimeter;whiteSpace=wrap;
               html=1;container=1;dropTarget=0;collapsible=0;recursiveResize=0;
               outlineConnect=0;portConstraint=eastwest;size=40;"
        vertex="1" parent="1">
  <mxGeometry x="120" y="40" width="140" height="420" as="geometry" />
</mxCell>
```

`size=40` is the head-box height; `height` is how far down the page the
lifeline runs — make every lifeline on a page the same height. An activation
bar is a child of the lifeline:

```xml
<mxCell id="act" style="html=1;points=[];perimeter=orthogonalPerimeter;"
        vertex="1" parent="ll">
  <mxGeometry x="65" y="100" width="10" height="120" as="geometry" />
</mxCell>
```

(`x = width/2 - 5` centres it on the stem; `y` is relative to the lifeline top,
so it is measured from the head, not the page.)

Messages are edges between activation bars or lifelines, kept horizontal:
call `html=1;verticalAlign=bottom;endArrow=block;` ,
return `html=1;verticalAlign=bottom;endArrow=open;endSize=8;dashed=1;` ,
async `html=1;verticalAlign=bottom;endArrow=openThin;` ,
self-call adds `edgeStyle=orthogonalEdgeStyle;curved=0;` with two waypoints.
Time flows strictly downward: a message's `y` must exceed that of every message
before it, which is the one rule that makes a generated sequence diagram
readable.

## 11. Multi-page

Repeat `<diagram>` inside `<mxfile>`; each carries its own complete
`<mxGraphModel>` with its own `id="0"` / `id="1"` cells. `name` is the tab
label. Pages are independent — an edge cannot cross pages. To link pages, add a
shape with a page-link action:

```
link=data:page/id,<target diagram id>
```

## 12. Compressed files

draw.io's default save wraps each page's XML as **base64( raw-deflate(
url-encoded XML ) )** placed as the text of `<diagram>`. Such a file looks
like:

```xml
<diagram id="x" name="Page-1">7VtZk9o4EP41PCblAxsew...</diagram>
```

You cannot edit or diff that. Inflate it first:

```bash
python scripts/build_drawio.py --decompress in.drawio -o out.drawio
```

Always **write** uncompressed: it diffs in git, greps, and can be reviewed.
draw.io opens both, and its Extras ▸ Edit Diagram dialog shows the plain XML of
the current page for a quick manual check.
