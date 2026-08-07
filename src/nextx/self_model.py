"""Bootstrap the user-owned Self model without inventing its answers."""

from __future__ import annotations

from pathlib import Path

from .vault import atomic_write_json, atomic_write_text, init_vault


SELF_TEMPLATES = {
    "Profile.md": """---
schema_version: 1
account_key: "primary"
type: "self"
self_section: "profile"
---
# Profile

## 一句话定位

## 目标受众

## 当前阶段

- 冷启动 / 爬坡 / 稳态：

## 目标与约束
""",
    "Voice.md": """---
schema_version: 1
account_key: "primary"
type: "self"
self_section: "voice"
---
# Voice

## 真实优秀样本

## 常用词与句式

## 结构和标点习惯

## 禁用词与 AI 腔反模式
""",
    "Pillars.md": """---
schema_version: 1
account_key: "primary"
type: "self"
self_section: "pillars"
---
# Content Pillars

最多填写四个内容柱。

1.
2.
3.

## 明确禁区
""",
    "Monitoring.md": """---
schema_version: 1
account_key: "primary"
type: "self"
self_section: "monitoring"
---
# Monitoring

## 对标账号

## 关键词

## X Lists

## 每日处理预算

- 自动候选：10
- 手动保留：2
""",
    "Playbook.md": """---
schema_version: 1
account_key: "primary"
type: "self"
self_section: "playbook"
---
# Playbook

这里只保存用户明确批准、具有支持样本和反例检查的规则。

## 已批准规则

## 待审建议
""",
}


def ensure_self_templates(vault: Path) -> list[Path]:
    vault = vault.expanduser().resolve()
    init_vault(vault)
    config = vault / ".nextx" / "config.json"
    if not config.exists():
        atomic_write_json(config, {"schema_version": 1, "account_key": "primary"})
    created: list[Path] = []
    for name, template in SELF_TEMPLATES.items():
        path = vault / "00. Self" / name
        if path.exists():
            continue
        atomic_write_text(path, template)
        created.append(path)
    return created
