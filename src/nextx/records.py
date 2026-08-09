"""Small record helpers for NextX's JSON-compatible Markdown frontmatter."""

from __future__ import annotations

import json
from pathlib import Path

from .vault import atomic_write_text


def _frontmatter_bounds(lines: list[str], path: Path) -> tuple[int, int]:
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"Missing frontmatter in {path}")
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return 0, index
    raise ValueError(f"Unclosed frontmatter in {path}")


def _parse_value(raw: str) -> object:
    value = raw.strip()
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def read_frontmatter(path: Path) -> tuple[dict[str, object], str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    _, closing = _frontmatter_bounds(lines, path)
    properties: dict[str, object] = {}
    for line in lines[1:closing]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        properties[key.strip()] = _parse_value(value)
    return properties, "".join(lines[closing + 1 :])


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def update_frontmatter(path: Path, changes: dict[str, object], *, body: str | None = None) -> None:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    _, closing = _frontmatter_bounds(lines, path)
    remaining = dict(changes)
    for index in range(1, closing):
        if ":" not in lines[index]:
            continue
        key = lines[index].split(":", 1)[0].strip()
        if key in remaining:
            lines[index] = f"{key}: {_json(remaining.pop(key))}\n"
    additions = [f"{key}: {_json(value)}\n" for key, value in remaining.items()]
    frontmatter = lines[:closing] + additions + [lines[closing]]
    rendered = "".join(frontmatter) + (
        body if body is not None else "".join(lines[closing + 1 :])
    )
    atomic_write_text(path, rendered)


def append_markdown(path: Path, markdown: str) -> None:
    current = path.read_text(encoding="utf-8").rstrip("\n")
    addition = markdown.strip("\n")
    atomic_write_text(path, f"{current}\n\n{addition}\n")
