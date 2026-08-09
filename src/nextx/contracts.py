"""Locate the versioned JSON contracts shipped with the NextX source tree."""

from __future__ import annotations

from pathlib import Path


CONTRACT_FILES = {
    "self": "self-input.v1.json",
    "collector": "collector-envelope.v1.json",
    "analysis": "analysis-input.v1.json",
    "decision": "decision-input.v1.json",
    "artifact": "artifact-input.v1.json",
    "outcome": "outcome-input.v1.json",
}
PROMPT_FILES = {
    "grok": "grok-collector.md",
    "quote": "quote-collector.md",
    "reply": "reply-collector.md",
}


def contracts_root() -> Path:
    return Path(__file__).resolve().parents[2] / "schemas"


def contract_catalog(name: str | None = None) -> dict[str, object]:
    """Return stable absolute paths so Agents need not infer repository layout."""
    names = (name,) if name else tuple(CONTRACT_FILES)
    unknown = [value for value in names if value not in CONTRACT_FILES]
    if unknown:
        raise ValueError(f"Unknown contract: {unknown[0]}")
    root = contracts_root()
    contracts = [
        {
            "name": value,
            "version": 1,
            "path": str(root / CONTRACT_FILES[value]),
            "available": (root / CONTRACT_FILES[value]).is_file(),
        }
        for value in names
    ]
    return {
        "ok": all(item["available"] for item in contracts),
        "command": "contracts",
        "contracts": contracts,
    }


def collector_prompt(source: str) -> dict[str, object]:
    """Locate a bundled Collector instruction without assuming a checkout CWD."""
    if source not in PROMPT_FILES:
        raise ValueError(f"Unknown collector prompt: {source}")
    path = contracts_root().parent / "prompts" / PROMPT_FILES[source]
    return {
        "ok": path.is_file(),
        "command": "collector-prompt",
        "source": source,
        "path": str(path),
        "available": path.is_file(),
    }
