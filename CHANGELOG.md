# Changelog

## Unreleased

## v0.3.0-alpha.2

- Fixed isolated installation and CI builds by declaring `setuptools`/`wheel` build requirements and enabling build isolation; bundled schemas and prompts are now present in wheel installs.
- Fixed the Bookmark → Signal → Decision path by accepting both collector headings (`原帖` and `原始内容`).
- Closed learning-loop edge cases: expired early Outcome windows are rejected, independent samples are keyed by Decision/experiment, zero-action samples can reach `stop`, and late backfills cannot distort rates.
- Added Conversion cold-start actions, changed the north star to `do Decision → review-ready Artifact`, and made Planner completion counts use published/measured Artifacts only.
- Enforced Artifact format contracts, consolidated Outcome frontmatter/body writes, and protected View, registry, and handoff writes with the Vault lock.
- Corrected Skill metadata validation and pinned the standalone installer default ref to `v0.3.0-alpha.2`.

- Growth Strategy now orders Discovery, Authority and Conversion work from the weekly lane allocation.
- Growth Loop includes regular Signals alongside Reply and Quote opportunities.
- Weekly Review reports a defined, computable north star: `do Decision → review-ready Artifact` median latency, target ≤20 minutes.
- Outcome windows are due-time gated and revisions retain their previous machine snapshot.
- Playbook proposals include evidence links, a low-performing counterexample, and a `repeat` / `alter` / `stop` recommendation for human confirmation.

## v0.2.0-rc.1

- Prevented lossy Signal filename collisions; added `nextx migrate-signals` preview/apply migration with Obsidian aliases.
- Made Vault lock recovery safe on Windows.
- Added single-account projection filtering and complete-snapshot protection for Bookmark reconciliation.
- Installer now installs the project into its isolated runtime and supports `--upgrade` for standalone source caches.
- Bundled NextX core workflow is usable when optional AYI Skills are unavailable; installed enhanced Skills remain preferred.

## v0.2.0

- Introduced the local-first single-account Growth Loop, Agent conversation routing, Obsidian Markdown records, manual X publication gate, Quote/Reply lanes, and 1h/24h/7d Outcomes.
