"""Bounded deep-analysis handoff for one selected Signal."""

from __future__ import annotations

from pathlib import Path

from .signals import signal_filename


def build_analysis_brief(vault: Path, signal_id: str) -> dict[str, object]:
    vault = vault.expanduser().resolve()
    normalized = f"x:{signal_id}" if signal_id.isdigit() else signal_id
    path = vault / "01. Signal" / signal_filename(normalized)
    if not path.exists():
        raise FileNotFoundError(f"Signal not found: {normalized}")
    signal = path.read_text(encoding="utf-8")
    brief = f"""深度拆解下面这一个已选 Signal，不要扫描整个 Vault，也不要写推文。

先明确分离“事实 / 原帖观点 / 推断”，无法从原文证明的内容必须标为推断或待核验。按以下标题输出：

## 事实 / 原帖观点 / 推断
## 内容结构
## 钩子
## 传播机制
## 可迁移方法
## 风险与反证

结尾给出它是否值得进入 topic-engine 裁决的简短建议，但不要替用户保存 Decision。

## Selected Signal

{signal}
"""
    return {
        "schema_version": 1,
        "ok": True,
        "command": "analysis-brief",
        "signal_path": str(path),
        "brief": brief,
    }
