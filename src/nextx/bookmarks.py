"""Normalize X bookmarks and persist them as idempotent Signal notes."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import hashlib
from typing import Any

from .records import read_frontmatter, update_frontmatter
from .naming import human_signal_filename, signal_display_title
from .signals import signal_path
from .vault import (
    atomic_write_json,
    atomic_write_text,
    init_vault,
    read_state,
    vault_lock,
    write_state,
)


MAX_BOOKMARKS_PER_SYNC = 500
MAX_BOOKMARK_TEXT_CHARS = 50_000
X_HANDLE = re.compile(r"^[A-Za-z0-9_]{1,15}$")


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
    refreshed: int
    deactivated: int
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
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(f"Bookmark metric {name!r} must be a finite non-negative number")
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
    if len(text) > MAX_BOOKMARK_TEXT_CHARS:
        raise ValueError(f"Bookmark field 'text' must be at most {MAX_BOOKMARK_TEXT_CHARS} characters")
    author = _mapping(item.get("author"), "author")
    author_handle = _required_string(author, "screenName")
    if X_HANDLE.fullmatch(author_handle) is None:
        raise ValueError("Bookmark author screenName must be a valid X handle")
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
    if len(items) > MAX_BOOKMARKS_PER_SYNC:
        raise ValueError(f"Bookmark payload must contain at most {MAX_BOOKMARKS_PER_SYNC} entries")
    return [_normalize_bookmark(item) for item in items]


def _yaml(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _content_fingerprint(text: str) -> str:
    normalized = " ".join(text.casefold().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def render_signal(bookmark: Bookmark, captured_at: datetime) -> str:
    display_title = signal_display_title(bookmark.text)
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
        'last_seen_at: ' + _yaml(captured_iso),
        "self_fit: 3",
        "novelty: 0",
        'why_today: "用户主动收藏，需人工判断其与 Self 的相关性。"',
        f"content_fingerprint: {_yaml(_content_fingerprint(bookmark.text))}",
        'analysis_status: "pending"',
        f"display_title: {_yaml(display_title)}",
        'triage_status: "pending"',
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

尚未判断。

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
        for path in signal_dir.glob("*.md"):
            properties, _ = read_frontmatter(path)
            signal_id = properties.get("id")
            if isinstance(signal_id, str) and signal_id.startswith("x:"):
                seen.add(signal_id[2:])
    return seen


def sync_bookmarks(
    vault: Path,
    payload: object,
    *,
    dry_run: bool = False,
    reconcile: bool = False,
    snapshot_complete: bool = False,
    now: datetime | None = None,
) -> SyncReport:
    if reconcile and not snapshot_complete:
        raise ValueError(
            "Bookmark reconciliation requires an explicitly declared complete snapshot"
        )
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
        refreshed=duplicates,
        deactivated=0,
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
        refreshed = 0
        for bookmark in bookmarks:
            signal_id = f"x:{bookmark.id}"
            try:
                target = signal_path(vault, signal_id)
                exists = True
            except FileNotFoundError:
                target = vault / "01. Signal" / human_signal_filename(
                    signal_id=signal_id,
                    platform="x",
                    author_handle=bookmark.author_handle,
                    observed_at=bookmark.published_at or timestamp.isoformat(),
                    display_title=signal_display_title(bookmark.text),
                )
                exists = False
            if bookmark.id in known_before and exists:
                update_frontmatter(
                    target,
                    {
                        "bookmark_active": True,
                        "last_seen_at": timestamp.isoformat(),
                        "retrieved_at": timestamp.isoformat(),
                        "metrics": bookmark.metrics,
                    },
                )
                refreshed += 1
                continue
            if target.exists():
                raise ValueError(
                    f"Signal filename collision at {target}; refusing to overwrite an unrelated record"
                )
            atomic_write_text(target, render_signal(bookmark, timestamp))
            known_before.add(bookmark.id)

        deactivated = 0
        if reconcile:
            active_ids = {f"x:{bookmark.id}" for bookmark in bookmarks}
            for target in (vault / "01. Signal").glob("*.md"):
                properties, _ = read_frontmatter(target)
                if (
                    properties.get("type") == "signal"
                    and properties.get("bookmark_active") is True
                    and properties.get("id") not in active_ids
                ):
                    update_frontmatter(
                        target,
                        {
                            "bookmark_active": False,
                            "bookmark_inactive_at": timestamp.isoformat(),
                        },
                    )
                    deactivated += 1

        report = SyncReport(
            fetched=len(bookmarks),
            created=created,
            duplicates=duplicates,
            refreshed=refreshed,
            deactivated=deactivated,
            rejected=0,
            dry_run=dry_run,
            run_id=run_id,
        )

        manifest = {
            "schema_version": 1,
            "run_id": run_id,
            "collector": "twitter-cli",
            "finished_at": timestamp.isoformat(),
            "reconcile": reconcile,
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
        write_bookmark_health(vault, status="ready", now=timestamp)
    return report


def bookmark_health_path(vault: Path) -> Path:
    return vault / ".nextx" / "bookmark-health.json"


def read_bookmark_health(vault: Path) -> dict[str, object]:
    path = bookmark_health_path(vault)
    if not path.exists():
        return {"schema_version": 1, "status": "unknown"}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": 1, "status": "unknown"}
    return value if isinstance(value, dict) else {"schema_version": 1, "status": "unknown"}


def write_bookmark_health(
    vault: Path, *, status: str, now: datetime | None = None, error: str | None = None
) -> None:
    timestamp = _utc_now(now).isoformat()
    previous = read_bookmark_health(vault)
    value: dict[str, object] = {
        "schema_version": 1,
        "status": status,
        "updated_at": timestamp,
        "last_success_at": previous.get("last_success_at"),
        "last_error_at": previous.get("last_error_at"),
        "last_error": previous.get("last_error"),
    }
    if status == "ready":
        value.update({"last_success_at": timestamp, "last_error": None})
    elif status == "failed":
        value.update(
            {
                "last_error_at": timestamp,
                "last_error": (error or "Bookmark sync failed")[:1_000],
            }
        )
    atomic_write_json(bookmark_health_path(vault), value)
