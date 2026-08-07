# NextX Bookmark MVP Implementation Plan

> **已被完整产品计划取代。** 本文只作为 `Signal/Bookmarks` 子模块的历史实施记录；NextX 的交付边界以 `2026-08-07-nextx-complete-product-design.md` 和完整产品实施计划为准。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local Python CLI that initializes a NextX Obsidian Vault, synchronizes the authenticated X account's bookmarks idempotently, and prepares one selected Signal for Agent-led deep analysis.

**Architecture:** `twitter-cli` remains the only X collector in v0.1. The `nextx` CLI validates and normalizes its JSON, writes stable Markdown Signals plus small JSON state/run manifests, and emits an Analysis Brief that Codex, Claude Code, or Grok Build can process through one canonical Skill. The operating system invokes the one-shot sync command every 180 seconds.

**Tech Stack:** Python 3.11+ standard library, `unittest`, Markdown/JSON files, Obsidian, `twitter-cli` 0.8.5+.

## Global Constraints

- Single authenticated X account only.
- New bookmarks must reach the Vault within five minutes while the workstation scheduler is active.
- Use no runtime dependency beyond the Python 3.11 standard library.
- Keep the four product primitives: Self, Signal, Decision, Artifact.
- Never store X cookies or tokens in the Vault.
- Never overwrite an existing Signal file.
- Never post, reply, DM, or mutate X state.
- Agent analysis receives only the selected Signal and necessary linked context.
- No Web frontend, database, Obsidian plugin, custom daemon, MCP server, multi-account layer, or collector factory.

---

## File Structure

```text
NextX/
├── pyproject.toml                   # package metadata and `nextx` console script
├── README.md                        # installation and first-run workflow
├── src/nextx/
│   ├── __init__.py                  # package version
│   ├── __main__.py                  # `python -m nextx`
│   ├── cli.py                       # argparse command surface and JSON responses
│   ├── vault.py                     # Vault layout, atomic files, state, lock
│   ├── bookmarks.py                 # validation, normalization, Markdown, sync report
│   ├── twitter_cli.py               # read-only subprocess adapter and smoke check
│   └── analysis.py                  # selected Signal lookup and Analysis Brief
├── skills/nextx/SKILL.md            # canonical Agent operating workflow
├── examples/com.nextx.bookmarks.plist
├── docs/product-architecture.md
├── tests/
│   ├── fixtures/bookmarks.json
│   ├── test_vault.py
│   ├── test_bookmarks.py
│   ├── test_twitter_cli.py
│   ├── test_analysis.py
│   └── test_cli.py
└── .gitignore
```

---

### Task 1: Vault Initialization and Safe Persistence

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `src/nextx/__init__.py`
- Create: `src/nextx/vault.py`
- Test: `tests/test_vault.py`

**Interfaces:**
- Produces: `init_vault(vault: Path) -> list[Path]`
- Produces: `atomic_write_text(path: Path, text: str) -> None`
- Produces: `read_state(vault: Path) -> dict[str, object]`
- Produces: `write_state(vault: Path, state: dict[str, object]) -> None`
- Produces: `vault_lock(vault: Path) -> ContextManager[None]`

- [ ] **Step 1: Write failing Vault tests**

```python
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from nextx.vault import init_vault, read_state, vault_lock


class VaultTests(unittest.TestCase):
    def test_init_creates_stable_type_folders_and_state(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            init_vault(vault)
            self.assertTrue((vault / "00. Self").is_dir())
            self.assertTrue((vault / "01. Signal").is_dir())
            self.assertTrue((vault / "02. Decision").is_dir())
            self.assertTrue((vault / "03. Artifact").is_dir())
            self.assertTrue((vault / "04. Views").is_dir())
            self.assertEqual(read_state(vault)["seen_ids"], [])

    def test_existing_lock_fails_immediately(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            init_vault(vault)
            with vault_lock(vault):
                with self.assertRaises(RuntimeError):
                    with vault_lock(vault):
                        pass
```

- [ ] **Step 2: Run the tests and verify import failure**

Run: `PYTHONPATH=src python -m unittest tests.test_vault -v`  
Expected: `ModuleNotFoundError: No module named 'nextx'`.

- [ ] **Step 3: Implement the minimal Vault layer**

Use `Path.mkdir`, `tempfile.NamedTemporaryFile`, and `Path.replace`. The initial state is exactly:

```python
{"schema_version": 1, "seen_ids": [], "last_success_at": None, "last_run_id": None}
```

`vault_lock` atomically creates `.nextx/sync.lock` as a directory and removes it in `finally`.

- [ ] **Step 4: Run Vault tests**

Run: `PYTHONPATH=src python -m unittest tests.test_vault -v`  
Expected: two passing tests.

- [ ] **Step 5: Commit Task 1**

```bash
git add pyproject.toml .gitignore src/nextx/__init__.py src/nextx/vault.py tests/test_vault.py
git commit -m "feat: initialize local NextX vault"
```

---

### Task 2: Bookmark Validation, Normalization, and Idempotent Sync

**Files:**
- Create: `src/nextx/bookmarks.py`
- Create: `tests/fixtures/bookmarks.json`
- Create: `tests/test_bookmarks.py`

**Interfaces:**
- Consumes: `init_vault`, `read_state`, `write_state`, `atomic_write_text`, `vault_lock`
- Produces: immutable `Bookmark` dataclass
- Produces: immutable `SyncReport` dataclass with `fetched`, `created`, `duplicates`, `rejected`, `dry_run`, `run_id`
- Produces: `parse_payload(payload: object) -> list[Bookmark]`
- Produces: `render_signal(bookmark: Bookmark, captured_at: datetime) -> str`
- Produces: `sync_bookmarks(vault: Path, payload: object, *, dry_run: bool = False, now: datetime | None = None) -> SyncReport`

- [ ] **Step 1: Add a realistic two-item fixture**

The fixture outer shape is:

```json
{
  "ok": true,
  "schema_version": "1",
  "data": [
    {
      "id": "2084556671712477485",
      "text": "Example bookmarked post",
      "author": {"id": "10", "name": "Example", "screenName": "example"},
      "metrics": {"likes": 58, "retweets": 2, "replies": 3, "quotes": 1, "views": 80373, "bookmarks": 28},
      "createdAtISO": "2026-08-04T08:26:54+00:00",
      "media": [{"type": "video", "url": "https://video.example/item.mp4", "width": 1080, "height": 1920}],
      "urls": []
    },
    {
      "id": "2084556671712477486",
      "text": "Second post",
      "author": {"id": "11", "name": "Second", "screenName": "second"},
      "metrics": {"likes": 4, "retweets": 0, "replies": 1, "quotes": 0, "views": 100, "bookmarks": 2},
      "createdAtISO": "2026-08-05T08:26:54+00:00",
      "media": [],
      "urls": ["https://example.com/source"]
    }
  ]
}
```

- [ ] **Step 2: Write failing sync tests**

Cover these exact behaviors:

```python
def test_sync_creates_two_signals_and_state(): ...
def test_second_sync_is_duplicate_and_preserves_manual_edit(): ...
def test_invalid_item_rejects_whole_batch_before_writes(): ...
def test_dry_run_writes_nothing(): ...
```

The first test asserts `01. Signal/x-2084556671712477485.md` exists, contains `analysis_status: "pending"`, and state contains both IDs. The second appends `\nmanual note\n`, syncs again, and asserts the text remains. The invalid test removes the second ID and asserts no Signal exists and `last_success_at` remains `None`.

- [ ] **Step 3: Run tests and verify failures**

Run: `PYTHONPATH=src python -m unittest tests.test_bookmarks -v`  
Expected: import failure for `nextx.bookmarks`.

- [ ] **Step 4: Implement validation and rendering**

Validation must require string `id`, string `text`, mapping `author`, and non-empty `author.screenName`. Metrics and media are optional and default to empty values. YAML scalar values use `json.dumps(value, ensure_ascii=False)` so strings and inline JSON stay valid without PyYAML.

Signal filenames are `x-<tweet-id>.md`; `source_url` is constructed as `https://x.com/<screenName>/status/<id>`.

- [ ] **Step 5: Implement sync ordering**

`sync_bookmarks` must:

1. Parse and validate the entire payload before acquiring the lock.
2. Initialize the Vault.
3. Acquire the global lock.
4. Compute unknown IDs from existing files and state.
5. Return counts only when `dry_run=True`.
6. Atomically write each unknown Signal.
7. Write `.nextx/runs/<run-id>.json` without post text.
8. Update state last.

- [ ] **Step 6: Run bookmark tests**

Run: `PYTHONPATH=src python -m unittest tests.test_bookmarks -v`  
Expected: four passing tests.

- [ ] **Step 7: Commit Task 2**

```bash
git add src/nextx/bookmarks.py tests/fixtures/bookmarks.json tests/test_bookmarks.py
git commit -m "feat: sync X bookmarks into signals"
```

---

### Task 3: Read-Only twitter-cli Adapter and CLI Surface

**Files:**
- Create: `src/nextx/twitter_cli.py`
- Create: `src/nextx/cli.py`
- Create: `src/nextx/__main__.py`
- Create: `tests/test_twitter_cli.py`
- Create: `tests/test_cli.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `fetch_bookmarks(limit: int, *, runner: Callable = subprocess.run) -> object`
- Produces: `doctor(vault: Path, *, runner: Callable = subprocess.run) -> dict[str, object]`
- Produces: `main(argv: Sequence[str] | None = None) -> int`

- [ ] **Step 1: Write failing adapter tests**

Use a fake runner and assert the exact command:

```python
["twitter", "bookmarks", "-n", "50", "--json"]
```

Cover valid JSON, missing binary, non-zero exit, and malformed JSON. Errors must raise `TwitterCLIError` without including cookie values or raw environment data.

- [ ] **Step 2: Write failing CLI tests**

Patch `nextx.cli.fetch_bookmarks` and run:

```python
main(["init", "--vault", tmp])
main(["sync-bookmarks", "--vault", tmp, "--input-json", fixture])
main(["doctor", "--vault", tmp, "--no-smoke"])
```

Assert exit code `0` and parse stdout as JSON. `doctor --no-smoke` must report the binary and Vault checks without reading private bookmarks.

- [ ] **Step 3: Run tests and verify failures**

Run: `PYTHONPATH=src python -m unittest tests.test_twitter_cli tests.test_cli -v`  
Expected: imports fail.

- [ ] **Step 4: Implement the adapter**

Use `shutil.which("twitter")` and `subprocess.run(..., capture_output=True, text=True, check=False)`. Reject `limit < 1` or `limit > 500`. Parse only stdout as JSON.

- [ ] **Step 5: Implement argparse commands**

Commands and behavior:

- `init`: create Vault and return created paths.
- `doctor`: check Python version, Vault writeability, twitter binary, then fetch one bookmark unless `--no-smoke` is set.
- `sync-bookmarks`: use `--input-json` when present; otherwise call twitter-cli. Default limit is 200 for empty state and 50 after the first successful sync.
- All successful commands emit one JSON object to stdout.
- All expected failures emit `{"ok": false, "error": "..."}` to stderr and return `1`.

- [ ] **Step 6: Add the console entry point**

```toml
[project.scripts]
nextx = "nextx.cli:main"
```

- [ ] **Step 7: Run adapter and CLI tests**

Run: `PYTHONPATH=src python -m unittest tests.test_twitter_cli tests.test_cli -v`  
Expected: all tests pass.

- [ ] **Step 8: Commit Task 3**

```bash
git add pyproject.toml src/nextx/twitter_cli.py src/nextx/cli.py src/nextx/__main__.py tests/test_twitter_cli.py tests/test_cli.py
git commit -m "feat: add bookmark sync CLI"
```

---

### Task 4: Selected-Signal Analysis Brief and Agent Skill

**Files:**
- Create: `src/nextx/analysis.py`
- Create: `tests/test_analysis.py`
- Create: `skills/nextx/SKILL.md`
- Modify: `src/nextx/cli.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produces: `normalize_signal_id(value: str) -> str`
- Produces: `build_analysis_brief(vault: Path, signal_id: str) -> dict[str, str]`
- Adds CLI: `nextx analysis-brief --vault <path> <tweet-id-or-signal-id>`

- [ ] **Step 1: Write failing analysis tests**

Create one Signal through `sync_bookmarks`, then assert both `2084556671712477485` and `x:2084556671712477485` resolve to the same file. Assert the Brief contains these exact headings:

```text
一句话主张
钩子机制
内容结构
证据质量
社交货币
传播动力
可迁移模式
不可照搬部分
可衍生选题
事实 / 观点 / 推断
```

Unknown IDs must raise `FileNotFoundError`.

- [ ] **Step 2: Run tests and verify failure**

Run: `PYTHONPATH=src python -m unittest tests.test_analysis -v`  
Expected: import failure for `nextx.analysis`.

- [ ] **Step 3: Implement the Brief**

The returned dictionary is exactly:

```python
{
    "signal_id": "x:<id>",
    "signal_path": "/absolute/path/to/x-<id>.md",
    "brief": "<analysis instructions followed by selected Signal markdown>",
}
```

Do not read other Signal files or Self automatically.

- [ ] **Step 4: Add and test the CLI command**

Run: `PYTHONPATH=src python -m unittest tests.test_analysis tests.test_cli -v`  
Expected: all tests pass and CLI output is valid JSON.

- [ ] **Step 5: Write the canonical Agent Skill**

The Skill must instruct the Agent to:

1. Run `nextx doctor` before X reads.
2. Run `nextx sync-bookmarks` for sync requests.
3. Run `nextx analysis-brief` for one selected Signal.
4. Analyze only the returned Signal and necessary linked post/thread/media.
5. Separate facts, opinions, and inference.
6. Write the result under the Signal's `# 深度拆解` heading without changing frontmatter or user notes.
7. Invoke `topic-engine` only when the user requests an angle or Decision.
8. Invoke `x-tweet-writer` only after a `do` Decision and explicit writing request.
9. Never post or mutate X.

- [ ] **Step 6: Commit Task 4**

```bash
git add src/nextx/analysis.py src/nextx/cli.py tests/test_analysis.py tests/test_cli.py skills/nextx/SKILL.md
git commit -m "feat: prepare bookmarks for agent analysis"
```

---

### Task 5: Product Architecture, Scheduler Example, and End-to-End Verification

**Files:**
- Create: `docs/product-architecture.md`
- Create: `examples/com.nextx.bookmarks.plist`
- Create: `README.md`

**Interfaces:**
- Documents the approved product architecture and one-account Bookmark workflow.
- Scheduler invokes only `nextx sync-bookmarks --vault <absolute-vault-path>` every 180 seconds.

- [ ] **Step 1: Write product architecture documentation**

Document:

- Positioning and north-star metrics.
- Self, Signal, Decision, Artifact ownership.
- Agent conversation, CLI core, Obsidian storage, and collector boundaries.
- Grok Build for open discovery; twitter-cli for private Bookmarks and exact X details.
- Bookmark light-triage versus selected deep-analysis flow.
- Local persistence versus selected cloud inference privacy boundary.
- v0.1 exclusions and Phase 2 official X API option.

- [ ] **Step 2: Add a valid launchd template**

Use `StartInterval` value `180`, `RunAtLoad` true, and explicit placeholders `/ABSOLUTE/PATH/TO/nextx` and `/ABSOLUTE/PATH/TO/Vault`. The README must tell the user to replace both before loading it.

- [ ] **Step 3: Write the README quick start**

Commands:

```bash
python3.11 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/nextx init --vault /absolute/path/to/vault
.venv/bin/nextx doctor --vault /absolute/path/to/vault
.venv/bin/nextx sync-bookmarks --vault /absolute/path/to/vault
.venv/bin/nextx analysis-brief --vault /absolute/path/to/vault x:2084556671712477485
```

- [ ] **Step 4: Run all unit tests**

Run: `PYTHONPATH=src python -m unittest discover -s tests -v`  
Expected: all tests pass.

- [ ] **Step 5: Run package and CLI smoke checks**

Run:

```bash
python -m compileall -q src
PYTHONPATH=src python -m nextx --help
PYTHONPATH=src python -m nextx sync-bookmarks --vault /tmp/nextx-demo --input-json tests/fixtures/bookmarks.json
PYTHONPATH=src python -m nextx analysis-brief --vault /tmp/nextx-demo x:2084556671712477485
```

Expected: compile succeeds; help exits zero; sync reports two created Signals; Analysis Brief returns valid JSON.

- [ ] **Step 6: Validate launchd XML and documentation links**

Run:

```bash
plutil -lint examples/com.nextx.bookmarks.plist
git diff --check
```

Expected: `OK` and no whitespace errors.

- [ ] **Step 7: Commit Task 5**

```bash
git add README.md docs/product-architecture.md examples/com.nextx.bookmarks.plist
git commit -m "docs: define NextX architecture and local scheduling"
```

---

## Plan Self-Review

- Spec coverage: Vault persistence, idempotent sync, `twitter-cli`, dry-run, lock, Analysis Brief, Agent workflow, scheduler, privacy, documentation, and verification each have a task.
- Dependency check: runtime and tests use only Python 3.11 standard library.
- Type consistency: Task 2 defines `Bookmark`, `SyncReport`, `parse_payload`, `render_signal`, and `sync_bookmarks`; later tasks consume those exact names.
- Scope check: official X API, cancellation reconciliation, media download/transcription, automatic topic generation, and posting remain outside v0.1.
- Placeholder check: scheduler paths are deliberate user configuration values and are explicitly validated/documented, not incomplete implementation steps.
