#!/usr/bin/env python3
"""Semantic diff between two OpenAPI specs, classified by impact.

    diff_openapi.py old.json new.json [--fail-on-breaking] [--json]

Every change lands in exactly one bucket:

  BREAKING   existing clients stop working, or silently get different behaviour
  ADDITIVE   new capability; every existing client keeps working
  COSMETIC   documentation only; the contract is unchanged

Classification is direction-aware, because the same edit means opposite things
on the way in and on the way out:

                                request (client sends)   response (client reads)
  field added                   additive (optional)      additive
                                breaking (required)
  field removed                 additive*                BREAKING
  field becomes required        BREAKING                 additive
  field becomes optional        additive                 BREAKING**
  type widened (adds null)      additive                 BREAKING***

    *   the server now ignores it; clients still sending it are unaffected
    **  the client can no longer rely on the field being present
    *** the client has no code path for the new type

Judgement calls this tool makes, so they are visible rather than buried:

  - a removed query/header parameter is BREAKING: the server silently ignores
    something clients still send, which is worse than an error
  - a changed operationId is BREAKING: it renames the method in every
    generated SDK
  - a removed non-2xx response is COSMETIC: it documents an error case, and
    removing the documentation does not change behaviour
  - a renamed path parameter (/orders/{id} -> /orders/{orderId}) is COSMETIC:
    the URL matched by clients is identical
  - format added or changed is BREAKING; format removed is ADDITIVE

Exit status: 0 normally; 1 if --fail-on-breaking and any BREAKING change was
found; 2 if a file could not be read.

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

BREAKING, ADDITIVE, COSMETIC = "BREAKING", "ADDITIVE", "COSMETIC"
HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
PATH_VAR = re.compile(r"\{[^}/]+\}")
MAX_REF_DEPTH = 24


def load_spec(path):
    if not os.path.exists(path):
        sys.stderr.write("error: no such file: {}\n".format(path))
        raise SystemExit(2)
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    if path.lower().endswith((".yaml", ".yml")):
        if not HAVE_YAML:
            sys.stderr.write(
                "error: {} is YAML but PyYAML is not installed.\n"
                "  pip install pyyaml, or diff JSON copies of the specs.\n".format(path))
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


class Changes:
    def __init__(self):
        self.items = []       # (impact, endpoint, message)

    def add(self, impact, endpoint, message):
        self.items.append((impact, endpoint, message))

    def of(self, impact):
        return [i for i in self.items if i[0] == impact]


# --------------------------------------------------------------------------
# $ref resolution
# --------------------------------------------------------------------------

def resolve(node, spec, depth=0):
    """Follow local $refs so two specs are compared by shape, not by pointer.

    A depth cap keeps a recursive schema (a comment with replies, a tree node)
    from spinning forever; past the cap the raw node is returned and compared
    as-is.
    """
    seen = 0
    while (isinstance(node, dict) and isinstance(node.get("$ref"), str)
           and node["$ref"].startswith("#/") and seen < MAX_REF_DEPTH
           and depth < MAX_REF_DEPTH):
        target = spec
        for part in node["$ref"][2:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            if isinstance(target, dict) and part in target:
                target = target[part]
            else:
                return node
        node = target
        seen += 1
    return node


def contains_ref(node, depth=0):
    """True if this subtree contains a $ref anywhere.

    Guards the equality shortcut in compare_schema: two subtrees can be
    byte-identical and still describe different APIs, because a $ref inside
    them resolves against a different document on each side. An unchanged
    wrapper (a page envelope whose items are {"$ref": ".../Order"}) would
    otherwise hide every change made to the schema it points at.
    """
    if depth > MAX_REF_DEPTH:
        return True                   # assume the worst; compare properly
    if isinstance(node, dict):
        if "$ref" in node:
            return True
        return any(contains_ref(v, depth + 1) for v in node.values())
    if isinstance(node, list):
        return any(contains_ref(v, depth + 1) for v in node)
    return False


def type_set(schema):
    """Normalise 'type' to a set, covering 3.1 type arrays and 3.0 nullable."""
    if not isinstance(schema, dict):
        return set()
    raw = schema.get("type")
    if raw is None:
        types = set()
    elif isinstance(raw, list):
        types = {str(t) for t in raw}
    else:
        types = {str(raw)}
    if schema.get("nullable") is True:          # 3.0 spelling
        types.add("null")
    return types


# --------------------------------------------------------------------------
# Schema comparison
# --------------------------------------------------------------------------

# constraint -> True if a smaller number is the tighter one
TIGHTENS_WHEN_SMALLER = {
    "maxLength": True, "maximum": True, "exclusiveMaximum": True, "maxItems": True,
    "maxProperties": True,
    "minLength": False, "minimum": False, "exclusiveMinimum": False,
    "minItems": False, "minProperties": False,
}


def compare_schema(old, new, old_spec, new_spec, direction, endpoint, where,
                   changes, depth=0):
    """Compare two schemas. `direction` is 'request' or 'response'."""
    if depth > MAX_REF_DEPTH:
        return
    old = resolve(old, old_spec)
    new = resolve(new, new_spec)
    if not isinstance(old, dict) or not isinstance(new, dict):
        return
    if old == new and not contains_ref(old):
        return

    request = direction == "request"

    # --- type -------------------------------------------------------------
    old_types, new_types = type_set(old), type_set(new)
    if old_types != new_types and (old_types or new_types):
        old_s = ",".join(sorted(old_types)) or "any"
        new_s = ",".join(sorted(new_types)) or "any"
        if new_types < old_types:
            changes.add(BREAKING, endpoint,
                        "{}: type narrowed {} -> {}".format(where, old_s, new_s))
        elif old_types < new_types:
            if request:
                changes.add(ADDITIVE, endpoint,
                            "{}: type widened {} -> {}".format(where, old_s, new_s))
            else:
                changes.add(BREAKING, endpoint,
                            "{}: response type widened {} -> {} (clients have no path "
                            "for the new type)".format(where, old_s, new_s))
        else:
            changes.add(BREAKING, endpoint,
                        "{}: type changed {} -> {}".format(where, old_s, new_s))

    # --- format -----------------------------------------------------------
    old_fmt, new_fmt = old.get("format"), new.get("format")
    if old_fmt != new_fmt:
        if new_fmt is None:
            changes.add(ADDITIVE, endpoint,
                        "{}: format {!r} removed".format(where, old_fmt))
        elif old_fmt is None:
            changes.add(BREAKING, endpoint,
                        "{}: format {!r} added (values are now constrained)"
                        .format(where, new_fmt))
        else:
            changes.add(BREAKING, endpoint,
                        "{}: format changed {!r} -> {!r}".format(where, old_fmt, new_fmt))

    # --- enum -------------------------------------------------------------
    old_enum, new_enum = old.get("enum"), new.get("enum")
    if old_enum != new_enum:
        if old_enum is None and new_enum is not None:
            changes.add(BREAKING, endpoint,
                        "{}: enum introduced ({}) where any value was allowed"
                        .format(where, ", ".join(map(str, new_enum))))
        elif new_enum is None and old_enum is not None:
            changes.add(ADDITIVE, endpoint,
                        "{}: enum removed; any value is now allowed".format(where))
        else:
            removed = [v for v in old_enum if v not in new_enum]
            added = [v for v in new_enum if v not in old_enum]
            if removed:
                changes.add(BREAKING, endpoint,
                            "{}: enum value(s) removed: {}".format(
                                where, ", ".join(map(str, removed))))
            if added:
                note = "" if request else " (strict clients may reject unknown values)"
                changes.add(ADDITIVE, endpoint,
                            "{}: enum value(s) added: {}{}".format(
                                where, ", ".join(map(str, added)), note))

    # --- numeric / length constraints -------------------------------------
    for key, smaller_is_tighter in TIGHTENS_WHEN_SMALLER.items():
        old_v, new_v = old.get(key), new.get(key)
        if old_v == new_v:
            continue
        if old_v is None:
            impact = BREAKING if request else ADDITIVE
            changes.add(impact, endpoint,
                        "{}: {} constraint added ({})".format(where, key, new_v))
        elif new_v is None:
            changes.add(ADDITIVE, endpoint,
                        "{}: {} constraint removed".format(where, key))
        else:
            try:
                tighter = (new_v < old_v) if smaller_is_tighter else (new_v > old_v)
            except TypeError:
                tighter = True
            impact = (BREAKING if tighter else ADDITIVE) if request else ADDITIVE
            changes.add(impact, endpoint,
                        "{}: {} {} -> {}".format(where, key, old_v, new_v))

    if old.get("pattern") != new.get("pattern"):
        if new.get("pattern") is None:
            changes.add(ADDITIVE, endpoint, "{}: pattern removed".format(where))
        elif old.get("pattern") is None:
            changes.add(BREAKING if request else ADDITIVE, endpoint,
                        "{}: pattern added ({})".format(where, new["pattern"]))
        else:
            changes.add(BREAKING if request else ADDITIVE, endpoint,
                        "{}: pattern changed".format(where))

    # --- object properties ------------------------------------------------
    old_props = old.get("properties") or {}
    new_props = new.get("properties") or {}
    old_required = set(old.get("required") or [])
    new_required = set(new.get("required") or [])

    for name in sorted(set(new_props) - set(old_props)):
        field = "{}.{}".format(where, name)
        if request and name in new_required:
            changes.add(BREAKING, endpoint,
                        "{}: new required request field".format(field))
        else:
            changes.add(ADDITIVE, endpoint, "{}: new field".format(field))

    for name in sorted(set(old_props) - set(new_props)):
        field = "{}.{}".format(where, name)
        if request:
            changes.add(ADDITIVE, endpoint,
                        "{}: request field removed (server ignores it; clients still "
                        "sending it are unaffected)".format(field))
        else:
            changes.add(BREAKING, endpoint, "{}: response field removed".format(field))

    for name in sorted(set(old_props) & set(new_props)):
        field = "{}.{}".format(where, name)
        was_req, now_req = name in old_required, name in new_required
        if was_req != now_req:
            if request and now_req:
                changes.add(BREAKING, endpoint,
                            "{}: became required in the request".format(field))
            elif request:
                changes.add(ADDITIVE, endpoint,
                            "{}: no longer required in the request".format(field))
            elif now_req:
                changes.add(ADDITIVE, endpoint,
                            "{}: now always present in the response".format(field))
            else:
                changes.add(BREAKING, endpoint,
                            "{}: no longer guaranteed in the response".format(field))
        compare_schema(old_props[name], new_props[name], old_spec, new_spec,
                       direction, endpoint, field, changes, depth + 1)

    # required entries naming properties that are not declared
    for name in sorted((new_required - old_required) - set(new_props)):
        if request:
            changes.add(BREAKING, endpoint,
                        "{}.{}: became required in the request".format(where, name))

    # --- arrays and composition -------------------------------------------
    if "items" in old or "items" in new:
        compare_schema(old.get("items") or {}, new.get("items") or {},
                       old_spec, new_spec, direction, endpoint,
                       "{}[]".format(where), changes, depth + 1)

    for key in ("oneOf", "anyOf", "allOf"):
        old_list, new_list = old.get(key), new.get(key)
        if old_list == new_list:
            continue
        if isinstance(old_list, list) and isinstance(new_list, list):
            if len(new_list) < len(old_list):
                changes.add(BREAKING, endpoint,
                            "{}: {} branch removed ({} -> {})".format(
                                where, key, len(old_list), len(new_list)))
            elif len(new_list) > len(old_list):
                impact = ADDITIVE if request else BREAKING
                changes.add(impact, endpoint,
                            "{}: {} branch added ({} -> {})".format(
                                where, key, len(old_list), len(new_list)))
            else:
                for i, (o, n) in enumerate(zip(old_list, new_list)):
                    compare_schema(o, n, old_spec, new_spec, direction, endpoint,
                                   "{}.{}[{}]".format(where, key, i), changes, depth + 1)
        elif old_list is None:
            changes.add(BREAKING if request else ADDITIVE, endpoint,
                        "{}: {} introduced".format(where, key))
        else:
            changes.add(ADDITIVE, endpoint, "{}: {} removed".format(where, key))

    old_ap, new_ap = old.get("additionalProperties"), new.get("additionalProperties")
    if old_ap != new_ap and (old_ap is False or new_ap is False):
        if new_ap is False:
            changes.add(BREAKING if request else ADDITIVE, endpoint,
                        "{}: additionalProperties now forbidden".format(where))
        else:
            changes.add(ADDITIVE, endpoint,
                        "{}: additionalProperties now allowed".format(where))

    for key in ("description", "title", "example", "examples", "deprecated"):
        if old.get(key) != new.get(key):
            if key == "deprecated" and new.get(key) is True:
                changes.add(COSMETIC, endpoint,
                            "{}: marked deprecated".format(where))
            else:
                changes.add(COSMETIC, endpoint, "{}: {} changed".format(where, key))


# --------------------------------------------------------------------------
# Operation-level comparison
# --------------------------------------------------------------------------

def content_schema(body):
    """First media-type schema in a requestBody/response, with its media type."""
    if not isinstance(body, dict):
        return None, None
    content = body.get("content")
    if not isinstance(content, dict) or not content:
        return None, None
    for media in ("application/json",):
        if media in content:
            return media, (content[media] or {}).get("schema")
    media = sorted(content)[0]
    return media, (content[media] or {}).get("schema")


def param_key(param):
    return (param.get("name"), param.get("in"))


def collect_params(item, op, spec):
    out = {}
    for raw in list(item.get("parameters") or []) + list(op.get("parameters") or []):
        param = resolve(raw, spec)
        if isinstance(param, dict) and param.get("name"):
            out[param_key(param)] = param
    return out


def effective_security(op, spec):
    """Operation-level security wins; otherwise the document default applies."""
    if "security" in op:
        return op["security"]
    return spec.get("security") or []


def security_signature(block):
    """{scheme: set(scopes)} across all alternatives, for comparison."""
    out = {}
    if isinstance(block, list):
        for requirement in block:
            if isinstance(requirement, dict):
                for name, scopes in requirement.items():
                    out.setdefault(name, set()).update(scopes or [])
    return out


def compare_operation(url, method, old_op, new_op, old_item, new_item,
                      old_spec, new_spec, changes):
    endpoint = "{} {}".format(method.upper(), url)

    if old_op.get("operationId") != new_op.get("operationId"):
        changes.add(BREAKING, endpoint,
                    "operationId {!r} -> {!r} (renames the method in every generated "
                    "SDK)".format(old_op.get("operationId"), new_op.get("operationId")))

    for key in ("summary", "description"):
        if old_op.get(key) != new_op.get(key):
            changes.add(COSMETIC, endpoint, "{} changed".format(key))
    if (old_op.get("tags") or []) != (new_op.get("tags") or []):
        changes.add(COSMETIC, endpoint, "tags changed {} -> {}".format(
            old_op.get("tags") or [], new_op.get("tags") or []))
    if old_op.get("deprecated") != new_op.get("deprecated"):
        if new_op.get("deprecated"):
            changes.add(COSMETIC, endpoint, "marked deprecated")
        else:
            changes.add(COSMETIC, endpoint, "no longer deprecated")

    # --- parameters -------------------------------------------------------
    old_params = collect_params(old_item, old_op, old_spec)
    new_params = collect_params(new_item, new_op, new_spec)

    for key in sorted(set(new_params) - set(old_params)):
        name, location = key
        param = new_params[key]
        if location == "path":
            continue                      # covered by the path-template comparison
        if param.get("required"):
            changes.add(BREAKING, endpoint,
                        "new required {} parameter {!r}".format(location, name))
        else:
            changes.add(ADDITIVE, endpoint,
                        "new optional {} parameter {!r}".format(location, name))

    for key in sorted(set(old_params) - set(new_params)):
        name, location = key
        if location == "path":
            continue
        changes.add(BREAKING, endpoint,
                    "{} parameter {!r} removed (clients still sending it lose that "
                    "behaviour silently)".format(location, name))

    for key in sorted(set(old_params) & set(new_params)):
        name, location = key
        old_p, new_p = old_params[key], new_params[key]
        was_req = bool(old_p.get("required"))
        now_req = bool(new_p.get("required"))
        if not was_req and now_req:
            changes.add(BREAKING, endpoint,
                        "{} parameter {!r} is now required".format(location, name))
        elif was_req and not now_req:
            changes.add(ADDITIVE, endpoint,
                        "{} parameter {!r} is now optional".format(location, name))
        if old_p.get("description") != new_p.get("description"):
            changes.add(COSMETIC, endpoint,
                        "{} parameter {!r} description changed".format(location, name))
        compare_schema(old_p.get("schema") or {}, new_p.get("schema") or {},
                       old_spec, new_spec, "request", endpoint,
                       "{} param {}".format(location, name), changes)

    # --- request body -----------------------------------------------------
    old_body, new_body = old_op.get("requestBody"), new_op.get("requestBody")
    old_body = resolve(old_body, old_spec) if old_body else None
    new_body = resolve(new_body, new_spec) if new_body else None
    if old_body and not new_body:
        changes.add(ADDITIVE, endpoint, "requestBody removed (server ignores it)")
    elif new_body and not old_body:
        if new_body.get("required"):
            changes.add(BREAKING, endpoint, "requestBody added and is required")
        else:
            changes.add(ADDITIVE, endpoint, "optional requestBody added")
    elif old_body and new_body:
        if not old_body.get("required") and new_body.get("required"):
            changes.add(BREAKING, endpoint, "requestBody is now required")
        elif old_body.get("required") and not new_body.get("required"):
            changes.add(ADDITIVE, endpoint, "requestBody is now optional")
        old_media, old_schema = content_schema(old_body)
        new_media, new_schema = content_schema(new_body)
        if old_media != new_media:
            changes.add(BREAKING, endpoint,
                        "request media type {} -> {}".format(old_media, new_media))
        compare_schema(old_schema or {}, new_schema or {}, old_spec, new_spec,
                       "request", endpoint, "body", changes)

    # --- responses --------------------------------------------------------
    old_resp = old_op.get("responses") or {}
    new_resp = new_op.get("responses") or {}
    old_codes = {str(c) for c in old_resp}
    new_codes = {str(c) for c in new_resp}

    old_success = sorted(c for c in old_codes if c.startswith("2"))
    new_success = sorted(c for c in new_codes if c.startswith("2"))
    if old_success and new_success and old_success != new_success:
        changes.add(BREAKING, endpoint,
                    "success status code {} -> {}".format(
                        ",".join(old_success), ",".join(new_success)))
    else:
        for code in sorted(new_codes - old_codes):
            impact = ADDITIVE if not code.startswith("2") else ADDITIVE
            changes.add(impact, endpoint, "response {} documented".format(code))
        for code in sorted(old_codes - new_codes):
            if code.startswith("2"):
                changes.add(BREAKING, endpoint, "response {} removed".format(code))
            else:
                changes.add(COSMETIC, endpoint,
                            "response {} no longer documented (error-case "
                            "documentation only)".format(code))

    for code in sorted(old_codes & new_codes):
        old_r = resolve(old_resp.get(code) or old_resp.get(int(code) if code.isdigit()
                                                           else code) or {}, old_spec)
        new_r = resolve(new_resp.get(code) or new_resp.get(int(code) if code.isdigit()
                                                           else code) or {}, new_spec)
        if not isinstance(old_r, dict) or not isinstance(new_r, dict):
            continue
        if old_r.get("description") != new_r.get("description"):
            changes.add(COSMETIC, endpoint,
                        "response {} description changed".format(code))
        old_headers = old_r.get("headers") or {}
        new_headers = new_r.get("headers") or {}
        for name in sorted(set(old_headers) - set(new_headers)):
            changes.add(BREAKING, endpoint,
                        "response {} header {!r} removed".format(code, name))
        for name in sorted(set(new_headers) - set(old_headers)):
            changes.add(ADDITIVE, endpoint,
                        "response {} header {!r} added".format(code, name))
        old_media, old_schema = content_schema(old_r)
        new_media, new_schema = content_schema(new_r)
        if old_media and new_media and old_media != new_media:
            changes.add(BREAKING, endpoint,
                        "response {} media type {} -> {}".format(
                            code, old_media, new_media))
        if old_schema is not None or new_schema is not None:
            compare_schema(old_schema or {}, new_schema or {}, old_spec, new_spec,
                           "response", endpoint, "{} body".format(code), changes)

    # --- security ---------------------------------------------------------
    old_sec = security_signature(effective_security(old_op, old_spec))
    new_sec = security_signature(effective_security(new_op, new_spec))
    if old_sec != new_sec:
        if not old_sec and new_sec:
            changes.add(BREAKING, endpoint,
                        "auth now required ({})".format(", ".join(sorted(new_sec))))
        elif old_sec and not new_sec:
            changes.add(ADDITIVE, endpoint, "auth requirement removed")
        else:
            removed = set(old_sec) - set(new_sec)
            added = set(new_sec) - set(old_sec)
            if added:
                changes.add(BREAKING, endpoint,
                            "auth scheme(s) added: {}".format(", ".join(sorted(added))))
            if removed:
                changes.add(ADDITIVE, endpoint,
                            "auth scheme(s) dropped: {}".format(", ".join(sorted(removed))))
            for name in sorted(set(old_sec) & set(new_sec)):
                new_scopes = new_sec[name] - old_sec[name]
                gone_scopes = old_sec[name] - new_sec[name]
                if new_scopes:
                    changes.add(BREAKING, endpoint,
                                "{}: additional scope(s) required: {}".format(
                                    name, ", ".join(sorted(new_scopes))))
                if gone_scopes:
                    changes.add(ADDITIVE, endpoint,
                                "{}: scope(s) no longer required: {}".format(
                                    name, ", ".join(sorted(gone_scopes))))


# --------------------------------------------------------------------------
# Document-level comparison
# --------------------------------------------------------------------------

def normalise_path(url):
    """/orders/{id} and /orders/{orderId} match: clients call the same URL."""
    return PATH_VAR.sub("{}", str(url)).rstrip("/") or "/"


def compare_specs(old_spec, new_spec):
    changes = Changes()
    old_paths = old_spec.get("paths") or {}
    new_paths = new_spec.get("paths") or {}

    old_by_norm = {}
    for url in old_paths:
        old_by_norm.setdefault(normalise_path(url), []).append(url)
    new_by_norm = {}
    for url in new_paths:
        new_by_norm.setdefault(normalise_path(url), []).append(url)

    for norm in sorted(set(old_by_norm) - set(new_by_norm)):
        for url in old_by_norm[norm]:
            item = old_paths[url] or {}
            for method in sorted(m for m in item if m.lower() in HTTP_METHODS):
                changes.add(BREAKING, "{} {}".format(method.upper(), url),
                            "path removed")

    for norm in sorted(set(new_by_norm) - set(old_by_norm)):
        for url in new_by_norm[norm]:
            item = new_paths[url] or {}
            for method in sorted(m for m in item if m.lower() in HTTP_METHODS):
                changes.add(ADDITIVE, "{} {}".format(method.upper(), url), "new path")

    for norm in sorted(set(old_by_norm) & set(new_by_norm)):
        old_url = old_by_norm[norm][0]
        new_url = new_by_norm[norm][0]
        if old_url != new_url:
            changes.add(COSMETIC, new_url,
                        "path parameter renamed: {} -> {} (same URL for clients)"
                        .format(old_url, new_url))
        old_item = old_paths.get(old_url) or {}
        new_item = new_paths.get(new_url) or {}
        old_methods = {m.lower() for m in old_item if m.lower() in HTTP_METHODS}
        new_methods = {m.lower() for m in new_item if m.lower() in HTTP_METHODS}
        for method in sorted(old_methods - new_methods):
            changes.add(BREAKING, "{} {}".format(method.upper(), new_url),
                        "method removed")
        for method in sorted(new_methods - old_methods):
            changes.add(ADDITIVE, "{} {}".format(method.upper(), new_url),
                        "new method")
        for method in sorted(old_methods & new_methods):
            compare_operation(new_url, method, old_item[method], new_item[method],
                              old_item, new_item, old_spec, new_spec, changes)

    # security scheme definitions themselves
    old_schemes = ((old_spec.get("components") or {}).get("securitySchemes") or {})
    new_schemes = ((new_spec.get("components") or {}).get("securitySchemes") or {})
    for name in sorted(set(old_schemes) & set(new_schemes)):
        old_s, new_s = old_schemes[name] or {}, new_schemes[name] or {}
        for key in ("type", "scheme", "in", "name", "bearerFormat", "openIdConnectUrl"):
            if old_s.get(key) != new_s.get(key):
                changes.add(BREAKING, "securityScheme {}".format(name),
                            "{} changed {!r} -> {!r}".format(
                                key, old_s.get(key), new_s.get(key)))
    for name in sorted(set(old_schemes) - set(new_schemes)):
        changes.add(BREAKING, "securityScheme {}".format(name), "scheme removed")
    for name in sorted(set(new_schemes) - set(old_schemes)):
        changes.add(ADDITIVE, "securityScheme {}".format(name), "scheme added")

    old_info = old_spec.get("info") or {}
    new_info = new_spec.get("info") or {}
    if old_info.get("version") != new_info.get("version"):
        changes.add(COSMETIC, "info",
                    "version {} -> {}".format(old_info.get("version"),
                                              new_info.get("version")))
    return changes


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def render(changes, old_path, new_path):
    lines = []
    lines.append("{} -> {}".format(old_path, new_path))
    total = len(changes.items)
    if not total:
        lines.append("no differences")
        return "\n".join(lines)

    for impact, header in ((BREAKING, "BREAKING  (existing clients stop working)"),
                           (ADDITIVE, "ADDITIVE  (backward compatible)"),
                           (COSMETIC, "COSMETIC  (documentation only)")):
        items = changes.of(impact)
        if not items:
            continue
        lines.append("")
        lines.append("{}  [{}]".format(header, len(items)))
        by_endpoint = {}
        for _impact, endpoint, msg in items:
            by_endpoint.setdefault(endpoint, []).append(msg)
        for endpoint in sorted(by_endpoint):
            lines.append("  {}".format(endpoint))
            for msg in by_endpoint[endpoint]:
                lines.append("      {}".format(msg))

    lines.append("")
    lines.append("summary: {} breaking, {} additive, {} cosmetic".format(
        len(changes.of(BREAKING)), len(changes.of(ADDITIVE)), len(changes.of(COSMETIC))))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Semantic diff between two OpenAPI specs, classified by impact.")
    ap.add_argument("old", help="the committed / previous spec")
    ap.add_argument("new", help="the regenerated / proposed spec")
    ap.add_argument("--fail-on-breaking", action="store_true",
                    help="exit 1 if any BREAKING change is found (for CI)")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = ap.parse_args(argv)

    old_spec = load_spec(args.old)
    new_spec = load_spec(args.new)
    changes = compare_specs(old_spec, new_spec)

    if args.json:
        print(json.dumps({
            "old": args.old,
            "new": args.new,
            "counts": {
                "breaking": len(changes.of(BREAKING)),
                "additive": len(changes.of(ADDITIVE)),
                "cosmetic": len(changes.of(COSMETIC)),
            },
            "changes": [{"impact": i, "endpoint": e, "change": m}
                        for i, e, m in changes.items],
        }, indent=2))
    else:
        print(render(changes, args.old, args.new))

    if args.fail_on_breaking and changes.of(BREAKING):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
