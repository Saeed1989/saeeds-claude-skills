#!/usr/bin/env python3
"""Build uncompressed draw.io (.drawio) XML from a JSON diagram spec.

Why this exists: hand-written draw.io XML breaks on two things every time --
coordinate math (overlapping boxes, swimlanes that swallow unrelated nodes) and
XML escaping (& < > in labels, newlines silently collapsing under html=1).
This script owns both.

Usage:
  build_drawio.py spec.json -o out.drawio
  build_drawio.py spec.json -o out.drawio --geometry     # print computed layout
  build_drawio.py --decompress in.drawio -o out.drawio   # inflate a compressed file

Spec (single page):
  {
    "name": "Page title",
    "direction": "vertical" | "horizontal",
    "nodes": [{"id": "a", "label": "A", "shape": "process", "color": "blue"}],
    "edges": [{"from": "a", "to": "b", "label": "calls"}],
    "groups": [{"id": "g1", "label": "Cluster", "members": ["a", "b"]}]
  }

Multi-page: {"pages": [ <page>, <page>, ... ]}

Standard library only.
"""

import argparse
import base64
import json
import re
import sys
import urllib.parse
import zlib
from xml.sax.saxutils import escape, quoteattr

# --------------------------------------------------------------------------
# Presets
# --------------------------------------------------------------------------

# draw.io's own default palette (the swatches in its Style panel), so output
# looks native rather than hand-tinted.  fill / stroke / font.
COLORS = {
    "blue":   ("#dae8fc", "#6c8ebf", "#000000"),
    "green":  ("#d5e8d4", "#82b366", "#000000"),
    "yellow": ("#fff2cc", "#d6b656", "#000000"),
    "orange": ("#ffe6cc", "#d79b00", "#000000"),
    "red":    ("#f8cecc", "#b85450", "#000000"),
    "purple": ("#e1d5e7", "#9673a6", "#000000"),
    "gray":   ("#f5f5f5", "#666666", "#333333"),
    "white":  ("#ffffff", "#000000", "#000000"),
    "none":   ("none",    "#000000", "#000000"),
}

# name -> (style fragment, default width, default height)
SHAPES = {
    "process":   ("rounded=0;whiteSpace=wrap;html=1;", 160, 60),
    "component": ("html=1;shape=module;align=left;spacingLeft=24;whiteSpace=wrap;", 180, 70),
    "service":   ("rounded=1;arcSize=12;whiteSpace=wrap;html=1;", 170, 60),
    "start":     ("ellipse;whiteSpace=wrap;html=1;", 120, 60),
    "end":       ("ellipse;whiteSpace=wrap;html=1;strokeWidth=3;", 120, 60),
    "decision":  ("rhombus;whiteSpace=wrap;html=1;", 160, 90),
    "database":  ("shape=cylinder3;boundedLbl=1;backgroundOutline=1;size=15;"
                  "whiteSpace=wrap;html=1;", 150, 90),
    "queue":     ("shape=process;whiteSpace=wrap;html=1;backgroundOutline=1;size=0.1;", 170, 60),
    "external":  ("rounded=1;whiteSpace=wrap;html=1;dashed=1;", 170, 60),
    "cloud":     ("ellipse;shape=cloud;whiteSpace=wrap;html=1;", 180, 110),
    "actor":     ("shape=umlActor;verticalLabelPosition=bottom;verticalAlign=top;"
                  "html=1;outlineConnect=0;", 40, 70),
    "note":      ("shape=note;whiteSpace=wrap;html=1;size=18;", 160, 80),
    "document":  ("shape=document;whiteSpace=wrap;html=1;boundedLbl=1;", 160, 80),
    "package":   ("shape=folder;tabWidth=70;tabHeight=20;tabPosition=left;"
                  "whiteSpace=wrap;html=1;", 180, 100),
}

# Shapes whose label sits outside the box: do not grow the box for the text.
FIXED_SIZE_SHAPES = {"actor"}

GROUP_STYLE = ("swimlane;whiteSpace=wrap;html=1;startSize={hdr};"
               "fillColor={fill};strokeColor={stroke};"
               "horizontal=1;fontStyle=1;verticalAlign=top;")

EDGE_STYLE = "edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;jettySize=auto;orthogonalLoop=1;"

# --------------------------------------------------------------------------
# Geometry constants
# --------------------------------------------------------------------------

MARGIN = 40          # page margin
LAYER_GAP = 90       # space between layers
NODE_GAP = 50        # space between nodes inside a layer
CHAR_W = 8           # approx px per character at the default 12px font
LINE_H = 20
PAD_X = 34
PAD_Y = 26
MIN_W = 120
MIN_H = 50
MAX_W = 320
GROUP_PAD = 24       # gap between group border and its members
GROUP_HDR = 34       # swimlane title bar height
GROUP_CLEAR = 30     # gap forced between a group box and a non-member node
MAX_RELAX = 200      # bound on layer relaxation passes (cycle safety)


class SpecError(Exception):
    """Raised for anything the author can fix in the spec."""


def die(msg):
    raise SpecError(msg)


# --------------------------------------------------------------------------
# Labels
# --------------------------------------------------------------------------

def label_html(text):
    """Escape XML, then turn newlines into <br>.

    html=1 (which every preset sets) means the renderer collapses raw newlines,
    so a literal newline in a label silently becomes a space.  Order matters:
    escape first, otherwise the <br> tags we insert get escaped too.
    """
    if text is None:
        return ""
    out = escape(str(text))
    out = out.replace("\r\n", "\n").replace("\r", "\n")
    return out.replace("\n", "<br>")


def label_lines(text):
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")


def size_for(node):
    """Size a box from its label, clamped, and rounded to a 10px grid."""
    shape = node["shape"]
    _frag, dw, dh = SHAPES[shape]
    lines = label_lines(node.get("label"))

    if node.get("width"):
        w = int(node["width"])
    elif shape in FIXED_SIZE_SHAPES:
        w = dw
    else:
        longest = max((len(line) for line in lines), default=0)
        w = min(MAX_W, max(dw, MIN_W, longest * CHAR_W + PAD_X))
        w = int(round(w / 10.0) * 10)

    if node.get("height"):
        h = int(node["height"])
    elif shape in FIXED_SIZE_SHAPES:
        h = dh
    else:
        # long single lines wrap inside the clamped width
        usable = max(1, w - PAD_X)
        wrapped = sum(max(1, -(-len(line) * CHAR_W // usable)) for line in lines) or 1
        h = max(dh, MIN_H, wrapped * LINE_H + PAD_Y)
        h = int(round(h / 10.0) * 10)
    return w, h


def node_style(node):
    if node.get("style"):
        return node["style"]          # raw passthrough, the author owns it
    frag = SHAPES[node["shape"]][0]
    fill, stroke, font = COLORS[node["color"]]
    return "{}fillColor={};strokeColor={};fontColor={};".format(frag, fill, stroke, font)


# --------------------------------------------------------------------------
# Layering
# --------------------------------------------------------------------------

def feedback_edges(nodes, edges):
    """Indices of edges that close a cycle (DFS back edges).

    Layering has to ignore these.  A retry loop pointing back at an earlier
    service is a real edge worth drawing, but if it feeds the longest-path
    calculation it pushes its own target one layer deeper on every pass, and
    everything downstream inherits the inflation -- the diagram ends up as a
    staircase.  Iterative DFS, so a deep graph cannot blow the stack.
    """
    order = [n["id"] for n in nodes]
    out = {nid: [] for nid in order}
    for i, e in enumerate(edges):
        if e["from"] != e["to"]:
            out[e["from"]].append((i, e["to"]))

    indeg = {nid: 0 for nid in order}
    for e in edges:
        if e["from"] != e["to"]:
            indeg[e["to"]] += 1
    roots = [nid for nid in order if indeg[nid] == 0] + order   # sources first

    WHITE, GRAY, BLACK = 0, 1, 2
    state = {nid: WHITE for nid in order}
    back = set()
    for root in roots:
        if state[root] != WHITE:
            continue
        stack = [(root, iter(out[root]))]
        state[root] = GRAY
        while stack:
            node, it = stack[-1]
            advanced = False
            for idx, nxt in it:
                if state[nxt] == GRAY:
                    back.add(idx)
                elif state[nxt] == WHITE:
                    state[nxt] = GRAY
                    stack.append((nxt, iter(out[nxt])))
                    advanced = True
                    break
            if not advanced:
                state[node] = BLACK
                stack.pop()
    return back


def assign_layers(nodes, edges):
    """Longest path from source nodes, cycle-safe.

    Back edges are dropped first (see feedback_edges), leaving a DAG.  Every
    node then starts at layer 0 and relaxation repeatedly enforces
    layer[v] >= layer[u]+1 for each remaining edge u->v, which converges to the
    longest-path layering in at most V passes.  The pass count is capped
    regardless, so a graph that still contains a cycle -- self loops, or one
    the DFS ordering missed -- ends up stacked in a stable order rather than
    hanging the build.  An explicit `layer` on a node pins it and is never
    relaxed.
    """
    layer = {n["id"]: 0 for n in nodes}
    pinned = {n["id"]: int(n["layer"]) for n in nodes if n.get("layer") is not None}
    layer.update(pinned)

    back = feedback_edges(nodes, edges)
    forward = [e for i, e in enumerate(edges) if i not in back]

    cap = min(MAX_RELAX, max(4, len(nodes) + 2))
    for _ in range(cap):
        changed = False
        for e in forward:
            u, v = e["from"], e["to"]
            if u == v or v in pinned:
                continue
            if layer[v] < layer[u] + 1:
                layer[v] = layer[u] + 1
                changed = True
        if not changed:
            break

    if layer:
        lo = min(layer.values())
        if lo:
            for k in layer:
                layer[k] -= lo
    return layer


def order_within_layer(nodes_in_layer, edges, layer, placed):
    """Order a layer by the mean position of already-placed predecessors.

    A cheap barycenter pass -- not full crossing minimisation, but it keeps
    edges from criss-crossing in the common fan-out / fan-in shapes.
    """
    preds = {}
    for e in edges:
        preds.setdefault(e["to"], []).append(e["from"])
    index = {n["id"]: i for i, n in enumerate(nodes_in_layer)}

    def key(n):
        ps = [p for p in preds.get(n["id"], []) if layer.get(p, 0) < layer[n["id"]]]
        ps = [p for p in ps if p in placed]
        if not ps:
            return (1, float(index[n["id"]]))
        return (0, sum(placed[p] for p in ps) / len(ps))

    return sorted(nodes_in_layer, key=key)


# --------------------------------------------------------------------------
# Layout
# --------------------------------------------------------------------------

def layout(nodes, edges, direction):
    """Place every node.  vertical = layers are rows; horizontal = columns."""
    vertical = direction == "vertical"
    placed = {}                        # node id -> centre on the cross axis
    layer = assign_layers(nodes, edges)
    for n in nodes:
        n["_layer"] = layer[n["id"]]
        n["_w"], n["_h"] = size_for(n)

    by_layer = {}
    for n in nodes:
        by_layer.setdefault(n["_layer"], []).append(n)

    def extent(group):
        if vertical:
            return sum(n["_w"] for n in group) + NODE_GAP * (len(group) - 1)
        return sum(n["_h"] for n in group) + NODE_GAP * (len(group) - 1)

    widest = max((extent(g) for g in by_layer.values()), default=0)
    main = float(MARGIN)
    for idx in sorted(by_layer):
        row = order_within_layer(by_layer[idx], edges, layer, placed)
        by_layer[idx] = row
        cross = MARGIN + (widest - extent(row)) / 2.0
        depth = max((n["_h"] if vertical else n["_w"]) for n in row)
        for n in row:
            if vertical:
                n["_x"] = cross
                n["_y"] = main + (depth - n["_h"]) / 2.0
                placed[n["id"]] = cross + n["_w"] / 2.0
                cross += n["_w"] + NODE_GAP
            else:
                n["_y"] = cross
                n["_x"] = main + (depth - n["_w"]) / 2.0
                placed[n["id"]] = cross + n["_h"] / 2.0
                cross += n["_h"] + NODE_GAP
        main += depth + LAYER_GAP

    # Pin overrides last: an explicit x/y wins over everything computed above.
    for n in nodes:
        if n.get("x") is not None:
            n["_x"] = float(n["x"])
        if n.get("y") is not None:
            n["_y"] = float(n["y"])

    for n in nodes:
        n["_x"] = int(round(n["_x"]))
        n["_y"] = int(round(n["_y"]))
    return by_layer


def bbox(members):
    x0 = min(n["_x"] for n in members)
    y0 = min(n["_y"] for n in members)
    x1 = max(n["_x"] + n["_w"] for n in members)
    y1 = max(n["_y"] + n["_h"] for n in members)
    return x0, y0, x1, y1


def group_boxes(groups, node_by_id):
    """Bounding box of each group, padded, with room for the title bar."""
    boxes = []
    for g in groups:
        members = [node_by_id[m] for m in g["members"]]
        x0, y0, x1, y1 = bbox(members)
        boxes.append({
            "group": g,
            "members": members,
            "x": x0 - GROUP_PAD,
            "y": y0 - GROUP_PAD - GROUP_HDR,
            "w": (x1 - x0) + 2 * GROUP_PAD,
            "h": (y1 - y0) + 2 * GROUP_PAD + GROUP_HDR,
        })
    return boxes


def overlaps(ax, ay, aw, ah, bx, by, bw, bh, gap=0):
    return not (ax + aw + gap <= bx or bx + bw + gap <= ax or
                ay + ah + gap <= by or by + bh + gap <= ay)


def push_clear_of_groups(boxes, nodes, direction):
    """Move non-members out of every group box.

    A group spanning several layers is a tall rectangle, and any unrelated node
    that happens to land inside those layers is visually swallowed by it (and,
    worse, reads as a member).  Push such nodes sideways -- away from the
    group's centre -- and carry everything already further out in that
    direction along with them, so the shove cannot create a fresh overlap.
    """
    vertical = direction == "vertical"
    axis = "_x" if vertical else "_y"
    size = "_w" if vertical else "_h"
    bkey = "x" if vertical else "y"
    bsize = "w" if vertical else "h"
    moved = []

    for box in boxes:
        member_ids = {n["id"] for n in box["members"]}
        for n in nodes:
            if n["id"] in member_ids or n.get("_pinned"):
                continue
            if not overlaps(n["_x"], n["_y"], n["_w"], n["_h"],
                            box["x"], box["y"], box["w"], box["h"]):
                continue
            n_centre = n[axis] + n[size] / 2.0
            g_centre = box[bkey] + box[bsize] / 2.0
            if n_centre >= g_centre:
                sign = 1
                delta = (box[bkey] + box[bsize] + GROUP_CLEAR) - n[axis]
            else:
                sign = -1
                delta = (n[axis] + n[size] + GROUP_CLEAR) - box[bkey]
            delta = int(round(abs(delta)))
            if delta <= 0:
                continue
            frontier = n[axis]
            for other in nodes:
                if other["id"] in member_ids or other.get("_pinned"):
                    continue
                if sign > 0 and other[axis] >= frontier:
                    other[axis] += delta
                elif sign < 0 and other[axis] <= frontier:
                    other[axis] -= delta
            moved.append((n["id"], box["group"]["id"], sign * delta))
    return moved


def separate_groups(boxes, direction):
    """Keep group boxes off each other; members travel with their box."""
    vertical = direction == "vertical"
    axis = "_x" if vertical else "_y"
    bkey = "x" if vertical else "y"
    bsize = "w" if vertical else "h"
    ordered = sorted(boxes, key=lambda b: b[bkey])
    for i, a in enumerate(ordered):
        for b in ordered[i + 1:]:
            if not overlaps(a["x"], a["y"], a["w"], a["h"],
                            b["x"], b["y"], b["w"], b["h"]):
                continue
            delta = int(round((a[bkey] + a[bsize] + GROUP_CLEAR) - b[bkey]))
            if delta <= 0:
                continue
            b[bkey] += delta
            for m in b["members"]:
                m[axis] += delta


def normalise_origin(nodes, boxes):
    """Pull the drawing back on-canvas if pushes drove it past the margin.

    Only ever shifts down/right, and shifts pinned nodes too: a pin is a
    position within the drawing, so moving everything except the pins would
    change the very relationship the author pinned it to hold.
    """
    xs = [n["_x"] for n in nodes] + [b["x"] for b in boxes]
    ys = [n["_y"] for n in nodes] + [b["y"] for b in boxes]
    if not xs:
        return
    dx = max(0, MARGIN - min(xs))
    dy = max(0, MARGIN - min(ys))
    if dx == 0 and dy == 0:
        return
    for n in nodes:
        n["_x"] += dx
        n["_y"] += dy
    for b in boxes:
        b["x"] += dx
        b["y"] += dy


# --------------------------------------------------------------------------
# Spec normalisation / validation
# --------------------------------------------------------------------------

def normalise_page(page, page_index):
    where = "page {}".format(page_index + 1)
    if not isinstance(page, dict):
        die("{}: expected an object, got {}".format(where, type(page).__name__))

    direction = page.get("direction", "vertical")
    if direction not in ("vertical", "horizontal"):
        die("{}: direction must be 'vertical' or 'horizontal', got {!r}".format(
            where, direction))

    raw_nodes = page.get("nodes") or []
    if not raw_nodes:
        die("{}: has no nodes".format(where))

    nodes, seen = [], set()
    for i, rn in enumerate(raw_nodes):
        if "id" not in rn:
            die("{}: node #{} has no 'id'".format(where, i + 1))
        nid = str(rn["id"])
        if nid in seen:
            die("{}: duplicate node id {!r}".format(where, nid))
        seen.add(nid)
        shape = rn.get("shape", "process")
        if shape not in SHAPES:
            die("{}: node {!r} uses unknown shape {!r}.\n  Known shapes: {}".format(
                where, nid, shape, ", ".join(sorted(SHAPES))))
        color = rn.get("color", "blue")
        if color not in COLORS:
            die("{}: node {!r} uses unknown color {!r}.\n  Known colors: {}".format(
                where, nid, color, ", ".join(sorted(COLORS))))
        n = dict(rn)
        n["id"] = nid
        n["shape"] = shape
        n["color"] = color
        n["label"] = rn.get("label", nid)
        n["layer"] = rn.get("layer")
        n["_pinned"] = rn.get("x") is not None or rn.get("y") is not None
        nodes.append(n)

    node_ids = {n["id"] for n in nodes}
    edges = []
    for i, raw in enumerate(page.get("edges") or []):
        src = raw.get("from", raw.get("source"))
        dst = raw.get("to", raw.get("target"))
        if src is None or dst is None:
            die("{}: edge #{} needs both 'from' and 'to'".format(where, i + 1))
        src, dst = str(src), str(dst)
        for end in (src, dst):
            if end not in node_ids:
                die("{}: edge #{} ({} -> {}) references unknown node {!r}.\n"
                    "  Defined nodes: {}".format(
                        where, i + 1, src, dst, end, ", ".join(sorted(node_ids))))
        e = dict(raw)
        e["from"], e["to"] = src, dst
        edges.append(e)

    groups = []
    for i, rg in enumerate(page.get("groups") or []):
        gid = str(rg.get("id", "group{}".format(i + 1)))
        members = [str(m) for m in (rg.get("members") or [])]
        if not members:
            die("{}: group {!r} has no members".format(where, gid))
        missing = [m for m in members if m not in node_ids]
        if missing:
            die("{}: group {!r} references unknown node(s): {}".format(
                where, gid, ", ".join(missing)))
        color = rg.get("color", "gray")
        if color not in COLORS:
            die("{}: group {!r} uses unknown color {!r}.\n  Known colors: {}".format(
                where, gid, color, ", ".join(sorted(COLORS))))
        if gid in node_ids:
            die("{}: group id {!r} collides with a node id".format(where, gid))
        groups.append({"id": gid, "label": rg.get("label", gid),
                       "members": members, "color": color})

    claimed = {}
    for g in groups:
        for m in g["members"]:
            if m in claimed:
                die("{}: node {!r} is in two groups ({} and {}); a draw.io cell has "
                    "exactly one parent".format(where, m, claimed[m], g["id"]))
            claimed[m] = g["id"]

    return {"name": page.get("name") or page.get("title") or "Page-{}".format(page_index + 1),
            "direction": direction, "nodes": nodes, "edges": edges, "groups": groups}


def normalise_spec(spec):
    if isinstance(spec, list):
        pages = spec
    elif isinstance(spec, dict) and "pages" in spec:
        pages = spec["pages"]
        if not isinstance(pages, list) or not pages:
            die("'pages' must be a non-empty list")
    elif isinstance(spec, dict):
        pages = [spec]
    else:
        die("spec must be an object or a list of pages, got {}".format(type(spec).__name__))
    return [normalise_page(p, i) for i, p in enumerate(pages)]


# --------------------------------------------------------------------------
# XML emission
# --------------------------------------------------------------------------

def cell_id(page_index, raw):
    """Namespace ids per page so multi-page files never collide."""
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(raw))
    return "p{}-{}".format(page_index, safe)


def render_page(page, page_index):
    nodes, edges, groups = page["nodes"], page["edges"], page["groups"]
    node_by_id = {n["id"]: n for n in nodes}

    layout(nodes, edges, page["direction"])
    boxes = group_boxes(groups, node_by_id)
    separate_groups(boxes, page["direction"])
    boxes = group_boxes(groups, node_by_id)          # recompute after any shift
    push_clear_of_groups(boxes, nodes, page["direction"])
    boxes = group_boxes(groups, node_by_id)
    normalise_origin(nodes, boxes)

    parent_of = {}
    for b in boxes:
        for m in b["members"]:
            parent_of[m["id"]] = b

    cells = []
    for b in boxes:
        g = b["group"]
        fill, stroke, _font = COLORS[g["color"]]
        style = GROUP_STYLE.format(hdr=GROUP_HDR, fill=fill, stroke=stroke)
        cells.append(
            '        <mxCell id={cid} value={val} style={style} vertex="1" parent="1">\n'
            '          <mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry" />\n'
            '        </mxCell>'.format(
                cid=quoteattr(cell_id(page_index, g["id"])),
                val=quoteattr(label_html(g["label"])),
                style=quoteattr(style),
                x=b["x"], y=b["y"], w=b["w"], h=b["h"]))

    for n in nodes:
        box = parent_of.get(n["id"])
        if box:
            # A child cell's geometry is relative to its parent's top-left
            # corner -- the title bar included, which is why members were laid
            # out below it.  Absolute coords here would fling the node off into
            # the canvas instead of into the lane.
            parent = cell_id(page_index, box["group"]["id"])
            gx, gy = n["_x"] - box["x"], n["_y"] - box["y"]
        else:
            parent, gx, gy = "1", n["_x"], n["_y"]
        cells.append(
            '        <mxCell id={cid} value={val} style={style} vertex="1" parent={p}>\n'
            '          <mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry" />\n'
            '        </mxCell>'.format(
                cid=quoteattr(cell_id(page_index, n["id"])),
                val=quoteattr(label_html(n["label"])),
                style=quoteattr(node_style(n)),
                p=quoteattr(parent), x=gx, y=gy, w=n["_w"], h=n["_h"]))

    for i, e in enumerate(edges):
        style = e.get("style") or EDGE_STYLE
        if not e.get("style"):
            if e.get("dashed"):
                style += "dashed=1;"
            if e.get("color"):
                if e["color"] not in COLORS:
                    die("page {}: edge #{} uses unknown color {!r}.\n"
                        "  Known colors: {}".format(
                            page_index + 1, i + 1, e["color"], ", ".join(sorted(COLORS))))
                style += "strokeColor={};".format(COLORS[e["color"]][1])
        cells.append(
            '        <mxCell id={cid} value={val} style={style} edge="1" parent="1" '
            'source={s} target={t}>\n'
            '          <mxGeometry relative="1" as="geometry" />\n'
            '        </mxCell>'.format(
                cid=quoteattr(cell_id(page_index, "e{}".format(i))),
                val=quoteattr(label_html(e.get("label"))),
                style=quoteattr(style),
                s=quoteattr(cell_id(page_index, e["from"])),
                t=quoteattr(cell_id(page_index, e["to"]))))

    xml = (
        '  <diagram id={did} name={name}>\n'
        '    <mxGraphModel dx="1024" dy="768" grid="1" gridSize="10" guides="1" '
        'tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" '
        'pageWidth="850" pageHeight="1100" math="0" shadow="0">\n'
        '      <root>\n'
        '        <mxCell id="0" />\n'
        '        <mxCell id="1" parent="0" />\n'
        '{cells}\n'
        '      </root>\n'
        '    </mxGraphModel>\n'
        '  </diagram>'
    ).format(did=quoteattr("diagram-{}".format(page_index)),
             name=quoteattr(page["name"]),
             cells="\n".join(cells))
    return xml, boxes


def render(spec):
    pages = normalise_spec(spec)
    body, geo = [], []
    for i, page in enumerate(pages):
        xml, boxes = render_page(page, i)
        body.append(xml)
        geo.append((page, boxes))
    doc = ('<mxfile host="app.diagrams.net" agent="build_drawio.py" version="24.0.0" '
           'type="device">\n{}\n</mxfile>\n'.format("\n".join(body)))
    return doc, geo


# --------------------------------------------------------------------------
# Compressed files
# --------------------------------------------------------------------------

def decompress_file(text):
    """Inflate the deflate+base64 payload draw.io writes by default.

    The chain is: base64 -> raw deflate -> URL-encoded XML.  Files saved with
    "Uncompressed XML" already hold plain XML, so those pass straight through.
    """
    def repl(m):
        payload = m.group(2).strip()
        if payload.startswith("&lt;") or payload.startswith("<"):
            return m.group(0)
        try:
            raw = zlib.decompress(base64.b64decode(payload), -15)
        except Exception as exc:
            die("could not inflate <diagram> payload: {}".format(exc))
        inner = urllib.parse.unquote(raw.decode("utf-8"))
        return "{}\n{}\n{}".format(m.group(1), inner, m.group(3))

    if "<diagram" not in text:
        die("no <diagram> element found -- is this really a .drawio file?")
    return re.sub(r"(<diagram\b[^>]*>)(.*?)(</diagram>)", repl, text, flags=re.S)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def print_geometry(geo):
    for page, boxes in geo:
        print("page: {}  ({}, {} nodes, {} edges, {} groups)".format(
            page["name"], page["direction"], len(page["nodes"]),
            len(page["edges"]), len(page["groups"])))
        member_of = {}
        for b in boxes:
            for m in b["members"]:
                member_of[m["id"]] = b["group"]["id"]
        for b in boxes:
            print("  group {:<12} x={:>5} y={:>5} w={:>4} h={:>4}  members={}".format(
                b["group"]["id"], b["x"], b["y"], b["w"], b["h"],
                ",".join(m["id"] for m in b["members"])))
        for n in sorted(page["nodes"], key=lambda n: (n["_layer"], n["_x"], n["_y"])):
            print("  L{:<2} {:<14} x={:>5} y={:>5} w={:>4} h={:>4}  {:<10}{}".format(
                n["_layer"], n["id"], n["_x"], n["_y"], n["_w"], n["_h"], n["shape"],
                "in:" + member_of[n["id"]] if n["id"] in member_of else ""))
        print()


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Build uncompressed .drawio XML from a JSON spec.")
    ap.add_argument("spec", nargs="?", help="JSON spec file, or '-' for stdin")
    ap.add_argument("-o", "--output", help="output .drawio path (default: stdout)")
    ap.add_argument("--geometry", action="store_true",
                    help="print the computed layout after writing")
    ap.add_argument("--decompress", metavar="FILE",
                    help="inflate a compressed .drawio file instead of building one")
    args = ap.parse_args(argv)

    try:
        if args.decompress:
            with open(args.decompress, "r", encoding="utf-8") as fh:
                doc = decompress_file(fh.read())
            geo = []
        else:
            if not args.spec:
                ap.error("a spec file is required (or use --decompress)")
            if args.spec == "-":
                spec = json.load(sys.stdin)
            else:
                with open(args.spec, "r", encoding="utf-8") as fh:
                    spec = json.load(fh)
            doc, geo = render(spec)
    except SpecError as exc:
        sys.stderr.write("error: {}\n".format(exc))
        return 2
    except ValueError as exc:                      # includes JSONDecodeError
        sys.stderr.write("error: bad spec: {}\n".format(exc))
        return 2
    except OSError as exc:
        sys.stderr.write("error: {}\n".format(exc))
        return 2

    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(doc)
        sys.stderr.write("wrote {}\n".format(args.output))
    else:
        sys.stdout.write(doc)
    if args.geometry and geo:
        print_geometry(geo)
    return 0


if __name__ == "__main__":
    sys.exit(main())
