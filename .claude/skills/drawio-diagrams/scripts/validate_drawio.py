#!/usr/bin/env python3
"""Validate a .drawio file before anyone opens it.

Catches the failures that make draw.io show a blank canvas, drop shapes, or
render a diagram that quietly says the wrong thing:

  errors    malformed XML; missing root cells id="0" / id="1"; duplicate ids;
            edges or parents pointing at ids that do not exist; vertices with
            no geometry or zero width/height; a node drawn on top of a
            swimlane it is not a child of (it reads as a member but is not)
  warnings  overlapping nodes; a child sticking out of its parent; edges with
            no source or target; empty pages

Exit status: 0 clean (warnings allowed), 1 errors found, 2 could not read the
file.  --strict turns warnings into errors.

Standard library only.
"""

import argparse
import sys
import xml.etree.ElementTree as ET

# A node may overlap a swimlane by this much before it counts as "inside" it.
SWIMLANE_TOLERANCE = 4
# Ignore hairline overlaps between siblings (rounding, deliberate touching).
OVERLAP_TOLERANCE = 2


class Report:
    def __init__(self):
        self.errors = []
        self.warnings = []

    def error(self, where, msg):
        self.errors.append((where, msg))

    def warn(self, where, msg):
        self.warnings.append((where, msg))


def is_true(cell, attr):
    return cell.get(attr) in ("1", "true")


def geometry_of(cell):
    for g in cell.findall("mxGeometry"):
        if g.get("as", "geometry") == "geometry":
            return g
    return None


def as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def collect_cells(diagram):
    """Every mxCell in a diagram, whatever depth it sits at."""
    return diagram.iter("mxCell")


def absolute_box(cid, boxes, parents, seen=None):
    """Resolve a cell's absolute position by walking up the parent chain.

    A child cell's geometry is relative to its parent's top-left corner, so an
    overlap check that reads raw x/y compares two different coordinate spaces
    and reports nonsense.
    """
    seen = seen or set()
    if cid in seen or cid not in boxes:
        return None
    seen.add(cid)
    x, y, w, h = boxes[cid]
    parent = parents.get(cid)
    if parent in ("0", "1", None) or parent not in boxes:
        return (x, y, w, h)
    pbox = absolute_box(parent, boxes, parents, seen)
    if pbox is None:
        return (x, y, w, h)
    return (pbox[0] + x, pbox[1] + y, w, h)


def rects_overlap(a, b, tol=0.0):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (ax + aw - tol <= bx or bx + bw - tol <= ax or
                ay + ah - tol <= by or by + bh - tol <= ay)


def validate_diagram(diagram, index, report):
    name = diagram.get("name") or "diagram {}".format(index + 1)
    where = "page '{}'".format(name)

    model = diagram.find("mxGraphModel")
    if model is None:
        # A compressed page holds base64 text rather than child elements.
        text = (diagram.text or "").strip()
        if text:
            report.error(where, "page holds compressed content, not XML. Inflate it "
                                "first: build_drawio.py --decompress FILE -o out.drawio")
        else:
            report.error(where, "no <mxGraphModel> element")
        return
    root = model.find("root")
    if root is None:
        report.error(where, "<mxGraphModel> has no <root>")
        return

    cells = list(collect_cells(root))
    ids, dupes = set(), set()
    for cell in cells:
        cid = cell.get("id")
        if cid is None:
            report.error(where, "an mxCell has no id attribute")
            continue
        if cid in ids:
            dupes.add(cid)
        ids.add(cid)
    for cid in sorted(dupes):
        report.error(where, "duplicate cell id '{}' -- draw.io keeps only one of "
                            "them".format(cid))

    for required, desc in (("0", "root cell"), ("1", "default layer")):
        if required not in ids:
            report.error(where, "missing mxCell id=\"{}\" ({}); the page opens "
                                "blank without it".format(required, desc))

    if not [c for c in cells if is_true(c, "vertex") or is_true(c, "edge")]:
        report.warn(where, "page has no vertices or edges")

    boxes, parents, vertices, swimlanes = {}, {}, [], []
    for cell in cells:
        cid = cell.get("id")
        if cid is None:
            continue
        parent = cell.get("parent")
        parents[cid] = parent
        # "0" and "1" are structural; if they are absent that is already
        # reported once above, and repeating it per cell buries everything else.
        if parent is not None and parent not in ids and parent not in ("0", "1"):
            report.error(where, "cell '{}' has parent '{}' which does not "
                                "exist".format(cid, parent))
        if not is_true(cell, "vertex"):
            continue
        geo = geometry_of(cell)
        if geo is None:
            report.error(where, "vertex '{}' has no <mxGeometry>; it will not "
                                "render".format(cid))
            continue
        w, h = as_float(geo.get("width")), as_float(geo.get("height"))
        if w <= 0 or h <= 0:
            report.error(where, "vertex '{}' has zero or missing size "
                                "(width={} height={})".format(
                                    cid, geo.get("width"), geo.get("height")))
            continue
        boxes[cid] = (as_float(geo.get("x")), as_float(geo.get("y")), w, h)
        vertices.append(cid)
        style = cell.get("style") or ""
        if "swimlane" in style or "shape=pool" in style:
            swimlanes.append(cid)

    for cell in cells:
        if not is_true(cell, "edge"):
            continue
        cid = cell.get("id")
        src, tgt = cell.get("source"), cell.get("target")
        for end, label in ((src, "source"), (tgt, "target")):
            if end is not None and end not in ids:
                report.error(where, "edge '{}' has {}='{}' but no cell with that id "
                                    "exists".format(cid, label, end))
        if src is None and tgt is None:
            report.warn(where, "edge '{}' is attached at neither end".format(cid))
        elif src is None or tgt is None:
            report.warn(where, "edge '{}' is dangling at its {}".format(
                cid, "source" if src is None else "target"))

    absolute = {}
    for cid in vertices:
        box = absolute_box(cid, boxes, parents)
        if box:
            absolute[cid] = box

    # A child that pokes out of its parent renders clipped or detached.
    for cid in vertices:
        parent = parents.get(cid)
        if parent in ("0", "1", None) or parent not in absolute or cid not in absolute:
            continue
        cx, cy, cw, ch = absolute[cid]
        px, py, pw, ph = absolute[parent]
        if cx < px - 1 or cy < py - 1 or cx + cw > px + pw + 1 or cy + ch > py + ph + 1:
            report.warn(where, "vertex '{}' extends outside its parent '{}'".format(
                cid, parent))

    # A node sitting on a swimlane it is not parented to reads as a member of
    # that lane while behaving as an outsider -- the diagram lies.
    lane_set = set(swimlanes)
    for lane in swimlanes:
        if lane not in absolute:
            continue
        lbox = absolute[lane]
        for cid in vertices:
            if cid == lane or cid in lane_set or cid not in absolute:
                continue
            ancestor, guard = parents.get(cid), 0
            inside = False
            while ancestor not in (None, "0", "1") and guard < 64:
                if ancestor == lane:
                    inside = True
                    break
                ancestor = parents.get(ancestor)
                guard += 1
            if inside:
                continue
            if rects_overlap(absolute[cid], lbox, SWIMLANE_TOLERANCE):
                report.error(where, "vertex '{}' is drawn over swimlane '{}' but is "
                                    "not a child of it".format(cid, lane))

    # Plain sibling overlaps: legible-diagram problem, not a broken file.
    ordered = [c for c in vertices if c in absolute and c not in lane_set]
    for i, a in enumerate(ordered):
        for b in ordered[i + 1:]:
            if parents.get(a) == b or parents.get(b) == a:
                continue
            if rects_overlap(absolute[a], absolute[b], OVERLAP_TOLERANCE):
                report.warn(where, "vertices '{}' and '{}' overlap".format(a, b))


def validate_file(path, report):
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        report.error(path, "malformed XML: {}".format(exc))
        return False
    except OSError as exc:
        report.error(path, str(exc))
        return False

    root = tree.getroot()
    if root.tag != "mxfile":
        report.error(path, "root element is <{}>, expected <mxfile>".format(root.tag))

    diagrams = root.findall("diagram") or ([root] if root.tag == "diagram" else [])
    if not diagrams:
        report.error(path, "no <diagram> pages found")
        return True

    seen_names = set()
    for i, diagram in enumerate(diagrams):
        name = diagram.get("name") or "diagram {}".format(i + 1)
        if name in seen_names:
            report.warn(path, "two pages are both named '{}'".format(name))
        seen_names.add(name)
        validate_diagram(diagram, i, report)
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate .drawio files.")
    ap.add_argument("files", nargs="+", help=".drawio file(s) to check")
    ap.add_argument("--strict", action="store_true",
                    help="treat warnings as errors")
    ap.add_argument("-q", "--quiet", action="store_true",
                    help="print only problems, not the OK line")
    args = ap.parse_args(argv)

    failed = False
    for path in args.files:
        report = Report()
        readable = validate_file(path, report)
        errors = list(report.errors)
        warnings = list(report.warnings)
        if args.strict:
            errors += warnings
            warnings = []

        for where, msg in errors:
            print("ERROR   {}: {}".format(where, msg))
        for where, msg in warnings:
            print("warning {}: {}".format(where, msg))

        if errors:
            failed = True
            print("FAIL    {} -- {} error(s), {} warning(s)".format(
                path, len(errors), len(warnings)))
        elif not args.quiet:
            print("OK      {} -- {} warning(s)".format(path, len(warnings)))
        if not readable:
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
