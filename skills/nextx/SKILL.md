---
name: nextx
description: Run the local-first NextX editorial workbench for one X account. Use when the user asks to collect X trends, competitor posts or Bookmarks; capture a signal; build today's topic queue; deeply analyze a selected post; make a do/defer/kill topic decision; create or save an X draft; record a manually published post or metrics; or run a weekly X operations review in an Obsidian Vault. Trigger on NextX, X 运营工作台, 热门话题, 选题裁决, 收藏同步, 推文草稿, Outcome, or 周复盘 requests.
---

# NextX

Operate NextX through its deterministic CLI and keep Markdown as the source of truth. Use Agent reasoning only at the explicit analysis, decision, and writing gates.

## Establish context

1. Resolve the user's NextX Vault path. Ask only when it cannot be inferred from the request or current project.
2. Run `nextx doctor --vault PATH --no-smoke` before the first collection in a session. Run the smoke check only when the user asks to verify live Bookmark access.
3. Read only the selected Self or record files needed for the current step. Never send the whole Vault or Bookmark archive to a model.

## Route the request

| Intent | Action |
| --- | --- |
| Initialize | Run `nextx init --vault PATH`; ask the user to complete `00. Self/*.md`. |
| Discover trends with Grok | Give Grok Build `prompts/grok-collector.md`, save its JSON result, then run `nextx collect --vault PATH --source grok --input-json FILE`. |
| Sync Bookmarks | Run `nextx collect --vault PATH --source bookmarks`; use `--dry-run` for a first live check. |
| Import another collector | Require `schemas/collector-envelope.v1.json`, then run `nextx collect --vault PATH --source twitter\|file --input-json FILE`. |
| Capture an idea | Run `nextx add-signal --vault PATH --text TEXT [--source-url URL]`. |
| Build today's queue | Run `nextx today --vault PATH`; present the selected IDs and `04. Views/Today.md`. |
| Deeply analyze one post | Run `nextx analysis-brief --vault PATH SIGNAL_ID`, analyze only that Brief, and separate fact, source opinion, and inference. Do not save a Decision unless requested. |
| Decide do/defer/kill | Run `nextx decision-brief --vault PATH SIGNAL_ID`; invoke the installed `topic-engine`; save its JSON with `nextx save-decision --vault PATH --input-json FILE`. |
| Draft a do Decision | Run `nextx artifact-brief --vault PATH DECISION_ID`; invoke the installed `x-tweet-writer`; let the user choose the final version; save only that version with `nextx save-artifact --vault PATH --input-json FILE`. |
| Record publication | Only after the user has published and supplied the status URL, run `nextx record-published --vault PATH ARTIFACT_ID --url URL`. |
| Record metrics | Build a 24h or 7d Outcome JSON and run `nextx record-outcome --vault PATH ARTIFACT_ID --input-json FILE`. |
| Review the week | Run `nextx weekly-review --vault PATH`; discuss the observations and at most five proposals. Change `Playbook.md` only after explicit approval of one experiment. |

Use `sync-bookmarks` only as the backward-compatible alias for Bookmark collection.

## Respect the gates

- Never publish, delete, like, repost, follow, or modify X through NextX.
- Never convert a `defer` or `kill` Decision into an Artifact.
- Require verifiable evidence for `do`; a Grok summary without a source URL is insufficient.
- Treat Views as rebuildable projections. Persist edits only in Self, Signal, Decision, or Artifact records.
- Preserve manual Markdown edits and report the paths written after each operation.
- Keep stdout JSON available to the next step; on a nonzero exit, surface the JSON error and stop that workflow.

## Report completion

State the completed stage, record IDs, and clickable Vault paths. For collection, include created, duplicate, and rejected counts. For a weekly review, distinguish observations from user-approved Playbook rules.
