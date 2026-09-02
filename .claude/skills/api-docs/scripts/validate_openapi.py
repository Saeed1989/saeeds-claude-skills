#!/usr/bin/env python3
"""Structural checks on an OpenAPI 3.1 document.

This is not a JSON-Schema validator. It catches the specific breakages that
make a spec fail in Swagger UI, break codegen, or quietly lie about the API:

  errors    missing openapi / info.title / info.version / paths
            a $ref that points at a component which does not exist
            missing or duplicate operationId
            a {param} in the URL template with no matching parameter object
            an in:path parameter that is not in the URL template
            an in:path parameter that is not required:true
            unquoted response status codes (YAML parses 200 as an integer)
            a security requirement naming a scheme not in components
  warnings  an operation with no non-2xx response documented
            requestBody on GET or DELETE
            components nothing references
            nullable:true (that is OpenAPI 3.0; 3.1 uses type arrays)
            external $refs, which cannot be checked from here

Exit status: 0 clean (warnings allowed), 1 errors found, 2 could not read the
file. --strict promotes warnings to errors.

Standard library only. YAML support needs PyYAML; without it JSON specs still
work and the script says so rather than failing silently.
"""

import argparse
import json
import os
import re
import sys

try:
    import yaml                      # type: ignore
    HAVE_YAML = True
except ImportError:                  # degrade, do not die
    HAVE_YAML = False

PATH_VAR = re.compile(r"\{([^}/]+)\}")
HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
COMPONENT_SECTIONS = (
    "schemas", "responses", "parameters", "examples", "requestBodies",
    "headers", "securitySchemes", "links", "callbacks", "pathItems",
)


class Report:
    def __init__(self):
        self.errors = []
        self.warnings = []

    def error(self, where, msg):
        self.errors.append((where, msg))

    def warn(self, where, msg):
        self.warnings.append((where, msg))


def load_spec(path):
    """Load a spec, or raise SystemExit(2) with an actionable message."""
    if not os.path.exists(path):
        sys.stderr.write("error: no such file: {}\n".format(path))
        raise SystemExit(2)
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    is_yaml = path.lower().endswith((".yaml", ".yml"))
    if is_yaml:
        if not HAVE_YAML:
            sys.stderr.write(
                "error: {} is YAML but PyYAML is not installed, so it cannot be "
                "parsed.\n"
                "  Fix with one of:\n"
                "    pip install pyyaml\n"
                "    convert the spec to JSON and pass that instead\n".format(path))
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


def walk(node, path=()):
    """Yield (json_pointer_ish_path, value) for every mapping and list member."""
    yield path, node
    if isinstance(node, dict):
        for k, v in node.items():
            for item in walk(v, path + (str(k),)):
                yield item
    elif isinstance(node, list):
        for i, v in enumerate(node):
            for item in walk(v, path + (str(i),)):
                yield item


def loc(path):
    return "/" + "/".join(path) if path else "<root>"


# --------------------------------------------------------------------------
# Individual checks
# --------------------------------------------------------------------------

def check_top_level(spec, report):
    if not isinstance(spec, dict):
        report.error("<root>", "spec must be a mapping at the top level")
        return False
    version = spec.get("openapi")
    if not version:
        report.error("<root>", "missing 'openapi' version key")
    elif not str(version).startswith("3."):
        report.error("<root>", "'openapi' is {!r}; this tool expects 3.x "
                               "(Swagger 2.0 uses 'swagger' instead)".format(version))
    elif not str(version).startswith("3.1"):
        report.warn("<root>", "'openapi' is {!r}; this skill targets 3.1 "
                              "(3.0 differs on nullable, examples, and webhooks)"
                              .format(version))

    info = spec.get("info")
    if not isinstance(info, dict):
        report.error("<root>", "missing 'info' object")
    else:
        if not info.get("title"):
            report.error("/info", "missing 'info.title'")
        if not info.get("version"):
            report.error("/info", "missing 'info.version'")

    paths = spec.get("paths")
    if paths is None and "webhooks" not in spec and "components" not in spec:
        report.error("<root>", "missing 'paths' (3.1 allows omitting it only when "
                               "'webhooks' or 'components' is present)")
    elif paths is not None and not isinstance(paths, dict):
        report.error("/paths", "'paths' must be a mapping of URL template to path item")
    return True


def collect_refs(spec):
    """Every $ref in the document, as (location, ref string)."""
    out = []
    for path, node in walk(spec):
        if isinstance(node, dict) and isinstance(node.get("$ref"), str):
            out.append((path, node["$ref"]))
    return out


def check_refs(spec, report):
    """Resolve local refs; report anything pointing into thin air."""
    components = spec.get("components") or {}
    referenced = {}
    for path, ref in collect_refs(spec):
        if not ref.startswith("#/"):
            report.warn(loc(path), "external $ref {!r} cannot be verified here"
                                   .format(ref))
            continue
        parts = ref[2:].split("/")
        if len(parts) != 3 or parts[0] != "components":
            # Legal but unusual (e.g. #/paths/...); resolve generically.
            node = spec
            ok = True
            for part in parts:
                part = part.replace("~1", "/").replace("~0", "~")
                if isinstance(node, dict) and part in node:
                    node = node[part]
                else:
                    ok = False
                    break
            if not ok:
                report.error(loc(path), "$ref {!r} does not resolve".format(ref))
            continue
        _, section, name = parts
        name = name.replace("~1", "/").replace("~0", "~")
        if section not in COMPONENT_SECTIONS:
            report.error(loc(path), "$ref {!r} names an unknown components section "
                                    "{!r}".format(ref, section))
            continue
        bucket = components.get(section) or {}
        if name not in bucket:
            known = ", ".join(sorted(bucket)) or "(none defined)"
            report.error(loc(path), "$ref {!r} does not resolve; components.{} has: {}"
                                    .format(ref, section, known))
        else:
            referenced.setdefault(section, set()).add(name)
    return referenced


def iter_operations(spec):
    """Yield (url, method, operation, path_item) for every operation."""
    paths = spec.get("paths")
    if not isinstance(paths, dict):
        return
    for url, item in paths.items():
        if not isinstance(item, dict):
            continue
        for method, op in item.items():
            if method.lower() in HTTP_METHODS and isinstance(op, dict):
                yield str(url), method.lower(), op, item


def check_operation_ids(spec, report):
    seen = {}
    for url, method, op, _item in iter_operations(spec):
        where = "{} {}".format(method.upper(), url)
        op_id = op.get("operationId")
        if not op_id:
            report.error(where, "missing operationId (codegen and client SDKs key "
                                "off it)")
            continue
        if op_id in seen:
            report.error(where, "duplicate operationId {!r}, already used by {}"
                                .format(op_id, seen[op_id]))
        else:
            seen[op_id] = where


def resolve_parameter(param, spec):
    """Follow a parameter $ref one level so in/required can be inspected."""
    if isinstance(param, dict) and "$ref" in param:
        ref = param["$ref"]
        if isinstance(ref, str) and ref.startswith("#/components/parameters/"):
            name = ref.rsplit("/", 1)[-1]
            return ((spec.get("components") or {}).get("parameters") or {}).get(name)
        return None
    return param


def check_path_parameters(spec, report):
    paths = spec.get("paths")
    if not isinstance(paths, dict):
        return
    for url, item in paths.items():
        if not isinstance(item, dict):
            continue
        template_vars = set(PATH_VAR.findall(str(url)))
        shared = [p for p in (item.get("parameters") or [])]
        for method, op in item.items():
            if method.lower() not in HTTP_METHODS or not isinstance(op, dict):
                continue
            where = "{} {}".format(method.upper(), url)
            declared = {}
            for raw in shared + list(op.get("parameters") or []):
                param = resolve_parameter(raw, spec)
                if not isinstance(param, dict):
                    report.error(where, "parameter entry could not be resolved: {!r}"
                                        .format(raw))
                    continue
                if param.get("in") == "path":
                    declared[param.get("name")] = param
            for var in sorted(template_vars):
                if var not in declared:
                    report.error(where, "URL template has {{{}}} but no parameter "
                                        "object with in:path, name:{}".format(var, var))
                elif declared[var].get("required") is not True:
                    report.error(where, "path parameter {!r} must set required:true"
                                        .format(var))
            for name in sorted(declared):
                if name not in template_vars:
                    report.error(where, "parameter {!r} is in:path but {{{}}} does not "
                                        "appear in the URL template".format(name, name))


def check_responses(spec, report):
    for url, method, op, _item in iter_operations(spec):
        where = "{} {}".format(method.upper(), url)
        responses = op.get("responses")
        if not isinstance(responses, dict) or not responses:
            report.error(where, "no responses documented")
            continue
        codes = []
        for code in responses:
            if isinstance(code, int):
                report.error(where, "response code {} is an integer; OpenAPI requires "
                                    "quoted strings ('{}': ...) and Swagger UI drops "
                                    "unquoted codes".format(code, code))
                codes.append(str(code))
            else:
                codes.append(str(code))
        has_success = any(c.startswith("2") for c in codes)
        has_failure = any(c == "default" or c[:1] in ("4", "5") for c in codes)
        if not has_success:
            report.warn(where, "no 2xx response documented")
        if not has_failure:
            report.warn(where, "no non-2xx response documented; every real endpoint "
                               "can fail (add at least the auth/validation error)")


def check_security(spec, report):
    schemes = ((spec.get("components") or {}).get("securitySchemes") or {})

    def check_block(block, where):
        if not isinstance(block, list):
            report.error(where, "'security' must be a list of requirement objects")
            return
        for requirement in block:
            if not isinstance(requirement, dict):
                report.error(where, "security requirement must be a mapping")
                continue
            for name in requirement:
                if name not in schemes:
                    known = ", ".join(sorted(schemes)) or "(none defined)"
                    report.error(where, "security requirement names {!r}, which is not "
                                        "in components.securitySchemes ({})"
                                        .format(name, known))

    if "security" in spec:
        check_block(spec["security"], "<root>/security")
    for url, method, op, _item in iter_operations(spec):
        if "security" in op:
            check_block(op["security"], "{} {}".format(method.upper(), url))


def check_request_bodies(spec, report):
    for url, method, op, _item in iter_operations(spec):
        if method in ("get", "delete") and "requestBody" in op:
            report.warn("{} {}".format(method.upper(), url),
                        "requestBody on {} -- many clients, proxies and caches drop "
                        "the body; use query parameters instead"
                        .format(method.upper()))


def check_orphans(spec, referenced, report):
    components = spec.get("components") or {}
    used_schemes = set()
    blocks = [spec.get("security") or []]
    for _url, _method, op, _item in iter_operations(spec):
        blocks.append(op.get("security") or [])
    for block in blocks:
        if isinstance(block, list):
            for requirement in block:
                if isinstance(requirement, dict):
                    used_schemes.update(requirement)

    for section, bucket in components.items():
        if not isinstance(bucket, dict):
            continue
        used = set(referenced.get(section, set()))
        if section == "securitySchemes":
            used |= used_schemes
        for name in sorted(bucket):
            if name not in used:
                report.warn("components.{}".format(section),
                            "{!r} is defined but nothing references it".format(name))


def check_31_idioms(spec, report):
    for path, node in walk(spec):
        if isinstance(node, dict) and "nullable" in node:
            report.warn(loc(path), "'nullable' is OpenAPI 3.0; in 3.1 use a type array "
                                   "such as type: [string, 'null']")
        if isinstance(node, dict) and "example" in node and "examples" in node:
            report.warn(loc(path), "both 'example' and 'examples' are set; Swagger UI "
                                   "shows only one of them")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def validate(spec, report):
    if not check_top_level(spec, report):
        return
    referenced = check_refs(spec, report)
    check_operation_ids(spec, report)
    check_path_parameters(spec, report)
    check_responses(spec, report)
    check_security(spec, report)
    check_request_bodies(spec, report)
    check_orphans(spec, referenced, report)
    check_31_idioms(spec, report)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Structurally validate an OpenAPI 3.1 spec.")
    ap.add_argument("specs", nargs="+", help="spec file(s): .yaml/.yml (needs PyYAML) or .json")
    ap.add_argument("--strict", action="store_true", help="treat warnings as errors")
    ap.add_argument("-q", "--quiet", action="store_true", help="print only problems")
    args = ap.parse_args(argv)

    if not HAVE_YAML and not args.quiet:
        print("note    PyYAML not installed -- JSON specs only "
              "(pip install pyyaml for .yaml support)")
        sys.stdout.flush()      # keep this ahead of any stderr load error

    failed = False
    for path in args.specs:
        spec = load_spec(path)
        report = Report()
        validate(spec, report)

        errors, warnings = list(report.errors), list(report.warnings)
        if args.strict:
            errors, warnings = errors + warnings, []

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
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
