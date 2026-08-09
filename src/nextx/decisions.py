"""Auditable do/defer/kill Decision records and topic-engine handoff."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from .briefs import untrusted_data_block
from .records import read_frontmatter
from .signals import signal_path
from .vault import atomic_write_text, init_vault, vault_lock


VERDICTS = {"do", "defer", "kill"}
EXECUTION_MODES = {"original", "quote", "reply"}
QUOTE_ANGLE_TYPES = {
    "extend",
    "constructive_disagree",
    "translate",
    "implementation",
    "question",
}
RELATIONSHIP_GOALS = {"reader_discovery", "author_dialogue", "credibility"}
GROWTH_OBJECTIVES = {"awareness", "authority", "conversion"}
RAW_SIGNAL_SECTION = re.compile(
    r"^## (?:原始内容|原帖)\s*$\n(?P<text>.*?)(?=^##\s|\Z)",
    re.MULTILINE | re.DOTALL,
)
EXPERIMENT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def _required_string(payload: dict[str, object], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Decision field {field!r} must be a non-empty string")
    return value.strip()


def _validate_envelope(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("Decision payload must be an object")
    if payload.get("schema_version") != 1:
        raise ValueError("Decision schema_version must be 1")
    if payload.get("account_key") != "primary":
        raise ValueError("Decision account_key must be 'primary'")
    return payload


def _signal_path(vault: Path, signal_id: str) -> Path:
    normalized = f"x:{signal_id}" if signal_id.isdigit() else signal_id
    return signal_path(vault, normalized)


def _utc_now(now: datetime | None) -> datetime:
    value = now or datetime.now(timezone.utc)
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _future_timestamp(value: object, field: str, now: datetime) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Decision field {field!r} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"Decision field {field!r} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        raise ValueError(f"Decision field {field!r} must include a timezone")
    if parsed.astimezone(timezone.utc) <= now:
        raise ValueError(f"Decision field {field!r} must be in the future")
    return value.strip()


def _parsed_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Decision field {field!r} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"Decision field {field!r} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        raise ValueError(f"Decision field {field!r} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _execution_mode(payload: dict[str, object]) -> str:
    value = payload.get("execution_mode", "original")
    if not isinstance(value, str) or value not in EXECUTION_MODES:
        raise ValueError("Decision execution_mode must be original, quote, or reply")
    return value


def _quote_signal(
    vault: Path, signal_ids: list[str], *, now: datetime, allow_expired: bool = False
) -> tuple[str, dict[str, object], datetime]:
    """Return the persisted original post eligible for a Quote Decision.

    Quote is an execution mode, not a new content object.  The source must
    therefore already exist as a verified, time-bounded Signal in the Vault.
    """
    if len(signal_ids) != 1:
        raise ValueError("A quote Decision must reference exactly one Signal")
    signal_id = signal_ids[0]
    properties, _ = read_frontmatter(_signal_path(vault, signal_id))
    if properties.get("quote_candidate") is not True:
        raise ValueError("A quote Decision requires a persisted quote_candidate Signal")
    if properties.get("platform") != "x":
        raise ValueError("A quote Decision requires an X Signal")
    if not isinstance(properties.get("source_url"), str) or not isinstance(
        properties.get("author_handle"), str
    ):
        raise ValueError("A quote Signal requires a canonical source URL and author")
    window = _parsed_timestamp(properties.get("quote_window_ends_at"), "quote_window_ends_at")
    if window <= now and not allow_expired:
        raise ValueError("The Quote decision window has expired; record kill or capture a fresh Signal")
    return signal_id, properties, window


def _reply_signal(
    vault: Path, signal_ids: list[str], *, now: datetime, allow_expired: bool = False
) -> tuple[str, dict[str, object], datetime]:
    """Return the exact persisted post eligible for a Reply Decision."""
    if len(signal_ids) != 1:
        raise ValueError("A reply Decision must reference exactly one Signal")
    signal_id = signal_ids[0]
    properties, _ = read_frontmatter(_signal_path(vault, signal_id))
    if properties.get("reply_candidate") is not True:
        raise ValueError("A reply Decision requires a persisted reply_candidate Signal")
    if properties.get("platform") != "x":
        raise ValueError("A reply Decision requires an X Signal")
    if not isinstance(properties.get("source_url"), str) or not isinstance(
        properties.get("author_handle"), str
    ):
        raise ValueError("A reply Signal requires a canonical source URL and author")
    window = _parsed_timestamp(properties.get("reply_window_ends_at"), "reply_window_ends_at")
    if window <= now and not allow_expired:
        raise ValueError("The Reply decision window has expired; record kill or capture a fresh Signal")
    return signal_id, properties, window


def _quote_choice(value: object, field: str, allowed: set[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        choices = ", ".join(sorted(allowed))
        raise ValueError(f"Decision field {field!r} must be one of: {choices}")
    return value


def _experiment(value: object, verdict: str) -> dict[str, str] | None:
    if value is None:
        return None
    if verdict != "do":
        raise ValueError("Only a do Decision can define an experiment")
    if not isinstance(value, dict):
        raise ValueError("Decision experiment must be an object")
    experiment_id = _required_string(value, "id")
    if EXPERIMENT_ID.fullmatch(experiment_id) is None:
        raise ValueError("Experiment id must use lowercase letters, digits, and hyphens")
    hypothesis = _required_string(value, "hypothesis")
    if len(hypothesis) > 1_000:
        raise ValueError("Experiment hypothesis must be at most 1000 characters")
    metric = value.get("metric", "engagement_rate")
    if metric != "engagement_rate":
        raise ValueError("Experiment metric must be engagement_rate")
    return {"id": experiment_id, "hypothesis": hypothesis, "metric": metric}


def _growth_contract(value: object, verdict: str, now: datetime) -> dict[str, str] | None:
    """Require a do Decision to declare the reader-level outcome it tests."""
    if verdict != "do":
        if value is not None:
            raise ValueError("Only a do Decision can define a growth_contract")
        return None
    if not isinstance(value, dict):
        raise ValueError("A do Decision requires a growth_contract object")
    objective = value.get("objective")
    if objective not in GROWTH_OBJECTIVES:
        raise ValueError("growth_contract.objective must be awareness, authority, or conversion")
    target_reader = _required_string(value, "target_reader")
    expected_action = _required_string(value, "expected_action")
    distribution_target = _required_string(value, "distribution_target")
    review_at = _future_timestamp(value.get("review_at"), "growth_contract.review_at", now)
    limits = {
        "target_reader": (target_reader, 600),
        "expected_action": (expected_action, 600),
        "distribution_target": (distribution_target, 600),
    }
    for field, (text, limit) in limits.items():
        if len(text) > limit:
            raise ValueError(f"growth_contract.{field} must be at most {limit} characters")
    return {
        "objective": objective,
        "target_reader": target_reader,
        "expected_action": expected_action,
        "distribution_target": distribution_target,
        "review_at": review_at,
    }


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _fingerprint(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _existing_decision(
    vault: Path, fingerprint: str
) -> tuple[str, Path, dict[str, object]] | None:
    for path in (vault / "02. Decision").glob("decision-*.md"):
        properties, _ = read_frontmatter(path)
        if properties.get("input_fingerprint") == fingerprint:
            decision_id = properties.get("id")
            if isinstance(decision_id, str):
                return decision_id, path, properties
    return None


def _new_decision_path(vault: Path, timestamp: datetime, digest: str) -> tuple[str, Path]:
    stem = f"{timestamp.strftime('%Y%m%dT%H%M%S%f')}-{digest}"
    attempt = 0
    while True:
        slug = stem if attempt == 0 else f"{stem}-{attempt}"
        path = vault / "02. Decision" / f"decision-{slug}.md"
        if not path.exists():
            return slug, path
        attempt += 1


def _validate_evidence(
    vault: Path, signal_ids: list[str], value: object
) -> list[dict[str, str | None]]:
    """Require a Decision to cite exact, persisted Signal evidence.

    The check cannot prove that a remote post still exists, but it prevents a
    Collector or Agent from inventing a URL or a quotation after import.
    """
    if not isinstance(value, list) or not value:
        raise ValueError("A do Decision requires a non-empty evidence list")
    available: dict[str, tuple[dict[str, object], str]] = {}
    for signal_id in signal_ids:
        properties, body = read_frontmatter(_signal_path(vault, signal_id))
        available[signal_id] = (properties, body)

    normalized: list[dict[str, str | None]] = []
    directly_supported = False
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("Each evidence item must be an object")
        signal_id = _required_string(item, "signal_id")
        if signal_id not in available:
            raise ValueError("Evidence must cite one of the Decision signal_ids")
        quote = _required_string(item, "quote")
        if len(quote) > 1_000:
            raise ValueError("Evidence quote must be at most 1000 characters")
        properties, body = available[signal_id]
        source_text = _source_text(body)
        if quote not in source_text:
            raise ValueError("Evidence quote must be an exact excerpt of the original Signal text")
        expected_url = properties.get("source_url")
        source_url = item.get("source_url")
        if expected_url is None:
            if source_url is not None:
                raise ValueError("Manual Signal evidence must use source_url=null")
            directly_supported = True
            normalized_url = None
        else:
            if not isinstance(expected_url, str) or source_url != expected_url:
                raise ValueError("Evidence source_url must exactly match the stored Signal")
            if properties.get("source_confidence") != "low":
                directly_supported = True
            normalized_url = expected_url
        normalized.append(
            {"signal_id": signal_id, "quote": quote, "source_url": normalized_url}
        )
    if not directly_supported:
        raise ValueError("A do Decision cannot rely only on low-confidence evidence")
    return normalized


def _source_text(body: str) -> str:
    match = RAW_SIGNAL_SECTION.search(body)
    if match is None:
        raise ValueError("Signal is missing its original-content section")
    return match.group("text").strip()


def decision_brief(
    vault: Path,
    signal_id: str,
    *,
    execution_mode: str = "original",
    now: datetime | None = None,
) -> dict[str, str | int | bool]:
    vault = vault.expanduser().resolve()
    if execution_mode not in EXECUTION_MODES:
        raise ValueError("Decision execution_mode must be original, quote, or reply")
    signal = _signal_path(vault, signal_id)
    signal_markdown = signal.read_text(encoding="utf-8")
    self_paths = [
        vault / "00. Self" / name
        for name in (
            "Profile.md",
            "Voice.md",
            "Pillars.md",
            "Monitoring.md",
            "Growth Strategy.md",
            "Playbook.md",
        )
    ]
    path_list = "\n".join(f"- {path}" for path in self_paths)
    mode_requirements = ""
    if execution_mode == "quote":
        _, signal_properties, quote_deadline = _quote_signal(
            vault, [signal_id], now=_utc_now(now)
        )
        mode_requirements = f"""
这是一个起号阶段的 Quote Sprint 候选。只评估“引用原帖后，是否能为目标读者新增一个可验证、非复述的观点”；不要把它降级成泛泛的转述、吹捧或跟风。

如果 verdict=do，额外必须提供：execution_mode="quote"、recommended_format="quote-post"、quote_angle_type（extend / constructive_disagree / translate / implementation / question）、relationship_goal（reader_discovery / author_dialogue / credibility）、quote_window_ends_at。该截止时间必须不晚于原 Signal 的 {quote_deadline.isoformat()}。
如果 verdict=defer，revisit_at 必须早于该截止时间；过期候选应 kill，而不是继续写作。只可引用这一条原帖（@{signal_properties['author_handle']}）。
"""
    elif execution_mode == "reply":
        _, signal_properties, reply_deadline = _reply_signal(
            vault, [signal_id], now=_utc_now(now)
        )
        mode_requirements = f"""
这是一个 Reply Sprint 候选。只评估“回复能否帮助目标读者理解、推进或校正当前讨论”；不要写套话、赞美或伪装熟人。

如果 verdict=do，额外必须提供：execution_mode="reply"、recommended_format="reply-post"、reply_angle_type（extend / constructive_disagree / translate / implementation / question）、relationship_goal（reader_discovery / author_dialogue / credibility）、reply_window_ends_at。该截止时间必须不晚于原 Signal 的 {reply_deadline.isoformat()}。
如果 verdict=defer，revisit_at 必须早于该截止时间；过期候选应 kill。只能回复 @{signal_properties['author_handle']} 的这一条原帖。
"""
    else:
        mode_requirements = "如果不是 Quote / Reply Sprint，execution_mode 可省略（默认 original）。"
    brief = f"""使用现有 topic-engine 对一个 Signal 做选题裁决。

只在需要判断定位时读取这些 Self 文件，不要在输出中复制整库内容：
{path_list}

输出一个 schema_version=1、account_key=primary 的 Decision JSON。verdict 只能是 do、defer、kill。

do 必须提供：angle、evidence_sufficient=true、evidence、original_value、risk、recommended_format、research_summary、why_now、why_self、reason_code、reason，以及 growth_contract。growth_contract 必须含 objective（awareness / authority / conversion）、target_reader、expected_action、distribution_target、review_at（未来带时区）。这是一次对读者行为的假设，不得承诺效果。
evidence 必须是数组；每项含 signal_id、quote 和 source_url（手动 Signal 的 source_url 可为 null）。quote 必须是所选 Signal 中逐字可见的短摘录，不要编造或改写。
defer 必须提供 reason_code、reason、revisit_at（未来且带时区）和 revisit_reason；kill 只需 reason_code 和 reason。不要写推文正文。
{mode_requirements}

{untrusted_data_block("Signal", signal_markdown)}
"""
    return {
        "schema_version": 1,
        "ok": True,
        "command": "decision-brief",
        "execution_mode": execution_mode,
        "signal_path": str(signal),
        "brief": brief,
    }


def save_decision(
    vault: Path,
    payload: object,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    decision = _validate_envelope(payload)
    verdict = _required_string(decision, "verdict")
    if verdict not in VERDICTS:
        raise ValueError("Decision verdict must be do, defer, or kill")
    signal_ids = decision.get("signal_ids")
    if not isinstance(signal_ids, list) or not signal_ids:
        raise ValueError("Decision signal_ids must be a non-empty list")
    normalized_signal_ids = [
        _required_string({"value": value}, "value") for value in signal_ids
    ]
    if len(set(normalized_signal_ids)) != len(normalized_signal_ids):
        raise ValueError("Decision signal_ids must not contain duplicates")
    vault = vault.expanduser().resolve()
    for signal_id in normalized_signal_ids:
        _signal_path(vault, signal_id)
    reason_code = _required_string(decision, "reason_code")
    reason = _required_string(decision, "reason")
    timestamp = _utc_now(now)
    execution_mode = _execution_mode(decision)
    quote_signal_id: str | None = None
    quote_properties: dict[str, object] | None = None
    quote_window_ends_at: str | None = None
    reply_signal_id: str | None = None
    reply_properties: dict[str, object] | None = None
    reply_window_ends_at: str | None = None
    if execution_mode == "quote":
        quote_signal_id, quote_properties, quote_deadline = _quote_signal(
            vault, normalized_signal_ids, now=timestamp, allow_expired=verdict == "kill"
        )
        quote_window_ends_at = quote_deadline.isoformat()
    elif execution_mode == "reply":
        reply_signal_id, reply_properties, reply_deadline = _reply_signal(
            vault, normalized_signal_ids, now=timestamp, allow_expired=verdict == "kill"
        )
        reply_window_ends_at = reply_deadline.isoformat()
    experiment = _experiment(decision.get("experiment"), verdict)
    growth_contract = _growth_contract(decision.get("growth_contract"), verdict, timestamp)
    if verdict != "do" and "experiment" in decision:
        raise ValueError("Only a do Decision can define an experiment")
    if verdict == "do":
        angle = _required_string(decision, "angle")
        original_value = _required_string(decision, "original_value")
        risk = _required_string(decision, "risk")
        if decision.get("evidence_sufficient") is not True:
            raise ValueError("A do Decision requires evidence_sufficient=true")
        evidence = _validate_evidence(
            vault=vault, signal_ids=normalized_signal_ids, value=decision.get("evidence")
        )
        revisit_at = None
        revisit_reason = None
        if execution_mode == "quote":
            recommended_format = _required_string(decision, "recommended_format")
            if recommended_format != "quote-post":
                raise ValueError("A quote do Decision requires recommended_format='quote-post'")
            quote_angle_type = _quote_choice(
                decision.get("quote_angle_type"), "quote_angle_type", QUOTE_ANGLE_TYPES
            )
            relationship_goal = _quote_choice(
                decision.get("relationship_goal"), "relationship_goal", RELATIONSHIP_GOALS
            )
            requested_window = _future_timestamp(
                decision.get("quote_window_ends_at"), "quote_window_ends_at", timestamp
            )
            if _parsed_timestamp(requested_window, "quote_window_ends_at") > quote_deadline:
                raise ValueError(
                    "quote_window_ends_at cannot be later than the Signal decision window"
                )
            quote_window_ends_at = requested_window
            reply_angle_type = None
        elif execution_mode == "reply":
            recommended_format = _required_string(decision, "recommended_format")
            if recommended_format != "reply-post":
                raise ValueError("A reply do Decision requires recommended_format='reply-post'")
            reply_angle_type = _quote_choice(
                decision.get("reply_angle_type"), "reply_angle_type", QUOTE_ANGLE_TYPES
            )
            relationship_goal = _quote_choice(
                decision.get("relationship_goal"), "relationship_goal", RELATIONSHIP_GOALS
            )
            requested_window = _future_timestamp(
                decision.get("reply_window_ends_at"), "reply_window_ends_at", timestamp
            )
            if _parsed_timestamp(requested_window, "reply_window_ends_at") > reply_deadline:
                raise ValueError(
                    "reply_window_ends_at cannot be later than the Signal decision window"
                )
            reply_window_ends_at = requested_window
            quote_angle_type = None
        else:
            quote_angle_type = None
            reply_angle_type = None
            relationship_goal = None
    elif verdict == "defer":
        angle = str(decision.get("angle") or "")
        original_value = str(decision.get("original_value") or "")
        risk = str(decision.get("risk") or "")
        evidence = []
        revisit_at = _future_timestamp(decision.get("revisit_at"), "revisit_at", timestamp)
        revisit_reason = _required_string(decision, "revisit_reason")
        if execution_mode == "quote" and _parsed_timestamp(revisit_at, "revisit_at") >= quote_deadline:
            raise ValueError("A quote defer revisit_at must be before the Quote decision window ends")
        if execution_mode == "reply" and _parsed_timestamp(revisit_at, "revisit_at") >= reply_deadline:
            raise ValueError("A reply defer revisit_at must be before the Reply decision window ends")
        quote_angle_type = None
        reply_angle_type = None
        relationship_goal = None
    else:
        angle = str(decision.get("angle") or "")
        original_value = str(decision.get("original_value") or "")
        risk = str(decision.get("risk") or "")
        evidence = []
        revisit_at = None
        revisit_reason = None
        quote_angle_type = None
        reply_angle_type = None
        relationship_goal = None

    fingerprint = _fingerprint(decision)
    digest = fingerprint[:8]
    properties = [
        "---",
        "schema_version: 1",
        'account_key: "primary"',
        "id: null",
        'type: "decision"',
        f"input_fingerprint: {_json(fingerprint)}",
        f"verdict: {_json(verdict)}",
        f"execution_mode: {_json(execution_mode)}",
        f"signal_ids: {_json(normalized_signal_ids)}",
        f"angle: {_json(angle)}",
        f"reason_code: {_json(reason_code)}",
        f"recommended_format: {_json(decision.get('recommended_format'))}",
        f"risk_level: {_json(decision.get('risk_level'))}",
        f"evidence_sufficient: {_json(decision.get('evidence_sufficient', False))}",
        f"evidence: {_json(evidence)}",
        f"revisit_at: {_json(revisit_at)}",
        f"revisit_reason: {_json(revisit_reason)}",
        f"quote_signal_id: {_json(quote_signal_id)}",
        f"quote_source_url: {_json(quote_properties.get('source_url') if quote_properties else None)}",
        f"quote_author_handle: {_json(quote_properties.get('author_handle') if quote_properties else None)}",
        f"quote_window_ends_at: {_json(quote_window_ends_at)}",
        f"quote_angle_type: {_json(quote_angle_type)}",
        f"reply_signal_id: {_json(reply_signal_id)}",
        f"reply_source_url: {_json(reply_properties.get('source_url') if reply_properties else None)}",
        f"reply_author_handle: {_json(reply_properties.get('author_handle') if reply_properties else None)}",
        f"reply_window_ends_at: {_json(reply_window_ends_at)}",
        f"reply_angle_type: {_json(reply_angle_type)}",
        f"relationship_goal: {_json(relationship_goal)}",
        f"growth_objective: {_json(growth_contract['objective'] if growth_contract else None)}",
        f"growth_target_reader: {_json(growth_contract['target_reader'] if growth_contract else None)}",
        f"growth_expected_action: {_json(growth_contract['expected_action'] if growth_contract else None)}",
        f"distribution_target: {_json(growth_contract['distribution_target'] if growth_contract else None)}",
        f"growth_review_at: {_json(growth_contract['review_at'] if growth_contract else None)}",
        f"experiment_id: {_json(experiment['id'] if experiment else None)}",
        f"experiment_hypothesis: {_json(experiment['hypothesis'] if experiment else None)}",
        f"experiment_metric: {_json(experiment['metric'] if experiment else None)}",
        f"created_at: {_json(timestamp.isoformat())}",
        "---",
    ]
    quote_strategy = "非 Quote 执行模式。"
    if execution_mode == "quote" and quote_signal_id and quote_properties:
        quote_strategy = "\n".join(
            (
                f"- 原帖：[[{signal_path(vault, quote_signal_id).stem}]]",
                f"- 作者：@{quote_properties.get('author_handle')}",
                f"- 决策窗口：{quote_window_ends_at}",
                f"- 增量类型：{quote_angle_type}",
                f"- 关系目标：{relationship_goal}",
            )
        )
    reply_strategy = "非 Reply 执行模式。"
    if execution_mode == "reply" and reply_signal_id and reply_properties:
        reply_strategy = "\n".join(
            (
                f"- 原帖：[[{signal_path(vault, reply_signal_id).stem}]]",
                f"- 作者：@{reply_properties.get('author_handle')}",
                f"- 决策窗口：{reply_window_ends_at}",
                f"- 增量类型：{reply_angle_type}",
                f"- 关系目标：{relationship_goal}",
            )
        )
    growth_strategy = (
        "不适用"
        if growth_contract is None
        else "\n".join(
            (
                f"- 目标：{growth_contract['objective']}",
                f"- 目标读者：{growth_contract['target_reader']}",
                f"- 期待动作：{growth_contract['expected_action']}",
                f"- 分发目标：{growth_contract['distribution_target']}",
                f"- 复盘时间：{growth_contract['review_at']}",
            )
        )
    )
    body = f"""
# Decision · {verdict.upper()}

## 裁决理由

{reason}

## 角度

{angle or '不适用'}

## 研究摘要

{decision.get('research_summary') or '不适用'}

## 为什么是现在

{decision.get('why_now') or '不适用'}

## 为什么适合 Self

{decision.get('why_self') or '不适用'}

## 原创增量

{original_value or '不适用'}

## 风险

{risk or '不适用'}

## Quote 策略

{quote_strategy}

## Reply 策略

{reply_strategy}

## 增长契约

{growth_strategy}

## 实验

{f"{experiment['id']} · {experiment['hypothesis']}（{experiment['metric']}）" if experiment else '不适用'}

## 复访

{f'{revisit_at} · {revisit_reason}' if revisit_at else '不适用'}

## 证据

""" + (
        "\n".join(
            f"- [[{signal_path(vault, item['signal_id']).stem}]]\n"
            f"  - 来源：{item['source_url'] or '用户手动输入'}\n"
            f"  - 摘录：{item['quote']}"
            for item in evidence
        )
        or "不适用"
    ) + """

## 关联 Signal

""" + "\n".join(f"- [[{signal_path(vault, signal_id).stem}]]" for signal_id in normalized_signal_ids) + "\n"
    init_vault(vault)
    with vault_lock(vault):
        existing = _existing_decision(vault, fingerprint)
        if existing is not None:
            existing_id, existing_path, existing_properties = existing
            return {
                "schema_version": 1,
                "ok": True,
                "command": "save-decision",
                "id": existing_id,
                "path": str(existing_path),
                "verdict": existing_properties.get("verdict", verdict),
                "signal_ids": existing_properties.get("signal_ids", normalized_signal_ids),
                "reused": True,
            }
        slug, path = _new_decision_path(vault, timestamp, digest)
        decision_id = f"decision:{slug}"
        properties[3] = f"id: {_json(decision_id)}"
        atomic_write_text(path, "\n".join(properties) + body)
    return {
        "schema_version": 1,
        "ok": True,
        "command": "save-decision",
        "id": decision_id,
        "path": str(path),
        "verdict": verdict,
        "signal_ids": normalized_signal_ids,
    }
