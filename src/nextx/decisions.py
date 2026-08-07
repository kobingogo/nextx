"""Auditable do/defer/kill Decision records and topic-engine handoff."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from .self_model import ensure_self_templates
from .signals import signal_filename
from .vault import atomic_write_text, init_vault, vault_lock


VERDICTS = {"do", "defer", "kill"}


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
    path = vault / "01. Signal" / signal_filename(normalized)
    if not path.exists():
        raise FileNotFoundError(f"Signal not found: {normalized}")
    return path


def _utc_now(now: datetime | None) -> datetime:
    value = now or datetime.now(timezone.utc)
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def decision_brief(vault: Path, signal_id: str) -> dict[str, str | int | bool]:
    vault = vault.expanduser().resolve()
    ensure_self_templates(vault)
    signal = _signal_path(vault, signal_id)
    signal_markdown = signal.read_text(encoding="utf-8")
    self_paths = [
        vault / "00. Self" / name
        for name in ("Profile.md", "Voice.md", "Pillars.md", "Monitoring.md", "Playbook.md")
    ]
    path_list = "\n".join(f"- {path}" for path in self_paths)
    brief = f"""使用现有 topic-engine 对下面这一个 Signal 做选题裁决。

只在需要判断定位时读取这些 Self 文件，不要在输出中复制整库内容：
{path_list}

输出一个 schema_version=1、account_key=primary 的 Decision JSON。verdict 只能是 do、defer、kill。

do 必须提供：angle、evidence_sufficient=true、original_value、risk、recommended_format、research_summary、why_now、why_self、reason_code、reason。
defer/kill 只需 reason_code 和 reason。不要写推文正文。

## Selected Signal

{signal_markdown}
"""
    return {
        "schema_version": 1,
        "ok": True,
        "command": "decision-brief",
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
    normalized_signal_ids = [str(value) for value in signal_ids]
    reason_code = _required_string(decision, "reason_code")
    reason = _required_string(decision, "reason")
    if verdict == "do":
        angle = _required_string(decision, "angle")
        original_value = _required_string(decision, "original_value")
        risk = _required_string(decision, "risk")
        if decision.get("evidence_sufficient") is not True:
            raise ValueError("A do Decision requires evidence_sufficient=true")
    else:
        angle = str(decision.get("angle") or "")
        original_value = str(decision.get("original_value") or "")
        risk = str(decision.get("risk") or "")

    vault = vault.expanduser().resolve()
    for signal_id in normalized_signal_ids:
        _signal_path(vault, signal_id)
    timestamp = _utc_now(now)
    digest = hashlib.sha256(
        json.dumps(decision, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()[:8]
    slug = f"{timestamp.strftime('%Y%m%dT%H%M%S')}-{digest}"
    decision_id = f"decision:{slug}"
    path = vault / "02. Decision" / f"decision-{slug}.md"
    properties = [
        "---",
        "schema_version: 1",
        'account_key: "primary"',
        f"id: {_json(decision_id)}",
        'type: "decision"',
        f"verdict: {_json(verdict)}",
        f"signal_ids: {_json(normalized_signal_ids)}",
        f"angle: {_json(angle)}",
        f"reason_code: {_json(reason_code)}",
        f"recommended_format: {_json(decision.get('recommended_format'))}",
        f"risk_level: {_json(decision.get('risk_level'))}",
        f"evidence_sufficient: {_json(decision.get('evidence_sufficient', False))}",
        f"created_at: {_json(timestamp.isoformat())}",
        "---",
    ]
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

## 关联 Signal

""" + "\n".join(f"- [[{signal_filename(signal_id)[:-3]}]]" for signal_id in normalized_signal_ids) + "\n"
    init_vault(vault)
    with vault_lock(vault):
        if path.exists():
            raise FileExistsError(f"Decision already exists: {path}")
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
