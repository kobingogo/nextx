"""Rebuildable Obsidian projections over NextX records."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .records import read_frontmatter
from .vault import atomic_write_text, init_vault


def _timestamp(properties: dict[str, object]) -> datetime:
    value = properties.get("published_at") or properties.get("captured_at")
    if not isinstance(value, str):
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def _records(folder: Path, record_type: str) -> list[tuple[Path, dict[str, object]]]:
    records: list[tuple[Path, dict[str, object]]] = []
    if not folder.exists():
        return records
    for path in folder.glob("*.md"):
        try:
            properties, _ = read_frontmatter(path)
        except ValueError:
            continue
        if properties.get("type") == record_type:
            records.append((path, properties))
    return records


def _decided_signal_ids(vault: Path) -> set[str]:
    decided: set[str] = set()
    for _, properties in _records(vault / "02. Decision", "decision"):
        values = properties.get("signal_ids", [])
        if isinstance(values, list):
            decided.update(str(value) for value in values)
    return decided


def _card(path: Path, properties: dict[str, object], reason: str) -> str:
    signal_id = str(properties.get("id", path.stem))
    author = properties.get("author_handle")
    author_text = f"@{author}" if author else "手动输入"
    source = properties.get("source_url") or "本地内容"
    metrics = properties.get("metrics") or {}
    return f"""### [[{path.stem}|{signal_id}]]

- 作者：{author_text}
- 来源：{source}
- 时间：{properties.get('published_at') or properties.get('captured_at') or '未知'}
- 指标：`{metrics}`
- 入选：{reason}
"""


def _render_bookmark_inbox(
    vault: Path, signals: list[tuple[Path, dict[str, object]]], generated_at: str
) -> None:
    bookmarks = [
        record for record in signals if record[1].get("signal_type") == "x_bookmark"
    ]
    bookmarks.sort(key=lambda record: _timestamp(record[1]), reverse=True)
    cards = "\n".join(
        _card(path, properties, "X Bookmark") for path, properties in bookmarks[:100]
    )
    content = cards or "暂无收藏 Signal。\n"
    atomic_write_text(
        vault / "04. Views" / "Bookmark Inbox.md",
        f"# Bookmark Inbox\n\n生成时间：{generated_at}\n\n{content}",
    )


def render_today(
    vault: Path, *, now: datetime | None = None
) -> dict[str, object]:
    vault = vault.expanduser().resolve()
    init_vault(vault)
    timestamp = now or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    generated_at = timestamp.astimezone(timezone.utc).isoformat()
    decided = _decided_signal_ids(vault)
    signals = _records(vault / "01. Signal", "signal")
    pending = [
        record for record in signals if str(record[1].get("id")) not in decided
    ]
    pending.sort(key=lambda record: _timestamp(record[1]), reverse=True)
    manual = [record for record in pending if record[1].get("signal_type") == "manual"][:2]
    automatic_pool = [
        record for record in pending if record[1].get("signal_type") != "manual"
    ]
    author_counts: Counter[str] = Counter()
    automatic: list[tuple[Path, dict[str, object]]] = []
    for record in automatic_pool:
        author = record[1].get("author_handle")
        author_key = str(author) if author else ""
        if author_key and author_counts[author_key] >= 2:
            continue
        automatic.append(record)
        if author_key:
            author_counts[author_key] += 1
        if len(automatic) == 10:
            break

    cards = [
        _card(path, properties, "人工保留位") for path, properties in manual
    ] + [
        _card(path, properties, "未裁决、近期且满足作者多样性")
        for path, properties in automatic
    ]
    card_text = "\n".join(cards) if cards else "暂无待裁决 Signal。"
    view = f"""# Today · 待裁决

生成时间：{generated_at}

- 自动候选：{len(automatic)} / 10
- 手动保留：{len(manual)} / 2
- 已排除已裁决 Signal：{len(decided)}

{card_text}
"""
    path = vault / "04. Views" / "Today.md"
    atomic_write_text(path, view)
    _render_bookmark_inbox(vault, signals, generated_at)
    selected = manual + automatic
    return {
        "schema_version": 1,
        "ok": True,
        "command": "today",
        "view": str(path),
        "manual_count": len(manual),
        "automatic_count": len(automatic),
        "selected_ids": [str(properties.get("id")) for _, properties in selected],
    }
