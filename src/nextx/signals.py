"""Versioned multi-source Signal ingestion."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from .vault import atomic_write_json, atomic_write_text, init_vault, vault_lock


X_STATUS = re.compile(
    r"^https?://(?:www\.)?(?:x\.com|twitter\.com)/[^/]+/status/(\d+)(?:[/?#].*)?$",
    re.IGNORECASE,
)


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


def _nonempty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Signal field {field!r} must be a non-empty string")
    return value.strip()


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Signal field {field!r} must be a string or null")
    return value.strip() or None


def _source_id(item: dict[str, Any]) -> str:
    value = item.get("source_id")
    if isinstance(value, str) and value.strip():
        source_id = value.strip()
        if source_id.startswith("x:") and not source_id[2:].isdigit():
            raise ValueError("X source_id must be x:<numeric-tweet-id>")
        return source_id
    source_url = _optional_string(item.get("source_url"), "source_url")
    match = X_STATUS.match(source_url or "")
    if match:
        return f"x:{match.group(1)}"
    raise ValueError("Signal requires source_id or a canonical X status URL")


def _metrics(value: object) -> dict[str, int | float]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("Signal field 'metrics' must be an object")
    normalized: dict[str, int | float] = {}
    for key, metric in value.items():
        if isinstance(metric, bool) or not isinstance(metric, (int, float)):
            raise ValueError(f"Signal metric {key!r} must be numeric")
        normalized[str(key)] = metric
    return normalized


def parse_signal_payload(payload: object, collector: str) -> list[Signal]:
    if not isinstance(payload, dict):
        raise ValueError("Collector payload must be an object")
    if payload.get("schema_version") != 1:
        raise ValueError("Collector payload schema_version must be 1")
    if payload.get("account_key") != "primary":
        raise ValueError("Collector payload account_key must be 'primary'")
    payload_collector = _nonempty_string(payload.get("collector"), "collector")
    if payload_collector != collector:
        raise ValueError(
            f"Collector mismatch: expected {collector!r}, received {payload_collector!r}"
        )
    retrieved_at = _nonempty_string(payload.get("retrieved_at"), "retrieved_at")
    query = _optional_string(payload.get("query"), "query")
    items = payload.get("items")
    if not isinstance(items, list):
        raise ValueError("Collector payload items must be a list")

    signals: list[Signal] = []
    for raw in items:
        if not isinstance(raw, dict):
            raise ValueError("Each collector item must be an object")
        confidence = _nonempty_string(raw.get("source_confidence"), "source_confidence")
        if confidence not in {"high", "medium", "low"}:
            raise ValueError("source_confidence must be high, medium, or low")
        media = raw.get("media", [])
        if not isinstance(media, list):
            raise ValueError("Signal field 'media' must be a list")
        signals.append(
            Signal(
                id=_source_id(raw),
                platform=_nonempty_string(raw.get("platform"), "platform"),
                source_url=_optional_string(raw.get("source_url"), "source_url"),
                author_handle=_optional_string(raw.get("author_handle"), "author_handle"),
                published_at=_optional_string(raw.get("published_at"), "published_at"),
                retrieved_at=retrieved_at,
                text=_nonempty_string(raw.get("text"), "text"),
                metrics=_metrics(raw.get("metrics")),
                media=tuple(media),
                source_confidence=confidence,
                discovery_reason=_optional_string(
                    raw.get("discovery_reason"), "discovery_reason"
                ),
                collector=collector,
                query=query,
            )
        )
    return signals


def signal_filename(signal_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", signal_id).strip("-")
    if not safe:
        raise ValueError("Signal ID cannot produce an empty filename")
    return f"{safe}.md"


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def render_signal(signal: Signal, captured_at: datetime) -> str:
    signal_type = "manual" if signal.collector == "manual" else "x_discovery"
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
        'analysis_status: "pending"',
        "---",
    ]
    source = signal.source_url or "无外部 URL"
    reason = signal.discovery_reason or "未提供"
    return "\n".join(properties) + f"""

# Signal · {signal.id}

## 原始内容

{signal.text}

来源：{source}

## 入选原因

{reason}

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
        target = vault / "01. Signal" / signal_filename(signal.id)
        if signal.id in seen or target.exists():
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
            target = vault / "01. Signal" / signal_filename(signal.id)
            if signal.id in written or target.exists():
                continue
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
            }
        ],
    }
    return ingest_signals(
        vault, payload, collector="manual", dry_run=dry_run, now=timestamp
    )
