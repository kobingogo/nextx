"""Rebuildable Obsidian projections over NextX records."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import re

from .records import read_frontmatter
from .self_model import growth_strategy, self_readiness
from .vault import atomic_write_text, init_vault, vault_lock


def _write_view(vault: Path, path: Path, content: str) -> None:
    with vault_lock(vault):
        atomic_write_text(path, content)


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
    index_path = folder.parent / ".nextx" / "index.json"
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
        if (
            not isinstance(index, dict)
            or index.get("schema_version") != 1
            or not isinstance(index.get("folders"), dict)
        ):
            raise ValueError("invalid index")
    except (OSError, ValueError, json.JSONDecodeError):
        index = {"schema_version": 1, "folders": {}}
    folders = index["folders"]
    cached = folders.get(folder.name, {})
    cached = cached if isinstance(cached, dict) else {}
    current: dict[str, object] = {}
    for path in folder.glob("*.md"):
        try:
            stat = path.stat()
            entry = cached.get(path.name)
            if (
                isinstance(entry, dict)
                and entry.get("mtime_ns") == stat.st_mtime_ns
                and entry.get("size") == stat.st_size
                and isinstance(entry.get("properties"), dict)
            ):
                properties = entry["properties"]
            else:
                properties, _ = read_frontmatter(path)
            current[path.name] = {
                "mtime_ns": stat.st_mtime_ns,
                "size": stat.st_size,
                "properties": properties,
            }
        except (OSError, ValueError):
            continue
        # A Vault can contain copied notes from another account.  Legacy notes
        # without an account key predate the registry and remain readable, but
        # an explicit non-primary key must never leak into this single-account
        # workspace's queues or metrics.
        if properties.get("type") == record_type and properties.get("account_key", "primary") == "primary":
            records.append((path, properties))
    if current != cached:
        folders[folder.name] = current
        index_path.parent.mkdir(parents=True, exist_ok=True)
        with vault_lock(folder.parent):
            atomic_write_text(
                index_path,
                json.dumps(index, ensure_ascii=False, separators=(",", ":")) + "\n",
            )
    return records


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _signal_queue_state(
    vault: Path, now: datetime
) -> tuple[set[str], set[str], int]:
    """Return permanently resolved and defer records due for reconsideration."""
    latest: dict[str, dict[str, object]] = {}
    for _, properties in _records(vault / "02. Decision", "decision"):
        created = _parse_time(properties.get("created_at")) or datetime.min.replace(
            tzinfo=timezone.utc
        )
        for signal_id in properties.get("signal_ids", []):
            if not isinstance(signal_id, str):
                continue
            previous = latest.get(signal_id)
            previous_created = _parse_time(previous.get("created_at")) if previous else None
            if previous is None or created >= (previous_created or datetime.min.replace(tzinfo=timezone.utc)):
                latest[signal_id] = properties
    excluded: set[str] = set()
    revisit_due: set[str] = set()
    completed_count = 0
    for signal_id, properties in latest.items():
        verdict = properties.get("verdict")
        if verdict in {"do", "kill"}:
            excluded.add(signal_id)
            completed_count += 1
        elif verdict == "defer":
            revisit_at = _parse_time(properties.get("revisit_at"))
            if revisit_at is not None and revisit_at <= now:
                revisit_due.add(signal_id)
            else:
                excluded.add(signal_id)
    return excluded, revisit_due, completed_count


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


def _bounded_score(properties: dict[str, object], field: str) -> int:
    value = properties.get(field, 0)
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 5 else 0


def _priority(properties: dict[str, object], now: datetime) -> tuple[int, str]:
    """Use explainable, deterministic ranking instead of popularity-only sorting."""
    self_fit = _bounded_score(properties, "self_fit")
    novelty = _bounded_score(properties, "novelty")
    confidence = {"high": 8, "medium": 4, "low": 0}.get(
        properties.get("source_confidence"), 0
    )
    observed = _timestamp(properties)
    age_hours = max(0.0, (now - observed).total_seconds() / 3600)
    recency = 5 if age_hours <= 6 else 4 if age_hours <= 24 else 2 if age_hours <= 72 else 0
    metrics = properties.get("metrics")
    values = metrics if isinstance(metrics, dict) else {}
    momentum = sum(
        float(value)
        for key, value in values.items()
        if key in {"views", "likes", "replies", "reposts", "bookmarks"}
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
        and value >= 0
    )
    popularity = min(4, int(math.log10(momentum + 1)))
    analyzed = 2 if properties.get("analysis_status") == "ready" else 0
    score = self_fit * 4 + novelty * 3 + confidence + recency + popularity + analyzed
    why = properties.get("why_today")
    why_text = " ".join(why.split()) if isinstance(why, str) and why.strip() else "近期未裁决"
    return (
        score,
        f"优先级 {score}（Self {self_fit}/5，新增 {novelty}/5，证据 {confidence}，时效 {recency}）· {why_text}",
    )


def _quote_priority(properties: dict[str, object], now: datetime) -> tuple[int, str]:
    """Rank a bounded Quote inbox without treating popularity as a verdict."""
    base, _ = _priority(properties, now)
    deadline = _parse_time(properties.get("quote_window_ends_at"))
    if deadline is None or deadline <= now:
        return -1, "Quote 决策窗口已过期"
    remaining_hours = (deadline - now).total_seconds() / 3600
    urgency = (
        8
        if remaining_hours <= 2
        else 6
        if remaining_hours <= 6
        else 4
        if remaining_hours <= 24
        else 2
    )
    score = base + urgency
    return (
        score,
        f"Quote 优先级 {score}（基础 {base}，窗口剩余 {remaining_hours:.1f} 小时，时效 {urgency}）",
    )


def _content_signature(path: Path, properties: dict[str, object]) -> set[str]:
    fingerprint = properties.get("content_fingerprint")
    try:
        _, body = read_frontmatter(path)
    except (OSError, ValueError):
        return {f"hash:{fingerprint}"} if isinstance(fingerprint, str) and fingerprint else set()
    if "## 原始内容" in body:
        raw = body.partition("## 原始内容")[2].split("\n来源：", 1)[0]
    else:
        raw = body.partition("## 原帖")[2].split("\n原帖：", 1)[0]
    normalized = re.sub(r"\s+", "", raw.casefold())
    signature = {f"hash:{fingerprint}"} if isinstance(fingerprint, str) and fingerprint else set()
    if len(normalized) < 6:
        return signature | ({normalized} if normalized else set())
    return signature | {
        normalized[index : index + 3] for index in range(min(len(normalized) - 2, 300))
    }


def _is_near_duplicate(
    path: Path,
    properties: dict[str, object],
    selected: list[tuple[Path, dict[str, object]]],
) -> bool:
    current = _content_signature(path, properties)
    if not current:
        return False
    for prior_path, prior_properties in selected:
        prior = _content_signature(prior_path, prior_properties)
        if not prior:
            continue
        if current == prior:
            return True
        union = current | prior
        if union and len(current) >= 8 and len(prior) >= 8 and len(current & prior) / len(union) >= 0.72:
            return True
    return False


def _render_bookmark_inbox(
    vault: Path, signals: list[tuple[Path, dict[str, object]]], generated_at: str
) -> None:
    bookmarks = [
        record for record in signals if record[1].get("bookmark_active") is True
    ]
    bookmarks.sort(key=lambda record: _timestamp(record[1]), reverse=True)
    cards = "\n".join(
        _card(path, properties, "X Bookmark") for path, properties in bookmarks[:100]
    )
    content = cards or "暂无收藏 Signal。\n"
    _write_view(
        vault,
        vault / "04. Views" / "Bookmark Inbox.md",
        f"# Bookmark Inbox\n\n生成时间：{generated_at}\n\n{content}",
    )


def render_quote_sprint(
    vault: Path, *, now: datetime | None = None
) -> dict[str, object]:
    """Create the small, time-bounded Quote queue used during account launch.

    This is deliberately a projection over persisted Signals and Decisions.
    It never posts, it does not infer that a popular post is worth quoting,
    and it leaves the final do/defer/kill decision to topic-engine + the user.
    """
    vault = vault.expanduser().resolve()
    init_vault(vault)
    timestamp = now or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    timestamp = timestamp.astimezone(timezone.utc)
    excluded, revisit_due, _ = _signal_queue_state(vault, timestamp)
    signals = _records(vault / "01. Signal", "signal")
    expired_count = 0
    pool: list[tuple[Path, dict[str, object]]] = []
    for record in signals:
        path, properties = record
        if properties.get("quote_candidate") is not True:
            continue
        deadline = _parse_time(properties.get("quote_window_ends_at"))
        if deadline is None or deadline <= timestamp:
            expired_count += 1
            continue
        if str(properties.get("id")) in excluded:
            continue
        pool.append((path, properties))
    pool.sort(
        key=lambda record: (_quote_priority(record[1], timestamp)[0], _timestamp(record[1])),
        reverse=True,
    )
    selected: list[tuple[Path, dict[str, object]]] = []
    selected_authors: set[str] = set()
    for record in pool:
        path, properties = record
        author = properties.get("author_handle")
        author_key = str(author).casefold() if isinstance(author, str) else ""
        if author_key and author_key in selected_authors:
            continue
        if _is_near_duplicate(path, properties, selected):
            continue
        selected.append(record)
        if author_key:
            selected_authors.add(author_key)
        if len(selected) == 3:
            break

    cards = "\n".join(
        _card(
            path,
            properties,
            "复访已到期"
            if str(properties.get("id")) in revisit_due
            else _quote_priority(properties, timestamp)[1],
        )
        + f"- Quote 截止：{properties.get('quote_window_ends_at')}\n"
        for path, properties in selected
    )
    content = f"""# Quote Sprint · 起号可见性队列

生成时间：{timestamp.isoformat()}

Quote 的目标是让相邻读者通过你的**新增判断**看见你，而不是借热门帖蹭曝光。每条候选必须先经 `quote-brief → topic-engine → 做 / 缓 / 毙`；只有 `do` 才能生成 `quote-post` 草稿，且仍需人工在 X 发布。

- 可裁决候选：{len(pool)}
- 今日呈现：{len(selected)} / 3
- 已过期候选：{expired_count}
- 每位作者最多：1 条

## 今日 Quote 候选

{cards or '暂无仍在窗口内的 Quote 候选。先用 Quote Collector 采集具备原帖 URL、作者、发布时间和截止时间的 X 帖子。'}

## 质量闸门

- 第一行是否有自己的可验证增量，而非复述或恭维？
- 这个角度是否对目标读者有用，而不仅对原作者有礼貌？
- 事实、归因与链接是否仍可从原帖核验？
- 如果现在不值得公开站队，是否应缓或毙？
"""
    path = vault / "04. Views" / "Quote Sprint.md"
    _write_view(vault, path, content)
    return {
        "schema_version": 1,
        "ok": True,
        "command": "quote-sprint",
        "view": str(path),
        "candidate_count": len(pool),
        "selected_count": len(selected),
        "expired_count": expired_count,
        "selected_ids": [str(properties.get("id")) for _, properties in selected],
    }


def render_reply_sprint(
    vault: Path, *, now: datetime | None = None
) -> dict[str, object]:
    """Create a bounded Reply queue; it is a prompt to think, never auto-engagement."""
    vault = vault.expanduser().resolve()
    init_vault(vault)
    timestamp = now or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    timestamp = timestamp.astimezone(timezone.utc)
    excluded, revisit_due, _ = _signal_queue_state(vault, timestamp)
    expired_count = 0
    pool: list[tuple[Path, dict[str, object]]] = []
    for path, properties in _records(vault / "01. Signal", "signal"):
        if properties.get("reply_candidate") is not True:
            continue
        deadline = _parse_time(properties.get("reply_window_ends_at"))
        if deadline is None or deadline <= timestamp:
            expired_count += 1
            continue
        if str(properties.get("id")) in excluded:
            continue
        pool.append((path, properties))
    pool.sort(
        key=lambda record: (_conversation_priority(record[1], timestamp, "reply_window_ends_at")[0], _timestamp(record[1])),
        reverse=True,
    )
    selected: list[tuple[Path, dict[str, object]]] = []
    selected_authors: set[str] = set()
    for record in pool:
        path, properties = record
        author = properties.get("author_handle")
        author_key = str(author).casefold() if isinstance(author, str) else ""
        if author_key and author_key in selected_authors:
            continue
        if _is_near_duplicate(path, properties, selected):
            continue
        selected.append(record)
        if author_key:
            selected_authors.add(author_key)
        if len(selected) == 3:
            break
    cards = "\n".join(
        _card(
            path,
            properties,
            "复访已到期"
            if str(properties.get("id")) in revisit_due
            else _conversation_priority(properties, timestamp, "reply_window_ends_at")[1],
        )
        + f"- Reply 截止：{properties.get('reply_window_ends_at')}\n"
        for path, properties in selected
    )
    content = f"""# Reply Sprint · 关系与讨论队列

生成时间：{timestamp.isoformat()}

Reply 的目标是推进一段具体讨论、帮助相邻读者理解问题，而不是刷存在感。每条候选必须先经 `reply-brief → topic-engine → 做 / 缓 / 毙`；只有 `do` 才能生成 `reply-post` 草稿，且仍需人工在 X 发布。

- 可裁决候选：{len(pool)}
- 今日呈现：{len(selected)} / 3
- 已过期候选：{expired_count}
- 每位作者最多：1 条

## 今日 Reply 候选

{cards or '暂无仍在窗口内的 Reply 候选。先采集有明确讨论入口、原帖 URL、作者、发布时间和截止时间的 X 帖子。'}

## 质量闸门

- 这条回复是否推进、校正或具体化了原讨论？
- 目标读者能否从中带走一个独立判断？
- 若删去原作者的名字，这段话是否依然有价值？
- 不能提供新增价值时，是否应该不回复？
"""
    path = vault / "04. Views" / "Reply Sprint.md"
    _write_view(vault, path, content)
    return {
        "schema_version": 1,
        "ok": True,
        "command": "reply-sprint",
        "view": str(path),
        "candidate_count": len(pool),
        "selected_count": len(selected),
        "expired_count": expired_count,
        "selected_ids": [str(properties.get("id")) for _, properties in selected],
    }


def _conversation_priority(
    properties: dict[str, object], now: datetime, deadline_key: str
) -> tuple[int, str]:
    base, _ = _priority(properties, now)
    deadline = _parse_time(properties.get(deadline_key))
    if deadline is None or deadline <= now:
        return -1, "讨论窗口已过期"
    remaining_hours = (deadline - now).total_seconds() / 3600
    urgency = 8 if remaining_hours <= 2 else 6 if remaining_hours <= 6 else 4 if remaining_hours <= 24 else 2
    return base + urgency, f"回复优先级 {base + urgency}（基础 {base}，窗口剩余 {remaining_hours:.1f} 小时）"


def _growth_lane(properties: dict[str, object]) -> str:
    if properties.get("growth_objective") == "conversion":
        return "conversion"
    if properties.get("execution_mode") in {"quote", "reply"}:
        return "discovery"
    return "authority"


def render_growth_loop(vault: Path, *, now: datetime | None = None) -> dict[str, object]:
    """Give a novice one explainable next action instead of another empty dashboard."""
    # Imported lazily to keep the derived-view reader independent from the
    # weekly-review renderer, which also consumes this module's record index.
    from .learning import outcome_next_due_window

    vault = vault.expanduser().resolve()
    init_vault(vault)
    timestamp = now or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    timestamp = timestamp.astimezone(timezone.utc)
    strategy = growth_strategy(vault)
    readiness = self_readiness(vault)
    resolved_signals, _, _ = _signal_queue_state(vault, timestamp)
    signals = _records(vault / "01. Signal", "signal")
    decisions = _records(vault / "02. Decision", "decision")
    artifacts = _records(vault / "03. Artifact", "artifact")
    artifact_decisions = {str(properties.get("decision_id")) for _, properties in artifacts}
    open_decisions = [
        (path, properties)
        for path, properties in decisions
        if properties.get("verdict") == "do" and str(properties.get("id")) not in artifact_decisions
    ]
    published_needing_outcome: list[tuple[Path, dict[str, object], str]] = []
    for path, properties in artifacts:
        if properties.get("status") not in {"published", "measured"}:
            continue
        _, body = read_frontmatter(path)
        due_window = outcome_next_due_window(properties, body, timestamp)
        if due_window is not None:
            published_needing_outcome.append((path, properties, due_window))
    drafts_needing_review = [
        (path, properties)
        for path, properties in artifacts
        if properties.get("status") == "draft"
    ]
    reviews_needing_confirmation = [
        (path, properties)
        for path, properties in artifacts
        if properties.get("status") == "review_ready"
    ]
    confirmed_needing_manual_publish = [
        (path, properties)
        for path, properties in artifacts
        if properties.get("status") == "publish_confirmed"
    ]
    reply_candidates = [
        properties
        for _, properties in signals
        if properties.get("reply_candidate") is True
        and str(properties.get("id")) not in resolved_signals
        and (_parse_time(properties.get("reply_window_ends_at")) or timestamp) > timestamp
    ]
    quote_candidates = [
        properties
        for _, properties in signals
        if properties.get("quote_candidate") is True
        and str(properties.get("id")) not in resolved_signals
        and (_parse_time(properties.get("quote_window_ends_at")) or timestamp) > timestamp
    ]
    regular_candidates = [
        properties
        for _, properties in signals
        if str(properties.get("id")) not in resolved_signals
        and properties.get("bookmark_active") is not False
        and properties.get("quote_candidate") is not True
        and properties.get("reply_candidate") is not True
    ]
    regular_candidates.sort(
        key=lambda properties: (_priority(properties, timestamp)[0], _timestamp(properties)),
        reverse=True,
    )
    weekly_cutoff = timestamp - timedelta(days=7)
    lane_counts = {"discovery": 0, "authority": 0, "conversion": 0}
    for _, properties in artifacts:
        created_at = _parse_time(properties.get("created_at"))
        if (
            properties.get("status") in {"published", "measured"}
            and created_at is not None
            and created_at >= weekly_cutoff
        ):
            lane_counts[_growth_lane(properties)] += 1
    allocation = strategy["lane_allocation"] if isinstance(strategy["lane_allocation"], dict) else {}
    lane_targets = {
        lane: value if isinstance(value := allocation.get(lane), int) else 0
        for lane in lane_counts
    }
    action_id = "configure_self"
    action_title = "先完成账号的基础定位"
    action_reason = "NextX 不能替你虚构定位、内容柱或禁区；这些是后续所有选题与增长判断的依据。"
    next_command = "configure-self"
    if readiness["ready"] and not strategy["configured"]:
        action_id = "configure_growth"
        action_title = "再确认本周唯一增长目标"
        action_reason = "NextX 不能替你虚构目标读者、主页承接或 CTA；确认一次后才可可靠地替你排序。"
    elif strategy["configured"] and readiness["ready"]:
        if published_needing_outcome:
            _, artifact, due_window = published_needing_outcome[0]
            action_id = "record_outcome"
            action_title = f"回写一条已发布帖的 {due_window} 反馈"
            action_reason = "这个观察窗口已经到期；先记录同一生命周期节点的反馈，再继续寻找热点。"
            next_command = f"record-outcome {artifact.get('id')}"
        elif drafts_needing_review:
            artifact = drafts_needing_review[0][1]
            action_id = "review_draft"
            action_title = "先审阅一条已完成草稿"
            action_reason = "已有内容包尚未通过发布检查；继续采集只会让小白在更多候选之间犹豫。"
            next_command = f"mark-review-ready {artifact.get('id')}"
        elif reviews_needing_confirmation:
            artifact = reviews_needing_confirmation[0][1]
            action_id = "confirm_publish"
            action_title = "确认是否人工发布已审阅草稿"
            action_reason = "NextX 不会自动发布；这是保留给运营者的明确人工闸门。"
            next_command = f"confirm-publish {artifact.get('id')} --yes"
        elif confirmed_needing_manual_publish:
            artifact = confirmed_needing_manual_publish[0][1]
            action_id = "manual_publish"
            action_title = "在 X 手动发布，然后回填链接"
            action_reason = "草稿已通过人工确认；请在 X 完成真实发布，NextX 只记录结果。"
            next_command = f"record-published {artifact.get('id')} --url <已发布 X 链接>"
        else:
            lane_actions: dict[str, list[tuple[str, str, str, str]]] = {
                "discovery": [], "authority": [], "conversion": []
            }
            if reply_candidates:
                lane_actions["discovery"].append((
                    "reply_sprint", "从 Reply Sprint 选一条高质量讨论入口",
                    "在目标读者已在看的讨论中补充新增判断，优先建立第一次有效可见性。", "reply-sprint"
                ))
            if quote_candidates:
                lane_actions["discovery"].append((
                    "quote_sprint", "从 Quote Sprint 选一条可进入的话题",
                    "用可核验的新判断进入相邻读者的注意力场，而不是只复述热门观点。", "quote-sprint"
                ))
            for _, decision in open_decisions:
                lane = _growth_lane(decision)
                lane_actions[lane].append((
                    "produce_artifact", "把已做出的裁决变成可发布内容包",
                    "已有 do Decision；先把已验证的判断交给写作，避免新采集稀释执行。",
                    f"artifact-brief {decision.get('id')}"
                ))
            if regular_candidates:
                signal = regular_candidates[0]
                if strategy["objective"] == "conversion":
                    lane_actions["conversion"].append((
                        "conversion_brief", "先评估一个已有候选的转化路径",
                        "本周目标是转化；先为这个 Signal 明确 CTA、承接资产和可观察的读者动作，再决定是否投入内容。",
                        f"decision-brief {signal.get('id')}"
                    ))
                else:
                    lane_actions["authority"].append((
                        "decision_brief", "先裁决一个已有的常规候选",
                        "已有可审 Signal；先明确做、缓或毙，再决定是否投入原创内容。",
                        f"decision-brief {signal.get('id')}"
                    ))
            available_lanes = [lane for lane, actions in lane_actions.items() if actions]
            if available_lanes:
                stage_order = {
                    "launch": ("discovery", "authority", "conversion"),
                    "ramp": ("authority", "discovery", "conversion"),
                    "steady": ("authority", "conversion", "discovery"),
                }.get(strategy["stage"], ("authority", "discovery", "conversion"))
                lane = max(
                    available_lanes,
                    key=lambda item: (
                        lane_targets[item] - lane_counts[item],
                        -stage_order.index(item),
                    ),
                )
                action_id, action_title, action_reason, next_command = lane_actions[lane][0]
                action_reason = (
                    f"本周 {lane} 已完成 {lane_counts[lane]} / 目标 {lane_targets[lane]}。{action_reason}"
                )
            else:
                action_id = "collect"
                action_title = "补一批与本周目标相符的候选"
                action_reason = "没有待写、待复盘或仍有效的候选；先补充少量可验证 Signal。"
                next_command = "collector-prompt --source grok"
    content = f"""# Growth Loop · 下一步行动

生成时间：{timestamp.isoformat()}

## 你今天只需先完成这一件事

**{action_title}**

{action_reason}

- 建议操作：`nextx {next_command}`
- 当前阶段：{strategy['stage'] or '未配置'}
- 本周目标：{strategy['objective'] or '未配置'}
- 目标读者：{strategy['target_reader'] or '未配置'}
- 本周聚焦：{strategy['weekly_focus'] or '未配置'}

## 队列事实

- 待产出 do Decision：{len(open_decisions)}
- 草稿待审阅：{len(drafts_needing_review)}
- 审阅待确认：{len(reviews_needing_confirmation)}
- 已确认待人工发布：{len(confirmed_needing_manual_publish)}
- 已发布待回写 Outcome：{len(published_needing_outcome)}
- 有效 Reply 候选：{len(reply_candidates)}
- 有效 Quote 候选：{len(quote_candidates)}
- 常规待裁决 Signal：{len(regular_candidates)}
- 行动配比：{strategy['lane_allocation'] or '未配置'}
- 本周已完成：Discovery {lane_counts['discovery']} / {lane_targets['discovery']}；Authority {lane_counts['authority']} / {lane_targets['authority']}；Conversion {lane_counts['conversion']} / {lane_targets['conversion']}

## 为什么不是“多发一条”

每次行动都要服务于一个读者级假设：谁会看到、为何现在进入、希望对方做什么、何时复盘。NextX 只推荐下一步；最终裁决、互动和发布始终由人完成。
"""
    path = vault / "04. Views" / "Growth Loop.md"
    _write_view(vault, path, content)
    return {
        "schema_version": 1,
        "ok": True,
        "command": "growth-loop",
        "view": str(path),
        "next_action": {
            "id": action_id,
            "title": action_title,
            "reason": action_reason,
            "command": next_command,
        },
        "strategy_configured": strategy["configured"],
        "open_decision_count": len(open_decisions),
        "draft_needing_review_count": len(drafts_needing_review),
        "review_needing_confirmation_count": len(reviews_needing_confirmation),
        "confirmed_needing_manual_publish_count": len(confirmed_needing_manual_publish),
        "published_needing_outcome_count": len(published_needing_outcome),
        "reply_candidate_count": len(reply_candidates),
        "quote_candidate_count": len(quote_candidates),
        "regular_candidate_count": len(regular_candidates),
        "lane_counts": lane_counts,
        "lane_targets": lane_targets,
    }
def render_today(
    vault: Path, *, now: datetime | None = None
) -> dict[str, object]:
    vault = vault.expanduser().resolve()
    init_vault(vault)
    timestamp = now or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    generated_at = timestamp.astimezone(timezone.utc).isoformat()
    readiness = self_readiness(vault)
    excluded, revisit_due, completed_count = _signal_queue_state(vault, timestamp)
    signals = _records(vault / "01. Signal", "signal")
    pending = [
        record
        for record in signals
        if str(record[1].get("id")) not in excluded
        and record[1].get("bookmark_active") is not False
        and record[1].get("quote_candidate") is not True
        and record[1].get("reply_candidate") is not True
    ]
    pending.sort(key=lambda record: _timestamp(record[1]), reverse=True)
    manual: list[tuple[Path, dict[str, object]]] = []
    for record in pending:
        if record[1].get("signal_type") != "manual" or _is_near_duplicate(*record, manual):
            continue
        manual.append(record)
        if len(manual) == 2:
            break
    automatic_pool = [
        record for record in pending if record[1].get("signal_type") != "manual"
    ]
    automatic_pool.sort(
        key=lambda record: (_priority(record[1], timestamp)[0], _timestamp(record[1])),
        reverse=True,
    )
    author_counts: Counter[str] = Counter()
    automatic: list[tuple[Path, dict[str, object]]] = []
    selected_for_dedupe = list(manual)
    for record in automatic_pool:
        if _is_near_duplicate(*record, selected_for_dedupe):
            continue
        author = record[1].get("author_handle")
        author_key = str(author) if author else ""
        if author_key and author_counts[author_key] >= 2:
            continue
        automatic.append(record)
        selected_for_dedupe.append(record)
        if author_key:
            author_counts[author_key] += 1
        if len(automatic) == 10:
            break

    cards = [
        _card(
            path,
            properties,
            "复访已到期"
            if str(properties.get("id")) in revisit_due
            else "人工保留位 · 用户主动输入",
        )
        for path, properties in manual
    ] + [
        _card(
            path,
            properties,
            "复访已到期"
            if str(properties.get("id")) in revisit_due
            else _priority(properties, timestamp)[1],
        )
        for path, properties in automatic
    ]
    card_text = "\n".join(cards) if cards else "暂无待裁决 Signal。"
    view = f"""# Today · 待裁决

生成时间：{generated_at}

## Self 就绪度

{'已就绪。' if readiness['ready'] else '待补齐：' + '、'.join(str(item) for item in readiness['missing'])}

- 自动候选：{len(automatic)} / 10
- 手动保留：{len(manual)} / 2
- 已完成/毙掉：{completed_count}
- 缓办未到期：{len(excluded) - completed_count}
- 到期复访：{len(revisit_due)}
- Quote 候选：独立进入 [[Quote Sprint]]

{card_text}
"""
    path = vault / "04. Views" / "Today.md"
    _write_view(vault, path, view)
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
        "self_ready": readiness["ready"],
        "self_missing": readiness["missing"],
    }


def render_decision_board(vault: Path) -> Path:
    vault = vault.expanduser().resolve()
    decisions = _records(vault / "02. Decision", "decision")
    groups: dict[str, list[str]] = {"do": [], "defer": [], "kill": []}
    for path, properties in decisions:
        verdict = str(properties.get("verdict"))
        if verdict in groups:
            angle = properties.get("angle") or properties.get("reason_code") or "无标题"
            groups[verdict].append(f"- [[{path.stem}|{angle}]]")
    sections = []
    for verdict, title in (("do", "做"), ("defer", "缓"), ("kill", "毙")):
        sections.append(f"## {title}\n\n" + ("\n".join(groups[verdict]) or "- 无"))
    path = vault / "04. Views" / "Decision Board.md"
    _write_view(vault, path, "# Decision Board\n\n" + "\n\n".join(sections) + "\n")
    return path
