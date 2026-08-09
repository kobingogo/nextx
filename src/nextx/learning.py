"""Outcome snapshots and the rebuildable weekly learning view."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import re
import secrets
from statistics import median

from .artifacts import _artifact
from .records import read_frontmatter, update_frontmatter
from .vault import atomic_write_text, init_vault, vault_lock
from .views import _records


METRICS = ("views", "likes", "replies", "reposts", "bookmarks")
WINDOWS = ("1h", "24h", "7d")
WINDOW_DELAYS = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
}
PLAYBOOK_MIN_SAMPLES = 3
LEGACY_START = "<!-- nextx-outcomes:start -->"
LEGACY_END = "<!-- nextx-outcomes:end -->"
OUTCOME_MARKER = re.compile(r"^[0-9a-f]{32}$")
OUTCOME_COMMENT = re.compile(r"<!-- nextx-outcome: (\{[^\n]+\}) -->")
OUTCOME_REVISION_COMMENT = re.compile(r"<!-- nextx-outcome-revision: (\{[^\n]+\}) -->")


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


def _quote_signals(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not value:
        raise ValueError("Outcome quote_signals must be a non-empty object")
    allowed = {
        "target_author_replied": bool,
        "target_community_replies": (int, float),
        "profile_visits": (int, float),
        "new_followers": (int, float),
    }
    unexpected = set(value) - set(allowed)
    if unexpected:
        raise ValueError(f"Outcome quote_signals contains an unknown field: {sorted(unexpected)[0]}")
    normalized: dict[str, object] = {}
    for field, item in value.items():
        expected = allowed[field]
        if expected is bool:
            if not isinstance(item, bool):
                raise ValueError(f"Outcome quote_signals.{field} must be a boolean")
        elif (
            isinstance(item, bool)
            or not isinstance(item, expected)
            or not math.isfinite(item)
            or item < 0
        ):
            raise ValueError(
                f"Outcome quote_signals.{field} must be a finite non-negative number"
            )
        normalized[field] = item
    return normalized


def _growth_signals(value: object) -> dict[str, object]:
    """Validate human-recorded feedback without pretending it is causal data."""
    if not isinstance(value, dict) or "follow_up_completed" not in value:
        raise ValueError("Outcome growth_signals must include follow_up_completed")
    allowed = {
        "follow_up_completed": bool,
        "target_author_replied": bool,
        "non_follower_replies": (int, float),
        "target_community_replies": (int, float),
        "profile_visits": (int, float),
        "new_followers": (int, float),
        "cta_actions": (int, float),
        "observations": list,
    }
    unexpected = set(value) - set(allowed)
    if unexpected:
        raise ValueError(f"Outcome growth_signals contains an unknown field: {sorted(unexpected)[0]}")
    normalized: dict[str, object] = {}
    for field, item in value.items():
        expected = allowed[field]
        if expected is bool:
            if not isinstance(item, bool):
                raise ValueError(f"Outcome growth_signals.{field} must be a boolean")
        elif expected is list:
            if not isinstance(item, list) or len(item) > 5:
                raise ValueError("Outcome growth_signals.observations must be a list with at most 5 items")
            notes: list[str] = []
            for note in item:
                if not isinstance(note, str) or not note.strip() or len(note.strip()) > 600:
                    raise ValueError("Outcome growth_signals observations must be non-empty strings under 600 characters")
                notes.append(note.strip())
            normalized[field] = notes
            continue
        elif (
            isinstance(item, bool)
            or not isinstance(item, expected)
            or not math.isfinite(item)
            or item < 0
        ):
            raise ValueError(
                f"Outcome growth_signals.{field} must be a finite non-negative number"
            )
        normalized[field] = item
    return normalized


def _validate_outcome(
    payload: object, recorded_at: datetime, *, is_quote: bool, requires_growth_signals: bool
) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("Outcome payload must be an object")
    if payload.get("schema_version") != 1 or payload.get("account_key") != "primary":
        raise ValueError("Outcome requires schema_version=1 and account_key='primary'")
    window = payload.get("window")
    if window not in WINDOWS:
        raise ValueError("Outcome window must be '1h', '24h', or '7d'")
    result: dict[str, object] = {
        "schema_version": 1,
        "account_key": "primary",
        "window": window,
        "recorded_at": recorded_at.isoformat(),
    }
    for metric in METRICS:
        value = payload.get(metric)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            raise ValueError(
                f"Outcome metric {metric!r} must be a finite non-negative number"
            )
        result[metric] = value
    if "quote_signals" in payload:
        if not is_quote:
            raise ValueError("quote_signals can only be recorded for a quote Artifact")
        result["quote_signals"] = _quote_signals(payload["quote_signals"])
    if "growth_signals" in payload:
        result["growth_signals"] = _growth_signals(payload["growth_signals"])
    elif requires_growth_signals:
        raise ValueError("A Growth Loop Artifact requires growth_signals for every Outcome")
    return result


def _outcome_tokens(marker: str | None) -> tuple[str, str]:
    if marker is None:
        return LEGACY_START, LEGACY_END
    return (
        f"<!-- nextx-outcomes:{marker}:start -->",
        f"<!-- nextx-outcomes:{marker}:end -->",
    )


def _outcome_bounds(body: str, marker: str | None) -> tuple[int, int, str, str]:
    start_token, end_token = _outcome_tokens(marker)
    start = body.rfind(start_token)
    if start < 0:
        raise ValueError("Artifact is missing its Outcome machine section")
    end = body.find(end_token, start + len(start_token))
    if end < 0:
        raise ValueError("Artifact Outcome machine section is unclosed")
    return start, end, start_token, end_token


def _snapshots(body: str, marker: str | None) -> dict[str, dict[str, object]]:
    start, end, start_token, _ = _outcome_bounds(body, marker)
    region = body[start + len(start_token) : end]
    snapshots: dict[str, dict[str, object]] = {}
    for match in OUTCOME_COMMENT.finditer(region):
        try:
            value = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("window") in WINDOWS:
            snapshots[str(value["window"])] = value
    return snapshots


def _outcome_revisions(body: str, marker: str | None) -> list[dict[str, object]]:
    start, end, start_token, _ = _outcome_bounds(body, marker)
    region = body[start + len(start_token) : end]
    revisions: list[dict[str, object]] = []
    for match in OUTCOME_REVISION_COMMENT.finditer(region):
        try:
            value = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if (
            isinstance(value, dict)
            and value.get("window") in WINDOWS
            and isinstance(value.get("snapshot"), dict)
        ):
            revisions.append(value)
    return revisions


def _outcome_due_at(properties: dict[str, object], window: str) -> datetime:
    published_at = _parse_time(properties.get("published_at"))
    if published_at is None:
        raise ValueError("Artifact is missing a valid published_at timestamp")
    return published_at + WINDOW_DELAYS[window]


def _outcome_expires_at(properties: dict[str, object], window: str) -> datetime | None:
    """Return the next checkpoint after which an early snapshot is stale."""
    index = WINDOWS.index(window)
    if index == len(WINDOWS) - 1:
        return None
    return _outcome_due_at(properties, WINDOWS[index + 1])


def outcome_next_due_window(
    properties: dict[str, object], body: str, now: datetime
) -> str | None:
    """Return the newest due, unrecorded checkpoint for a published Artifact.

    Early checkpoints are observations at a particular age, not estimates to
    fill in retrospect.  If an operator missed 1h and reaches the post at 24h,
    the next useful action is the 24h snapshot.
    """
    if properties.get("status") not in {"published", "measured"}:
        return None
    published_at = _parse_time(properties.get("published_at"))
    if published_at is None:
        return None
    marker = properties.get("outcome_marker")
    try:
        snapshots = _snapshots(body, marker if isinstance(marker, str) else None)
    except ValueError:
        return None
    due = [
        window
        for window in WINDOWS
        if window not in snapshots and now >= published_at + WINDOW_DELAYS[window]
    ]
    return due[-1] if due else None


def _snapshot_markdown(snapshot: dict[str, object]) -> str:
    metric_rows = "\n".join(f"| {metric} | {snapshot[metric]} |" for metric in METRICS)
    machine = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
    quote_signals = snapshot.get("quote_signals")
    quote_section = ""
    if isinstance(quote_signals, dict):
        quote_rows = "\n".join(
            f"| {field} | {value} |" for field, value in quote_signals.items()
        )
        quote_section = f"""

#### Quote 可见性信号（人工观察，不代表因果）

| signal | value |
| --- | ---: |
{quote_rows}
"""
    growth_signals = snapshot.get("growth_signals")
    growth_section = ""
    if isinstance(growth_signals, dict):
        rows = "\n".join(
            f"| {field} | {value} |"
            for field, value in growth_signals.items()
            if field != "observations"
        )
        observations = growth_signals.get("observations")
        notes = "\n".join(f"- {note}" for note in observations) if isinstance(observations, list) else "- 无"
        growth_section = f"""

#### 增长反馈（人工观察，不代表因果）

| signal | value |
| --- | ---: |
{rows}

观察笔记：

{notes}
"""
    return f"""### Outcome · {snapshot['window']}

| metric | value |
| --- | ---: |
{metric_rows}
{quote_section}
{growth_section}

<!-- nextx-outcome: {machine} -->"""


def _replace_outcomes(
    body: str,
    snapshots: dict[str, dict[str, object]],
    marker: str | None,
    revisions: list[dict[str, object]],
) -> str:
    rendered = "\n\n".join(
        _snapshot_markdown(snapshots[window]) for window in WINDOWS if window in snapshots
    )
    if revisions:
        history = "\n".join(
            f"<!-- nextx-outcome-revision: {json.dumps(revision, ensure_ascii=False, separators=(',', ':'))} -->"
            for revision in revisions
        )
        rendered = (
            f"{rendered}\n\n#### Outcome 修订历史（保留审计记录）\n\n{history}"
        )
    start, end, start_token, end_token = _outcome_bounds(body, marker)
    marked = f"{start_token}\n{rendered}\n{end_token}"
    return body[:start] + marked + body[end + len(end_token) :]


def _ensure_outcome_marker(
    properties: dict[str, object], body: str
) -> tuple[str | None, str, bool]:
    """Migrate a legacy predictable marker before the next Outcome write."""
    marker = properties.get("outcome_marker")
    if isinstance(marker, str) and OUTCOME_MARKER.fullmatch(marker):
        _outcome_bounds(body, marker)
        return marker, body, False
    start, end, start_token, end_token = _outcome_bounds(body, None)
    marker = secrets.token_hex(16)
    new_start, new_end = _outcome_tokens(marker)
    migrated = (
        body[:start]
        + new_start
        + body[start + len(start_token) : end]
        + new_end
        + body[end + len(end_token) :]
    )
    return marker, migrated, True


def record_outcome(
    vault: Path,
    artifact_id: str,
    payload: object,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    vault = vault.expanduser().resolve()
    timestamp = _utc_now(now)
    with vault_lock(vault):
        path, properties, body = _artifact(vault, artifact_id)
        if properties.get("status") not in {"published", "measured"}:
            raise ValueError("Only a published Artifact can record an Outcome")
        outcome = _validate_outcome(
            payload,
            timestamp,
            is_quote=properties.get("execution_mode") == "quote",
            requires_growth_signals=properties.get("growth_objective")
            in {"awareness", "authority", "conversion"},
        )
        due_at = _outcome_due_at(properties, str(outcome["window"]))
        if timestamp < due_at:
            raise ValueError(
                f"Outcome window {outcome['window']} is not due until {due_at.isoformat()}"
            )
        expires_at = _outcome_expires_at(properties, str(outcome["window"]))
        if expires_at is not None and timestamp >= expires_at:
            raise ValueError(
                f"Outcome window {outcome['window']} expired at {expires_at.isoformat()}; "
                "record the newest due checkpoint instead"
            )
        marker, working_body, marker_created = _ensure_outcome_marker(properties, body)
        snapshots = _snapshots(working_body, marker)
        revisions = _outcome_revisions(working_body, marker)
        previous = snapshots.get(str(outcome["window"]))
        if previous is not None:
            revisions.append(
                {
                    "schema_version": 1,
                    "window": outcome["window"],
                    "superseded_at": timestamp.isoformat(),
                    "snapshot": previous,
                }
            )
        snapshots[str(outcome["window"])] = outcome
        status = "measured" if outcome["window"] == "7d" else str(properties["status"])
        updated_body = _replace_outcomes(working_body, snapshots, marker, revisions)
        changes: dict[str, object] = {}
        if marker_created:
            changes["outcome_marker"] = marker
        if status != properties.get("status"):
            changes["status"] = status
        update_frontmatter(path, changes, body=updated_body)
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
    folder: Path, record_type: str, cutoff: datetime, *, timestamp_field: str = "created_at"
) -> list[tuple[Path, dict[str, object]]]:
    return [
        record
        for record in _records(folder, record_type)
        if (_parse_time(record[1].get(timestamp_field)) or datetime.min.replace(tzinfo=timezone.utc))
        >= cutoff
    ]


def render_weekly_review(
    vault: Path, *, now: datetime | None = None
) -> dict[str, object]:
    vault = vault.expanduser().resolve()
    init_vault(vault)
    timestamp = _utc_now(now)
    cutoff = timestamp - timedelta(days=7)
    four_week_cutoff = timestamp - timedelta(days=28)
    decisions = _weekly_records(vault / "02. Decision", "decision", cutoff)
    artifacts = _weekly_records(
        vault / "03. Artifact", "artifact", cutoff, timestamp_field="published_at"
    )
    four_week_decisions = _weekly_records(
        vault / "02. Decision", "decision", four_week_cutoff
    )
    four_week_artifacts = _weekly_records(
        vault / "03. Artifact", "artifact", four_week_cutoff, timestamp_field="published_at"
    )
    four_week_drafts = _weekly_records(vault / "03. Artifact", "artifact", four_week_cutoff)
    verdicts = Counter(str(properties.get("verdict")) for _, properties in decisions)
    quote_decisions = Counter(
        str(properties.get("verdict"))
        for _, properties in decisions
        if properties.get("execution_mode") == "quote"
    )
    do_count = verdicts["do"]
    weekly_do_ids = {
        str(properties.get("id"))
        for _, properties in decisions
        if properties.get("verdict") == "do"
    }
    converted_artifacts = [
        record
        for record in artifacts
        if str(record[1].get("decision_id")) in weekly_do_ids
    ]
    decision_times = {
        str(properties.get("id")): _parse_time(properties.get("created_at"))
        for _, properties in four_week_decisions
    }
    latencies = []
    measured = []
    four_week_rates: list[float] = []
    weekly_rates: list[float] = []
    experiments: dict[str, list[float]] = {}
    growth_groups: dict[tuple[str, str], dict[str, object]] = {}
    quote_measured_count = 0
    quote_author_replied_count = 0
    for _, properties in four_week_drafts:
        created = _parse_time(properties.get("review_ready_at"))
        decided = decision_times.get(str(properties.get("decision_id")))
        if created and decided:
            latencies.append((created - decided).total_seconds() / 60)
    for path, properties in four_week_artifacts:
        _, body = read_frontmatter(path)
        marker = properties.get("outcome_marker")
        outcomes = _snapshots(body, marker if isinstance(marker, str) else None)
        # 1h/24h are early signals only.  The weekly and four-week scorecards
        # must compare the same lifecycle checkpoint, so they use 7d only.
        snapshot = outcomes.get("7d")
        if snapshot:
            measured.append((float(snapshot["views"]), path, snapshot))
            rate = _engagement_rate(snapshot)
            if rate is not None:
                four_week_rates.append(rate)
                experiment_id = properties.get("experiment_id")
                if isinstance(experiment_id, str) and experiment_id:
                    experiments.setdefault(experiment_id, []).append(rate)
                published_at = _parse_time(properties.get("published_at"))
                if published_at is not None and published_at >= cutoff:
                    weekly_rates.append(rate)
            execution_mode = properties.get("execution_mode")
            objective = properties.get("growth_objective")
            if isinstance(execution_mode, str) and objective in {
                "awareness",
                "authority",
                "conversion",
            }:
                group = growth_groups.setdefault(
                    (execution_mode, str(objective)),
                    {
                        "rates": [],
                        "qualified_actions": [],
                        "follow_up_completed": [],
                        "samples_by_key": {},
                    },
                )
                decision_id = str(properties.get("decision_id", ""))
                experiment_id = properties.get("experiment_id")
                experiment_key = experiment_id if isinstance(experiment_id, str) else ""
                sample_key = f"{decision_id}:{experiment_key}"
                samples_by_key = group["samples_by_key"]
                if not isinstance(samples_by_key, dict) or sample_key in samples_by_key:
                    continue
                samples_by_key[sample_key] = (
                    path,
                    snapshot,
                    str(properties.get("published_url", "")),
                )
                if rate is not None:
                    group["rates"].append(rate)
                growth_signals = snapshot.get("growth_signals")
                if isinstance(growth_signals, dict):
                    group["qualified_actions"].append(float(_observed_actions(growth_signals)))
                    if growth_signals.get("follow_up_completed") is True:
                        group["follow_up_completed"].append(1.0)
            if properties.get("execution_mode") == "quote":
                quote_measured_count += 1
                quote_signals = snapshot.get("quote_signals")
                if isinstance(quote_signals, dict) and quote_signals.get("target_author_replied") is True:
                    quote_author_replied_count += 1
    measured.sort(key=lambda item: item[0], reverse=True)
    top = measured[0] if measured else None
    bottom = measured[-1] if measured else None
    latency_median = median(latencies) if latencies else None
    latency = f"{latency_median:.1f} 分钟" if latency_median is not None else "暂无数据"
    latency_on_target = sum(1 for value in latencies if value <= 20)
    baseline_rate = _percent(median(four_week_rates)) if four_week_rates else "暂无数据"
    weekly_rate = _percent(median(weekly_rates)) if weekly_rates else "暂无数据"
    experiment_rows = "\n".join(
        f"- `{experiment_id}`：{len(rates)} 条已测量帖，中位互动命中率 {_percent(median(rates))}"
        for experiment_id, rates in sorted(experiments.items())
    ) or "- 暂无带实验标记的已测量帖。"
    quote_artifacts = [
        record for record in artifacts if record[1].get("execution_mode") == "quote"
    ]
    growth_scorecards: dict[str, dict[str, object]] = {}
    growth_rows: list[str] = []
    playbook_proposals: list[dict[str, object]] = []
    for (mode, objective), values in sorted(growth_groups.items()):
        rates = values["rates"]
        samples_by_key = values["samples_by_key"]
        samples = list(samples_by_key.values())
        sample_count = len(samples)
        key = f"{mode}:{objective}"
        evidence_ready = sample_count >= PLAYBOOK_MIN_SAMPLES
        scorecard = {
            "execution_mode": mode,
            "objective": objective,
            "measured_count": sample_count,
            "median_engagement_rate": median(rates) if rates else None,
            "median_observed_actions": median(values["qualified_actions"])
            if values["qualified_actions"]
            else None,
            "follow_up_completed_count": int(sum(values["follow_up_completed"])),
            "playbook_evidence_ready": evidence_ready,
            "independent_sample_keys": sorted(str(key) for key in samples_by_key),
        }
        growth_scorecards[key] = scorecard
        rate_text = _percent(median(rates)) if rates else "暂无有效曝光分母"
        action_text = (
            f"{median(values['qualified_actions']):.1f}"
            if values["qualified_actions"]
            else "暂无人工观察"
        )
        gate = "可提出待审 Playbook" if evidence_ready else f"样本不足 {PLAYBOOK_MIN_SAMPLES}，只记录假设"
        growth_rows.append(
            f"- `{mode} × {objective}`：{sample_count} 条 · 中位互动率 {rate_text} · "
            f"中位观察动作 {action_text} · {gate}"
        )
        if evidence_ready:
            samples = sorted(samples, key=lambda sample: float(sample[1]["views"]), reverse=True)
            group_rate = median(rates) if rates else 0.0
            baseline_rates = list(four_week_rates)
            for rate in rates:
                try:
                    baseline_rates.remove(rate)
                except ValueError:
                    pass
            all_rate = median(baseline_rates) if baseline_rates else group_rate
            median_actions = median(values["qualified_actions"]) if values["qualified_actions"] else 0.0
            action = (
                "stop" if median_actions <= 0 or group_rate < all_rate * 0.5 else
                "repeat" if group_rate >= all_rate else "alter"
            )
            playbook_proposals.append(
                {
                    "group": key,
                    "action": action,
                    "evidence": [sample[0].stem for sample in samples[:-1][:3]],
                    "counterexample": samples[-1][0].stem,
                }
            )
    growth_rows_text = "\n".join(growth_rows) or "- 暂无带增长契约的 7d 样本。"
    approved_groups = [
        key for key, scorecard in growth_scorecards.items() if scorecard["playbook_evidence_ready"]
    ]

    def pole(label: str, item: tuple[float, Path, dict[str, object]] | None) -> str:
        if item is None:
            return f"- {label}：暂无已测量 Artifact"
        return f"- {label}：[[{item[1].stem}]] · {item[2]['views']} views"

    proposals = (
        "\n".join(
            f"- [ ] **{proposal['action']}** · `{proposal['group']}` · "
            f"证据：{', '.join(f'[[{stem}]]' for stem in proposal['evidence'])}；"
            f"反例/低表现样本：[[{proposal['counterexample']}]]。人工确认后才写入 Playbook。"
            for proposal in playbook_proposals
        )
        if playbook_proposals
        else f"- 样本尚未达到同类 {PLAYBOOK_MIN_SAMPLES} 条的证据门槛；本周只保留假设，不写入 Playbook。"
    )
    content = f"""# Weekly Review

生成时间：{timestamp.isoformat()}

## 裁决漏斗

- 做：{do_count}
- 缓：{verdicts['defer']}
- 毙：{verdicts['kill']}
- Artifact 转化：{len(converted_artifacts)} / {do_count}
- 北极星（do Decision → 通过发布检查）中位时延：{latency}（≤20 分钟：{latency_on_target} / {len(latencies)}）
- 4 周中位互动命中率：{baseline_rate}
- 本周中位互动命中率：{weekly_rate}

## Quote Sprint（起号可见性）

- Quote 做：{quote_decisions['do']}；缓：{quote_decisions['defer']}；毙：{quote_decisions['kill']}
- Quote Artifact：{len(quote_artifacts)}
- 4 周已测量 Quote：{quote_measured_count}
- 目标作者回复：{quote_author_replied_count}（人工观察，不代表 Quote 唯一造成）

## 两极帖

{pole('Top', top)}
{pole('Bottom', bottom)}

## 实验结果（4 周）

{experiment_rows}

## 增长记分卡（同执行模式 × 同目标）

{growth_rows_text}

人工观察用于发现下一步，不代表帖子唯一造成了回复、关注、主页访问或 CTA 行动。只有同类样本达到门槛后，才可以提出待审 Playbook。

## 学习提案（人工确认后再写入 Playbook）

{proposals}

## 下周唯一实验

- [ ]
"""
    path = vault / "04. Views" / "Weekly Review.md"
    with vault_lock(vault):
        atomic_write_text(path, content)
    return {
        "schema_version": 1,
        "ok": True,
        "command": "weekly-review",
        "view": str(path),
        "decision_counts": {key: verdicts[key] for key in ("do", "defer", "kill")},
        "artifact_count": len(converted_artifacts),
        "weekly_artifact_count": len(artifacts),
        "north_star": {
            "definition": "do Decision 创建到 Artifact 通过发布检查（review_ready）的时延",
            "target_minutes": 20,
            "sample_count": len(latencies),
            "median_minutes": latency_median,
            "on_target_count": latency_on_target,
        },
        "measured_count": len(measured),
        "four_week_median_engagement_rate": median(four_week_rates) if four_week_rates else None,
        "weekly_median_engagement_rate": median(weekly_rates) if weekly_rates else None,
        "experiments": {
            experiment_id: {"measured_count": len(rates), "median_engagement_rate": median(rates)}
            for experiment_id, rates in sorted(experiments.items())
        },
        "growth_scorecards": growth_scorecards,
        "playbook_evidence_ready_groups": approved_groups,
        "playbook_proposals": playbook_proposals,
        "quote": {
            "decision_counts": {key: quote_decisions[key] for key in ("do", "defer", "kill")},
            "artifact_count": len(quote_artifacts),
            "four_week_measured_count": quote_measured_count,
            "target_author_replied_count": quote_author_replied_count,
        },
    }


def _engagement_rate(snapshot: dict[str, object]) -> float | None:
    views = float(snapshot["views"])
    if views <= 0:
        return None
    interactions = sum(float(snapshot[metric]) for metric in METRICS if metric != "views")
    return interactions / views


def _observed_actions(signals: dict[str, object]) -> int:
    total = 1 if signals.get("target_author_replied") is True else 0
    for field in (
        "non_follower_replies",
        "target_community_replies",
        "new_followers",
        "cta_actions",
    ):
        value = signals.get(field, 0)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            total += int(value)
    return total


def _percent(value: float) -> str:
    return f"{value * 100:.2f}%"
