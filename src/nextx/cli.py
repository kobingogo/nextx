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
from .twitter_cli import TwitterCLIError, fetch_bookmarks
from .vault import init_vault, read_state


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nextx", description="Local-first X editorial decision workbench"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="Initialize a NextX Obsidian Vault")
    init.add_argument("--vault", required=True, type=Path)

    doctor = subparsers.add_parser("doctor", help="Check local bookmark capability")
    doctor.add_argument("--vault", required=True, type=Path)
    doctor.add_argument("--no-smoke", action="store_true")

    sync = subparsers.add_parser(
        "sync-bookmarks", help="Synchronize X Bookmarks into Signal notes"
    )
    sync.add_argument("--vault", required=True, type=Path)
    sync.add_argument("--limit", type=int)
    sync.add_argument("--input-json", type=Path)
    sync.add_argument("--dry-run", action="store_true")
    return parser


def _print_json(value: object, *, stream=None) -> None:
    target = stream if stream is not None else sys.stdout
    if isinstance(value, dict) and "schema_version" not in value:
        value = {"schema_version": 1, **value}
    print(json.dumps(value, ensure_ascii=False), file=target)


def _init_command(vault: Path) -> dict[str, object]:
    created = init_vault(vault)
    return {
        "ok": True,
        "command": "init",
        "vault": str(vault.expanduser().resolve()),
        "created": [str(path) for path in created],
    }


def _doctor_command(vault: Path, *, smoke: bool) -> tuple[dict[str, object], int]:
    vault = vault.expanduser().resolve()
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
        and checks["twitter_binary"] == "ready"
        and checks["bookmark_smoke"] in {"ready", "skipped"}
    )
    return {"ok": ready, "command": "doctor", "checks": checks}, 0 if ready else 1


def _load_input(path: Path) -> object:
    return json.loads(path.expanduser().read_text(encoding="utf-8"))


def _sync_command(arguments: argparse.Namespace) -> dict[str, object]:
    vault: Path = arguments.vault.expanduser().resolve()
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


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "init":
            result = _init_command(arguments.vault)
            code = 0
        elif arguments.command == "doctor":
            result, code = _doctor_command(
                arguments.vault, smoke=not arguments.no_smoke
            )
        else:
            result = _sync_command(arguments)
            code = 0
        _print_json(result)
        return code
    except (OSError, RuntimeError, ValueError, TwitterCLIError) as error:
        _print_json({"ok": False, "error": str(error)}, stream=sys.stderr)
        return 1
