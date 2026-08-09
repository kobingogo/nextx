"""User-level NextX configuration and Vault resolution."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
from datetime import datetime, timezone

from .vault import atomic_write_json, init_vault


def _home_path() -> Path:
    """Resolve a usable home directory even when CI clears HOME variables."""
    try:
        return Path.home()
    except RuntimeError:
        for name in ("HOME", "USERPROFILE"):
            value = os.environ.get(name)
            if value:
                return Path(value).expanduser()
        drive = os.environ.get("HOMEDRIVE")
        home = os.environ.get("HOMEPATH")
        if drive and home:
            return Path(f"{drive}{home}")
        return Path.cwd()


def default_vault() -> Path:
    return (_home_path() / "Documents" / "NextX").expanduser().resolve()


def user_config_path() -> Path:
    configured = os.environ.get("XDG_CONFIG_HOME")
    if configured:
        root = Path(configured)
    elif os.name == "nt" and os.environ.get("APPDATA"):
        root = Path(os.environ["APPDATA"]) / "NextX"
    else:
        root = _home_path() / ".config"
    return root.expanduser() / "nextx" / "config.json"


def load_user_config() -> dict[str, object]:
    path = user_config_path()
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Invalid NextX config: {path}; run `nextx setup` to repair it") from error
    if not isinstance(value, dict):
        raise ValueError(f"Invalid NextX config: {path}; expected a JSON object")
    return value


def resolve_vault(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit.expanduser().resolve()
    environment = os.environ.get("NEXTX_VAULT")
    if environment:
        return Path(environment).expanduser().resolve()
    configured = load_user_config().get("vault")
    if isinstance(configured, str) and configured:
        return Path(configured).expanduser().resolve()
    return default_vault()


def save_user_config(vault: Path, *, runtime: Path | None = None) -> Path:
    path = user_config_path()
    value: dict[str, object] = {
        "schema_version": 1,
        "vault": str(vault.expanduser().resolve()),
        "setup_at": datetime.now(timezone.utc).isoformat(),
    }
    if runtime is None:
        try:
            previous = load_user_config().get("runtime")
        except ValueError:
            previous = None
        if isinstance(previous, str) and previous:
            value["runtime"] = previous
    else:
        value["runtime"] = str(runtime.expanduser().resolve())
    atomic_write_json(path, value)
    return path


def setup_vault(vault: Path | None = None, *, runtime: Path | None = None) -> dict[str, object]:
    resolved = resolve_vault(vault)
    created = init_vault(resolved)
    from .self_model import ensure_self_templates

    created.extend(ensure_self_templates(resolved))
    config_path = save_user_config(resolved, runtime=runtime)
    configured_runtime = load_user_config().get("runtime")
    return {
        "ok": True,
        "command": "setup",
        "vault": str(resolved),
        "config": str(config_path),
        "runtime": configured_runtime,
        "created": [str(path) for path in created],
    }


def config_snapshot() -> dict[str, object]:
    value = load_user_config()
    resolved = resolve_vault()
    return {
        "ok": True,
        "command": "config",
        "config": str(user_config_path().expanduser().resolve()),
        "vault": str(resolved),
        "vault_source": (
            "explicit/environment" if os.environ.get("NEXTX_VAULT") else
            "config" if isinstance(value.get("vault"), str) else "default"
        ),
        "runtime": value.get("runtime"),
        "twitter_binary": "ready" if shutil.which("twitter") else "missing",
    }
