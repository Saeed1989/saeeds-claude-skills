# House style, calibrated against this repo

**Provenance, so you know what to trust here.** This repo had four commits when
this file was written (`git log --oneline`), and all four are off-style — the
house style is the target below, not what the log currently shows. So this file
is in two parts:

- **Part 1** quotes all four real commits verbatim, with what each actually
  changed and the message it should have had. Real SHAs; check them with
  `git show`.
- **Part 2** is target-style messages written for **real changesets in this
  repo** — work that exists in the tree but was swept into the big "adds skill"
  commits rather than committed separately. The changes are real; the messages
  were never in the log.

Refresh Part 1 from `git log` once the history has commits worth imitating, and
retire Part 2 as real ones replace it.

---

## Part 1 — the existing log, and what it should have been

### 1. `923f626` — `first commit`

Added `README.md` containing one line: `# saeeds-claude-skills`.

**Bad.** "first commit" describes the position in history, not the change. Every
repo's first commit is the first commit; the word carries nothing. No type, no
scope.

```
chore: add readme with repo title
```

### 2. `693c633` — `adds skill`

Added the whole `drawio-diagrams` skill: `SKILL.md`, four references, two
scripts (`build_drawio.py`, `validate_drawio.py`), and `template.drawio` —
2,171 lines across 8 files.

**Bad on three counts.** Wrong mood ("adds" — the convention is "add"). No type
or scope. And *which* skill? The message is indistinguishable from the next
commit, so `git log --oneline` shows two lines that both say a skill was added
and neither says which.

```
feat(drawio-diagrams): add skill for generating editable .drawio files
```

### 3. `50b27aa` — `adds skill api-docs`

Added the `api-docs` skill: `SKILL.md`, three references, three scripts
(`validate_openapi.py`, `diff_openapi.py`, `check_coverage.py`), and
`starter-openapi.yaml` — 2,459 lines across 8 files.

**Better — it names the skill — but still wrong.** "adds" again, and the scope
belongs in the parentheses where tooling can parse it, not trailing off the end
of the summary.

```
feat(api-docs): add skill for generating and diffing OpenAPI specs
```

### 4. `551e9c2` — `adds readme`

Replaced the one-line README with an 86-line index: skill table, per-skill
sections, requirements, layout conventions.

**Bad, and actively misleading.** "adds readme" describes commit 1. This one
*replaced* a placeholder with a real index — a reader scanning the log sees two
commits adding a readme and cannot tell which one matters.

```
docs: replace placeholder readme with skill index
```

---

## Part 2 — target style, real changesets

### 5. Simple one-liner

```
fix(validate_drawio): skip parent check for structural cells 0 and 1
```

The whole change fits in the summary: when `id="1"` was missing, every cell
cascaded a bogus "parent does not exist" error and buried the eight real ones.
Scope names the script. No body needed — the summary is the entire story.

### 6. One-liner, behaviour visible in the summary

```
fix(build_drawio): shift layout back on-canvas only when it overflows
```

Says what it does *and* implies the old behaviour. Compare "fix layout bug",
which says nothing.

### 7. With a body — the cause is not obvious

```
fix(diff_openapi): compare through unchanged $ref wrappers

The old == new shortcut returned early whenever two schema subtrees were
textually identical. A page envelope whose items are {"$ref": ".../Order"}
is identical in both specs even when Order itself changed, so every field
removed from Order went unreported behind the unchanged wrapper -- three
breaking changes missed on GET /v1/orders.

The shortcut now applies only to subtrees with no $ref anywhere.
```

This earns its body. The summary alone would leave a reader wondering how a
diff could miss a removed field. The body gives the mechanism, the blast radius
(three missed breaking changes), and the fix — and nothing about *which lines*
moved, which the diff already shows.

### 8. With a body — a rejected alternative

```
refactor(build_drawio): drop back edges before assigning layers

Longest-path layering inflated every downstream node on a graph with a
cycle: a retry edge pointing at an earlier service pushed its own target
one layer deeper per relaxation pass, turning a six-node flowchart into a
26-layer staircase.

A DFS now marks back edges and excludes them from layering; they are still
drawn. The bounded relaxation cap stays as a safety net for self-loops and
anything the DFS ordering misses.
```

The last paragraph is why the body exists: it records that the cap was kept
deliberately, so nobody deletes it later as dead code.

### 9. Scoped fix, no body

```
fix(check_coverage): normalise :id and <int:id> path params before matching
```

Names the scope, the inputs, and the operation. A reader who knows the codebase
needs nothing more.

### 10. Refactor — no behaviour change, and says so

```
refactor(validate_openapi): extract response checks into check_responses
```

`refactor` is a promise that behaviour is unchanged. If behaviour changed, the
type is `fix` or `feat`, however much the diff looks like a move.

### 11. Docs

```
docs(api-docs): document the merge rule as the skill's top priority
```

`docs` covers reference files and skill prose. Note the scope is the skill, not
the filename — scopes name areas, so they stay stable when files are renamed.

### 12. Chore

```
chore: remove __pycache__ left by a test run
```

`chore` is for changes with no effect on behaviour or documented interface.
It is not a bucket for "I could not decide" — if a `chore` needs a body to
explain what it really does, it is the wrong type.

### 13. Perf

```
perf(build_drawio): bound layer relaxation to node count + 2 passes
```

`perf` when the point is speed or resource use. This one is also a correctness
guard, but the reason it was written was to stop a cyclic graph from spinning —
pick the type that matches the intent.

---

## Recurring mistakes in this repo's log

| Pattern | Instead |
| --- | --- |
| `adds skill` | `feat(drawio-diagrams): add ...` — imperative, typed, scoped |
| `adds readme` for two different changes | say which change: `add` vs `replace` |
| Scope trailing the summary (`adds skill api-docs`) | put it in parentheses: `feat(api-docs):` |
| `first commit` | describe the change, not its position in history |
| A message that would fit any of the last four commits | name the thing that changed |

Two rules the current log breaks every time, worth stating plainly: **imperative
mood** ("add", never "adds" or "added" — the summary completes the sentence
"this commit will ..."), and **name the specific thing** — a message that could
be pasted onto three different commits is not a message.
