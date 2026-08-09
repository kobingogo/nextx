#!/usr/bin/env python3
"""Dependency-free semantic checks for the canonical NextX Agent Skill."""

from __future__ import annotations

import json
from pathlib import Path
import re
import stat
import sys


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "nextx"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def frontmatter(text: str) -> dict[str, str]:
    match = re.match(r"^---\n(?P<body>.*?)\n---\n", text, re.DOTALL)
    require(match is not None, "SKILL.md must start with YAML frontmatter")
    values: dict[str, str] = {}
    for line in match.group("body").splitlines():
        key, separator, value = line.partition(":")
        require(bool(separator) and key and value.strip(), "SKILL.md frontmatter is malformed")
        values[key.strip()] = value.strip().strip('"')
    return values


def validate() -> None:
    skill_md = SKILL / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8")
    metadata = frontmatter(text)
    require(set(metadata) == {"name", "description"}, "SKILL.md frontmatter must contain only name and description")
    require(metadata["name"] == "nextx", "SKILL name must be nextx")
    require(0 < len(metadata["description"]) <= 1024, "SKILL description is missing or too long")
    require(len(text.splitlines()) <= 500, "SKILL.md must stay below 500 lines")
    require("<skill-dir>/scripts/install-nextx --json" in text, "Skill must use its portable installer")
    require("python3 skills/nextx/scripts/bootstrap.py" not in text, "Skill must not hard-code a source-only bootstrap path")
    require("./install-nextx" not in text, "Skill must not assume its current working directory")
    require("schemas/" not in text and "prompts/" not in text, "Skill must obtain runtime resources through the CLI")
    require("preflight" in text and "contracts --name" in text, "Skill must gate workflows and reference contracts")
    require("next-step" in text and "configure-self" in text, "Skill must support conversational onboarding")
    for expected in ("growth-loop", "reply-sprint", "reply-brief", "growth_contract", "thread_pack", "1h/24h/7d"):
        require(expected in text, f"Skill is missing Growth Loop behavior: {expected}")
    triage_route = ("triage-brief", "save-triage", "signal-inbox")
    for expected in triage_route:
        require(expected in text, f"Skill is missing Signal triage behavior: {expected}")
    require("agent_skills" in text and "force-agent-skills" in text, "Skill must handle cross-Agent installation safely")
    require("初始化 NextX" in text, "Skill must expose the one-sentence initialization trigger")
    contract_reference = SKILL / "references" / "contracts.md"
    require(contract_reference.is_file(), "Skill contract reference is missing")
    reference_text = contract_reference.read_text(encoding="utf-8")
    for expected in triage_route:
        require(expected in reference_text, f"Skill contract reference is missing Signal triage behavior: {expected}")

    for relative in ("scripts/install-nextx", "scripts/bootstrap.py", "scripts/install-nextx.cmd"):
        path = SKILL / relative
        require(path.is_file(), f"Skill support file is missing: {relative}")
    if sys.platform != "win32":
        mode = (SKILL / "scripts" / "install-nextx").stat().st_mode
        require(bool(mode & stat.S_IXUSR), "POSIX Skill installer must be executable")

    installer = (SKILL / "scripts" / "bootstrap.py").read_text(encoding="utf-8")
    for expected in ("--agents", "_install_agent_skills", "AGENTS =", "force-agent-skills"):
        require(expected in installer, f"Installer is missing cross-Agent behavior: {expected}")

    agent_config = (SKILL / "agents" / "openai.yaml").read_text(encoding="utf-8")
    for expected in ("display_name:", "short_description:", "default_prompt:"):
        require(expected in agent_config, f"Agent metadata is missing {expected}")
    require(
        re.search(r"^interface:\n(?:  .*\n)*  default_prompt:", agent_config, re.MULTILINE)
        is not None,
        "default_prompt must be nested under interface",
    )
    require("do not install or initialize unless I ask" in agent_config, "Default prompt must not cause an implicit write")

    for filename in (
        "self-input.v1.json",
        "collector-envelope.v1.json",
        "triage-input.v1.json",
        "analysis-input.v1.json",
        "decision-input.v1.json",
        "artifact-input.v1.json",
        "outcome-input.v1.json",
    ):
        value = json.loads((ROOT / "schemas" / filename).read_text(encoding="utf-8"))
        require(value.get("$schema", "").endswith("schema"), f"Schema declaration is invalid: {filename}")
        require(value.get("properties", {}).get("schema_version", {}).get("const") == 1, f"Schema version is invalid: {filename}")

    decision_schema = json.loads((ROOT / "schemas" / "decision-input.v1.json").read_text(encoding="utf-8"))
    modes = decision_schema.get("properties", {}).get("execution_mode", {}).get("enum", [])
    require(set(modes) == {"original", "quote", "reply"}, "Decision schema must expose all Growth Loop modes")
    require("growth_contract" in decision_schema.get("properties", {}), "Decision schema lacks growth_contract")
    artifact_schema = json.loads((ROOT / "schemas" / "artifact-input.v1.json").read_text(encoding="utf-8"))
    require("thread_pack" in artifact_schema.get("properties", {}), "Artifact schema lacks Thread Pack")
    outcome_schema = json.loads((ROOT / "schemas" / "outcome-input.v1.json").read_text(encoding="utf-8"))
    windows = outcome_schema.get("properties", {}).get("window", {}).get("enum", [])
    require(set(windows) == {"1h", "24h", "7d"}, "Outcome schema must include 1h/24h/7d")


if __name__ == "__main__":
    try:
        validate()
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"NextX Skill validation failed: {error}", file=sys.stderr)
        raise SystemExit(1)
    print("NextX Skill semantics are valid.")
