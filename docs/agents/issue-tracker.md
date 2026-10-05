# Issue tracker: GitHub via claude-gh-harness

Issues and specs for this repo live as GitHub issues.

Never call Homebrew `gh` or a bare `gh`. Every `gh` or `git` command that targets GitHub goes through the harness shims. The shim `gh` always acts as the GitHub App `qveys-claude-bot`, never a personal identity. `gh auth login`, `logout`, `token`, `refresh`, `setup-git`, and `switch` are refused.

Prefix every call:

```bash
PATH=/usr/local/libexec/claude-gh-harness/bin:$PATH gh …
```

Same prefix for `git` aimed at GitHub. The `git` shim refuses `git push` to GitHub. Publishing a commit uses `git-signed-commit` (the branch must already exist on `origin`):

```bash
PATH=/usr/local/libexec/claude-gh-harness/bin:$PATH git-signed-commit -m "message"
```

Check the harness with `claude-gh-check` (exit code = number of failures). Do not bypass the shims.

## Conventions

- **Create an issue**: `PATH=/usr/local/libexec/claude-gh-harness/bin:$PATH gh issue create --title "..." --body "..."`. Use a heredoc for multi-line bodies.
- **Read an issue**: `PATH=/usr/local/libexec/claude-gh-harness/bin:$PATH gh issue view <number> --comments`, filtering comments by `jq` and also fetching labels.
- **List issues**: `PATH=/usr/local/libexec/claude-gh-harness/bin:$PATH gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'` with appropriate `--label` and `--state` filters.
- **Comment on an issue**: `PATH=/usr/local/libexec/claude-gh-harness/bin:$PATH gh issue comment <number> --body "..."`
- **Apply / remove labels**: `PATH=/usr/local/libexec/claude-gh-harness/bin:$PATH gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **Close**: `PATH=/usr/local/libexec/claude-gh-harness/bin:$PATH gh issue close <number> --comment "..."`

Infer the repo from `git remote -v`. There is no GitHub remote until one is added; the shim cannot publish before that.

## Pull requests as a triage surface

**PRs as a request surface: no.** _(Set to `yes` if this repo treats external PRs as feature requests; `/triage` reads this flag.)_

When set to `yes`, PRs run through the same labels and states as issues, using the harness-prefixed `gh pr` equivalents:

- **Read a PR**: `PATH=/usr/local/libexec/claude-gh-harness/bin:$PATH gh pr view <number> --comments` and `gh pr diff <number>` for the diff.
- **List external PRs for triage**: `PATH=/usr/local/libexec/claude-gh-harness/bin:$PATH gh pr list --state open --json number,title,body,labels,author,authorAssociation,comments` then keep only `authorAssociation` of `CONTRIBUTOR`, `FIRST_TIME_CONTRIBUTOR`, or `NONE` (drop `OWNER`/`MEMBER`/`COLLABORATOR`).
- **Comment / label / close**: harness-prefixed `gh pr comment`, `gh pr edit --add-label`/`--remove-label`, `gh pr close`.

GitHub shares one number space across issues and PRs, so a bare `#42` may be either: resolve with harness-prefixed `gh pr view 42` and fall back to `gh issue view 42`.

## When a skill says "publish to the issue tracker"

Create a GitHub issue with the harness-prefixed `gh issue create`.

## When a skill says "fetch the relevant ticket"

Run harness-prefixed `gh issue view <number> --comments`.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single issue with **child** issues as tickets. Every `gh` / `gh api` call below is harness-prefixed (`PATH=/usr/local/libexec/claude-gh-harness/bin:$PATH`).

- **Map**: a single issue labelled `wayfinder:map`, holding the Notes / Decisions-so-far / Fog body. `gh issue create --label wayfinder:map`.
- **Child ticket**: an issue linked to the map as a GitHub sub-issue (`gh api` on the sub-issues endpoint). Where sub-issues aren't enabled, add the child to a task list in the map body and put `Part of #<map>` at the top of the child body. Labels: `wayfinder:<type>` (`research`/`prototype`/`grilling`/`task`). Once claimed, the ticket is assigned to the driving dev.
- **Blocking**: GitHub's **native issue dependencies**, the canonical, UI-visible representation. Add an edge with `gh api --method POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`, where `<blocker-db-id>` is the blocker's numeric **database id** (`gh api repos/<owner>/<repo>/issues/<n> --jq .id`, _not_ the `#number` or `node_id`). GitHub reports `issue_dependencies_summary.blocked_by` (open blockers only, the live gate). Where dependencies aren't available, fall back to a `Blocked by: #<n>, #<n>` line at the top of the child body. A ticket is unblocked when every blocker is closed.
- **Frontier query**: list the map's open children (`gh issue list --state open`, scoped to the map's sub-issues / task list), drop any with an open blocker (`issue_dependencies_summary.blocked_by > 0`, or an open issue in the `Blocked by` line) or an assignee; first in map order wins.
- **Claim**: `gh issue edit <n> --add-assignee @me`, the session's first write.
- **Resolve**: `gh issue comment <n> --body "<answer>"`, then `gh issue close <n>`, then append a context pointer (gist + link) to the map's Decisions-so-far.
