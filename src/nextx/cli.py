"""Command-line interface for NextX."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import re
import shutil
import sys
from typing import Sequence

from . import __version__
from .bookmarks import (
    parse_payload,
    read_bookmark_health,
    sync_bookmarks,
    write_bookmark_health,
)
from .accounts import account_status
from .analysis import build_analysis_brief, save_analysis
from .artifacts import (
    artifact_brief,
    confirm_publish,
    mark_review_ready,
    record_published,
    save_artifact,
)
from .config import config_snapshot, resolve_vault, setup_vault
from .contracts import CONTRACT_FILES, PROMPT_FILES, collector_prompt, contract_catalog
from .decisions import decision_brief, save_decision
from .learning import record_outcome, render_weekly_review
from .preflight import INTENT_REQUIREMENTS, run_preflight
from .self_model import configure_self, ensure_self_templates, growth_strategy, self_readiness
from .signals import add_manual_signal, ingest_signals, migrate_signal_filenames
from .twitter_cli import TwitterCLIError, fetch_bookmarks
from .vault import atomic_write_text, init_vault, read_state, recover_vault_lock, vault_lock
from .views import (
    render_decision_board,
    render_growth_loop,
    render_quote_sprint,
    render_reply_sprint,
    render_today,
)


MAX_INPUT_JSON_BYTES = 5 * 1024 * 1024
EXPECTED_COLLECTORS = {"grok": "grok-build", "twitter": "twitter-cli"}


class CLIArgumentParser(argparse.ArgumentParser):
    """Return a machine-readable error instead of argparse's text-only exit."""

    def error(self, message: str) -> None:
        raise ValueError(message)


def _parser() -> argparse.ArgumentParser:
    parser = CLIArgumentParser(
        prog="nextx", description="Local-first X growth decision workbench"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    setup = subparsers.add_parser("setup", help="Install the default local Vault configuration")
    setup.add_argument("--vault", type=Path)
    setup.add_argument("--runtime", type=Path)
    setup.add_argument("--yes", action="store_true", help="Run non-interactively")

    config = subparsers.add_parser("config", help="Show resolved local configuration")
    config.add_argument("--show", action="store_true", help="Show resolved configuration")

    subparsers.add_parser("version", help="Show the installed NextX version")

    contracts = subparsers.add_parser(
        "contracts", help="List the versioned JSON contracts available to this NextX runtime"
    )
    contracts.add_argument("--name", choices=tuple(CONTRACT_FILES))

    collector_prompt_parser = subparsers.add_parser(
        "collector-prompt", help="Locate a bundled Collector prompt for the active runtime"
    )
    collector_prompt_parser.add_argument("--source", required=True, choices=tuple(PROMPT_FILES))

    init = subparsers.add_parser("init", help="Initialize a NextX Obsidian Vault")
    _add_vault_argument(init)

    doctor = subparsers.add_parser("doctor", help="Check local bookmark capability")
    _add_vault_argument(doctor)
    doctor.add_argument("--no-smoke", action="store_true")

    preflight = subparsers.add_parser(
        "preflight", help="Read-only check of Vault, Agent capability, and collector prerequisites"
    )
    _add_vault_argument(preflight)
    preflight.add_argument("--intent", required=True, choices=tuple(INTENT_REQUIREMENTS))
    preflight.add_argument(
        "--agent-capability",
        action="append",
        default=[],
        metavar="NAME",
        help="Capability supplied by the calling Agent; repeat for each capability",
    )
    preflight.add_argument(
        "--skills-root",
        action="append",
        type=Path,
        default=[],
        metavar="PATH",
        help="Skill root containing <capability>/SKILL.md; repeatable",
    )

    sync = subparsers.add_parser(
        "sync-bookmarks", help="Synchronize X Bookmarks into Signal notes"
    )
    _add_vault_argument(sync)
    sync.add_argument("--limit", type=int)
    sync.add_argument("--input-json", type=Path)
    sync.add_argument("--dry-run", action="store_true")
    sync.add_argument(
        "--reconcile",
        action="store_true",
        help="Treat this complete bookmark snapshot as authoritative and mark absent bookmarks inactive",
    )

    collect = subparsers.add_parser(
        "collect", help="Collect or import Signals through a versioned contract"
    )
    _add_vault_argument(collect)
    collect.add_argument(
        "--source", required=True, choices=("bookmarks", "grok", "twitter", "file")
    )
    collect.add_argument("--limit", type=int)
    collect.add_argument("--input-json", type=Path)
    collect.add_argument("--dry-run", action="store_true")
    collect.add_argument(
        "--reconcile",
        action="store_true",
        help="For bookmarks only, mark entries absent from this complete snapshot inactive",
    )

    manual = subparsers.add_parser("add-signal", help="Capture a manual Signal")
    _add_vault_argument(manual)
    manual.add_argument("--text", required=True)
    manual.add_argument("--source-url")
    manual.add_argument("--dry-run", action="store_true")

    today = subparsers.add_parser("today", help="Rebuild the daily decision View")
    _add_vault_argument(today)

    quote_sprint = subparsers.add_parser(
        "quote-sprint", help="Rebuild the time-bounded launch-stage Quote queue"
    )
    _add_vault_argument(quote_sprint)

    reply_sprint = subparsers.add_parser(
        "reply-sprint", help="Rebuild the time-bounded relationship Reply queue"
    )
    _add_vault_argument(reply_sprint)

    growth_loop = subparsers.add_parser(
        "growth-loop", help="Give one explainable next action for the current growth loop"
    )
    _add_vault_argument(growth_loop)

    readiness = subparsers.add_parser(
        "readiness", help="Check whether the editorial Self model is ready for reliable decisions"
    )
    _add_vault_argument(readiness)

    next_step = subparsers.add_parser(
        "next-step", help="Read-only onboarding status and the next safe Agent action"
    )
    _add_vault_argument(next_step)

    configure_self_parser = subparsers.add_parser(
        "configure-self", help="Save explicit conversational Self configuration"
    )
    _add_vault_argument(configure_self_parser)
    configure_self_parser.add_argument("--input-json", required=True, type=Path)

    account = subparsers.add_parser(
        "account-status", help="Show the active account and current isolation boundary"
    )
    _add_vault_argument(account)

    brief = subparsers.add_parser(
        "decision-brief", help="Prepare one Signal for topic-engine"
    )
    _add_vault_argument(brief)
    brief.add_argument("signal_id")

    quote_brief = subparsers.add_parser(
        "quote-brief", help="Prepare a Quote candidate Signal for topic-engine"
    )
    _add_vault_argument(quote_brief)
    quote_brief.add_argument("signal_id")

    reply_brief = subparsers.add_parser(
        "reply-brief", help="Prepare a Reply candidate Signal for topic-engine"
    )
    _add_vault_argument(reply_brief)
    reply_brief.add_argument("signal_id")

    analysis = subparsers.add_parser(
        "analysis-brief", help="Prepare one Signal for deep decomposition"
    )
    _add_vault_argument(analysis)
    analysis.add_argument("signal_id")

    save_analysis_parser = subparsers.add_parser(
        "save-analysis", help="Validate and persist a deep Signal analysis"
    )
    _add_vault_argument(save_analysis_parser)
    save_analysis_parser.add_argument("--input-json", required=True, type=Path)

    decision = subparsers.add_parser(
        "save-decision", help="Validate and persist a do/defer/kill Decision"
    )
    _add_vault_argument(decision)
    decision.add_argument("--input-json", required=True, type=Path)

    artifact_brief_parser = subparsers.add_parser(
        "artifact-brief", help="Prepare a do Decision for x-tweet-writer"
    )
    _add_vault_argument(artifact_brief_parser)
    artifact_brief_parser.add_argument("decision_id")

    artifact = subparsers.add_parser("save-artifact", help="Persist a selected draft")
    _add_vault_argument(artifact)
    artifact.add_argument("--input-json", required=True, type=Path)

    review_ready = subparsers.add_parser(
        "mark-review-ready", help="Validate the publish checklist and enter review"
    )
    _add_vault_argument(review_ready)
    review_ready.add_argument("artifact_id")

    confirm = subparsers.add_parser(
        "confirm-publish", help="Record explicit human confirmation before URL write-back"
    )
    _add_vault_argument(confirm)
    confirm.add_argument("artifact_id")
    confirm.add_argument("--yes", action="store_true", help="Confirm that the user approved publication")

    published = subparsers.add_parser(
        "record-published", help="Record an already-published X URL"
    )
    _add_vault_argument(published)
    published.add_argument("artifact_id")
    published.add_argument("--url", required=True)

    outcome = subparsers.add_parser(
        "record-outcome", help="Record a 1h, 24h, or 7d metric snapshot"
    )
    _add_vault_argument(outcome)
    outcome.add_argument("artifact_id")
    outcome.add_argument("--input-json", required=True, type=Path)

    weekly = subparsers.add_parser(
        "weekly-review", help="Rebuild the weekly learning View"
    )
    _add_vault_argument(weekly)

    recover_lock = subparsers.add_parser(
        "recover-lock", help="Recover a stale local NextX lock after an interrupted run"
    )
    _add_vault_argument(recover_lock)
    recover_lock.add_argument(
        "--force",
        action="store_true",
        help="Remove an ownerless legacy lock after verifying no NextX process is running",
    )

    migrate = subparsers.add_parser(
        "migrate-signals", help="Preview or apply the safe Signal filename migration"
    )
    _add_vault_argument(migrate)
    migrate.add_argument(
        "--apply",
        action="store_true",
        help="Apply the migration after reviewing the default dry-run output",
    )
    return parser


def _add_vault_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--vault",
        type=Path,
        help="Vault path; defaults to NEXTX_VAULT, saved config, or ~/Documents/NextX",
    )


def _print_json(value: object, *, stream=None) -> None:
    target = stream if stream is not None else sys.stdout
    if isinstance(value, dict) and "schema_version" not in value:
        value = {"schema_version": 1, **value}
    print(json.dumps(value, ensure_ascii=False), file=target)


def _init_command(vault: Path) -> dict[str, object]:
    created = init_vault(vault)
    created.extend(ensure_self_templates(vault))
    return {
        "ok": True,
        "command": "init",
        "vault": str(vault.expanduser().resolve()),
        "created": [str(path) for path in created],
    }


def _next_step_command(vault: Path | None) -> dict[str, object]:
    """Give a calling Agent a read-only, non-speculative onboarding decision."""
    resolved = resolve_vault(vault)
    configured = config_snapshot()
    vault_ready = resolved.is_dir() and os.access(resolved, os.W_OK)
    readiness = self_readiness(resolved, initialize=False)
    strategy = growth_strategy(resolved)
    if not vault_ready:
        phase = "setup_required"
        action = {
            "id": "setup",
            "requires_user_confirmation": True,
            "message": "需要创建本地 Vault 和 Self 模板；默认使用 ~/Documents/NextX，或由用户指定路径。",
        }
    elif not readiness["ready"]:
        phase = "self_required"
        action = {
            "id": "configure_self",
            "requires_user_confirmation": True,
            "message": "需要向用户收集定位、受众、阶段、3–4 个内容柱、禁区和真实表达样本，再保存 Self。",
            "questions": [
                "你希望别人如何用一句话介绍这个账号？",
                "你最想服务的读者是谁、处在哪个具体场景？",
                "当前是冷启动、爬坡还是稳态？",
                "列出 3–4 个会持续输出的内容柱，以及明确不做什么。",
                "给出 1–3 条你认可的真实表达样本。",
            ],
        }
    elif not strategy["configured"]:
        phase = "growth_required"
        action = {
            "id": "configure_growth",
            "requires_user_confirmation": True,
            "message": "Self 已就绪；还需确认阶段、单一增长目标、目标读者、主页承接、CTA 和本周行动配比，NextX 才能替你排序。",
            "questions": [
                "这周只优先改善 awareness、authority 还是 conversion？",
                "本周最希望被哪类读者看见？",
                "他们进主页后应该理解什么承诺，并采取什么 CTA？",
                "本周聚焦哪一个具体分发或内容动作？",
                "Discovery、Authority、Conversion 分别投入几次（总计 1–12）？",
            ],
        }
    else:
        phase = "ready"
        action = {
            "id": "capture_or_collect",
            "requires_user_confirmation": False,
            "message": "可让用户提供一个想法、导入 Grok 采集结果，或在已授权后同步 X Bookmarks。",
            "questions": ["你现在已有一个想法/收藏帖，还是希望先从 Grok 收集少量可验证候选？"],
        }
    return {
        "schema_version": 1,
        "ok": True,
        "command": "next-step",
        "phase": phase,
        "vault": str(resolved),
        "vault_source": "explicit" if vault is not None else configured["vault_source"],
        "self": readiness,
        "growth_strategy": strategy,
        "twitter_binary": "ready" if shutil.which("twitter") else "missing",
        "next_action": action,
    }


def _doctor_command(vault: Path | None, *, smoke: bool) -> tuple[dict[str, object], int]:
    vault = resolve_vault(vault)
    vault_ready = vault.is_dir() and os.access(vault, os.W_OK)
    twitter_ready = shutil.which("twitter") is not None
    checks: dict[str, object] = {
        "python": "ready" if sys.version_info >= (3, 11) else "unsupported",
        "vault": "ready" if vault_ready else "not_writable",
        "twitter_binary": "ready" if twitter_ready else "missing",
        "bookmark_smoke": "skipped",
        "bookmark_sync": read_bookmark_health(vault).get("status", "unknown"),
    }
    if smoke and twitter_ready:
        try:
            parse_payload(fetch_bookmarks(1))
            checks["bookmark_smoke"] = "ready"
        except (TwitterCLIError, ValueError) as error:
            checks["bookmark_smoke"] = "failed"
            checks["bookmark_error"] = str(error)
    ready = (
        checks["python"] == "ready"
        and checks["vault"] == "ready"
        and (not smoke or checks["twitter_binary"] == "ready")
        and (not smoke or checks["bookmark_smoke"] in {"ready", "skipped"})
    )
    return {"ok": ready, "command": "doctor", "checks": checks}, 0 if ready else 1


def _load_input(path: Path) -> object:
    if str(path) == "-":
        raw = sys.stdin.read(MAX_INPUT_JSON_BYTES + 1)
        if len(raw.encode("utf-8")) > MAX_INPUT_JSON_BYTES:
            raise ValueError(
                f"Input JSON exceeds the {MAX_INPUT_JSON_BYTES // (1024 * 1024)} MiB safety limit"
            )
    else:
        resolved = path.expanduser().resolve()
        if resolved.stat().st_size > MAX_INPUT_JSON_BYTES:
            raise ValueError(
                f"Input JSON exceeds the {MAX_INPUT_JSON_BYTES // (1024 * 1024)} MiB safety limit"
            )
        raw = resolved.read_text(encoding="utf-8")
    if len(raw.encode("utf-8")) > MAX_INPUT_JSON_BYTES:
        raise ValueError(
            f"Input JSON exceeds the {MAX_INPUT_JSON_BYTES // (1024 * 1024)} MiB safety limit"
        )

    def reject_nonstandard_number(value: str) -> object:
        raise ValueError(f"Input JSON contains unsupported numeric constant: {value}")

    return json.loads(
        raw, parse_constant=reject_nonstandard_number
    )


def _sync_command(arguments: argparse.Namespace) -> dict[str, object]:
    vault = resolve_vault(arguments.vault)
    state = read_state(vault)
    default_limit = 50 if state.get("last_success_at") else 200
    limit = arguments.limit if arguments.limit is not None else default_limit
    payload = (
        _load_input(arguments.input_json)
        if arguments.input_json is not None
        else _fetch_bookmarks_with_health(
            vault, limit, record_failure=not arguments.dry_run
        )
    )
    snapshot_complete = isinstance(payload, dict) and payload.get("snapshot_complete") is True
    report = sync_bookmarks(
        vault,
        payload,
        dry_run=arguments.dry_run,
        reconcile=arguments.reconcile,
        snapshot_complete=snapshot_complete,
    )
    return {
        "ok": True,
        "command": "sync-bookmarks",
        "vault": str(vault),
        "report": asdict(report),
    }


def _fetch_bookmarks_with_health(
    vault: Path, limit: int, *, record_failure: bool = True
) -> object:
    try:
        return fetch_bookmarks(limit)
    except TwitterCLIError as error:
        if record_failure:
            init_vault(vault)
            write_bookmark_health(vault, status="failed", error=str(error))
        raise


def _collect_command(arguments: argparse.Namespace) -> dict[str, object]:
    if arguments.source == "bookmarks":
        result = _sync_command(arguments)
        result["command"] = "collect"
        result["source"] = "bookmarks"
        return result
    if arguments.input_json is None:
        raise ValueError(f"--input-json is required for {arguments.source} collection")
    payload = _load_input(arguments.input_json)
    if not isinstance(payload, dict):
        raise ValueError("Collector input must be a JSON object")
    collector = payload.get("collector")
    if not isinstance(collector, str) or not collector:
        raise ValueError("Collector input must declare collector")
    expected = EXPECTED_COLLECTORS.get(arguments.source)
    if expected is not None and collector != expected:
        raise ValueError(
            f"--source {arguments.source!r} requires collector={expected!r}, received {collector!r}"
        )
    report = ingest_signals(
        resolve_vault(arguments.vault),
        payload,
        collector=collector,
        dry_run=arguments.dry_run,
    )
    return {
        "ok": True,
        "command": "collect",
        "source": arguments.source,
        "collector": collector,
        "vault": str(resolve_vault(arguments.vault)),
        "report": asdict(report),
    }


def _manual_signal_command(arguments: argparse.Namespace) -> dict[str, object]:
    report = add_manual_signal(
        resolve_vault(arguments.vault),
        arguments.text,
        arguments.source_url,
        dry_run=arguments.dry_run,
    )
    return {
        "ok": True,
        "command": "add-signal",
        "vault": str(resolve_vault(arguments.vault)),
        "report": asdict(report),
    }


def _save_decision_command(arguments: argparse.Namespace) -> dict[str, object]:
    vault = resolve_vault(arguments.vault)
    result = save_decision(vault, _load_input(arguments.input_json))
    render_decision_board(vault)
    render_today(vault)
    render_quote_sprint(vault)
    render_reply_sprint(vault)
    render_growth_loop(vault)
    return result


def _save_artifact_command(arguments: argparse.Namespace) -> dict[str, object]:
    return save_artifact(resolve_vault(arguments.vault), _load_input(arguments.input_json))


def _persist_handoff(
    vault: Path, kind: str, subject: str, result: dict[str, object]
) -> dict[str, object]:
    """Keep an Agent-ready Brief in the Vault instead of requiring a temporary file."""
    brief = result.get("brief")
    if not isinstance(brief, str):
        return result
    init_vault(vault)
    safe_subject = re.sub(r"[^A-Za-z0-9._-]+", "-", subject).strip("-") or "item"
    path = vault / ".nextx" / "handoffs" / f"{kind}-{safe_subject}.md"
    with vault_lock(vault):
        atomic_write_text(path, f"# NextX {kind} handoff\n\n{brief.rstrip()}\n")
    return {**result, "handoff_path": str(path)}


def main(argv: Sequence[str] | None = None) -> int:
    try:
        arguments = _parser().parse_args(argv)
        if arguments.command == "init":
            result = _init_command(resolve_vault(arguments.vault))
            code = 0
        elif arguments.command == "setup":
            result = setup_vault(arguments.vault, runtime=arguments.runtime)
            code = 0
        elif arguments.command == "config":
            result = config_snapshot()
            code = 0
        elif arguments.command == "version":
            result = {"ok": True, "command": "version", "version": __version__}
            code = 0
        elif arguments.command == "contracts":
            result = contract_catalog(arguments.name)
            code = 0 if result["ok"] else 1
        elif arguments.command == "collector-prompt":
            result = collector_prompt(arguments.source)
            code = 0 if result["ok"] else 1
        elif arguments.command == "doctor":
            result, code = _doctor_command(
                arguments.vault, smoke=not arguments.no_smoke
            )
        elif arguments.command == "preflight":
            result = run_preflight(
                resolve_vault(arguments.vault),
                intent=arguments.intent,
                agent_capabilities=arguments.agent_capability,
                skills_roots=arguments.skills_root,
            )
            code = 0 if result["ok"] else 1
        elif arguments.command == "sync-bookmarks":
            result = _sync_command(arguments)
            code = 0
        elif arguments.command == "collect":
            result = _collect_command(arguments)
            code = 0
        elif arguments.command == "add-signal":
            result = _manual_signal_command(arguments)
            code = 0
        elif arguments.command == "today":
            result = render_today(resolve_vault(arguments.vault))
            result["quote_sprint"] = render_quote_sprint(resolve_vault(arguments.vault))
            result["reply_sprint"] = render_reply_sprint(resolve_vault(arguments.vault))
            result["growth_loop"] = render_growth_loop(resolve_vault(arguments.vault))
            code = 0
        elif arguments.command == "quote-sprint":
            result = render_quote_sprint(resolve_vault(arguments.vault))
            code = 0
        elif arguments.command == "reply-sprint":
            result = render_reply_sprint(resolve_vault(arguments.vault))
            code = 0
        elif arguments.command == "growth-loop":
            result = render_growth_loop(resolve_vault(arguments.vault))
            code = 0
        elif arguments.command == "readiness":
            result = self_readiness(resolve_vault(arguments.vault))
            code = 0
        elif arguments.command == "next-step":
            result = _next_step_command(arguments.vault)
            code = 0
        elif arguments.command == "configure-self":
            result = configure_self(
                resolve_vault(arguments.vault), _load_input(arguments.input_json)
            )
            code = 0
        elif arguments.command == "account-status":
            result = account_status(resolve_vault(arguments.vault))
            code = 0
        elif arguments.command == "decision-brief":
            vault = resolve_vault(arguments.vault)
            result = _persist_handoff(
                vault, "decision", arguments.signal_id, decision_brief(vault, arguments.signal_id)
            )
            code = 0
        elif arguments.command == "quote-brief":
            vault = resolve_vault(arguments.vault)
            result = _persist_handoff(
                vault,
                "quote-decision",
                arguments.signal_id,
                decision_brief(vault, arguments.signal_id, execution_mode="quote"),
            )
            code = 0
        elif arguments.command == "reply-brief":
            vault = resolve_vault(arguments.vault)
            result = _persist_handoff(
                vault,
                "reply-decision",
                arguments.signal_id,
                decision_brief(vault, arguments.signal_id, execution_mode="reply"),
            )
            code = 0
        elif arguments.command == "analysis-brief":
            vault = resolve_vault(arguments.vault)
            result = _persist_handoff(
                vault, "analysis", arguments.signal_id, build_analysis_brief(vault, arguments.signal_id)
            )
            code = 0
        elif arguments.command == "save-analysis":
            result = save_analysis(
                resolve_vault(arguments.vault), _load_input(arguments.input_json)
            )
            code = 0
        elif arguments.command == "save-decision":
            result = _save_decision_command(arguments)
            code = 0
        elif arguments.command == "artifact-brief":
            vault = resolve_vault(arguments.vault)
            result = _persist_handoff(
                vault,
                "artifact",
                arguments.decision_id,
                artifact_brief(vault, arguments.decision_id),
            )
            code = 0
        elif arguments.command == "save-artifact":
            result = _save_artifact_command(arguments)
            code = 0
        elif arguments.command == "mark-review-ready":
            result = mark_review_ready(
                resolve_vault(arguments.vault), arguments.artifact_id
            )
            code = 0
        elif arguments.command == "confirm-publish":
            result = confirm_publish(
                resolve_vault(arguments.vault), arguments.artifact_id, confirmed=arguments.yes
            )
            code = 0
        elif arguments.command == "record-published":
            result = record_published(
                resolve_vault(arguments.vault), arguments.artifact_id, arguments.url
            )
            code = 0
        elif arguments.command == "record-outcome":
            result = record_outcome(
                resolve_vault(arguments.vault),
                arguments.artifact_id,
                _load_input(arguments.input_json),
            )
            code = 0
        elif arguments.command == "weekly-review":
            result = render_weekly_review(resolve_vault(arguments.vault))
            code = 0
        elif arguments.command == "migrate-signals":
            result = migrate_signal_filenames(
                resolve_vault(arguments.vault), dry_run=not arguments.apply
            )
            code = 0
        else:
            result = recover_vault_lock(resolve_vault(arguments.vault), force=arguments.force)
            code = 0
        _print_json(result)
        return code
    except (OSError, RuntimeError, ValueError, TwitterCLIError) as error:
        _print_json({"ok": False, "error": str(error)}, stream=sys.stderr)
        return 1
