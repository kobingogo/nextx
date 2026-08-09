"""Rebuildable cache and identity-based lookup for Vault records."""

from __future__ import annotations

import json
from pathlib import Path

from .records import read_frontmatter
from .vault import atomic_write_text, vault_lock


INDEX_SCHEMA_VERSION = 1


def _empty_index() -> dict[str, object]:
    return {"schema_version": INDEX_SCHEMA_VERSION, "folders": {}}


def _load_index(index_path: Path) -> dict[str, object]:
    """Load a disposable index, treating every malformed variant as empty."""
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return _empty_index()
    if (
        not isinstance(index, dict)
        or index.get("schema_version") != INDEX_SCHEMA_VERSION
        or not isinstance(index.get("folders"), dict)
    ):
        return _empty_index()
    return index


def _is_primary_record(properties: dict[str, object], record_type: str) -> bool:
    return (
        properties.get("type") == record_type
        and properties.get("account_key") == "primary"
    )


def _record_path(folder: Path, filename: str) -> Path | None:
    """Return a safe Markdown child path, rejecting cache path traversal."""
    if Path(filename).name != filename or not filename.endswith(".md"):
        return None
    path = folder / filename
    try:
        path.resolve().relative_to(folder.resolve())
    except (OSError, ValueError):
        return None
    return path


def indexed_records(
    vault: Path,
    folder_name: str,
    record_type: str,
) -> list[tuple[Path, dict[str, object]]]:
    """Return valid primary-account records and refresh the disposable cache."""
    folder = vault / folder_name
    index_path = vault / ".nextx" / "index.json"
    index = _load_index(index_path)
    folders = index["folders"]
    assert isinstance(folders, dict)
    cached = folders.get(folder_name, {})
    cached = cached if isinstance(cached, dict) else {}
    current: dict[str, object] = {}
    records: list[tuple[Path, dict[str, object]]] = []

    if folder.is_dir():
        for path in sorted(folder.glob("*.md")):
            safe_path = _record_path(folder, path.name)
            if safe_path is None:
                continue
            try:
                stat = safe_path.stat()
                properties, _ = read_frontmatter(safe_path)
            except (OSError, ValueError):
                continue
            if not _is_primary_record(properties, record_type):
                continue
            current[safe_path.name] = {
                "mtime_ns": stat.st_mtime_ns,
                "size": stat.st_size,
                "properties": properties,
            }
            records.append((safe_path, properties))

    if current != cached:
        folders[folder_name] = current
        with vault_lock(vault):
            atomic_write_text(
                index_path,
                json.dumps(index, ensure_ascii=False, separators=(",", ":")) + "\n",
            )
    return records


def resolve_record_path(
    vault: Path,
    folder_name: str,
    record_type: str,
    record_id: str,
    *,
    id_field: str = "id",
) -> Path:
    """Resolve by frontmatter identity; consult cache, verify the file, then scan."""
    folder = vault / folder_name
    index = _load_index(vault / ".nextx" / "index.json")
    folders = index["folders"]
    assert isinstance(folders, dict)
    cached = folders.get(folder_name, {})

    if isinstance(cached, dict):
        for filename, entry in cached.items():
            if not isinstance(filename, str) or not isinstance(entry, dict):
                continue
            properties = entry.get("properties")
            if not isinstance(properties, dict) or properties.get(id_field) != record_id:
                continue
            path = _record_path(folder, filename)
            if path is None:
                continue
            try:
                verified, _ = read_frontmatter(path)
            except (OSError, ValueError):
                continue
            if (
                _is_primary_record(verified, record_type)
                and verified.get(id_field) == record_id
            ):
                return path

    if folder.is_dir():
        for path in sorted(folder.glob("*.md")):
            path = _record_path(folder, path.name)
            if path is None:
                continue
            try:
                properties, _ = read_frontmatter(path)
            except (OSError, ValueError):
                continue
            if (
                _is_primary_record(properties, record_type)
                and properties.get(id_field) == record_id
            ):
                return path
    raise FileNotFoundError(f"Record not found: {record_id}")
