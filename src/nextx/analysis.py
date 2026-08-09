"""Bounded deep-analysis handoff for one selected Signal."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import secrets

from .briefs import untrusted_data_block
from .records import read_frontmatter, update_frontmatter
from .signals import signal_path
from .vault import atomic_write_text, vault_lock


ANALYSIS_FIELDS = (
    "facts",
    "structure",
    "hook",
    "distribution",
    "transferable",
    "risks",
    "recommendation",
)


def build_analysis_brief(vault: Path, signal_id: str) -> dict[str, object]:
    vault = vault.expanduser().resolve()
    normalized = f"x:{signal_id}" if signal_id.isdigit() else signal_id
    path = signal_path(vault, normalized)
    signal = path.read_text(encoding="utf-8")
    brief = f"""深度拆解一个已选 Signal，不要扫描整个 Vault，也不要写推文。

先明确分离“事实 / 原帖观点 / 推断”，无法从原文证明的内容必须标为推断或待核验。按以下标题输出：

## 事实 / 原帖观点 / 推断
## 内容结构
## 钩子
## 传播机制
## 可迁移方法
## 风险与反证

结尾给出它是否值得进入 topic-engine 裁决的简短建议，但不要替用户保存 Decision。
最终输出一个 schema_version=1、account_key=primary、signal_id 和以下字段都为字符串的 Analysis JSON：facts、structure、hook、distribution、transferable、risks、recommendation。

{untrusted_data_block("Signal", signal)}
"""
    return {
        "schema_version": 1,
        "ok": True,
        "command": "analysis-brief",
        "signal_path": str(path),
        "brief": brief,
    }


def save_analysis(
    vault: Path, payload: object, *, now: datetime | None = None
) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("Analysis payload must be an object")
    if payload.get("schema_version") != 1 or payload.get("account_key") != "primary":
        raise ValueError("Analysis requires schema_version=1 and account_key='primary'")
    signal_id = payload.get("signal_id")
    if not isinstance(signal_id, str) or not signal_id.strip():
        raise ValueError("Analysis requires a non-empty signal_id")
    sections: dict[str, str] = {}
    for field in ANALYSIS_FIELDS:
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 12_000:
            raise ValueError(f"Analysis field {field!r} must be a non-empty string under 12000 characters")
        sections[field] = value.strip()
    vault = vault.expanduser().resolve()
    timestamp = now or datetime.now(timezone.utc)
    timestamp = (
        timestamp.replace(tzinfo=timezone.utc)
        if timestamp.tzinfo is None
        else timestamp.astimezone(timezone.utc)
    )
    normalized = f"x:{signal_id}" if signal_id.isdigit() else signal_id
    path = signal_path(vault, normalized)
    with vault_lock(vault):
        properties, body = read_frontmatter(path)
        marker = properties.get("analysis_marker")
        if not isinstance(marker, str) or len(marker) != 32:
            marker = secrets.token_hex(16)
        new_body = _replace_analysis(body, sections, marker)
        _write_body(path, body, new_body)
        update_frontmatter(
            path,
            {
                "analysis_status": "ready",
                "analysis_marker": marker,
                "analysis_updated_at": timestamp.isoformat(),
            },
        )
    return {
        "schema_version": 1,
        "ok": True,
        "command": "save-analysis",
        "signal_id": normalized,
        "path": str(path),
        "analysis_status": "ready",
    }


def _replace_analysis(body: str, sections: dict[str, str], marker: str) -> str:
    rendered = "\n\n".join(
        f"### {label}\n\n{sections[key]}"
        for key, label in (
            ("facts", "事实 / 原帖观点 / 推断"),
            ("structure", "内容结构"),
            ("hook", "钩子"),
            ("distribution", "传播机制"),
            ("transferable", "可迁移方法"),
            ("risks", "风险与反证"),
            ("recommendation", "进入裁决建议"),
        )
    )
    section = (
        "## 深度拆解\n\n"
        f"<!-- nextx-analysis:{marker}:start -->\n{rendered}\n"
        f"<!-- nextx-analysis:{marker}:end -->"
    )
    start = body.rfind("## 深度拆解")
    end = body.find("## 关联决策", start)
    if start >= 0 and end >= 0:
        return body[:start] + section + "\n\n" + body[end:]
    return body.rstrip() + "\n\n" + section + "\n"


def _write_body(path: Path, old_body: str, new_body: str) -> None:
    full_text = path.read_text(encoding="utf-8")
    prefix = full_text[: len(full_text) - len(old_body)] if old_body else full_text
    atomic_write_text(path, prefix + new_body)
