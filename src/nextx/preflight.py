"""Read-only capability checks before an Agent starts a NextX workflow."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys
from typing import Iterable

from .bookmarks import read_bookmark_health
from .self_model import self_readiness


CapabilityRequirement = str | tuple[str, ...]


INTENT_REQUIREMENTS: dict[str, tuple[CapabilityRequirement, ...]] = {
    "setup": (),
    "collect-grok": ("grok-build",),
    # Grok Build is the preferred discovery surface.  An already-authorized
    # agent-reach/twitter-cli path is a valid read-only fallback, so Quote
    # collection needs one of these capabilities rather than all three.
    "collect-quote": (("grok-build", "agent-reach", "twitter-cli"),),
    "collect-reply": (("grok-build", "agent-reach", "twitter-cli"),),
    "collect-bookmarks": (),
    # NextX ships a conversation-first core workflow.  A user's installed AYI
    # Skills remain preferred enhancements, but their absence must not make a
    # fresh open-source installation incapable of making a decision or draft.
    "decision": (("topic-engine", "nextx-core"),),
    "draft": (("x-tweet-writer", "nextx-core"),),
    "daily": (("topic-engine", "nextx-core"), ("x-tweet-writer", "nextx-core")),
}
SELF_REQUIRED_INTENTS = {"decision", "draft", "daily"}


def _vault_status(vault: Path) -> str:
    if not vault.is_dir():
        return "missing"
    return "ready" if os.access(vault, os.W_OK) else "not_writable"


def _skill_path(capability: str, roots: Iterable[Path]) -> Path | None:
    if capability == "nextx-core":
        bundled = Path(__file__).resolve().parents[2] / "skills" / "nextx" / "SKILL.md"
        return bundled if bundled.is_file() else None
    for root in roots:
        candidate = root.expanduser().resolve() / capability / "SKILL.md"
        if candidate.is_file():
            return candidate
    return None


def run_preflight(
    vault: Path,
    *,
    intent: str,
    agent_capabilities: Iterable[str] = (),
    skills_roots: Iterable[Path] = (),
) -> dict[str, object]:
    """Return actionable preconditions without creating or modifying any file."""
    if intent not in INTENT_REQUIREMENTS:
        raise ValueError(f"Unknown preflight intent: {intent}")

    resolved_vault = vault.expanduser().resolve()
    capabilities = {value.strip() for value in agent_capabilities if value.strip()}
    roots = list(skills_roots)
    blockers: list[str] = []
    warnings: list[str] = []
    vault_status = _vault_status(resolved_vault)
    if intent != "setup" and vault_status != "ready":
        blockers.append("Vault 尚未就绪；先运行 `nextx setup --yes`")

    self_status = self_readiness(resolved_vault, initialize=False)
    if intent in SELF_REQUIRED_INTENTS and not self_status["ready"]:
        blockers.append("Self 模型未就绪；补齐 `nextx readiness` 列出的字段")

    agents: list[dict[str, object]] = []
    for requirement in INTENT_REQUIREMENTS[intent]:
        alternatives = (requirement,) if isinstance(requirement, str) else requirement
        label = alternatives[0] if len(alternatives) == 1 else " / ".join(alternatives)
        resolved = next(
            (
                (capability, path)
                for capability in alternatives
                if (path := _skill_path(capability, roots)) is not None
            ),
            None,
        )
        declared = next((capability for capability in alternatives if capability in capabilities), None)
        if resolved is not None:
            capability, path = resolved
            status = "ready"
        elif declared is not None:
            capability = declared
            path = None
            status = "declared"
            warnings.append(
                f"Agent 能力 {capability} 仅由调用方声明；传入 --skills-root 可验证本地 Skill 路径"
            )
        else:
            capability = None
            path = None
            status = "missing"
            if len(alternatives) == 1:
                blockers.append(f"缺少 Agent 能力：{label}")
            else:
                blockers.append(f"缺少 Agent 能力（任选其一）：{label}")
        agents.append(
            {
                "capability": label,
                "alternatives": list(alternatives) if len(alternatives) > 1 else None,
                "selected_capability": capability,
                "required": True,
                "status": status,
                "skill_path": str(path) if path is not None else None,
            }
        )

    twitter_binary = "ready" if shutil.which("twitter") else "missing"
    if intent == "collect-bookmarks" and twitter_binary != "ready":
        blockers.append("缺少 twitter-cli；安装并登录后再同步收藏")
    if intent == "collect-bookmarks":
        health = read_bookmark_health(resolved_vault)
        if health.get("status") == "failed":
            warnings.append("上次收藏同步失败；运行 `nextx doctor` 查看原因")
    else:
        health = {"schema_version": 1, "status": "not_checked"}

    return {
        "ok": not blockers,
        "command": "preflight",
        "intent": intent,
        "read_only": True,
        "vault": str(resolved_vault),
        "checks": {
            "python": "ready" if sys.version_info >= (3, 11) else "unsupported",
            "vault": vault_status,
            "self": self_status,
            "agents": agents,
            "twitter_binary": twitter_binary,
            "bookmark_sync": health,
        },
        "blockers": blockers,
        "warnings": warnings,
    }
