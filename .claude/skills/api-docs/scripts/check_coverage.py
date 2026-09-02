#!/usr/bin/env python3
"""Cross-check a routes.json inventory against an OpenAPI spec.

    check_coverage.py routes.json openapi.json [--strict] [--json]

This exists because summarising a large codebase loses endpoints. A model that
reads 40 route files and writes a spec from memory will quietly drop three of
them, and nothing downstream notices -- the spec still validates, still renders
in Swagger UI, and is still wrong. Writing the inventory first and diffing it
against the spec turns that silent loss into a failed check.

  errors    a route found in code with no matching operation in the spec
            a malformed routes.json entry
  warnings  a spec path with no matching route (likely a deleted endpoint,
            or a route the discovery pass missed)
            an auth mismatch between the inventory and the spec

routes.json schema:

    [
      {"method": "POST", "path": "/v1/orders",
       "handler": "src/routes/orders.ts:createOrder", "auth": "bearer"}
    ]

`method` and `path` are required; `handler` and `auth` are optional but make
the report actionable. Path parameters may be written in any common framework
style -- :id, {id}, <int:id>, <id>, $id -- they are normalised before matching.

Exit status: 0 clean, 1 errors found, 2 could not read a file.

Standard library only. YAML support needs PyYAML; JSON always works.
"""

import argparse
import json
import os
import re
import sys

try:
    import yaml                      # type: ignore
    HAVE_YAML = True
except ImportError:
    HAVE_YAML = False

HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")

# :id | {id} | <int:id> | <id> | $id  ->  {}
PARAM_PATTERNS = (
    re.compile(r"\{[^}/]*\}"),        # {id}, {orderId}, {id:int} (Spring/OpenAPI)
    re.compile(r"<[^>/]*>"),          # <int:id>, <id>            (Flask/Django)
    re.compile(r":[A-Za-z_][\w-]*"),  # :id                       (Express/Rails/gin)
    re.compile(r"\$[A-Za-z_]\w*"),    # $id
)


def load_any(path):
    if not os.path.exists(path):
        sys.stderr.write("error: no such file: {}\n".format(path))
        raise SystemExit(2)
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    if path.lower().endswith((".yaml", ".yml")):
        if not HAVE_YAML:
            sys.stderr.write(
                "error: {} is YAML but PyYAML is not installed.\n"
                "  pip install pyyaml, or use a JSON copy of the spec.\n".format(path))
            raise SystemExit(2)
        try:
            return yaml.safe_load(text)
        except yaml.YAMLError as exc:
            sys.stderr.write("error: {} is not valid YAML: {}\n".format(path, exc))
            raise SystemExit(2)
    try:
        return json.loads(text)
    except ValueError as exc:
        sys.stderr.write("error: {} is not valid JSON: {}\n".format(path, exc))
        raise SystemExit(2)


def normalise_path(raw):
    """Framework path -> comparable shape: lowercase, no trailing slash, {} params."""
    path = str(raw or "").strip()
    if not path.startswith("/"):
        path = "/" + path
    for pattern in PARAM_PATTERNS:
        path = pattern.sub("{}", path)
    path = re.sub(r"/{2,}", "/", path)
    path = path.rstrip("/") or "/"
    return path.lower()


def spec_operations(spec):
    """(METHOD, normalised path) -> original 'METHOD /path' plus the operation."""
    out = {}
    paths = spec.get("paths") or {}
    if not isinstance(paths, dict):
        return out
    for url, item in paths.items():
        if not isinstance(item, dict):
            continue
        for method, op in item.items():
            if method.lower() not in HTTP_METHODS or not isinstance(op, dict):
                continue
            key = (method.upper(), normalise_path(url))
            out[key] = {"display": "{} {}".format(method.upper(), url), "op": op}
    return out


def operation_has_auth(op, spec):
    """Operation security wins; otherwise the document-level default applies."""
    block = op["security"] if "security" in op else (spec.get("security") or [])
    if not isinstance(block, list):
        return False
    # `security: []` on an operation explicitly opts out of the global default.
    return any(isinstance(req, dict) and req for req in block)


def check(routes, spec, report_errors, report_warnings):
    ops = spec_operations(spec)
    seen = set()
    documented = 0

    for i, route in enumerate(routes):
        label = "routes.json[{}]".format(i)
        if not isinstance(route, dict):
            report_errors.append((label, "entry is not an object"))
            continue
        method = str(route.get("method") or "").upper()
        path = route.get("path")
        if not method or not path:
            report_errors.append((label, "entry needs both 'method' and 'path': {!r}"
                                         .format(route)))
            continue
        if method.lower() not in HTTP_METHODS:
            report_errors.append((label, "unknown HTTP method {!r}".format(method)))
            continue
        key = (method, normalise_path(path))
        where = "{} {}".format(method, path)
        handler = route.get("handler")
        suffix = "  [{}]".format(handler) if handler else ""

        if key not in ops:
            report_errors.append((where, "found in code but missing from the spec{}"
                                         .format(suffix)))
            continue

        seen.add(key)
        documented += 1
        declared_auth = route.get("auth")
        has_auth = operation_has_auth(ops[key]["op"], spec)
        if declared_auth and str(declared_auth).lower() not in ("none", "false", "public"):
            if not has_auth:
                report_warnings.append(
                    (where, "code applies auth ({}) but the spec documents no security "
                            "requirement{}".format(declared_auth, suffix)))
        else:
            if has_auth:
                report_warnings.append(
                    (where, "spec requires auth but the inventory records none{}"
                            .format(suffix)))

    for key in sorted(set(ops) - seen):
        report_warnings.append((ops[key]["display"],
                                "in the spec but no matching route in code -- deleted "
                                "endpoint, or the discovery pass missed it"))

    return {"routes": len(routes), "documented": documented,
            "spec_operations": len(ops), "undocumented": len(routes) - documented,
            "unmatched_spec_paths": len(set(ops) - seen)}


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Cross-check a routes.json inventory against an OpenAPI spec.")
    ap.add_argument("routes", help="routes.json written during route discovery")
    ap.add_argument("spec", help="openapi.yaml (needs PyYAML) or openapi.json")
    ap.add_argument("--strict", action="store_true", help="treat warnings as errors")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = ap.parse_args(argv)

    routes = load_any(args.routes)
    spec = load_any(args.spec)

    if not isinstance(routes, list):
        sys.stderr.write("error: {} must contain a JSON array of route objects\n"
                         .format(args.routes))
        return 2
    if not isinstance(spec, dict):
        sys.stderr.write("error: {} does not look like an OpenAPI document\n"
                         .format(args.spec))
        return 2

    errors, warnings = [], []
    stats = check(routes, spec, errors, warnings)
    if args.strict:
        errors, warnings = errors + warnings, []

    if args.json:
        print(json.dumps({
            "stats": stats,
            "errors": [{"where": w, "message": m} for w, m in errors],
            "warnings": [{"where": w, "message": m} for w, m in warnings],
        }, indent=2))
    else:
        for where, msg in errors:
            print("ERROR   {}: {}".format(where, msg))
        for where, msg in warnings:
            print("warning {}: {}".format(where, msg))
        pct = (100.0 * stats["documented"] / stats["routes"]) if stats["routes"] else 100.0
        print("coverage: {}/{} routes documented ({:.0f}%), {} spec operation(s), "
              "{} unmatched spec path(s)".format(
                  stats["documented"], stats["routes"], pct,
                  stats["spec_operations"], stats["unmatched_spec_paths"]))
        print("FAIL" if errors else "OK")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
