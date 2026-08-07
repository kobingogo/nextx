"""Command-line interface for NextX."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Sequence

from .bookmarks import parse_payload, sync_bookmarks
from .analysis import build_analysis_brief
from .artifacts import artifact_brief, record_published, save_artifact
from .config import config_snapshot, resolve_vault, setup_vault
from .decisions import decision_brief, save_decision
from .learning import record_outcome, render_weekly_review
from .self_model import ensure_self_templates
from .signals import add_manual_signal, ingest_signals
from .twitter_cli import TwitterCLIError, fetch_bookmarks
from .vault import init_vault, read_state
from .views import render_decision_board, render_today


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nextx", description="Local-first X editorial decision workbench"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    setup = subparsers.add_parser("setup", help="Install the default local Vault configuration")
    setup.add_argument("--vault", type=Path)
    setup.add_argument("--runtime", type=Path)
    setup.add_argument("--yes", action="store_true", help="Run non-interactively")

    config = subparsers.add_parser("config", help="Show resolved local configuration")
    config.add_argument("--show", action="store_true", help="Show resolved configuration")

    init = subparsers.add_parser("init", help="Initialize a NextX Obsidian Vault")
    _add_vault_argument(init)

    doctor = subparsers.add_parser("doctor", help="Check local bookmark capability")
    _add_vault_argument(doctor)
    doctor.add_argument("--no-smoke", action="store_true")

    sync = subparsers.add_parser(
        "sync-bookmarks", help="Synchronize X Bookmarks into Signal notes"
    )
    _add_vault_argument(sync)
    sync.add_argument("--limit", type=int)
    sync.add_argument("--input-json", type=Path)
    sync.add_argument("--dry-run", action="store_true")

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

    manual = subparsers.add_parser("add-signal", help="Capture a manual Signal")
    _add_vault_argument(manual)
    manual.add_argument("--text", required=True)
    manual.add_argument("--source-url")
    manual.add_argument("--dry-run", action="store_true")

    today = subparsers.add_parser("today", help="Rebuild the daily decision View")
    _add_vault_argument(today)

    brief = subparsers.add_parser(
        "decision-brief", help="Prepare one Signal for topic-engine"
    )
    _add_vault_argument(brief)
    brief.add_argument("signal_id")

    analysis = subparsers.add_parser(
        "analysis-brief", help="Prepare one Signal for deep decomposition"
    )
    _add_vault_argument(analysis)
    analysis.add_argument("signal_id")

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

    published = subparsers.add_parser(
        "record-published", help="Record an already-published X URL"
    )
    _add_vault_argument(published)
    published.add_argument("artifact_id")
    published.add_argument("--url", required=True)

    outcome = subparsers.add_parser(
        "record-outcome", help="Record a 24h or 7d metric snapshot"
    )
    _add_vault_argument(outcome)
    outcome.add_argument("artifact_id")
    outcome.add_argument("--input-json", required=True, type=Path)

    weekly = subparsers.add_parser(
        "weekly-review", help="Rebuild the weekly learning View"
    )
    _add_vault_argument(weekly)
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


def _doctor_command(vault: Path | None, *, smoke: bool) -> tuple[dict[str, object], int]:
    vault = resolve_vault(vault)
    vault_ready = vault.is_dir() and os.access(vault, os.W_OK)
    twitter_ready = shutil.which("twitter") is not None
    checks: dict[str, object] = {
        "python": "ready" if sys.version_info >= (3, 11) else "unsupported",
        "vault": "ready" if vault_ready else "not_writable",
        "twitter_binary": "ready" if twitter_ready else "missing",
        "bookmark_smoke": "skipped",
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
    return json.loads(path.expanduser().read_text(encoding="utf-8"))


def _sync_command(arguments: argparse.Namespace) -> dict[str, object]:
    vault = resolve_vault(arguments.vault)
    state = read_state(vault)
    default_limit = 50 if state.get("last_success_at") else 200
    limit = arguments.limit if arguments.limit is not None else default_limit
    payload = (
        _load_input(arguments.input_json)
        if arguments.input_json is not None
        else fetch_bookmarks(limit)
    )
    report = sync_bookmarks(vault, payload, dry_run=arguments.dry_run)
    return {
        "ok": True,
        "command": "sync-bookmarks",
        "vault": str(vault),
        "report": asdict(report),
    }


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
    return result


def _save_artifact_command(arguments: argparse.Namespace) -> dict[str, object]:
    return save_artifact(resolve_vault(arguments.vault), _load_input(arguments.input_json))


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "init":
            result = _init_command(resolve_vault(arguments.vault))
            code = 0
        elif arguments.command == "setup":
            result = setup_vault(arguments.vault, runtime=arguments.runtime)
            code = 0
        elif arguments.command == "config":
            result = config_snapshot()
            code = 0
        elif arguments.command == "doctor":
            result, code = _doctor_command(
                arguments.vault, smoke=not arguments.no_smoke
            )
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
            code = 0
        elif arguments.command == "decision-brief":
            result = decision_brief(resolve_vault(arguments.vault), arguments.signal_id)
            code = 0
        elif arguments.command == "analysis-brief":
            result = build_analysis_brief(resolve_vault(arguments.vault), arguments.signal_id)
            code = 0
        elif arguments.command == "save-decision":
            result = _save_decision_command(arguments)
            code = 0
        elif arguments.command == "artifact-brief":
            result = artifact_brief(resolve_vault(arguments.vault), arguments.decision_id)
            code = 0
        elif arguments.command == "save-artifact":
            result = _save_artifact_command(arguments)
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
        else:
            result = render_weekly_review(resolve_vault(arguments.vault))
            code = 0
        _print_json(result)
        return code
    except (OSError, RuntimeError, ValueError, TwitterCLIError) as error:
        _print_json({"ok": False, "error": str(error)}, stream=sys.stderr)
        return 1
