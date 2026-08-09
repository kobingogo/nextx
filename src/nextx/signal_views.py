"""Disposable classification inboxes derived from authoritative Signal notes."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re

from .record_index import indexed_records
from .triage import (
    ACTIONS,
    CONFIDENCE_LEVELS,
    CONTENT_LANES,
    FACTOR_WEIGHTS,
    triage_is_stale,
)
from .vault import atomic_write_text, init_vault, vault_lock


VIEW_FILES = {
    "immediate_action": "Immediate Action.md",
    "ai_productivity": "AI Productivity.md",
    "ai_content": "AI Content.md",
    "builder_core": "Builder Core.md",
    "adjacent_exploration": "Adjacent Exploration.md",
    "needs_triage": "Needs Triage.md",
    "archived": "Archived.md",
}

_VIEW_TITLES = {
    "immediate_action": "Immediate Action",
    "ai_productivity": "AI Productivity",
    "ai_content": "AI Content",
    "builder_core": "Builder Core",
    "adjacent_exploration": "Adjacent Exploration",
    "needs_triage": "Needs Triage",
    "archived": "Archived",
}
_CONFIDENCE_ORDER = {"high": 3, "medium": 2, "low": 1}
_RAW_HASH = re.compile(r"[0-9a-f]{64}", re.IGNORECASE)


def _utc_now(now: datetime | None) -> datetime:
    value = now or datetime.now(timezone.utc)
    if not isinstance(value, datetime):
        raise ValueError("now must be a datetime")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _score(properties: dict[str, object]) -> int:
    value = properties.get("triage_score")
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
        return -1
    return value


def _valid_ready_triage(properties: dict[str, object]) -> bool:
    title = properties.get("display_title")
    lane = properties.get("content_lane")
    action = properties.get("recommended_action")
    confidence = properties.get("triage_confidence")
    factors = properties.get("triage_factors")
    return (
        properties.get("triage_version") == 1
        and isinstance(title, str)
        and bool(title.strip())
        and lane in CONTENT_LANES
        and action in ACTIONS - {"archive"}
        and _score(properties) >= 0
        and confidence in CONFIDENCE_LEVELS
        and isinstance(factors, dict)
        and set(factors) == set(FACTOR_WEIGHTS)
        and all(
            isinstance(value, int)
            and not isinstance(value, bool)
            and 0 <= value <= 5
            for value in factors.values()
        )
        and isinstance(properties.get("triage_action_eligible"), bool)
        and (
            action not in {"quote", "reply"}
            or _action_deadline(properties) is not None
        )
    )


def _action_deadline(properties: dict[str, object]) -> datetime | None:
    action = properties.get("recommended_action")
    if action not in {"quote", "reply"}:
        return None
    if properties.get(f"{action}_candidate") is not True:
        return None
    return _parse_time(properties.get(f"{action}_window_ends_at"))


def _compact(value: object, fallback: str) -> str:
    if not isinstance(value, str) or not value.strip():
        return fallback
    return " ".join(value.split())


def _card(path: Path, properties: dict[str, object], *, note: str | None = None) -> str:
    raw_title = _compact(
        properties.get("display_title") or properties.get("id") or path.stem,
        path.stem,
    )
    title = ("未命名 Signal" if _RAW_HASH.fullmatch(raw_title) else raw_title).replace(
        "|", "／"
    ).replace("]", "）")
    author = properties.get("author_handle")
    platform = _compact(properties.get("platform"), "unknown")
    author_text = f"@{author}" if isinstance(author, str) and author.strip() else "手动输入"
    action = _compact(properties.get("recommended_action"), "待判断")
    score = properties.get("triage_score")
    score_text = (
        str(score)
        if isinstance(score, int) and not isinstance(score, bool)
        else "待计算"
    )
    confidence = _compact(properties.get("triage_confidence"), "待判断")
    relevance = _compact(
        properties.get("why_relevant") or properties.get("why_today"), "待补充"
    )
    value_add = _compact(properties.get("value_add"), "待补充")
    risk = _compact(properties.get("risk"), "待补充")
    deadline = _action_deadline(properties)
    deadline_text = deadline.isoformat() if deadline is not None else "无硬截止"
    note_line = f"\n- 状态：{note}" if note else ""
    return f"""### [[{path.stem}|{title}]]

- 作者/平台：{author_text} · {platform}
- 建议动作：{action}
- 判断分：{score_text}
- 置信度：{confidence}
- 相关性：{relevance}
- 价值增量：{value_add}
- 风险：{risk}
- 截止：{deadline_text}{note_line}
"""


def _active_sort_key(record: tuple[Path, dict[str, object]]) -> tuple[int, int, float]:
    _, properties = record
    captured = _parse_time(
        properties.get("captured_at") or properties.get("published_at")
    )
    return (
        _score(properties),
        _CONFIDENCE_ORDER.get(str(properties.get("triage_confidence")), 0),
        captured.timestamp() if captured is not None else float("-inf"),
    )


def _immediate_sort_key(
    record: tuple[Path, dict[str, object]],
) -> tuple[datetime, int, int]:
    _, properties = record
    deadline = _action_deadline(properties)
    assert deadline is not None
    return (
        deadline,
        -_score(properties),
        -_CONFIDENCE_ORDER.get(str(properties.get("triage_confidence")), 0),
    )


def render_signal_inboxes(
    vault: Path,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    """Rebuild all Signal inbox projections from Markdown authority."""
    vault = vault.expanduser().resolve()
    init_vault(vault)
    timestamp = _utc_now(now)
    records = indexed_records(vault, "01. Signal", "signal")
    routed: dict[str, list[tuple[Path, dict[str, object], str | None]]] = {
        name: [] for name in VIEW_FILES
    }

    for path, properties in records:
        status = properties.get("triage_status")
        if status == "filtered":
            routed["archived"].append((path, properties, "已过滤"))
            continue
        if status in {None, "pending"}:
            routed["needs_triage"].append((path, properties, "待快速判断"))
            continue
        if status == "needs_review":
            routed["needs_triage"].append((path, properties, "需要复核"))
            continue
        if status != "ready" or not _valid_ready_triage(properties):
            routed["needs_triage"].append((path, properties, "快速判断数据无效"))
            continue
        if triage_is_stale(properties, vault):
            routed["needs_triage"].append((path, properties, "策略已变化"))
            continue

        action = properties.get("recommended_action")
        deadline = _action_deadline(properties)
        if (
            action in {"quote", "reply"}
            and properties.get("triage_action_eligible") is True
            and deadline is not None
            and deadline > timestamp
        ):
            routed["immediate_action"].append((path, properties, None))

        lane = str(properties["content_lane"])
        routed[lane].append((path, properties, None))

    immediate = routed["immediate_action"]
    immediate.sort(key=lambda item: _immediate_sort_key((item[0], item[1])))
    for name in CONTENT_LANES:
        routed[name].sort(
            key=lambda item: _active_sort_key((item[0], item[1])), reverse=True
        )
    routed["needs_triage"].sort(
        key=lambda item: _active_sort_key((item[0], item[1])), reverse=True
    )
    routed["archived"].sort(
        key=lambda item: _active_sort_key((item[0], item[1])), reverse=True
    )

    root = vault / "04. Views" / "Signals"
    paths = {name: root / filename for name, filename in VIEW_FILES.items()}
    generated_at = timestamp.isoformat()
    with vault_lock(vault):
        for name in VIEW_FILES:
            cards = "\n".join(
                _card(path, properties, note=note)
                for path, properties, note in routed[name]
            )
            body = cards if cards else "暂无。"
            atomic_write_text(
                paths[name],
                f"# {_VIEW_TITLES[name]}\n\n生成时间：{generated_at}\n\n{body}\n",
            )

    return {
        "schema_version": 1,
        "ok": True,
        "command": "signal-inbox",
        "paths": {name: str(path) for name, path in paths.items()},
        "counts": {name: len(routed[name]) for name in VIEW_FILES},
    }
