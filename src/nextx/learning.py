"""Outcome snapshots and the rebuildable weekly learning view."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
from statistics import median

from .artifacts import _artifact
from .records import read_frontmatter, update_frontmatter
from .self_model import ensure_self_templates
from .vault import atomic_write_text, init_vault, vault_lock
from .views import _records


METRICS = ("views", "likes", "replies", "reposts", "bookmarks")
WINDOWS = ("24h", "7d")
START = "<!-- nextx-outcomes:start -->"
END = "<!-- nextx-outcomes:end -->"
OUTCOME_COMMENT = re.compile(r"<!-- nextx-outcome: (\{[^\n]+\}) -->")


def _utc_now(now: datetime | None) -> datetime:
    value = now or datetime.now(timezone.utc)
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _validate_outcome(payload: object, recorded_at: datetime) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("Outcome payload must be an object")
    if payload.get("schema_version") != 1 or payload.get("account_key") != "primary":
        raise ValueError("Outcome requires schema_version=1 and account_key='primary'")
    window = payload.get("window")
    if window not in WINDOWS:
        raise ValueError("Outcome window must be '24h' or '7d'")
    result: dict[str, object] = {
        "schema_version": 1,
        "account_key": "primary",
        "window": window,
        "recorded_at": recorded_at.isoformat(),
    }
    for metric in METRICS:
        value = payload.get(metric)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ValueError(f"Outcome metric {metric!r} must be a non-negative number")
        result[metric] = value
    return result


def _snapshots(body: str) -> dict[str, dict[str, object]]:
    snapshots: dict[str, dict[str, object]] = {}
    for match in OUTCOME_COMMENT.finditer(body):
        try:
            value = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("window") in WINDOWS:
            snapshots[str(value["window"])] = value
    return snapshots


def _snapshot_markdown(snapshot: dict[str, object]) -> str:
    rows = "\n".join(f"| {metric} | {snapshot[metric]} |" for metric in METRICS)
    machine = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
    return f"""### Outcome · {snapshot['window']}

| metric | value |
| --- | ---: |
{rows}

<!-- nextx-outcome: {machine} -->"""


def _replace_outcomes(body: str, snapshots: dict[str, dict[str, object]]) -> str:
    rendered = "\n\n".join(
        _snapshot_markdown(snapshots[window]) for window in WINDOWS if window in snapshots
    )
    marked = f"{START}\n{rendered}\n{END}"
    if START in body and END in body:
        return re.sub(
            rf"{re.escape(START)}.*?{re.escape(END)}",
            marked,
            body,
            count=1,
            flags=re.DOTALL,
        )
    placeholder = "## Outcome\n\n尚未发布。"
    if placeholder in body:
        return body.replace(placeholder, f"## Outcome\n\n{marked}", 1)
    return body.rstrip() + f"\n\n## Outcome\n\n{marked}\n"


def _write_body(path: Path, old_body: str, new_body: str) -> None:
    full_text = path.read_text(encoding="utf-8")
    prefix = full_text[: len(full_text) - len(old_body)] if old_body else full_text
    atomic_write_text(path, prefix + new_body)


def record_outcome(
    vault: Path,
    artifact_id: str,
    payload: object,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    vault = vault.expanduser().resolve()
    timestamp = _utc_now(now)
    outcome = _validate_outcome(payload, timestamp)
    path, properties, body = _artifact(vault, artifact_id)
    if properties.get("status") not in {"published", "measured"}:
        raise ValueError("Only a published Artifact can record an Outcome")
    snapshots = _snapshots(body)
    snapshots[str(outcome["window"])] = outcome
    status = "measured" if outcome["window"] == "7d" else str(properties["status"])
    with vault_lock(vault):
        _write_body(path, body, _replace_outcomes(body, snapshots))
        if status != properties.get("status"):
            update_frontmatter(path, {"status": status})
    return {
        "schema_version": 1,
        "ok": True,
        "command": "record-outcome",
        "id": artifact_id,
        "path": str(path),
        "window": outcome["window"],
        "status": status,
    }


def _weekly_records(
    folder: Path, record_type: str, cutoff: datetime
) -> list[tuple[Path, dict[str, object]]]:
    return [
        record
        for record in _records(folder, record_type)
        if (_parse_time(record[1].get("created_at")) or datetime.min.replace(tzinfo=timezone.utc))
        >= cutoff
    ]


def render_weekly_review(
    vault: Path, *, now: datetime | None = None
) -> dict[str, object]:
    vault = vault.expanduser().resolve()
    init_vault(vault)
    ensure_self_templates(vault)
    timestamp = _utc_now(now)
    cutoff = timestamp - timedelta(days=7)
    decisions = _weekly_records(vault / "02. Decision", "decision", cutoff)
    artifacts = _weekly_records(vault / "03. Artifact", "artifact", cutoff)
    verdicts = Counter(str(properties.get("verdict")) for _, properties in decisions)
    do_count = verdicts["do"]
    decision_times = {
        str(properties.get("id")): _parse_time(properties.get("created_at"))
        for _, properties in decisions
    }
    latencies = []
    measured = []
    for path, properties in artifacts:
        created = _parse_time(properties.get("created_at"))
        decided = decision_times.get(str(properties.get("decision_id")))
        if created and decided:
            latencies.append((created - decided).total_seconds() / 60)
        _, body = read_frontmatter(path)
        outcomes = _snapshots(body)
        snapshot = outcomes.get("7d") or outcomes.get("24h")
        if snapshot:
            measured.append((float(snapshot["views"]), path, snapshot))
    measured.sort(key=lambda item: item[0], reverse=True)
    top = measured[0] if measured else None
    bottom = measured[-1] if measured else None
    latency = f"{median(latencies):.1f} 分钟" if latencies else "暂无数据"

    def pole(label: str, item: tuple[float, Path, dict[str, object]] | None) -> str:
        if item is None:
            return f"- {label}：暂无已测量 Artifact"
        return f"- {label}：[[{item[1].stem}]] · {item[2]['views']} views"

    proposals = "\n".join(f"- [ ] 候选 Playbook {index}：" for index in range(1, 6))
    content = f"""# Weekly Review

生成时间：{timestamp.isoformat()}

## 裁决漏斗

- 做：{do_count}
- 缓：{verdicts['defer']}
- 毙：{verdicts['kill']}
- Artifact 转化：{len(artifacts)} / {do_count}
- 草稿时延中位数：{latency}

## 两极帖

{pole('Top', top)}
{pole('Bottom', bottom)}

## 学习提案（人工确认后再写入 Playbook）

{proposals}

## 下周唯一实验

- [ ] 
"""
    path = vault / "04. Views" / "Weekly Review.md"
    atomic_write_text(path, content)
    return {
        "schema_version": 1,
        "ok": True,
        "command": "weekly-review",
        "view": str(path),
        "decision_counts": {key: verdicts[key] for key in ("do", "defer", "kill")},
        "artifact_count": len(artifacts),
        "measured_count": len(measured),
    }
