# saeeds-claude-skills

Project skills for [Claude Code](https://claude.com/claude-code). Each one lives
in `.claude/skills/<name>/` and is picked up automatically in any session
started in this repo — describe what you want and the matching skill loads, or
invoke it directly with `/<name>`.

Each skill's `SKILL.md` is the source of truth for how it behaves. This file is
just the index.

## Skills

| Skill | Fires on | Produces |
| --- | --- | --- |
| [`drawio-diagrams`](.claude/skills/drawio-diagrams/SKILL.md) | "diagram this repo", "draw the data flow", "flowchart", "architecture picture", "visualize this codebase", plus named types (sequence, ER, C4, state machine, org chart) and any `.drawio` file work | An **editable** uncompressed `.drawio` file you open in diagrams.net and rearrange by hand — real shapes and geometry, not an image |
| [`api-docs`](.claude/skills/api-docs/SKILL.md) | "document the API", "generate an OpenAPI spec", "swagger", "what endpoints does this expose", "update the API docs after my changes", "did I break the API" | An **OpenAPI 3.1** spec that matches the handlers, kept in sync without clobbering human-written prose |

### drawio-diagrams

Coordinate math and XML escaping are what break hand-written draw.io files, so
a builder owns both: layering by longest path (cycle-safe), label-derived box
sizing, swimlane groups that reparent children to relative coordinates and push
non-members clear, and `&`/`<`/`>`/newline escaping through draw.io's
double-decode chain.

```bash
S=.claude/skills/drawio-diagrams/scripts
python $S/build_drawio.py spec.json -o out.drawio --geometry   # build + print layout
python $S/validate_drawio.py out.drawio --strict               # before you open it
python $S/build_drawio.py --decompress in.drawio -o out.drawio # inflate a saved file
```

The validator catches what makes a file open blank: missing `mxCell id="0"`/`"1"`,
edges pointing at nonexistent cells, duplicate ids, zero-size vertices, and
nodes drawn over a swimlane they aren't a child of.

### api-docs

Two problems drive the design: regenerating must never overwrite human prose
(descriptions, summaries, examples, `x-` fields), and endpoints must not go
missing when summarising a large codebase — so route discovery writes a
`routes.json` inventory that gets cross-checked against the spec.

```bash
S=.claude/skills/api-docs/scripts
python $S/check_coverage.py docs/routes.json docs/openapi.yaml        # nothing dropped
python $S/validate_openapi.py docs/openapi.yaml --strict              # structurally sound
python $S/diff_openapi.py base.yaml docs/openapi.yaml --fail-on-breaking
```

The diff classifies every change BREAKING / ADDITIVE / COSMETIC and is
direction-aware — a field becoming optional is additive in a request and
breaking in a response. It exits nonzero on breaking changes, so all three
compose into a CI job.

Framework coverage for route extraction: Express, NestJS, FastAPI, Flask,
Django REST, Spring Boot, Go (chi/gin/echo), Rails, Laravel.

## Requirements

Python 3 (developed against 3.10). All five scripts are **standard library
only** — nothing to install for drawio-diagrams.

`api-docs` reads YAML specs through PyYAML if it is present; without it the
scripts handle JSON and say so rather than failing quietly. Since specs are
usually YAML:

```bash
pip install pyyaml
```

## Layout

```
.claude/skills/<name>/
  SKILL.md        # frontmatter (name, description) + workflow. The behaviour.
  scripts/        # stdlib-only helpers the skill runs
  references/     # loaded on demand, not up front
  assets/         # templates and starting points
```

`SKILL.md` frontmatter descriptions are trigger-heavy on purpose: they are what
decides whether a skill fires on a request that never names it literally.
Reference files stay out of the initial context and are read only when the task
needs them.

Editing a skill takes effect in the next session started in this repo.
