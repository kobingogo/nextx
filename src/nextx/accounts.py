"""Single-account guardrails that make a future account split explicit and safe."""

from __future__ import annotations

import json
from pathlib import Path

from .vault import atomic_write_json, init_vault, vault_lock


PRIMARY_ACCOUNT = "primary"


def ensure_account_registry(vault: Path) -> dict[str, object]:
    """Create/migrate the local account registry without exposing multi-account routing yet."""
    vault = vault.expanduser().resolve()
    init_vault(vault)
    path = vault / ".nextx" / "config.json"
    if path.exists():
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"Invalid Vault account config: {path}") from error
        if not isinstance(value, dict):
            raise ValueError(f"Invalid Vault account config: {path}")
    else:
        value = {"schema_version": 1}
    if value.get("account_key", PRIMARY_ACCOUNT) != PRIMARY_ACCOUNT:
        raise ValueError("This NextX release supports only the primary account in one Vault")
    accounts = value.get("accounts")
    if accounts is None:
        accounts = {}
    if not isinstance(accounts, dict):
        raise ValueError("Vault account config accounts must be an object")
    if set(accounts) - {PRIMARY_ACCOUNT}:
        raise ValueError("This NextX release refuses mixed-account Vault configuration")
    primary = accounts.get(PRIMARY_ACCOUNT)
    if primary is None:
        primary = {"status": "active", "storage": "this_vault"}
    if not isinstance(primary, dict) or primary.get("status", "active") != "active":
        raise ValueError("The primary account must be active")
    accounts[PRIMARY_ACCOUNT] = {"status": "active", "storage": "this_vault"}
    normalized = {**value, "schema_version": 1, "account_key": PRIMARY_ACCOUNT, "accounts": accounts}
    if value != normalized:
        with vault_lock(vault):
            atomic_write_json(path, normalized)
    return normalized


def account_status(vault: Path) -> dict[str, object]:
    vault = vault.expanduser().resolve()
    registry = ensure_account_registry(vault)
    return {
        "schema_version": 1,
        "ok": True,
        "command": "account-status",
        "active_account": PRIMARY_ACCOUNT,
        "storage_scope": "this_vault",
        "multi_account_routing": "not_enabled",
        "accounts": registry["accounts"],
        "vault": str(vault),
    }
