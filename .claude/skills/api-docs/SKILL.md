---
name: api-docs
description: >-
  Generate and maintain an OpenAPI 3.1 spec from the route handlers in a
  codebase. Use whenever someone wants their HTTP API written down or kept up
  to date — "document the API", "generate an OpenAPI spec", "write a swagger
  file", "what endpoints does this expose", "list the routes", "update the API
  docs after my changes", "is the spec still accurate", "did I break the API",
  "add this endpoint to the docs", "check for breaking changes in the API".
  Covers Express, NestJS, FastAPI, Flask, Django REST, Spring Boot, Go
  (chi/gin/echo), Rails and Laravel. Also for working on an existing
  openapi.yaml / openapi.json / swagger.json: validating it, finding
  undocumented endpoints, or diffing it against the committed version.
---

# API docs (OpenAPI 3.1)

Produces a spec that matches the code, and keeps matching it as the code
changes. The hard part is not writing YAML — it is **regenerating without
destroying what humans wrote**, and **not silently losing endpoints** in a
large codebase. Everything below serves those two problems.

## The merge rule

**Regenerating must never clobber human-written prose.**

When `openapi.yaml` already exists, it is the base and the code supplies
corrections. For anything still present in the code, preserve verbatim:

- `description` (on operations, parameters, schemas, properties, responses)
- `summary`
- `example` and `examples`
- every `x-` extension field
- `tags`, `servers`, `info.description`, and the ordering of existing keys

Change only what the code actually changed: add operations, parameters,
properties and responses that are new; remove ones that are gone; correct types,
required lists, status codes and auth to match the handler.

Why this is the highest-priority rule: a regeneration that rewrites every
description produces a diff where the real change — one field became required —
is buried in 900 lines of reworded prose. Nobody can review that, so nobody
does, and from then on the spec is something the tool owns rather than
something the team trusts. **A regeneration whose diff touches prose is a bug,
not a style preference.**

If prose contradicts the code, do not delete it. Keep it, correct the
machine-readable part, and tell the user in your report: *"`POST /orders` says
it returns 200; the handler returns 201. I corrected the status code and left
the description alone — it may need rewording."*

## Workflow

**1. Discover routes.** Read the router registration, not filenames.
`references/framework-extraction.md` has per-framework instructions: where
routes are registered, where the request/response types live, how auth is
applied, and how to spot a prefix (`app.use('/v1', router)` — miss it and every
path is wrong).

**2. Write `docs/routes.json` before writing any spec.** One entry per route:

```json
[
  {"method": "POST", "path": "/v1/orders",
   "handler": "src/routes/orders.ts:createOrder", "auth": "bearer"}
]
```

`path` is the full path including every prefix. `method` and `path` are
required; `handler` and `auth` make the report actionable. Framework param
syntax (`:id`, `{id}`, `<int:id>`) is normalised by the coverage script.

This step exists because summarising 40 route files loses endpoints, and
nothing downstream notices — the spec still validates and still renders.

**3. Generate, or merge.** No spec yet: start from
`assets/starter-openapi.yaml` and follow `references/conventions.md`. Spec
exists: apply the merge rule above.

**4. Check coverage.**

```bash
python .claude/skills/api-docs/scripts/check_coverage.py docs/routes.json docs/openapi.yaml
```

Reports routes in code that are missing from the spec (error), spec paths with
no matching route (warning — a deleted endpoint, or one discovery missed), and
auth mismatches between the two.

**5. Validate.**

```bash
python .claude/skills/api-docs/scripts/validate_openapi.py docs/openapi.yaml
```

Structural checks: `$ref`s that resolve, unique `operationId`s, path parameters
matching the URL template, quoted status codes, security schemes that exist,
every operation documenting a failure case. `--strict` fails on warnings.

**6. Diff against the committed spec.**

```bash
git show HEAD:docs/openapi.yaml > /tmp/openapi.base.yaml
python .claude/skills/api-docs/scripts/diff_openapi.py /tmp/openapi.base.yaml \
    docs/openapi.yaml --fail-on-breaking
```

Every change is classified BREAKING / ADDITIVE / COSMETIC. In CI,
`--fail-on-breaking` exits 1 so a breaking change cannot merge unnoticed.

**7. Report.** Lead with breaking changes, then coverage gaps, then anything
you inferred rather than verified. Never hand back a spec without saying which
parts you were unsure about.

## Honesty rules

**Document only what you verified in the handler.** These rules override
completeness — a spec with gaps is repairable; a spec with invented fields
teaches clients to send data the server ignores, and the bug surfaces in
production.

- If a response shape cannot be determined from types, do **not** invent
  fields. Write a `description` saying what the endpoint returns in prose, mark
  the schema `type: object` with `x-undocumented-shape: true`, and list the
  endpoint in your report as needing author input.
- Untyped languages, dynamic responses, and `res.json(anything)` are the normal
  cases for this. Reading the handler body to infer keys is fine — say that you
  inferred them.
- Never copy a status code from convention. If the handler writes `201`,
  document `201`, even where `200` would be more usual.
- Never guess auth. If the middleware chain is unclear, say so rather than
  assuming the document default applies.
- Error responses: document the ones the handler actually returns, plus those
  the framework's error middleware adds. Do not pad with plausible-looking 500s
  that the code never emits.
- Flag every inference explicitly in your report to the user, grouped, with
  file references — not buried in the spec.

## Scope and structure

- One spec per deployable service, at `docs/openapi.yaml` (or wherever the repo
  already keeps it — match the existing location and filename).
- Anything referenced twice goes in `components`. One shared `Error` schema,
  one pagination shape, shared `Page`/`Limit` parameters.
- Uncompressed, committed, and diffable. The spec is reviewed like code.
- Large APIs: keep one file until it is genuinely unwieldy (roughly 3000 lines),
  then split `components` into `$ref`'d files — but only if the toolchain
  resolves external refs, which many do not.

## Reference files

Read the relevant one; do not work from memory on OpenAPI syntax.

| File | Read it when |
| --- | --- |
| `references/framework-extraction.md` | discovering routes — per-framework route registration, type sources, auth middleware, prefixes |
| `references/openapi-reference.md` | writing or fixing spec syntax — components and `$ref`, parameters vs requestBody, securitySchemes, `example` vs `examples`, 3.1 nullability, what breaks Swagger UI |
| `references/conventions.md` | house style — shared Error schema, pagination, summaries, tags, versioning, naming. **Edit this file to match the team's conventions**; it overrides the defaults |
| `assets/starter-openapi.yaml` | starting a spec from nothing — a complete skeleton with the conventions already applied |

## Notes on the scripts

All three are standard library only. YAML needs PyYAML; without it they handle
JSON and say so rather than failing quietly. Each exits nonzero on failure, so
they compose into a CI job:

```bash
check_coverage.py docs/routes.json docs/openapi.yaml            # nothing dropped
validate_openapi.py docs/openapi.yaml --strict                  # structurally sound
diff_openapi.py base.yaml docs/openapi.yaml --fail-on-breaking  # no silent breakage
```

`diff_openapi.py` is direction-aware: the same edit is classified differently on
the request and the response side (a field becoming optional is additive in a
request, breaking in a response). Its docstring lists the judgement calls it
makes — read it before disputing a classification.
