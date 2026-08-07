"""Normalize X bookmarks and persist them as idempotent Signal notes."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .vault import (
    atomic_write_json,
    atomic_write_text,
    init_vault,
    read_state,
    vault_lock,
    write_state,
)


@dataclass(frozen=True)
class Bookmark:
    id: str
    text: str
    author_id: str
    author_name: str
    author_handle: str
    published_at: str | None
    metrics: dict[str, int]
    media: tuple[dict[str, Any], ...]
    urls: tuple[str, ...]


@dataclass(frozen=True)
class SyncReport:
    fetched: int
    created: int
    duplicates: int
    rejected: int
    dry_run: bool
    run_id: str


def _mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"Bookmark field {field!r} must be an object")
    return value


def _required_string(mapping: dict[str, Any], field: str) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Bookmark field {field!r} must be a non-empty string")
    return value


def _metric(metrics: dict[str, Any], name: str) -> int:
    value = metrics.get(name, 0)
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Bookmark metric {name!r} must be numeric")
    return int(value)


def _urls(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("Bookmark field 'urls' must be a list")
    normalized: list[str] = []
    for item in value:
        if isinstance(item, str):
            normalized.append(item)
        elif isinstance(item, dict):
            url = item.get("expanded_url") or item.get("url")
            if isinstance(url, str):
                normalized.append(url)
    return tuple(normalized)


def _normalize_bookmark(raw: object) -> Bookmark:
    item = _mapping(raw, "item")
    tweet_id = _required_string(item, "id")
    if not tweet_id.isdigit():
        raise ValueError("Bookmark field 'id' must contain only digits")
    text = _required_string(item, "text")
    author = _mapping(item.get("author"), "author")
    author_handle = _required_string(author, "screenName")
    metrics = _mapping(item.get("metrics", {}), "metrics")
    media_value = item.get("media", [])
    if not isinstance(media_value, list) or not all(isinstance(value, dict) for value in media_value):
        raise ValueError("Bookmark field 'media' must be a list of objects")
    published_at = item.get("createdAtISO")
    if published_at is not None and not isinstance(published_at, str):
        raise ValueError("Bookmark field 'createdAtISO' must be a string")
    return Bookmark(
        id=tweet_id,
        text=text,
        author_id=str(author.get("id", "")),
        author_name=str(author.get("name", author_handle)),
        author_handle=author_handle,
        published_at=published_at,
        metrics={
            "likes": _metric(metrics, "likes"),
            "reposts": _metric(metrics, "retweets"),
            "replies": _metric(metrics, "replies"),
            "quotes": _metric(metrics, "quotes"),
            "views": _metric(metrics, "views"),
            "bookmarks": _metric(metrics, "bookmarks"),
        },
        media=tuple(media_value),
        urls=_urls(item.get("urls")),
    )


def parse_payload(payload: object) -> list[Bookmark]:
    if isinstance(payload, dict):
        if payload.get("ok") is False:
            raise ValueError("twitter-cli reported an unsuccessful response")
        items = payload.get("data")
    else:
        items = payload
    if not isinstance(items, list):
        raise ValueError("Bookmark payload must contain a data list")
    return [_normalize_bookmark(item) for item in items]


def _yaml(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def render_signal(bookmark: Bookmark, captured_at: datetime) -> str:
    source_url = f"https://x.com/{bookmark.author_handle}/status/{bookmark.id}"
    media_types = [
        str(item.get("type")) for item in bookmark.media if item.get("type")
    ]
    media_urls = [
        str(item.get("url")) for item in bookmark.media if item.get("url")
    ]
    related_urls = list(bookmark.urls)
    captured_iso = captured_at.astimezone(timezone.utc).isoformat()
    frontmatter = [
        "---",
        "schema_version: 1",
        'account_key: "primary"',
        f"id: {_yaml(f'x:{bookmark.id}')}",
        'type: "signal"',
        'signal_type: "x_bookmark"',
        'platform: "x"',
        f"source_url: {_yaml(source_url)}",
        f"author_handle: {_yaml(bookmark.author_handle)}",
        f"author_name: {_yaml(bookmark.author_name)}",
        f"published_at: {_yaml(bookmark.published_at)}",
        f"captured_at: {_yaml(captured_iso)}",
        f"retrieved_at: {_yaml(captured_iso)}",
        'collector: "twitter-cli"',
        'source_confidence: "high"',
        "bookmark_active: true",
        'analysis_status: "pending"',
        f"media_types: {_yaml(media_types)}",
        f"metrics: {_yaml(bookmark.metrics)}",
        "---",
    ]
    links = "\n".join(f"- {url}" for url in related_urls) or "- 无"
    media = "\n".join(f"- {url}" for url in media_urls) or "- 无"
    return "\n".join(frontmatter) + f"""

# @{bookmark.author_handle} 的收藏帖子

## 原帖

{bookmark.text}

原帖：{source_url}

## 媒体

{media}

## 外部链接

{links}

## 快速判断

- 内容柱：
- Self 匹配：
- 值得深拆：
- 原因：

## 深度拆解

尚未拆解。

## 关联决策

- 无
"""


def _utc_now(now: datetime | None) -> datetime:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _known_ids(vault: Path, state: dict[str, object]) -> set[str]:
    raw_ids = state.get("seen_ids", [])
    seen = {str(value) for value in raw_ids} if isinstance(raw_ids, list) else set()
    signal_dir = vault / "01. Signal"
    if signal_dir.exists():
        seen.update(path.stem[2:] for path in signal_dir.glob("x-*.md"))
    return seen


def sync_bookmarks(
    vault: Path,
    payload: object,
    *,
    dry_run: bool = False,
    now: datetime | None = None,
) -> SyncReport:
    bookmarks = parse_payload(payload)
    timestamp = _utc_now(now)
    run_id = timestamp.strftime("%Y%m%dT%H%M%S%fZ")
    vault = vault.expanduser().resolve()
    state = read_state(vault)
    known = _known_ids(vault, state)
    created = 0
    duplicates = 0
    for bookmark in bookmarks:
        if bookmark.id in known:
            duplicates += 1
        else:
            known.add(bookmark.id)
            created += 1
    report = SyncReport(
        fetched=len(bookmarks),
        created=created,
        duplicates=duplicates,
        rejected=0,
        dry_run=dry_run,
        run_id=run_id,
    )
    if dry_run:
        return report

    init_vault(vault)
    with vault_lock(vault):
        state = read_state(vault)
        known_before = _known_ids(vault, state)
        for bookmark in bookmarks:
            if bookmark.id in known_before:
                continue
            target = vault / "01. Signal" / f"x-{bookmark.id}.md"
            atomic_write_text(target, render_signal(bookmark, timestamp))
            known_before.add(bookmark.id)

        manifest = {
            "schema_version": 1,
            "run_id": run_id,
            "collector": "twitter-cli",
            "finished_at": timestamp.isoformat(),
            **asdict(report),
        }
        atomic_write_json(vault / ".nextx" / "runs" / f"{run_id}.json", manifest)
        write_state(
            vault,
            {
                "schema_version": 1,
                "seen_ids": sorted(known_before),
                "last_success_at": timestamp.isoformat(),
                "last_run_id": run_id,
            },
        )
    return report
