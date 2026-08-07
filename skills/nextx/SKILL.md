---
name: nextx
description: Run the local-first NextX editorial workbench for one X account. Use when the user asks to collect X trends, competitor posts or Bookmarks; capture a signal; build today's topic queue; deeply analyze a selected post; make a do/defer/kill topic decision; create or save an X draft; record a manually published post or metrics; or run a weekly X operations review in an Obsidian Vault. Trigger on NextX, X 运营工作台, 热门话题, 选题裁决, 收藏同步, 推文草稿, Outcome, or 周复盘 requests.
---

# NextX

Operate NextX through its deterministic CLI and keep Markdown as the source of truth. Use Agent reasoning only at the explicit analysis, decision, and writing gates.

## Install and establish context

1. If this is the first use, run `python3 skills/nextx/scripts/bootstrap.py` and use the JSON `executable` it returns for all following commands. The script creates a user-scoped Python 3.11+ runtime and never installs or authenticates `twitter-cli`.
2. Run `<nextx> setup --runtime RUNTIME` once, where `RUNTIME` is the bootstrap JSON value (omit it if no runtime was returned). It creates the default `~/Documents/NextX` Vault and Self templates, is idempotent, and preserves manual Markdown. Use `setup --vault PATH` once to choose another Vault.
3. Run `<nextx> doctor --no-smoke` before the first collection in a session. Missing `twitter-cli` is an optional warning in this mode; run the smoke check only when the user asks to verify live Bookmark access.
4. Commands may omit `--vault` after setup. Resolution is explicit `--vault`, `NEXTX_VAULT`, saved user config, then `~/Documents/NextX`.
5. Read only the selected Self or record files needed for the current step. Never send the whole Vault or Bookmark archive to a model.

## Route the request

| Intent | Action |
| --- | --- |
| Initialize | Run `<nextx> setup --runtime RUNTIME --yes` using bootstrap's runtime (omit when unavailable); ask the user to complete `00. Self/*.md`. |
| Discover trends with Grok | Give Grok Build `prompts/grok-collector.md`, save its JSON result, then run `<nextx> collect --source grok --input-json FILE`. |
| Sync Bookmarks | Run `<nextx> collect --source bookmarks`; use `--dry-run` for a first live check. |
| Import another collector | Require `schemas/collector-envelope.v1.json`, then run `<nextx> collect --source twitter\|file --input-json FILE`. |
| Capture an idea | Run `<nextx> add-signal --text TEXT [--source-url URL]`. |
| Build today's queue | Run `<nextx> today`; present the selected IDs and `04. Views/Today.md`. |
| Deeply analyze one post | Run `<nextx> analysis-brief SIGNAL_ID`, analyze only that Brief, and separate fact, source opinion, and inference. Do not save a Decision unless requested. |
| Decide do/defer/kill | Run `<nextx> decision-brief SIGNAL_ID`; invoke the installed `topic-engine`; save its JSON with `<nextx> save-decision --input-json FILE`. |
| Draft a do Decision | Run `<nextx> artifact-brief DECISION_ID`; invoke the installed `x-tweet-writer`; let the user choose the final version; save only that version with `<nextx> save-artifact --input-json FILE`. |
| Record publication | Only after the user has published and supplied the status URL, run `<nextx> record-published ARTIFACT_ID --url URL`. |
| Record metrics | Build a 24h or 7d Outcome JSON and run `<nextx> record-outcome ARTIFACT_ID --input-json FILE`. |
| Review the week | Run `<nextx> weekly-review`; discuss the observations and at most five proposals. Change `Playbook.md` only after explicit approval of one experiment. |

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
