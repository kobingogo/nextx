"""Obsidian Vault layout and safe local persistence."""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
from typing import Iterator


VAULT_FOLDERS = (
    "00. Self",
    "01. Signal",
    "02. Decision",
    "03. Artifact",
    "04. Views",
    ".nextx/runs",
)

DEFAULT_STATE: dict[str, object] = {
    "schema_version": 1,
    "seen_ids": [],
    "last_success_at": None,
    "last_run_id": None,
}


def atomic_write_text(path: Path, text: str) -> None:
    """Write UTF-8 text in the destination directory, then replace atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
            temporary_path = Path(handle.name)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def atomic_write_json(path: Path, value: object) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def state_path(vault: Path) -> Path:
    return vault / ".nextx" / "bookmarks-state.json"


def read_state(vault: Path) -> dict[str, object]:
    path = state_path(vault)
    if not path.exists():
        return dict(DEFAULT_STATE)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Invalid NextX state: {path}")
    return value


def write_state(vault: Path, state: dict[str, object]) -> None:
    atomic_write_json(state_path(vault), state)


def init_vault(vault: Path) -> list[Path]:
    vault = vault.expanduser().resolve()
    vault.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    for relative in VAULT_FOLDERS:
        path = vault / relative
        if not path.exists():
            path.mkdir(parents=True)
            created.append(path)
    if not state_path(vault).exists():
        write_state(vault, dict(DEFAULT_STATE))
        created.append(state_path(vault))
    return created


@contextmanager
def vault_lock(vault: Path) -> Iterator[None]:
    """Hold the one global sync lock for a Vault."""
    lock = vault / ".nextx" / "sync.lock"
    try:
        # ponytail: one global lock is sufficient for a single-account local Vault.
        lock.mkdir()
    except FileExistsError as error:
        raise RuntimeError(f"Another NextX sync is already running: {lock}") from error
    try:
        yield
    finally:
        lock.rmdir()
