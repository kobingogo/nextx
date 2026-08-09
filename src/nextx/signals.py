"""Versioned multi-source Signal ingestion."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any

from .naming import human_signal_filename, signal_display_title
from .record_index import resolve_record_path
from .records import read_frontmatter, update_frontmatter
from .vault import atomic_write_json, atomic_write_text, init_vault, vault_lock


X_STATUS = re.compile(
    r"^https://(?:www\.)?(?:x\.com|twitter\.com)/(?P<handle>[A-Za-z0-9_]{1,15})/status/(?P<id>\d+)(?:[/?#].*)?$",
    re.IGNORECASE,
)
MAX_COLLECTOR_ITEMS = 500
MAX_SIGNAL_TEXT_CHARS = 50_000
MAX_URL_CHARS = 2_048


@dataclass(frozen=True)
class Signal:
    id: str
    platform: str
    source_url: str | None
    author_handle: str | None
    published_at: str | None
    retrieved_at: str
    text: str
    metrics: dict[str, int | float]
    media: tuple[object, ...]
    source_confidence: str
    discovery_reason: str | None
    why_today: str | None
    self_fit: int
    novelty: int
    quote_candidate: bool
    quote_window_ends_at: str | None
    reply_candidate: bool
    reply_window_ends_at: str | None
    collector: str
    query: str | None


@dataclass(frozen=True)
class SignalReport:
    fetched: int
    created: int
    duplicates: int
    rejected: int
    dry_run: bool
    run_id: str


def _nonempty_string(value: object, field: str, *, max_chars: int | None = None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Signal field {field!r} must be a non-empty string")
    normalized = value.strip()
    if max_chars is not None and len(normalized) > max_chars:
        raise ValueError(f"Signal field {field!r} must be at most {max_chars} characters")
    return normalized


def _optional_string(
    value: object, field: str, *, max_chars: int | None = None
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Signal field {field!r} must be a string or null")
    normalized = value.strip()
    if max_chars is not None and len(normalized) > max_chars:
        raise ValueError(f"Signal field {field!r} must be at most {max_chars} characters")
    return normalized or None


def _source_id(item: dict[str, Any], source_url: str | None) -> str:
    value = item.get("source_id")
    if isinstance(value, str) and value.strip():
        source_id = value.strip()
        if len(source_id) > 256:
            raise ValueError("Signal field 'source_id' must be at most 256 characters")
        if source_id.startswith("x:") and not source_id[2:].isdigit():
            raise ValueError("X source_id must be x:<numeric-tweet-id>")
        return source_id
    match = X_STATUS.match(source_url or "")
    if match:
        return f"x:{match.group('id')}"
    raise ValueError("Signal requires source_id or a canonical X status URL")


def _timestamp(value: object, field: str, *, optional: bool = False) -> str | None:
    normalized = (
        _optional_string(value, field, max_chars=64)
        if optional
        else _nonempty_string(value, field, max_chars=64)
    )
    if normalized is None:
        return None
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"Signal field {field!r} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        raise ValueError(f"Signal field {field!r} must include a timezone")
    return normalized


def _validate_x_source(
    *, source_id: str, source_url: str | None, author_handle: str | None
) -> None:
    match = X_STATUS.fullmatch(source_url or "")
    if match is None:
        raise ValueError("X Signal requires a canonical https X/Twitter status URL")
    if source_id != f"x:{match.group('id')}":
        raise ValueError("X Signal source_id must match the status URL tweet ID")
    if author_handle is not None and author_handle.casefold() != match.group("handle").casefold():
        raise ValueError("X Signal author_handle must match the status URL handle")


def _metrics(value: object) -> dict[str, int | float]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("Signal field 'metrics' must be an object")
    normalized: dict[str, int | float] = {}
    for key, metric in value.items():
        if (
            isinstance(metric, bool)
            or not isinstance(metric, (int, float))
            or not math.isfinite(metric)
            or metric < 0
        ):
            raise ValueError(f"Signal metric {key!r} must be a finite non-negative number")
        normalized[str(key)] = metric
    return normalized


def _priority_score(value: object, field: str) -> int:
    """Validate an optional 0–5 Collector assessment without treating it as truth."""
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 5:
        raise ValueError(f"Signal field {field!r} must be an integer from 0 to 5")
    return value


def _boolean(value: object, field: str, *, default: bool = False) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ValueError(f"Signal field {field!r} must be a boolean")
    return value


def _conversation_candidate(
    raw: dict[str, Any],
    *,
    kind: str,
    platform: str,
    source_url: str | None,
    author_handle: str | None,
    published_at: str | None,
    retrieved_at: str,
) -> tuple[bool, str | None]:
    """Validate the extra evidence a time-sensitive conversation workflow needs.

    A generic Signal may be incomplete.  A Signal that is explicitly offered
    for a conversation action, however, must retain a canonical original, its author, and a
    collector-supplied decision window.  This prevents a stale or inferred
    post from silently entering the fast path.
    """
    candidate_field = f"{kind}_candidate"
    window_field = f"{kind}_window_ends_at"
    candidate = _boolean(raw.get(candidate_field), candidate_field)
    window = _timestamp(
        raw.get(window_field), window_field, optional=True
    )
    if not candidate:
        if window is not None:
            raise ValueError(
                f"{window_field} is only allowed when {candidate_field}=true"
            )
        return False, None
    if platform != "x" or source_url is None or author_handle is None or published_at is None:
        raise ValueError(
            f"A {candidate_field} requires an X URL, author_handle, and published_at"
        )
    if window is None:
        raise ValueError(f"A {candidate_field} requires {window_field}")
    published = datetime.fromisoformat(published_at.replace("Z", "+00:00")).astimezone(
        timezone.utc
    )
    retrieved = datetime.fromisoformat(retrieved_at.replace("Z", "+00:00")).astimezone(
        timezone.utc
    )
    ends_at = datetime.fromisoformat(window.replace("Z", "+00:00")).astimezone(timezone.utc)
    if ends_at <= published:
        raise ValueError(f"{window_field} must be after published_at")
    if published > retrieved:
        raise ValueError(f"A {candidate_field} published_at cannot be after retrieved_at")
    if retrieved - published > timedelta(hours=72):
        raise ValueError(f"A {candidate_field} must be published within 72 hours of collection")
    if ends_at <= retrieved:
        raise ValueError(f"{window_field} must be after retrieved_at")
    if ends_at - retrieved > timedelta(hours=48):
        raise ValueError(f"{window_field} must be within 48 hours of collection")
    return True, window


def parse_signal_payload(payload: object, collector: str) -> list[Signal]:
    if not isinstance(payload, dict):
        raise ValueError("Collector payload must be an object")
    if payload.get("schema_version") != 1:
        raise ValueError("Collector payload schema_version must be 1")
    if payload.get("account_key") != "primary":
        raise ValueError("Collector payload account_key must be 'primary'")
    payload_collector = _nonempty_string(payload.get("collector"), "collector", max_chars=128)
    if payload_collector != collector:
        raise ValueError(
            f"Collector mismatch: expected {collector!r}, received {payload_collector!r}"
        )
    retrieved_at = _timestamp(payload.get("retrieved_at"), "retrieved_at")
    query = _optional_string(payload.get("query"), "query", max_chars=4_000)
    items = payload.get("items")
    if not isinstance(items, list):
        raise ValueError("Collector payload items must be a list")
    if len(items) > MAX_COLLECTOR_ITEMS:
        raise ValueError(f"Collector payload items must contain at most {MAX_COLLECTOR_ITEMS} entries")

    signals: list[Signal] = []
    for raw in items:
        if not isinstance(raw, dict):
            raise ValueError("Each collector item must be an object")
        confidence = _nonempty_string(raw.get("source_confidence"), "source_confidence", max_chars=16)
        if confidence not in {"high", "medium", "low"}:
            raise ValueError("source_confidence must be high, medium, or low")
        media = raw.get("media", [])
        if not isinstance(media, list):
            raise ValueError("Signal field 'media' must be a list")
        if len(media) > 20:
            raise ValueError("Signal field 'media' must contain at most 20 entries")
        platform = _nonempty_string(raw.get("platform"), "platform", max_chars=64)
        source_url = _optional_string(raw.get("source_url"), "source_url", max_chars=MAX_URL_CHARS)
        author_handle = _optional_string(raw.get("author_handle"), "author_handle", max_chars=64)
        source_id = _source_id(raw, source_url)
        if platform == "x":
            _validate_x_source(
                source_id=source_id,
                source_url=source_url,
                author_handle=author_handle,
            )
        elif source_id.startswith("x:"):
            raise ValueError("An x:<tweet-id> source_id requires platform='x'")
        published_at = _timestamp(raw.get("published_at"), "published_at", optional=True)
        quote_candidate, quote_window_ends_at = _conversation_candidate(
            raw,
            kind="quote",
            platform=platform,
            source_url=source_url,
            author_handle=author_handle,
            published_at=published_at,
            retrieved_at=retrieved_at,
        )
        reply_candidate, reply_window_ends_at = _conversation_candidate(
            raw,
            kind="reply",
            platform=platform,
            source_url=source_url,
            author_handle=author_handle,
            published_at=published_at,
            retrieved_at=retrieved_at,
        )
        signals.append(
            Signal(
                id=source_id,
                platform=platform,
                source_url=source_url,
                author_handle=author_handle,
                published_at=published_at,
                retrieved_at=retrieved_at,
                text=_nonempty_string(raw.get("text"), "text", max_chars=MAX_SIGNAL_TEXT_CHARS),
                metrics=_metrics(raw.get("metrics")),
                media=tuple(media),
                source_confidence=confidence,
                discovery_reason=_optional_string(
                    raw.get("discovery_reason"), "discovery_reason", max_chars=4_000
                ),
                why_today=_optional_string(raw.get("why_today"), "why_today", max_chars=1_000),
                self_fit=_priority_score(raw.get("self_fit"), "self_fit"),
                novelty=_priority_score(raw.get("novelty"), "novelty"),
                quote_candidate=quote_candidate,
                quote_window_ends_at=quote_window_ends_at,
                reply_candidate=reply_candidate,
                reply_window_ends_at=reply_window_ends_at,
                collector=collector,
                query=query,
            )
        )
    return signals


def legacy_signal_filename(signal_id: str) -> str | None:
    """Return the pre-v0.2 filename, when that representation was possible.

    Older Vaults used a lossy slug as the filename. Keep this helper only for
    compatibility resolution and the explicit legacy migration command.
    """
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", signal_id).strip("-")
    return f"{safe}.md" if safe else None


def signal_filename(signal_id: str) -> str:
    """Return the legacy stable, collision-resistant filename for a Signal identity.

    A filename is an index, not the identity itself.  The old ``feed:a`` →
    ``feed-a.md`` transformation silently merged distinct source IDs such as
    ``feed:a`` and ``feed-a``.  Retain a readable prefix while adding the full
    SHA-256 of the original Unicode identifier.  The 160-character prefix keeps
    the resulting filename below common 255-byte filesystem limits for the
    validated 256-character source IDs. New captures use
    :func:`nextx.naming.human_signal_filename`; this name remains for old Vault
    compatibility and explicit migration.
    """
    if not isinstance(signal_id, str) or not signal_id:
        raise ValueError("Signal ID must be a non-empty string")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", signal_id).strip("-") or "signal"
    digest = hashlib.sha256(signal_id.encode("utf-8")).hexdigest()
    return f"{safe[:160]}--{digest}.md"


def signal_path(vault: Path, signal_id: str) -> Path:
    """Resolve a Signal by frontmatter identity, including legacy Vault notes.

    We never trust a filename alone: a legacy slug may belong to a different
    source ID.  This permits a safe, explicit migration later without breaking
    existing Vaults or accidentally reading the wrong record.
    """
    try:
        return resolve_record_path(vault, "01. Signal", "signal", signal_id)
    except FileNotFoundError:
        old_canonical = vault / "01. Signal" / signal_filename(signal_id)
        if old_canonical.is_file():
            properties, _ = read_frontmatter(old_canonical)
            if properties.get("id") != signal_id:
                raise ValueError(
                    f"Signal filename identity mismatch in {old_canonical}; refusing corrupted data"
                )
        raise


def migrate_signal_filenames(vault: Path, *, dry_run: bool = True) -> dict[str, object]:
    """Explicitly migrate legacy Signal filenames without breaking Obsidian links.

    Legacy names remain supported at read time. Applying this migration adds
    the old stem as an Obsidian alias before the atomic rename, so existing
    links keep resolving while historical records use the prior hashed index.
    """
    vault = vault.expanduser().resolve()
    directory = vault / "01. Signal"
    candidates: list[tuple[Path, Path, str]] = []
    conflicts: list[dict[str, str]] = []
    if directory.is_dir():
        for path in sorted(directory.glob("*.md")):
            try:
                properties, _ = read_frontmatter(path)
            except (OSError, ValueError):
                continue
            signal_id = properties.get("id")
            if (
                properties.get("type") != "signal"
                or properties.get("account_key", "primary") != "primary"
                or not isinstance(signal_id, str)
                or not signal_id
            ):
                continue
            if path.name != legacy_signal_filename(signal_id):
                continue
            target = directory / signal_filename(signal_id)
            if path == target:
                continue
            if target.exists():
                conflicts.append(
                    {"id": signal_id, "source": str(path), "target": str(target)}
                )
                continue
            candidates.append((path, target, signal_id))
    if dry_run:
        return {
            "schema_version": 1,
            "ok": not conflicts,
            "command": "migrate-signals",
            "dry_run": True,
            "migrated": [],
            "planned": [
                {"id": signal_id, "source": str(source), "target": str(target)}
                for source, target, signal_id in candidates
            ],
            "conflicts": conflicts,
        }
    if conflicts:
        raise ValueError("Signal filename migration has conflicts; resolve them before applying")
    init_vault(vault)
    migrated: list[dict[str, str]] = []
    with vault_lock(vault):
        for source, target, signal_id in candidates:
            if not source.is_file() or target.exists():
                raise RuntimeError("Signal filenames changed during migration; rerun the dry run")
            properties, _ = read_frontmatter(source)
            if properties.get("id") != signal_id:
                raise RuntimeError("Signal identity changed during migration; rerun the dry run")
            aliases = properties.get("aliases")
            aliases_list = list(aliases) if isinstance(aliases, list) and all(
                isinstance(alias, str) for alias in aliases
            ) else []
            if source.stem not in aliases_list:
                aliases_list.append(source.stem)
                update_frontmatter(source, {"aliases": aliases_list})
            source.replace(target)
            migrated.append({"id": signal_id, "source": str(source), "target": str(target)})
    return {
        "schema_version": 1,
        "ok": True,
        "command": "migrate-signals",
        "dry_run": False,
        "migrated": migrated,
        "planned": [],
        "conflicts": [],
    }


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _content_fingerprint(text: str) -> str:
    normalized = " ".join(text.casefold().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def render_signal(signal: Signal, captured_at: datetime) -> str:
    display_title = signal_display_title(signal.text)
    signal_type = (
        "quote_candidate"
        if signal.quote_candidate
        else "reply_candidate"
        if signal.reply_candidate
        else "manual" if signal.collector == "manual" else "x_discovery"
    )
    properties = [
        "---",
        "schema_version: 1",
        'account_key: "primary"',
        f"id: {_json(signal.id)}",
        'type: "signal"',
        f"signal_type: {_json(signal_type)}",
        f"platform: {_json(signal.platform)}",
        f"source_url: {_json(signal.source_url)}",
        f"author_handle: {_json(signal.author_handle)}",
        f"published_at: {_json(signal.published_at)}",
        f"retrieved_at: {_json(signal.retrieved_at)}",
        f"captured_at: {_json(captured_at.astimezone(timezone.utc).isoformat())}",
        f"collector: {_json(signal.collector)}",
        f"source_confidence: {_json(signal.source_confidence)}",
        f"metrics: {_json(signal.metrics)}",
        f"self_fit: {signal.self_fit}",
        f"novelty: {signal.novelty}",
        f"why_today: {_json(signal.why_today)}",
        f"quote_candidate: {_json(signal.quote_candidate)}",
        f"quote_window_ends_at: {_json(signal.quote_window_ends_at)}",
        f"reply_candidate: {_json(signal.reply_candidate)}",
        f"reply_window_ends_at: {_json(signal.reply_window_ends_at)}",
        f"content_fingerprint: {_json(_content_fingerprint(signal.text))}",
        'analysis_status: "pending"',
        f"display_title: {_json(display_title)}",
        'triage_status: "pending"',
        "---",
    ]
    source = signal.source_url or "无外部 URL"
    reason = signal.discovery_reason or "未提供"
    quote_note = (
        f"- 候选：是\n- 决策窗口截止：{signal.quote_window_ends_at}"
        if signal.quote_candidate
        else "- 非 Quote 候选。"
    )
    reply_note = (
        f"- 候选：是\n- 决策窗口截止：{signal.reply_window_ends_at}"
        if signal.reply_candidate
        else "- 非 Reply 候选。"
    )
    return "\n".join(properties) + f"""

# Signal · {signal.id}

## 原始内容

{signal.text}

来源：{source}

## 入选原因

{reason}

## 快速判断

尚未判断。

## Quote 机会

{quote_note}

## Reply 机会

{reply_note}

## 深度拆解

尚未拆解。

## 关联决策

- 无
"""


def _utc_now(now: datetime | None) -> datetime:
    value = now or datetime.now(timezone.utc)
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def ingest_signals(
    vault: Path,
    payload: object,
    *,
    collector: str,
    dry_run: bool = False,
    now: datetime | None = None,
) -> SignalReport:
    signals = parse_signal_payload(payload, collector)
    timestamp = _utc_now(now)
    run_id = timestamp.strftime("%Y%m%dT%H%M%S%fZ")
    vault = vault.expanduser().resolve()
    seen: set[str] = set()
    created = 0
    duplicates = 0
    for signal in signals:
        try:
            signal_path(vault, signal.id)
            exists = True
        except FileNotFoundError:
            exists = False
        if signal.id in seen or exists:
            duplicates += 1
        else:
            seen.add(signal.id)
            created += 1
    report = SignalReport(len(signals), created, duplicates, 0, dry_run, run_id)
    if dry_run:
        return report

    init_vault(vault)
    with vault_lock(vault):
        written: set[str] = set()
        for signal in signals:
            try:
                signal_path(vault, signal.id)
                exists = True
            except FileNotFoundError:
                exists = False
            display_title = signal_display_title(signal.text)
            observed_at = signal.published_at or signal.retrieved_at or timestamp.isoformat()
            target = vault / "01. Signal" / human_signal_filename(
                signal_id=signal.id,
                platform=signal.platform,
                author_handle=signal.author_handle,
                observed_at=observed_at,
                display_title=display_title,
            )
            if signal.id in written or exists:
                continue
            if target.exists():
                raise ValueError(
                    f"Signal filename collision at {target}; refusing to overwrite an unrelated record"
                )
            atomic_write_text(target, render_signal(signal, timestamp))
            written.add(signal.id)
        atomic_write_json(
            vault / ".nextx" / "runs" / f"signals-{run_id}.json",
            {
                "schema_version": 1,
                "account_key": "primary",
                "run_id": run_id,
                "collector": collector,
                "finished_at": timestamp.isoformat(),
                **asdict(report),
            },
        )
    return report


def add_manual_signal(
    vault: Path,
    text: str,
    source_url: str | None = None,
    *,
    dry_run: bool = False,
    now: datetime | None = None,
) -> SignalReport:
    normalized_text = " ".join(text.split())
    if not normalized_text:
        raise ValueError("Manual Signal text cannot be empty")
    if len(normalized_text) > MAX_SIGNAL_TEXT_CHARS:
        raise ValueError(f"Manual Signal text must be at most {MAX_SIGNAL_TEXT_CHARS} characters")
    normalized_url = source_url.strip() if isinstance(source_url, str) and source_url.strip() else None
    digest = hashlib.sha256(f"{normalized_text}\n{normalized_url or ''}".encode()).hexdigest()[:20]
    timestamp = _utc_now(now)
    payload = {
        "schema_version": 1,
        "account_key": "primary",
        "collector": "manual",
        "query": None,
        "retrieved_at": timestamp.isoformat(),
        "items": [
            {
                "source_id": f"manual:{digest}",
                "platform": "internal",
                "source_url": normalized_url,
                "author_handle": None,
                "published_at": None,
                "text": normalized_text,
                "metrics": {},
                "media": [],
                "source_confidence": "high",
                "discovery_reason": "User-added Signal",
                "why_today": "用户主动加入，优先处理。",
                "self_fit": 5,
                "novelty": 0,
            }
        ],
    }
    return ingest_signals(
        vault, payload, collector="manual", dry_run=dry_run, now=timestamp
    )
