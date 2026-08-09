"""Obsidian Vault layout and safe local persistence."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import tempfile
from typing import Iterator


VAULT_FOLDERS = (
    "00. Self",
    "01. Signal",
    "02. Decision",
    "03. Artifact",
    "04. Views",
    ".nextx/handoffs",
    ".nextx/runs",
)

DEFAULT_STATE: dict[str, object] = {
    "schema_version": 1,
    "seen_ids": [],
    "last_success_at": None,
    "last_run_id": None,
}


def atomic_write_text(path: Path, text: str) -> None:
    """Write UTF-8 text in the destination directory, then replace atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
            temporary_path = Path(handle.name)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def atomic_write_json(path: Path, value: object) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def state_path(vault: Path) -> Path:
    return vault / ".nextx" / "bookmarks-state.json"


def read_state(vault: Path) -> dict[str, object]:
    path = state_path(vault)
    if not path.exists():
        return dict(DEFAULT_STATE)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Invalid NextX state: {path}")
    return value


def write_state(vault: Path, state: dict[str, object]) -> None:
    atomic_write_json(state_path(vault), state)


def init_vault(vault: Path) -> list[Path]:
    vault = vault.expanduser().resolve()
    vault.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    for relative in VAULT_FOLDERS:
        path = vault / relative
        if not path.exists():
            path.mkdir(parents=True)
            created.append(path)
    if not state_path(vault).exists():
        write_state(vault, dict(DEFAULT_STATE))
        created.append(state_path(vault))
    return created


def _lock_paths(vault: Path) -> tuple[Path, Path]:
    lock = vault / ".nextx" / "sync.lock"
    return lock, lock / "owner.json"


def _read_lock_owner(owner_path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(owner_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    pid = value.get("pid")
    hostname = value.get("hostname")
    if isinstance(pid, bool) or not isinstance(pid, int) or not isinstance(hostname, str):
        return None
    return value


def _windows_pid_is_running(pid: int) -> bool:
    """Check a Windows process without emulating POSIX ``kill(pid, 0)``.

    ``os.kill(pid, 0)`` is not a safe existence probe on Windows: its signal
    argument is not POSIX-compatible and can map to a terminating operation.
    The Win32 exit-code API is read-only and lets recovery distinguish a dead
    owner from a process we cannot inspect.
    """
    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    still_active = 259
    error_access_denied = 5
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        # An access-denied process may still own the Vault, so never recover it.
        return ctypes.get_last_error() == error_access_denied
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return True
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        return _windows_pid_is_running(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        # Treat platform-specific errors conservatively as an active process.
        return True
    return True


def recover_vault_lock(vault: Path, *, force: bool = False) -> dict[str, object]:
    """Recover only a provably stale lock; ownerless legacy locks need consent."""
    vault = vault.expanduser().resolve()
    lock, owner_path = _lock_paths(vault)
    if not lock.exists():
        return {
            "schema_version": 1,
            "ok": True,
            "command": "recover-lock",
            "status": "absent",
            "lock": str(lock),
        }
    if not lock.is_dir():
        raise RuntimeError(f"NextX lock path is not a directory: {lock}")
    owner = _read_lock_owner(owner_path)
    if owner is not None and owner["hostname"] == socket.gethostname():
        pid = int(owner["pid"])
        if _pid_is_running(pid):
            raise RuntimeError(
                f"Another NextX process is still running (pid {pid}): {lock}"
            )
        reason = "stale_owner"
    elif owner is None and force:
        reason = "forced_legacy_lock"
    elif owner is not None:
        raise RuntimeError(
            "NextX lock is owned by another host and cannot be safely recovered: %s"
            % lock
        )
    else:
        raise RuntimeError(
            "NextX lock has no verifiable stale local owner; verify no NextX process is "
            "running, then retry with recover-lock --force"
        )
    if owner_path.exists():
        owner_path.unlink()
    try:
        lock.rmdir()
    except OSError as error:
        raise RuntimeError(f"NextX lock contains unexpected files: {lock}") from error
    return {
        "schema_version": 1,
        "ok": True,
        "command": "recover-lock",
        "status": "recovered",
        "reason": reason,
        "lock": str(lock),
    }


@contextmanager
def vault_lock(vault: Path) -> Iterator[None]:
    """Hold the one global sync lock for a Vault."""
    lock, owner_path = _lock_paths(vault.expanduser().resolve())
    try:
        # ponytail: one global lock is sufficient for a single-account local Vault.
        lock.mkdir()
    except FileExistsError as error:
        try:
            recovered = recover_vault_lock(vault)
        except RuntimeError as recovery_error:
            raise recovery_error from error
        if recovered["status"] != "recovered":
            raise RuntimeError(f"Another NextX sync is already running: {lock}") from error
        try:
            lock.mkdir()
        except FileExistsError as retry_error:
            raise RuntimeError(f"Another NextX sync is already running: {lock}") from retry_error
    try:
        atomic_write_json(
            owner_path,
            {
                "schema_version": 1,
                "pid": os.getpid(),
                "hostname": socket.gethostname(),
                "started_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    except OSError:
        lock.rmdir()
        raise
    try:
        yield
    finally:
        if owner_path.exists():
            owner_path.unlink()
        lock.rmdir()
