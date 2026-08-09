"""Artifact handoff and human-controlled publication lifecycle."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import secrets

from .briefs import untrusted_data_block
from .records import read_frontmatter, update_frontmatter
from .signals import signal_path
from .vault import atomic_write_text, init_vault, vault_lock


X_POST_URL = re.compile(
    r"^https://(?:www\.)?(?:x\.com|twitter\.com)/[^/]+/status/\d+(?:[/?#].*)?$",
    re.IGNORECASE,
)
ARTIFACT_STATUSES = {"draft", "review_ready", "publish_confirmed", "published", "measured"}
THREAD_FORMATS = {"thread", "thread-post"}
ARTIFACT_FORMATS = {"single-post", "thread", "thread-post", "quote-post", "reply-post"}
ASSET_ROLES = {"cover", "supporting", "diagram"}
PUBLISH_CHECKLIST = (
    "- [x] 事实与链接已核验",
    "- [x] 声纹和禁区已检查",
    "- [x] 用户已确认发布",
)
CHECKLIST_MARKER = re.compile(r"^[0-9a-f]{32}$")


def _utc_now(now: datetime | None) -> datetime:
    value = now or datetime.now(timezone.utc)
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _required_string(payload: dict[str, object], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Artifact field {field!r} must be a non-empty string")
    return value.strip()


def _optional_string(payload: dict[str, object], field: str, *, limit: int) -> str | None:
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise ValueError(f"Artifact field {field!r} must be a non-empty string under {limit} characters")
    return value.strip()


def _thread_pack(payload: dict[str, object], artifact_format: str) -> dict[str, object] | None:
    value = payload.get("thread_pack")
    if artifact_format not in THREAD_FORMATS:
        if value is not None:
            raise ValueError("thread_pack is only allowed when format is thread or thread-post")
        return None
    if not isinstance(value, dict):
        raise ValueError("A Thread Artifact requires a thread_pack object")
    posts = value.get("posts")
    if not isinstance(posts, list) or not 2 <= len(posts) <= 25:
        raise ValueError("thread_pack.posts must contain 2 to 25 posts")
    normalized_posts: list[str] = []
    for index, post in enumerate(posts, start=1):
        if not isinstance(post, str) or not post.strip() or len(post.strip()) > 25_000:
            raise ValueError(f"thread_pack.posts[{index}] must be a non-empty string under 25000 characters")
        normalized_posts.append(post.strip())
    cta = _required_string(value, "cta")
    if len(cta) > 600:
        raise ValueError("thread_pack.cta must be at most 600 characters")
    return {"posts": normalized_posts, "cta": cta}


def _asset_manifest(payload: dict[str, object]) -> list[dict[str, str]]:
    value = payload.get("asset_manifest", [])
    if not isinstance(value, list) or len(value) > 6:
        raise ValueError("asset_manifest must be a list with at most 6 items")
    assets: list[dict[str, str]] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"asset_manifest[{index}] must be an object")
        role = item.get("role")
        if role not in ASSET_ROLES:
            raise ValueError("asset_manifest role must be cover, supporting, or diagram")
        asset: dict[str, str] = {"role": role}
        for field, limit in (("purpose", 600), ("prompt", 4_000), ("alt_text", 1_000)):
            text = _required_string(item, field)
            if len(text) > limit:
                raise ValueError(f"asset_manifest.{field} must be at most {limit} characters")
            asset[field] = text
        local_path = item.get("local_path")
        if local_path is not None:
            if not isinstance(local_path, str) or not local_path.strip() or len(local_path.strip()) > 2_048:
                raise ValueError("asset_manifest.local_path must be a non-empty string under 2048 characters")
            asset["local_path"] = local_path.strip()
        assets.append(asset)
    return assets


def _follow_up_tasks(payload: dict[str, object], execution_mode: str) -> list[str]:
    value = payload.get("follow_up_tasks")
    if value is None:
        first_hour = "发布后 60 分钟内：回复与目标读者有关、能推进讨论的互动。"
        if execution_mode in {"quote", "reply"}:
            first_hour = "发布后 60 分钟内：观察原作者与相邻读者的互动；只在有新增价值时继续回应。"
        return [
            first_hour,
            "24 小时：记录可获得指标、非粉丝反馈与是否完成互动。",
            "7 天：与同目标、同执行模式的样本比较后选择 repeat / alter / stop。",
        ]
    if not isinstance(value, list) or not 2 <= len(value) <= 6:
        raise ValueError("follow_up_tasks must contain 2 to 6 items")
    tasks: list[str] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, str) or not item.strip() or len(item.strip()) > 600:
            raise ValueError(f"follow_up_tasks[{index}] must be a non-empty string under 600 characters")
        tasks.append(item.strip())
    return tasks


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


def _quote_source(
    vault: Path, decision_properties: dict[str, object]
) -> tuple[str, dict[str, object], str]:
    """Resolve the exact persisted original for a quote Artifact.

    The Artifact receives this information from the Decision's linked Signal,
    rather than accepting an Agent-provided URL.  This keeps the quoted post
    auditable and stops a draft from being quietly retargeted.
    """
    signal_ids = decision_properties.get("signal_ids")
    if not isinstance(signal_ids, list) or len(signal_ids) != 1 or not isinstance(
        signal_ids[0], str
    ):
        raise ValueError("A quote Artifact requires exactly one linked Signal")
    signal_id = signal_ids[0]
    try:
        path = signal_path(vault, signal_id)
    except FileNotFoundError as error:
        raise FileNotFoundError(f"Quote Signal not found: {signal_id}") from error
    properties, body = read_frontmatter(path)
    source_url = properties.get("source_url")
    author = properties.get("author_handle")
    if properties.get("quote_candidate") is not True or not isinstance(source_url, str) or not isinstance(
        author, str
    ):
        raise ValueError("The linked Signal is not a valid persisted Quote candidate")
    if (
        decision_properties.get("quote_source_url") != source_url
        or decision_properties.get("quote_author_handle") != author
    ):
        raise ValueError("The linked Quote Signal no longer matches the persisted Decision source")
    return signal_id, properties, body


def _quote_window_open(decision_properties: dict[str, object], now: datetime) -> str:
    value = decision_properties.get("quote_window_ends_at")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("A quote Decision is missing its decision window")
    try:
        deadline = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("A quote Decision has an invalid decision window") from error
    if deadline.tzinfo is None:
        raise ValueError("A quote Decision has an invalid decision window")
    if deadline.astimezone(timezone.utc) <= now:
        raise ValueError("The Quote decision window has expired; create a fresh Decision before drafting")
    return value


def _reply_source(
    vault: Path, decision_properties: dict[str, object]
) -> tuple[str, dict[str, object], str]:
    signal_ids = decision_properties.get("signal_ids")
    if not isinstance(signal_ids, list) or len(signal_ids) != 1 or not isinstance(
        signal_ids[0], str
    ):
        raise ValueError("A reply Artifact requires exactly one linked Signal")
    signal_id = signal_ids[0]
    try:
        path = signal_path(vault, signal_id)
    except FileNotFoundError as error:
        raise FileNotFoundError(f"Reply Signal not found: {signal_id}") from error
    properties, body = read_frontmatter(path)
    source_url = properties.get("source_url")
    author = properties.get("author_handle")
    if properties.get("reply_candidate") is not True or not isinstance(source_url, str) or not isinstance(
        author, str
    ):
        raise ValueError("The linked Signal is not a valid persisted Reply candidate")
    if (
        decision_properties.get("reply_source_url") != source_url
        or decision_properties.get("reply_author_handle") != author
    ):
        raise ValueError("The linked Reply Signal no longer matches the persisted Decision source")
    return signal_id, properties, body


def _reply_window_open(decision_properties: dict[str, object], now: datetime) -> str:
    value = decision_properties.get("reply_window_ends_at")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("A reply Decision is missing its decision window")
    try:
        deadline = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("A reply Decision has an invalid decision window") from error
    if deadline.tzinfo is None:
        raise ValueError("A reply Decision has an invalid decision window")
    if deadline.astimezone(timezone.utc) <= now:
        raise ValueError("The Reply decision window has expired; create a fresh Decision before drafting")
    return value


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _fingerprint(payload: dict[str, object]) -> str:
    """Stable retry key; the raw Agent input never needs to be stored twice."""
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _existing_artifact(
    vault: Path, fingerprint: str
) -> tuple[str, Path, dict[str, object]] | None:
    for path in (vault / "03. Artifact").glob("artifact-*.md"):
        properties, _ = read_frontmatter(path)
        if properties.get("input_fingerprint") == fingerprint:
            artifact_id = properties.get("id")
            if isinstance(artifact_id, str):
                return artifact_id, path, properties
    return None


def _new_artifact_path(vault: Path, timestamp: datetime, digest: str) -> tuple[str, Path]:
    stem = f"{timestamp.strftime('%Y%m%dT%H%M%S%f')}-{digest}"
    attempt = 0
    while True:
        slug = stem if attempt == 0 else f"{stem}-{attempt}"
        path = vault / "03. Artifact" / f"artifact-{slug}.md"
        if not path.exists():
            return slug, path
        attempt += 1


def _checklist_tokens(marker: str) -> tuple[str, str]:
    return (
        f"<!-- nextx-publish-checklist:{marker}:start -->",
        f"<!-- nextx-publish-checklist:{marker}:end -->",
    )


def _checklist_section(properties: dict[str, object], body: str) -> str:
    """Read only the machine-delimited checklist, never matching draft text."""
    marker = properties.get("publish_checklist_marker")
    if isinstance(marker, str) and CHECKLIST_MARKER.fullmatch(marker):
        start_token, end_token = _checklist_tokens(marker)
        start = body.find(start_token)
        end = body.find(end_token, start + len(start_token)) if start >= 0 else -1
        if end >= 0:
            return body[start + len(start_token) : end]
        raise ValueError("Artifact publish checklist machine section is unclosed")

    # Artifacts created before the marker was introduced retain a safe fallback:
    # the final checklist heading belongs to the template, after the draft body.
    headings = list(re.finditer(r"^## 发布检查\s*$", body, re.MULTILINE))
    if not headings:
        raise ValueError("Artifact is missing its publish checklist section")
    start = headings[-1].end()
    next_heading = re.search(r"^##\s", body[start:], re.MULTILINE)
    return body[start : start + next_heading.start() if next_heading else len(body)]


def artifact_brief(
    vault: Path, decision_id: str, *, now: datetime | None = None
) -> dict[str, object]:
    vault = vault.expanduser().resolve()
    path, properties, body = _decision(vault, decision_id)
    if properties.get("verdict") != "do":
        raise ValueError("Only a do Decision can create an Artifact Brief")
    execution_mode = properties.get("execution_mode", "original")
    if execution_mode not in {"original", "quote", "reply"}:
        raise ValueError("Decision has an invalid execution_mode")
    self_paths = [
        vault / "00. Self" / name
        for name in ("Profile.md", "Voice.md", "Pillars.md", "Growth Strategy.md", "Playbook.md")
    ]
    path_list = "\n".join(f"- {self_path}" for self_path in self_paths)
    quote_instructions = ""
    quote_source = ""
    if execution_mode == "quote":
        signal_id, signal_properties, signal_body = _quote_source(vault, properties)
        quote_deadline = _quote_window_open(properties, _utc_now(now))
        quote_instructions = f"""
这是 Quote Sprint 的 do Decision。必须调用 x-tweet-writer 的 QT 模式；最终 format 必须为 quote-post。原帖将在用户手动发布时作为 X 的 Quote 对象选择，不要把原帖全文复述成普通单帖。

质量闸门：首句必须提供独立增量；必须尊重原帖事实边界；不使用空泛认同、奉承或只替换措辞的复述；若不能增加价值，应回到 Decision 改为 defer/kill。引用目标固定为 @{signal_properties['author_handle']} 的 {signal_id}，不得换帖或编造原帖上下文。决策窗口截止：{quote_deadline}。
"""
        quote_source = "\n" + untrusted_data_block("Quoted Signal", signal_body)
    elif execution_mode == "reply":
        signal_id, signal_properties, signal_body = _reply_source(vault, properties)
        reply_deadline = _reply_window_open(properties, _utc_now(now))
        quote_instructions = f"""
这是 Reply Sprint 的 do Decision。最终 format 必须为 reply-post，用户应在 X 手动回复 @{signal_properties['author_handle']} 的指定原帖；不要把它伪装成独立主帖，也不要用模板化寒暄。

质量闸门：第一句必须推进原讨论或提供可验证补充；尊重原帖事实边界；不因关系目标而夸大认识或承诺效果。回复目标固定为 {signal_id}，不得换帖或编造上下文。决策窗口截止：{reply_deadline}。
"""
        quote_source = "\n" + untrusted_data_block("Reply Signal", signal_body)
    brief = f"""使用现有 x-tweet-writer 根据下面的 do Decision 生成草稿。

按需读取这些 Self 文件：
{path_list}

遵守 Decision 的角度、证据、风险和 recommended_format。输出三温度版本并完成 x-tweet-writer 自带 validation。不要发布到 X。
{quote_instructions}

最终交给 NextX 的 Artifact JSON 必须包含 schema_version=1、account_key=primary、decision_id、format、draft；draft 只保存用户选择的定稿版本。若 format 是 thread 或 thread-post，必须额外提供 thread_pack（2–25 条 posts 和 CTA）。asset_manifest 是配图执行清单：只写真实需要制作/核验的资产，不虚构已经生成的图片；每项都要有 role、purpose、prompt 和 alt_text。

{untrusted_data_block("Decision", body)}
{quote_source}
"""
    return {
        "schema_version": 1,
        "ok": True,
        "command": "artifact-brief",
        "execution_mode": execution_mode,
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
    if artifact_format not in ARTIFACT_FORMATS:
        raise ValueError(f"Artifact format must be one of: {', '.join(sorted(ARTIFACT_FORMATS))}")
    draft = _required_string(payload, "draft")
    thread_pack = _thread_pack(payload, artifact_format)
    asset_manifest = _asset_manifest(payload)
    vault = vault.expanduser().resolve()
    _, decision_properties, _ = _decision(vault, decision_id)
    if decision_properties.get("verdict") != "do":
        raise ValueError("Only a do Decision can create an Artifact")
    execution_mode = decision_properties.get("execution_mode", "original")
    if execution_mode not in {"original", "quote", "reply"}:
        raise ValueError("Decision has an invalid execution_mode")
    recommended_format = decision_properties.get("recommended_format")
    if execution_mode == "original" and isinstance(recommended_format, str):
        if artifact_format != recommended_format:
            raise ValueError(
                "Artifact format must match the Decision recommended_format"
            )
    signal_ids = decision_properties.get("signal_ids", [])
    if not isinstance(signal_ids, list):
        raise ValueError("Decision signal_ids are invalid")
    quote_signal_id: str | None = None
    quote_source_url: str | None = None
    quote_author_handle: str | None = None
    quote_window_ends_at: str | None = None
    reply_signal_id: str | None = None
    reply_source_url: str | None = None
    reply_author_handle: str | None = None
    reply_window_ends_at: str | None = None
    if execution_mode == "quote":
        if artifact_format != "quote-post":
            raise ValueError("A quote Decision can only create an Artifact with format='quote-post'")
        quote_signal_id, quote_signal, _ = _quote_source(vault, decision_properties)
        quote_source_url = str(quote_signal["source_url"])
        quote_author_handle = str(quote_signal["author_handle"])
        quote_window_ends_at = _quote_window_open(decision_properties, _utc_now(now))
    elif execution_mode == "reply":
        if artifact_format != "reply-post":
            raise ValueError("A reply Decision can only create an Artifact with format='reply-post'")
        reply_signal_id, reply_signal, _ = _reply_source(vault, decision_properties)
        reply_source_url = str(reply_signal["source_url"])
        reply_author_handle = str(reply_signal["author_handle"])
        reply_window_ends_at = _reply_window_open(decision_properties, _utc_now(now))
    follow_up_tasks = _follow_up_tasks(payload, execution_mode)
    experiment_id = decision_properties.get("experiment_id")
    experiment_hypothesis = decision_properties.get("experiment_hypothesis")
    experiment_metric = decision_properties.get("experiment_metric")
    timestamp = _utc_now(now)
    fingerprint = _fingerprint(payload)
    digest = fingerprint[:8]
    outcome_marker = secrets.token_hex(16)
    checklist_marker = secrets.token_hex(16)
    outcome_start = f"<!-- nextx-outcomes:{outcome_marker}:start -->"
    outcome_end = f"<!-- nextx-outcomes:{outcome_marker}:end -->"
    init_vault(vault)
    with vault_lock(vault):
        existing = _existing_artifact(vault, fingerprint)
        if existing is not None:
            artifact_id, path, existing_properties = existing
            return {
                "schema_version": 1,
                "ok": True,
                "command": "save-artifact",
                "id": artifact_id,
                "path": str(path),
                "status": existing_properties.get("status", "draft"),
                "decision_id": existing_properties.get("decision_id", decision_id),
                "reused": True,
            }
        slug, path = _new_artifact_path(vault, timestamp, digest)
        artifact_id = f"artifact:{slug}"
        properties = [
            "---",
            "schema_version: 1",
            'account_key: "primary"',
            f"id: {_json(artifact_id)}",
            'type: "artifact"',
            f"input_fingerprint: {_json(fingerprint)}",
            f"decision_id: {_json(decision_id)}",
            f"signal_ids: {_json(signal_ids)}",
            f"execution_mode: {_json(execution_mode)}",
            f"quote_signal_id: {_json(quote_signal_id)}",
            f"quote_source_url: {_json(quote_source_url)}",
            f"quote_author_handle: {_json(quote_author_handle)}",
            f"quote_window_ends_at: {_json(quote_window_ends_at)}",
            f"reply_signal_id: {_json(reply_signal_id)}",
            f"reply_source_url: {_json(reply_source_url)}",
            f"reply_author_handle: {_json(reply_author_handle)}",
            f"reply_window_ends_at: {_json(reply_window_ends_at)}",
            f"growth_objective: {_json(decision_properties.get('growth_objective'))}",
            f"growth_target_reader: {_json(decision_properties.get('growth_target_reader'))}",
            f"growth_expected_action: {_json(decision_properties.get('growth_expected_action'))}",
            f"distribution_target: {_json(decision_properties.get('distribution_target'))}",
            f"growth_review_at: {_json(decision_properties.get('growth_review_at'))}",
            f"experiment_id: {_json(experiment_id)}",
            f"experiment_hypothesis: {_json(experiment_hypothesis)}",
            f"experiment_metric: {_json(experiment_metric)}",
            'status: "draft"',
            f"format: {_json(artifact_format)}",
            f"thread_post_count: {_json(len(thread_pack['posts']) if thread_pack else None)}",
            f"thread_cta: {_json(thread_pack['cta'] if thread_pack else None)}",
            f"asset_count: {len(asset_manifest)}",
            f"created_at: {_json(timestamp.isoformat())}",
            f"outcome_marker: {_json(outcome_marker)}",
            f"publish_checklist_marker: {_json(checklist_marker)}",
            "published_url: null",
            "published_at: null",
            "review_ready_at: null",
            "publish_confirmed_at: null",
            "---",
        ]
        quote_section = ""
        if execution_mode == "quote":
            quote_section = f"""
## Quote 原帖

- 原帖：{quote_source_url}
- 作者：@{quote_author_handle}
- 决策窗口：{quote_window_ends_at}
- 原帖证据：[[{signal_path(vault, str(quote_signal_id)).stem}]]
"""
        reply_section = ""
        if execution_mode == "reply":
            reply_section = f"""
## Reply 原帖

- 原帖：{reply_source_url}
- 作者：@{reply_author_handle}
- 决策窗口：{reply_window_ends_at}
- 原帖证据：[[{signal_path(vault, str(reply_signal_id)).stem}]]
"""
        thread_section = ""
        if thread_pack is not None:
            posts = "\n\n".join(
                f"### {index}/{len(thread_pack['posts'])}\n\n{post}"
                for index, post in enumerate(thread_pack["posts"], start=1)
            )
            thread_section = f"""
## Thread Pack

{posts}

### CTA

{thread_pack['cta']}
"""
        asset_rows = "\n".join(
            "\n".join(
                (
                    f"### {index}. {asset['role']}",
                    f"- 用途：{asset['purpose']}",
                    f"- 提示词：{asset['prompt']}",
                    f"- Alt text：{asset['alt_text']}",
                    f"- 本地文件：{asset.get('local_path', '待生成 / 待附加')}",
                )
            )
            for index, asset in enumerate(asset_manifest, start=1)
        ) or "无需配图，或待用户补充真实资产需求。"
        follow_up_rows = "\n".join(f"- [ ] {task}" for task in follow_up_tasks)
        body = f"""
# Artifact · Draft

## 定稿

{draft}
{quote_section}
{reply_section}
{thread_section}

## 资产清单

{asset_rows}

## 发布后行动

{follow_up_rows}

## 发布检查

{_checklist_tokens(checklist_marker)[0]}
- [ ] 事实与链接已核验
- [ ] 声纹和禁区已检查
- [ ] 用户已确认发布
{_checklist_tokens(checklist_marker)[1]}

## Outcome

{outcome_start}
尚未发布。
{outcome_end}
"""
        atomic_write_text(path, "\n".join(properties) + body)
    return {
        "schema_version": 1,
        "ok": True,
        "command": "save-artifact",
        "id": artifact_id,
        "path": str(path),
        "status": "draft",
        "decision_id": decision_id,
        "execution_mode": execution_mode,
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
    timestamp = _utc_now(now)
    with vault_lock(vault):
        path, properties, _ = _artifact(vault, artifact_id)
        if properties.get("status") != "publish_confirmed":
            raise ValueError(
                "Only a publish_confirmed Artifact can record a published URL"
            )
        if not isinstance(properties.get("publish_confirmed_at"), str):
            raise ValueError("Artifact is missing an explicit publish confirmation")
        _ensure_unique_published_url(vault, url, artifact_id)
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


def mark_review_ready(
    vault: Path, artifact_id: str, *, now: datetime | None = None
) -> dict[str, object]:
    """Move a draft to review only after its human checklist is visibly complete."""
    vault = vault.expanduser().resolve()
    timestamp = _utc_now(now)
    with vault_lock(vault):
        path, properties, body = _artifact(vault, artifact_id)
        if properties.get("status") != "draft":
            raise ValueError("Only a draft Artifact can be marked review_ready")
        checklist = _checklist_section(properties, body)
        checked = {line.strip() for line in checklist.splitlines()}
        missing = [item for item in PUBLISH_CHECKLIST if item not in checked]
        if missing:
            raise ValueError("Complete all three publish checklist items before review")
        update_frontmatter(
            path,
            {"status": "review_ready", "review_ready_at": timestamp.isoformat()},
        )
    return {
        "schema_version": 1,
        "ok": True,
        "command": "mark-review-ready",
        "id": artifact_id,
        "path": str(path),
        "status": "review_ready",
    }


def confirm_publish(
    vault: Path,
    artifact_id: str,
    *,
    confirmed: bool,
    now: datetime | None = None,
) -> dict[str, object]:
    """Record the explicit human confirmation required before URL write-back."""
    if not confirmed:
        raise ValueError("Pass --yes only after the user explicitly confirms publication")
    vault = vault.expanduser().resolve()
    timestamp = _utc_now(now)
    with vault_lock(vault):
        path, properties, _ = _artifact(vault, artifact_id)
        if properties.get("status") != "review_ready":
            raise ValueError("Only a review_ready Artifact can be publish_confirmed")
        update_frontmatter(
            path,
            {
                "status": "publish_confirmed",
                "publish_confirmed_at": timestamp.isoformat(),
            },
        )
    return {
        "schema_version": 1,
        "ok": True,
        "command": "confirm-publish",
        "id": artifact_id,
        "path": str(path),
        "status": "publish_confirmed",
    }


def _ensure_unique_published_url(vault: Path, url: str, artifact_id: str) -> None:
    for candidate in (vault / "03. Artifact").glob("artifact-*.md"):
        properties, _ = read_frontmatter(candidate)
        if properties.get("id") != artifact_id and properties.get("published_url") == url:
            raise ValueError("Published URL is already linked to another Artifact")
