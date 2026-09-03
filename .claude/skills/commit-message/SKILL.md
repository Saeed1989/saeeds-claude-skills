---
name: commit-message
description: >-
  Write a commit message for the staged changes in this repo, in its house
  style (Conventional Commits). Use whenever someone is about to commit or
  needs the wording for one — "commit this", "commit my changes", "write a
  commit message", "what should I call this commit", "stage and commit this",
  "make a commit for this fix" — and for rewording or amending an existing
  message. Reads the actual diff, proposes a message, and commits only after
  the user approves.
---

# Commit messages

## Workflow

1. `git diff --staged` and read the hunks. **The message describes what changed
   and why — never a restatement of the filenames.** "update 3 files" is not a
   message.
2. If nothing is staged: run `git status --short`, show what is modified, and
   **ask what to stage**. Never `git add -A` on your own initiative.
3. Check the diff for unrelated concerns (see Splitting).
4. Propose the message and stop. **Do not run `git commit`.**
5. Once the user approves, commit it.

## Format

```
type(scope): summary

Optional body, wrapped at 72 columns, explaining why rather than what.
```

- **type** — one of `feat` `fix` `refactor` `chore` `docs` `test` `perf`. No others.
- **scope** — optional, lowercase, the area touched: a skill name, a script, a
  directory. `fix(diff_openapi)`, `feat(drawio-diagrams)`.
- **summary** — imperative mood: "add", never "added" or "adds". Under 72
  characters including the type and scope. No trailing period. Lowercase after
  the colon.
- **body** — optional. Add one only when the summary cannot carry the *why*:
  a non-obvious cause, a rejected alternative, a consequence for callers.
  Blank line before it, wrapped at 72. Skip it for self-evident changes.

## Splitting

If the staged diff mixes unrelated concerns — a bug fix plus a dependency bump,
two unrelated features, a refactor plus a behaviour change — **say so and
propose separate commits** rather than writing one message that papers over
both. Name the groups and give the `git reset` / `git add -p` commands to
separate them. A `chore:` that quietly bundles a behaviour change is the
failure this rule exists to prevent.

The exception: a change that genuinely cannot be split (a rename that forces
call-site updates) is one commit — say why in the body.

## Calibration

`references/examples.md` holds this repo's own commits, annotated with what
makes each one good or bad, plus the target style. Read it before proposing a
message — house style is what that file shows, not the generic convention.
