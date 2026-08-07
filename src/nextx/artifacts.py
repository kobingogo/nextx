"""Artifact handoff and human-controlled publication lifecycle."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from .records import read_frontmatter, update_frontmatter
from .self_model import ensure_self_templates
from .vault import atomic_write_text, init_vault, vault_lock


X_POST_URL = re.compile(
    r"^https://(?:www\.)?(?:x\.com|twitter\.com)/[^/]+/status/\d+(?:[/?#].*)?$",
    re.IGNORECASE,
)


def _utc_now(now: datetime | None) -> datetime:
    value = now or datetime.now(timezone.utc)
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _required_string(payload: dict[str, object], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Artifact field {field!r} must be a non-empty string")
    return value.strip()


def _record_path(vault: Path, folder: str, prefix: str, record_id: str) -> Path:
    expected = f"{prefix}:"
    if not record_id.startswith(expected) or not record_id[len(expected) :]:
        raise ValueError(f"Invalid {prefix} ID: {record_id}")
    path = vault / folder / f"{prefix}-{record_id[len(expected):]}.md"
    if not path.exists():
        raise FileNotFoundError(f"{prefix.title()} not found: {record_id}")
    return path


def _decision(vault: Path, decision_id: str) -> tuple[Path, dict[str, object], str]:
    path = _record_path(vault, "02. Decision", "decision", decision_id)
    properties, body = read_frontmatter(path)
    return path, properties, body


def _artifact(vault: Path, artifact_id: str) -> tuple[Path, dict[str, object], str]:
    path = _record_path(vault, "03. Artifact", "artifact", artifact_id)
    properties, body = read_frontmatter(path)
    return path, properties, body


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def artifact_brief(vault: Path, decision_id: str) -> dict[str, object]:
    vault = vault.expanduser().resolve()
    ensure_self_templates(vault)
    path, properties, body = _decision(vault, decision_id)
    if properties.get("verdict") != "do":
        raise ValueError("Only a do Decision can create an Artifact Brief")
    self_paths = [
        vault / "00. Self" / name
        for name in ("Profile.md", "Voice.md", "Pillars.md", "Playbook.md")
    ]
    path_list = "\n".join(f"- {self_path}" for self_path in self_paths)
    brief = f"""使用现有 x-tweet-writer 根据下面的 do Decision 生成草稿。

按需读取这些 Self 文件：
{path_list}

遵守 Decision 的角度、证据、风险和 recommended_format。输出三温度版本并完成 x-tweet-writer 自带 validation。不要发布到 X。

最终交给 NextX 的 Artifact JSON 必须包含 schema_version=1、account_key=primary、decision_id、format、draft；draft 只保存用户选择的定稿版本。

## Selected Decision

{body}
"""
    return {
        "schema_version": 1,
        "ok": True,
        "command": "artifact-brief",
        "decision_path": str(path),
        "brief": brief,
    }


def save_artifact(
    vault: Path,
    payload: object,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("Artifact payload must be an object")
    if payload.get("schema_version") != 1 or payload.get("account_key") != "primary":
        raise ValueError("Artifact requires schema_version=1 and account_key='primary'")
    decision_id = _required_string(payload, "decision_id")
    artifact_format = _required_string(payload, "format")
    draft = _required_string(payload, "draft")
    vault = vault.expanduser().resolve()
    _, decision_properties, _ = _decision(vault, decision_id)
    if decision_properties.get("verdict") != "do":
        raise ValueError("Only a do Decision can create an Artifact")
    signal_ids = decision_properties.get("signal_ids", [])
    if not isinstance(signal_ids, list):
        raise ValueError("Decision signal_ids are invalid")
    timestamp = _utc_now(now)
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()[:8]
    slug = f"{timestamp.strftime('%Y%m%dT%H%M%S')}-{digest}"
    artifact_id = f"artifact:{slug}"
    path = vault / "03. Artifact" / f"artifact-{slug}.md"
    properties = [
        "---",
        "schema_version: 1",
        'account_key: "primary"',
        f"id: {_json(artifact_id)}",
        'type: "artifact"',
        f"decision_id: {_json(decision_id)}",
        f"signal_ids: {_json(signal_ids)}",
        'status: "draft"',
        f"format: {_json(artifact_format)}",
        f"created_at: {_json(timestamp.isoformat())}",
        "published_url: null",
        "published_at: null",
        "---",
    ]
    body = f"""
# Artifact · Draft

## 定稿

{draft}

## 发布检查

- [ ] 事实与链接已核验
- [ ] 声纹和禁区已检查
- [ ] 用户已确认发布

## Outcome

<!-- nextx-outcomes:start -->
尚未发布。
<!-- nextx-outcomes:end -->
"""
    init_vault(vault)
    with vault_lock(vault):
        if path.exists():
            raise FileExistsError(f"Artifact already exists: {path}")
        atomic_write_text(path, "\n".join(properties) + body)
    return {
        "schema_version": 1,
        "ok": True,
        "command": "save-artifact",
        "id": artifact_id,
        "path": str(path),
        "status": "draft",
        "decision_id": decision_id,
    }


def record_published(
    vault: Path,
    artifact_id: str,
    url: str,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    if not X_POST_URL.match(url):
        raise ValueError("Published URL must be an X/Twitter status URL")
    vault = vault.expanduser().resolve()
    path, _, _ = _artifact(vault, artifact_id)
    timestamp = _utc_now(now)
    with vault_lock(vault):
        update_frontmatter(
            path,
            {
                "status": "published",
                "published_url": url,
                "published_at": timestamp.isoformat(),
            },
        )
    return {
        "schema_version": 1,
        "ok": True,
        "command": "record-published",
        "id": artifact_id,
        "path": str(path),
        "status": "published",
        "published_url": url,
    }
