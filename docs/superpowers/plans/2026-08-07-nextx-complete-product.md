# NextX Complete Product Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a working local-first, single-account NextX vertical slice from Self and multi-source Signals through Decision, Artifact, Outcome, Weekly Review, and Agent orchestration.

**Architecture:** A dependency-free Python 3.11 CLI is the deterministic execution and persistence core. Obsidian Markdown is the user-owned system of record; rebuildable Views are derived from records. Codex, Claude Code, and Grok Build share one canonical Skill and invoke existing `topic-engine` and `x-tweet-writer` rather than duplicating their rules.

**Tech Stack:** Python 3.11+ standard library, `unittest`, Obsidian Markdown, JSON collector contracts, `twitter-cli` 0.8.5+.

## Global Constraints

- Single X account in v0.1.
- Keep only Self, Signal, Decision, and Artifact as persisted product primitives.
- Use no runtime dependency beyond Python 3.11 standard library.
- Never overwrite an existing record unless the command explicitly records a lifecycle transition or Outcome.
- Never store cookies, tokens, or model credentials in the Vault.
- Never publish, reply, like, bookmark, follow, or DM from NextX.
- Keep Grok Build as the primary discovery collector and twitter-cli as exact X/Bookmark collector.
- Reuse `topic-engine` for Decision reasoning and `x-tweet-writer` for post writing.
- Limit Today to 10 automatic plus 2 manual Signals.
- Keep all Agent/model calls outside the Python core.
- No Web UI, database, Obsidian plugin, custom daemon, MCP server, multi-account framework, or speculative provider factory.

---

### Task 1: Stabilize the Existing Core and CLI Contract

**Files:**
- Modify: `src/nextx/cli.py`
- Modify: `tests/test_cli.py`
- Existing: `src/nextx/vault.py`, `src/nextx/bookmarks.py`, `src/nextx/twitter_cli.py`

**Interfaces:**
- Keeps: `main(argv: Sequence[str] | None = None) -> int`
- Keeps: `sync_bookmarks(...) -> SyncReport`
- Produces stable stdout/stderr JSON that respects Python stream redirection.

- [ ] Fix the already-failing CLI tests by changing `_print_json(..., stream=None)` and selecting `sys.stdout` at call time.
- [ ] Add a test that expected failures return code `1` and JSON only on stderr.
- [ ] Run `PYTHONPATH=src python -m unittest discover -s tests -v`; all existing tests must pass.
- [ ] Commit: `fix: stabilize NextX CLI output`.

---

### Task 2: Shared Markdown Records and Self Bootstrap

**Files:**
- Create: `src/nextx/records.py`
- Create: `src/nextx/self_model.py`
- Create: `tests/test_records.py`
- Create: `tests/test_self_model.py`
- Modify: `src/nextx/vault.py`
- Modify: `src/nextx/cli.py`

**Interfaces:**
- Produces: `read_frontmatter(path: Path) -> tuple[dict[str, object], str]`
- Produces: `update_frontmatter(path: Path, changes: dict[str, object]) -> None`
- Produces: `append_markdown(path: Path, markdown: str) -> None`
- Produces: `ensure_self_templates(vault: Path) -> list[Path]`
- `nextx init` creates `Profile.md`, `Voice.md`, `Pillars.md`, `Monitoring.md`, and `Playbook.md` only when absent.

- [ ] Write tests proving JSON-compatible frontmatter values round-trip, body text is preserved, and explicit property updates do not remove unknown user properties.
- [ ] Run tests and confirm missing-module failure.
- [ ] Implement the smallest line-based frontmatter reader/updater for NextX-generated files; do not implement general YAML.
- [ ] Write Self bootstrap tests proving first init creates five templates and second init preserves a manual edit.
- [ ] Implement concise templates with onboarding questions, no generated strategy claims.
- [ ] Run all tests and commit: `feat: bootstrap Self and shared records`.

---

### Task 3: Generic Signal Contract, Manual Capture, and Grok Import

**Files:**
- Create: `src/nextx/signals.py`
- Create: `tests/fixtures/grok-signals.json`
- Create: `tests/test_signals.py`
- Create: `prompts/grok-collector.md`
- Modify: `src/nextx/cli.py`
- Modify: `src/nextx/bookmarks.py`

**Interfaces:**
- Produces immutable `Signal` and `SignalReport` dataclasses.
- Produces: `parse_signal_payload(payload: object, collector: str) -> list[Signal]`
- Produces: `ingest_signals(vault: Path, payload: object, *, collector: str, dry_run: bool = False) -> SignalReport`
- Produces: `add_manual_signal(vault: Path, text: str, source_url: str | None = None) -> SignalReport`
- Adds CLI:
  - `nextx collect --source bookmarks [--limit N] [--input-json FILE] [--dry-run]`
  - `nextx collect --source grok|twitter|file --input-json FILE [--dry-run]`
  - `nextx add-signal --text TEXT [--source-url URL]`
- Keeps `sync-bookmarks` as a compatibility alias.

- [ ] Test normalized Grok import, cross-run deduplication by `source_id`, URL-derived X IDs, manual SHA-256 IDs, whole-batch validation, and dry-run.
- [ ] Run tests and confirm failure before implementation.
- [ ] Implement one generic JSON contract without collector classes or a provider registry.
- [ ] Make Bookmarks write the same common Signal frontmatter fields while preserving its richer media body.
- [ ] Write `prompts/grok-collector.md` requiring verifiable X URLs, exact quotes only when present, confidence, discovery reason, and the shared JSON shape.
- [ ] Run all tests and commit: `feat: ingest multi-source signals`.

---

### Task 4: Today Queue and Rebuildable Obsidian Views

**Files:**
- Create: `src/nextx/views.py`
- Create: `tests/test_views.py`
- Modify: `src/nextx/cli.py`

**Interfaces:**
- Produces: `render_today(vault: Path, *, now: datetime | None = None) -> dict[str, object]`
- Produces `04. Views/Today.md` and `04. Views/Bookmark Inbox.md`.
- Adds CLI: `nextx today --vault PATH`.

- [ ] Test that decided Signals are excluded, automatic items cap at 10, manual reserve caps at 2, one author caps at 2, and newest valid records win within each group.
- [ ] Test that rebuilding a View replaces only the generated View, never a source record.
- [ ] Implement deterministic frontmatter-only selection; Self semantic fit remains an Agent responsibility in v0.1.
- [ ] Render each candidate with wikilink, source, author, age, metrics, and explicit selection reason.
- [ ] Run all tests and commit: `feat: render daily decision queue`.

---

### Task 5: Auditable Do/Defer/Kill Decisions

**Files:**
- Create: `src/nextx/decisions.py`
- Create: `tests/test_decisions.py`
- Modify: `src/nextx/cli.py`
- Modify: `src/nextx/views.py`

**Interfaces:**
- Produces: `save_decision(vault: Path, payload: object, *, now: datetime | None = None) -> dict[str, object]`
- Produces: `decision_brief(vault: Path, signal_id: str) -> dict[str, str]`
- Adds CLI:
  - `nextx decision-brief --vault PATH SIGNAL_ID`
  - `nextx save-decision --vault PATH --input-json FILE`

- [ ] Test the three verdicts, missing Signal rejection, invalid verdict rejection, and `do` requirements: non-empty angle, evidence sufficient, original value, and risk.
- [ ] Test `defer` and `kill` only require a reason code and short reason.
- [ ] Implement stable `decision:<timestamp>-<hash>` IDs and new-file-only persistence.
- [ ] Build the `topic-engine` handoff Brief from selected Signal plus paths to Self files, without embedding all Self content.
- [ ] Update Decision Board View generation and Today exclusion.
- [ ] Run all tests and commit: `feat: persist auditable topic decisions`.

---

### Task 6: Artifact Brief, Draft Persistence, and Manual Publish Record

**Files:**
- Create: `src/nextx/artifacts.py`
- Create: `tests/test_artifacts.py`
- Modify: `src/nextx/cli.py`
- Modify: `src/nextx/views.py`

**Interfaces:**
- Produces: `artifact_brief(vault: Path, decision_id: str) -> dict[str, str]`
- Produces: `save_artifact(vault: Path, payload: object, *, now: datetime | None = None) -> dict[str, object]`
- Produces: `record_published(vault: Path, artifact_id: str, url: str, *, now: datetime | None = None) -> dict[str, object]`
- Adds CLI:
  - `nextx artifact-brief --vault PATH DECISION_ID`
  - `nextx save-artifact --vault PATH --input-json FILE`
  - `nextx record-published --vault PATH ARTIFACT_ID --url URL`

- [ ] Test that only `do` Decisions can create Artifacts, draft text is required, and Artifact links its Decision and source Signals.
- [ ] Test that record-published accepts only `https://x.com/.../status/...` or `https://twitter.com/.../status/...`, changes status to `published`, and preserves draft/user notes.
- [ ] Build the `x-tweet-writer` Brief with Self file paths, Decision body, evidence links, format, and risk.
- [ ] Run all tests and commit: `feat: manage artifact lifecycle`.

---

### Task 7: Outcome Snapshots and Weekly Learning Loop

**Files:**
- Create: `src/nextx/learning.py`
- Create: `tests/test_learning.py`
- Modify: `src/nextx/cli.py`
- Modify: `src/nextx/views.py`

**Interfaces:**
- Produces: `record_outcome(vault: Path, artifact_id: str, payload: object, *, now: datetime | None = None) -> dict[str, object]`
- Produces: `render_weekly_review(vault: Path, *, now: datetime | None = None) -> dict[str, object]`
- Adds CLI:
  - `nextx record-outcome --vault PATH ARTIFACT_ID --input-json FILE`
  - `nextx weekly-review --vault PATH`

- [ ] Test 24h and 7d windows, numeric non-negative metrics, published-only guard, duplicate-window replacement, and status `measured` after 7d.
- [ ] Store each snapshot as a human-readable Markdown table plus a machine-readable `nextx-outcome` HTML comment.
- [ ] Test Weekly Review counts all verdicts, conversion to Artifact, top/bottom measured posts, median draft latency when timestamps exist, and creates at most five empty proposal slots plus one “下周唯一实验” slot.
- [ ] Implement no automatic Playbook write.
- [ ] Run all tests and commit: `feat: close the outcome learning loop`.

---

### Task 8: Analysis Brief, Canonical Agent Skill, and Product Documentation

**Files:**
- Create: `src/nextx/analysis.py`
- Create: `tests/test_analysis.py`
- Create: `skills/nextx/SKILL.md`
- Create: `docs/product-architecture.md`
- Create: `README.md`
- Create: `examples/com.nextx.bookmarks.plist`
- Modify: `src/nextx/cli.py`

**Interfaces:**
- Produces: `build_analysis_brief(vault: Path, signal_id: str) -> dict[str, str]`
- Adds CLI: `nextx analysis-brief --vault PATH SIGNAL_ID`.

- [ ] Test bare tweet ID and `x:<id>` resolution, unknown ID rejection, and required decomposition headings.
- [ ] Implement a selected-Signal-only Brief with fact/opinion/inference separation.
- [ ] Use the skill-creator instructions to write one canonical Skill that maps natural language to all NextX commands, invokes `topic-engine` and `x-tweet-writer` at their proper gates, and never posts.
- [ ] Write user-facing product architecture from the master spec without duplicating implementation-plan detail.
- [ ] Write installation, onboarding, Grok JSON import, Bookmark schedule, daily flow, weekly flow, privacy, and troubleshooting documentation.
- [ ] Add a valid macOS launchd template with `StartInterval=180` and explicit path replacement instructions.
- [ ] Run all tests and commit: `docs: deliver NextX product workflow`.

---

### Task 9: End-to-End and Live Read-Only Verification

**Files:**
- Modify only when a failing test proves a defect.

- [ ] Run `python -m compileall -q src`.
- [ ] Run `PYTHONPATH=src python -m unittest discover -s tests -v`.
- [ ] Create a temporary Vault and execute the complete fixture-backed flow: init, Grok import, Bookmark import, manual Signal, Today, Decision, Artifact, publish record, Outcome, Weekly Review.
- [ ] Run `nextx doctor` against the real local environment.
- [ ] Run one real Bookmark `--dry-run`; do not persist the user's private bookmark text in the repository.
- [ ] Run `plutil -lint examples/com.nextx.bookmarks.plist` and `git diff --check`.
- [ ] Review all commands for any X write verb; there must be none.
- [ ] Commit any verification-proven fixes separately.

---

## Plan Self-Review

- Complete-product coverage: Self, all Signal sources, Bookmarks, Today, Decision, Artifact, Outcome, Learn, Obsidian Views, Agent Skill, scheduling, privacy, and open-source documentation each have a task.
- Vertical acceptance: fixture-backed Task 9 crosses every product primitive and the Learn process.
- Existing-work reuse: tested Vault and Bookmark code is retained and normalized into the shared Signal contract.
- Dependency discipline: no database, runtime package, server, frontend, provider registry, or custom scheduler is introduced.
- Agent boundary: model reasoning remains in existing Skills; Python handles validation, state, files, and reproducibility.
- No placeholders: exact external scheduler paths remain documented user configuration, not incomplete code.
