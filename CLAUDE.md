# Working in NS Trackstar

## Keep the task list current

Use Claude Code's built-in task tools (`TaskCreate`, `TaskUpdate`, `TaskList`)
as the progress record. They are what Jonny watches: they write to
`~/.claude/todos/`, which is the directory every Claude Code task viewer reads,
so a standard tool shows live progress with nothing custom to install. Two that
work out of the box:

- [Claude Task Viewer](https://github.com/L1AD/claude-task-viewer) — web Kanban
  board, task blocking relationships, timeline mode
- [cc-plan-viewer](https://github.com/tomohiro-owada/cc-plan-viewer) — desktop
  viewer across sessions

Rules that make the list worth watching:

- Run `TaskList` at the start of a session and work from what is already there
  rather than inventing a fresh plan.
- Set a task `in_progress` before you begin, not after. One at a time.
- Set `completed` only on verified work, never on written code. Say how it was
  verified.
- Discovering work outside your task means `TaskCreate`, not silently widening
  the task you are on.
- Subagents track their own progress the same way. Name each one's task in its
  prompt.

The task list is per session. Anything that must outlive this session belongs in
the repo or the Notion roadmap, not only in a task.

### Mirror it to the board Jonny watches

A viewer running on Jonny's machine reads his local `~/.claude/todos/`, which a
remote session's task list never reaches. So when working remotely, mirror the
task list to the board page after each batch of status changes:

> Artifact `write_db`, `db_op: "set"`, collection `board`, doc `tasks`, url
> `https://claude.ai/code/artifact/99861cfa-607f-4b25-b357-a1056b20cee3`
>
> Body: `{"note": "...", "tasks": [{"id", "status", "owner", "subject", "detail"}]}`
> where `status` is `pending`, `in_progress`, `blocked` or `completed`.

Keep finished work in the mirror rather than dropping it, so the board shows
what moved and not just what is left.

## Verify visually before calling UI work done

This project shipped a completely broken first open under green CI, because the
release suite asserted that the map canvas element exists, which stays true when
the map never loads and no data is ever fetched.

So: green CI is evidence about the code paths CI exercises, and nothing more.
For anything that changes what the user sees, look at a real screenshot:

```bash
NEXT_PUBLIC_API_BASE_URL=<backend> pnpm --filter @ns-trackstar/web start
node apps/web/scripts/ui-screenshots.mjs --out /tmp/shots
```

That captures every surface at phone and desktop size. Read the PNGs. The
harness bridges external requests through Node, so the basemap still loads in
sandboxes where the browser process has no outbound network — if the map shows
"Map could not load" there, suspect the environment before the app.

`docs/UI_FINDINGS_2026-09-13.md` records what is already known broken and why.
Read it before re-diagnosing anything on the consumer UI.

## Do not add a twelfth stylesheet

`apps/web/src/app/layout.tsx` stacks eleven global stylesheets carrying 903
`!important` declarations. Every past pass appended a new layer instead of
editing the file that already owned the rule, which is why the result of an edit
depends on import order rather than intent. Three separate layers declare the
project card's max-height; only the last one applies.

`pnpm ui:gate` enforces this and runs in CI. It fails if you add a global layer,
add `!important`, add another token source, or leave an unreachable module
behind. When you pay debt down it also fails until you lower the committed
ceiling with `node scripts/ui-debt-gate.mjs --write`, so progress cannot quietly
erode.

Before changing a CSS value, find which layer actually wins. Editing a losing
declaration changes nothing and looks like the fix did not work.

`.claude/skills/ui-rebuild/SKILL.md` is the phased way out of the stack.

## Design and product truth

- `docs/VISUAL_SYSTEM_V1.md` is canonical for colour, type and touch targets.
  Its "explicitly rejected direction" list describes a build that existed, so
  treat every item on it as a regression test.
- The Notion page "NS Trackstar — Master Roadmap" is the canonical product
  roadmap. Much of it is marked done on the strength of CI rather than
  verification, so confirm before trusting a checkbox.
- Never present collector metadata as project activity. `last_activity_at` is
  the time the collector ran, not the time anything happened to the project, and
  showing it as recency puts a false freshness claim on every record.
