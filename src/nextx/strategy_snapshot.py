"""Stable fingerprinting for the active growth strategy."""

from __future__ import annotations

import hashlib
from pathlib import Path


SELF_SNAPSHOT_FILES = (
    "Profile.md",
    "Pillars.md",
    "Voice.md",
    "Growth Strategy.md",
    "Playbook.md",
)


def strategy_snapshot_id(vault: Path) -> str:
    """Return a deterministic identity for the strategy-defining Self files."""
    digest = hashlib.sha256()
    root = vault.expanduser().resolve() / "00. Self"
    for name in SELF_SNAPSHOT_FILES:
        path = root / name
        text = path.read_text(encoding="utf-8") if path.is_file() else "<missing>"
        normalized = "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").split("\n"))
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(normalized.encode("utf-8"))
        digest.update(b"\0")
    return f"strategy:{digest.hexdigest()[:16]}"
