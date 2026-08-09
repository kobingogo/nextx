# Contributing to NextX

NextX is a local-first, single-account X editorial workbench. Contributions must preserve Markdown as the source of truth, human-controlled publication, and the narrow `do / defer / kill` workflow.

Before opening a pull request, discuss material behavior or storage-format changes in a GitHub issue; preserve v1 JSON compatibility; never add credentials, cookie exports, real Bookmark payloads, private Vault data, or generated `.nextx/` content; and update tests, documentation, and `docs/TASKS.md` when task status changes.

Run these checks from the repository root:

```bash
python -m pip install -e . --no-build-isolation
python -m compileall -q src skills/nextx/scripts/bootstrap.py
python scripts/validate_skill.py
python -m unittest discover -s tests -q
```

The canonical Skill in `skills/nextx/` is product behavior: preserve its explicit setup, preflight, contract, evidence, and publication gates. Do not introduce automatic X posting, credential scraping, cloud synchronization, a database as the source of truth, or speculative plugin frameworks without a concrete issue and maintainer agreement.

By submitting a contribution, you agree that it may be distributed under the repository's [Apache License 2.0](LICENSE).
