"""Bootstrap the user-owned Self model without inventing its answers."""

from __future__ import annotations

from pathlib import Path
import re

from .accounts import ensure_account_registry
from .records import read_frontmatter, update_frontmatter
from .vault import atomic_write_text, init_vault, vault_lock


GROWTH_STAGES = {"launch", "ramp", "steady"}
GROWTH_OBJECTIVES = {"awareness", "authority", "conversion"}
GROWTH_LANES = ("discovery", "authority", "conversion")


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

## Quote Sprint（起号阶段）

- 每日高质量 Quote：1–3
- 优先对话的作者：
- 希望被谁看见（相邻读者）：
- 不做的 Quote：只复述、只恭维、无法核验原帖、超过讨论窗口
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
    "Growth Strategy.md": """---
schema_version: 1
account_key: "primary"
type: "self"
self_section: "growth_strategy"
growth_stage: null
growth_objective: null
growth_target_reader: null
profile_promise: null
primary_cta: null
weekly_focus: null
lane_allocation: null
---
# Growth Strategy

这是一周内唯一的增长导航，不是又一张数据看板。NextX 会据此把候选压成一项可解释的下一步行动；用户仍保留最终判断和人工发布权。

## 当前策略

- 阶段：未配置
- 本周唯一目标：未配置
- 目标读者：未配置
- 主页承接：未配置
- CTA：未配置
- 本周聚焦：未配置

## 行动配比

- Discovery（Quote / Reply）：未配置
- Authority（原创 Thread / 系列）：未配置
- Conversion（案例 / CTA）：未配置
""",
}


def ensure_self_templates(vault: Path) -> list[Path]:
    vault = vault.expanduser().resolve()
    init_vault(vault)
    ensure_account_registry(vault)
    created: list[Path] = []
    for name, template in SELF_TEMPLATES.items():
        path = vault / "00. Self" / name
        if path.exists():
            continue
        atomic_write_text(path, template)
        created.append(path)
    return created


def self_readiness(vault: Path, *, initialize: bool = False) -> dict[str, object]:
    """Report missing editorial inputs without inventing a user identity or blocking work."""
    vault = vault.expanduser().resolve()
    if initialize:
        ensure_self_templates(vault)

    def section_has_content(name: str, heading: str) -> bool:
        text = (vault / "00. Self" / name).read_text(encoding="utf-8")
        match = re.search(
            rf"^{re.escape(heading)}\s*$\n(?P<body>.*?)(?=^##\s|\Z)",
            text,
            re.MULTILINE | re.DOTALL,
        )
        return bool(match and match.group("body").strip())

    expected = [vault / "00. Self" / name for name in SELF_TEMPLATES]
    if not all(path.is_file() for path in expected):
        return {
            "schema_version": 1,
            "ok": True,
            "command": "readiness",
            "ready": False,
            "missing": ["Self 模型尚未初始化；运行 `nextx setup --yes`"],
            "pillar_count": 0,
            "growth_ready": False,
            "growth_missing": ["增长策略"],
        }

    pillars = (vault / "00. Self" / "Pillars.md").read_text(encoding="utf-8")
    pillar_count = sum(
        bool(re.match(r"^\d+\.\s*\S", line))
        for line in pillars.splitlines()
    )
    missing: list[str] = []
    if not section_has_content("Profile.md", "## 一句话定位"):
        missing.append("一句话定位")
    if pillar_count < 3:
        missing.append("至少三个内容柱")
    if not section_has_content("Voice.md", "## 真实优秀样本"):
        missing.append("真实优秀样本")
    if not section_has_content("Pillars.md", "## 明确禁区"):
        missing.append("明确禁区")
    strategy = growth_strategy(vault)
    return {
        "schema_version": 1,
        "ok": True,
        "command": "readiness",
        "ready": not missing,
        "missing": missing,
        "pillar_count": pillar_count,
        "growth_ready": strategy["configured"],
        "growth_missing": strategy["missing"],
    }


def _configured_text(payload: dict[str, object], field: str, *, limit: int) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise ValueError(f"Self field {field!r} must be a non-empty string under {limit} characters")
    return value.strip()


def _configured_list(
    payload: dict[str, object], field: str, *, minimum: int, maximum: int, item_limit: int
) -> list[str]:
    value = payload.get(field)
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ValueError(f"Self field {field!r} must contain {minimum} to {maximum} items")
    items: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip() or len(item.strip()) > item_limit:
            raise ValueError(f"Self field {field!r} contains an invalid item")
        items.append(item.strip())
    if len(set(items)) != len(items):
        raise ValueError(f"Self field {field!r} must not contain duplicate items")
    return items


def _replace_section(markdown: str, heading: str, content: str) -> str:
    pattern = re.compile(
        rf"^{re.escape(heading)}\s*$\n.*?(?=^##\s|\Z)", re.MULTILINE | re.DOTALL
    )
    replacement = f"{heading}\n\n{content.strip()}\n"
    if pattern.search(markdown):
        return pattern.sub(replacement, markdown, count=1)
    return markdown.rstrip() + f"\n\n{replacement}"


def _growth_strategy_input(value: object) -> dict[str, object] | None:
    """Validate the small amount of strategy a novice must explicitly own.

    The workbench can recommend an action, but it must not invent a target
    reader, promise, or CTA.  Keeping this in Self makes the recommendation
    explainable and keeps it out of a separate hidden database.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Self field 'growth_strategy' must be an object")
    stage = value.get("stage")
    objective = value.get("objective")
    if stage not in GROWTH_STAGES:
        raise ValueError("growth_strategy.stage must be launch, ramp, or steady")
    if objective not in GROWTH_OBJECTIVES:
        raise ValueError("growth_strategy.objective must be awareness, authority, or conversion")
    result: dict[str, object] = {"stage": stage, "objective": objective}
    limits = {
        "target_reader": 600,
        "profile_promise": 600,
        "cta": 400,
        "weekly_focus": 600,
    }
    for field, limit in limits.items():
        result[field] = _configured_text(value, field, limit=limit)
    allocation = value.get("lane_allocation")
    if not isinstance(allocation, dict) or set(allocation) != set(GROWTH_LANES):
        raise ValueError(
            "growth_strategy.lane_allocation must contain discovery, authority, and conversion"
        )
    normalized: dict[str, int] = {}
    for lane in GROWTH_LANES:
        count = allocation[lane]
        if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= 7:
            raise ValueError("growth_strategy lane allocation values must be integers from 0 to 7")
        normalized[lane] = count
    if not 1 <= sum(normalized.values()) <= 12:
        raise ValueError("growth_strategy lane allocation total must be from 1 to 12")
    result["lane_allocation"] = normalized
    return result


def growth_strategy(vault: Path) -> dict[str, object]:
    """Read the optional, user-authored strategy without initializing a Vault."""
    path = vault.expanduser().resolve() / "00. Self" / "Growth Strategy.md"
    empty = {
        "configured": False,
        "missing": ["增长策略"],
        "stage": None,
        "objective": None,
        "target_reader": None,
        "profile_promise": None,
        "cta": None,
        "weekly_focus": None,
        "lane_allocation": None,
    }
    if not path.is_file():
        return empty
    try:
        properties, _ = read_frontmatter(path)
    except (OSError, ValueError):
        return empty
    stage = properties.get("growth_stage")
    objective = properties.get("growth_objective")
    values = {
        "target_reader": properties.get("growth_target_reader"),
        "profile_promise": properties.get("profile_promise"),
        "cta": properties.get("primary_cta"),
        "weekly_focus": properties.get("weekly_focus"),
        "lane_allocation": properties.get("lane_allocation"),
    }
    candidate = {"stage": stage, "objective": objective, **values}
    try:
        normalized = _growth_strategy_input(candidate)
    except ValueError:
        return empty
    if normalized is None:
        return empty
    return {
        "configured": True,
        "missing": [],
        "stage": normalized["stage"],
        "objective": normalized["objective"],
        "target_reader": normalized["target_reader"],
        "profile_promise": normalized["profile_promise"],
        "cta": normalized["cta"],
        "weekly_focus": normalized["weekly_focus"],
        "lane_allocation": normalized["lane_allocation"],
    }


def configure_self(vault: Path, payload: object) -> dict[str, object]:
    """Persist explicit conversational Self inputs without inventing an identity."""
    if not isinstance(payload, dict):
        raise ValueError("Self configuration payload must be an object")
    if payload.get("schema_version") != 1 or payload.get("account_key") != "primary":
        raise ValueError("Self configuration requires schema_version=1 and account_key='primary'")
    positioning = _configured_text(payload, "positioning", limit=600)
    audience = _configured_text(payload, "audience", limit=600)
    stage = _configured_text(payload, "stage", limit=120)
    boundaries = _configured_text(payload, "boundaries", limit=1_200)
    pillars = _configured_list(payload, "pillars", minimum=3, maximum=4, item_limit=160)
    voice_samples = _configured_list(
        payload, "voice_samples", minimum=1, maximum=10, item_limit=1_200
    )
    goals = payload.get("goals", "")
    if not isinstance(goals, str) or len(goals.strip()) > 1_200:
        raise ValueError("Self field 'goals' must be a string under 1200 characters")
    strategy = _growth_strategy_input(payload.get("growth_strategy"))

    vault = vault.expanduser().resolve()
    ensure_self_templates(vault)
    profile = vault / "00. Self" / "Profile.md"
    pillars_path = vault / "00. Self" / "Pillars.md"
    voice = vault / "00. Self" / "Voice.md"
    strategy_path = vault / "00. Self" / "Growth Strategy.md"
    with vault_lock(vault):
        profile_text = profile.read_text(encoding="utf-8")
        profile_text = _replace_section(profile_text, "## 一句话定位", positioning)
        profile_text = _replace_section(profile_text, "## 目标受众", audience)
        profile_text = _replace_section(profile_text, "## 当前阶段", f"- {stage}")
        profile_text = _replace_section(profile_text, "## 目标与约束", goals.strip() or "未设置")

        pillars_text = pillars_path.read_text(encoding="utf-8")
        numbered_pillars = "\n".join(
            f"{index}. {pillar}" for index, pillar in enumerate(pillars, start=1)
        )
        pillars_text = re.sub(
            r"^最多填写四个内容柱。\n\n.*?(?=^## 明确禁区\s*$)",
            f"最多填写四个内容柱。\n\n{numbered_pillars}\n\n",
            pillars_text,
            count=1,
            flags=re.MULTILINE | re.DOTALL,
        )
        pillars_text = _replace_section(pillars_text, "## 明确禁区", boundaries)

        voice_text = voice.read_text(encoding="utf-8")
        voice_text = _replace_section(
            voice_text, "## 真实优秀样本", "\n".join(f"- {sample}" for sample in voice_samples)
        )
        atomic_write_text(profile, profile_text)
        atomic_write_text(pillars_path, pillars_text)
        atomic_write_text(voice, voice_text)
        if strategy is not None:
            strategy_text = strategy_path.read_text(encoding="utf-8")
            allocation = strategy["lane_allocation"]
            strategy_text = _replace_section(
                strategy_text,
                "## 当前策略",
                "\n".join(
                    (
                        f"- 阶段：{strategy['stage']}",
                        f"- 本周唯一目标：{strategy['objective']}",
                        f"- 目标读者：{strategy['target_reader']}",
                        f"- 主页承接：{strategy['profile_promise']}",
                        f"- CTA：{strategy['cta']}",
                        f"- 本周聚焦：{strategy['weekly_focus']}",
                    )
                ),
            )
            strategy_text = _replace_section(
                strategy_text,
                "## 行动配比",
                "\n".join(
                    (
                        f"- Discovery（Quote / Reply）：{allocation['discovery']}",
                        f"- Authority（原创 Thread / 系列）：{allocation['authority']}",
                        f"- Conversion（案例 / CTA）：{allocation['conversion']}",
                    )
                ),
            )
            atomic_write_text(strategy_path, strategy_text)
            update_frontmatter(
                strategy_path,
                {
                    "growth_stage": strategy["stage"],
                    "growth_objective": strategy["objective"],
                    "growth_target_reader": strategy["target_reader"],
                    "profile_promise": strategy["profile_promise"],
                    "primary_cta": strategy["cta"],
                    "weekly_focus": strategy["weekly_focus"],
                    "lane_allocation": allocation,
                },
            )
    readiness = self_readiness(vault)
    return {
        "schema_version": 1,
        "ok": True,
        "command": "configure-self",
        "vault": str(vault),
        "paths": [str(profile), str(pillars_path), str(voice)]
        + ([str(strategy_path)] if strategy is not None else []),
        "ready": readiness["ready"],
        "missing": readiness["missing"],
        "growth_ready": readiness["growth_ready"],
        "growth_missing": readiness["growth_missing"],
    }
