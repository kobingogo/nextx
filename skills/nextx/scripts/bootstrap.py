#!/usr/bin/env python3
"""Install or locate the isolated NextX CLI for the Skill."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys


def _source_root(value: str | None) -> Path | None:
    if value:
        return Path(value).expanduser().resolve()
    candidate = Path(__file__).resolve().parents[3]
    return candidate if (candidate / "pyproject.toml").exists() else None


def _python_version(executable: str) -> tuple[int, int] | None:
    try:
        result = subprocess.run(
            [executable, "-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"],
            check=True,
            capture_output=True,
            text=True,
        )
        major, minor = result.stdout.strip().split(".", 1)
        return int(major), int(minor)
    except (OSError, subprocess.CalledProcessError, ValueError):
        return None


def _find_python() -> str:
    candidates = [sys.executable, shutil.which("python3.11"), shutil.which("python3"), shutil.which("python")]
    for candidate in candidates:
        if candidate and (_python_version(candidate) or (0, 0)) >= (3, 11):
            return candidate
    raise RuntimeError("NextX requires Python 3.11 or newer; install it and retry")


def _runtime_executable(runtime: Path) -> Path:
    return runtime / ("Scripts" if os.name == "nt" else "bin") / ("nextx.exe" if os.name == "nt" else "nextx")


def _expose_command(executable: Path, bin_dir: Path, *, dry_run: bool) -> tuple[Path, bool]:
    command = bin_dir.expanduser().resolve() / ("nextx.exe" if os.name == "nt" else "nextx")
    if command.exists() or command.is_symlink():
        try:
            return command, command.resolve() == executable.resolve()
        except OSError:
            return command, False
    if not dry_run:
        command.parent.mkdir(parents=True, exist_ok=True)
        command.symlink_to(executable)
    return command, not dry_run


def _run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def _ensure_runtime(runtime: Path, executable: Path) -> None:
    python = _runtime_python(runtime)
    if not executable.exists():
        _run([_find_python(), "-m", "venv", str(runtime)])
    if (_python_version(str(python)) or (0, 0)) < (3, 11):
        raise RuntimeError(f"NextX runtime uses Python below 3.11: {python}")


def _write_source_launcher(executable: Path, runtime: Path, source: Path) -> None:
    python = _runtime_python(runtime)
    if os.name == "nt":
        text = f'@echo off\nset "PYTHONPATH={source / "src"};%PYTHONPATH%"\n"{python}" -m nextx %*\n'
    else:
        text = f'#!/bin/sh\nPYTHONPATH={shlex.quote(str(source / "src"))}:"$PYTHONPATH" exec {shlex.quote(str(python))} -m nextx "$@"\n'
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_text(text, encoding="utf-8")
    if os.name != "nt":
        executable.chmod(0o755)


def bootstrap(*, runtime: Path, source: Path | None, dry_run: bool, bin_dir: Path) -> dict[str, object]:
    runtime = runtime.expanduser().resolve()
    if source is not None:
        if not (source / "pyproject.toml").exists():
            raise RuntimeError(f"NextX source does not contain pyproject.toml: {source}")
        executable = _runtime_executable(runtime)
        if not dry_run:
            _ensure_runtime(runtime, executable)
            _write_source_launcher(executable, runtime, source)
        command, exposed = _expose_command(executable, bin_dir, dry_run=dry_run)
        return {
            "ok": True,
            "command": "bootstrap",
            "executable": str(executable),
            "nextx": str(command),
            "command_exposed": exposed,
            "runtime": str(runtime),
            "source": str(source),
            "installed": not dry_run,
            "mode": "source",
            "dependencies": [],
            "source_command": [str(_runtime_python(runtime)), "-m", "nextx"],
        }

    existing = shutil.which("nextx")
    if existing:
        return {
            "ok": True,
            "command": "bootstrap",
            "executable": str(Path(existing).resolve()),
            "nextx": str(Path(existing).resolve()),
            "command_exposed": True,
            "runtime": None,
            "source": None,
            "installed": False,
            "reason": "existing_path",
        }

    executable = _runtime_executable(runtime)
    python = _runtime_python(runtime)
    prerequisites = [str(python), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"]
    install = [str(python), "-m", "pip", "install", "nextx-workbench"]
    if not dry_run:
        _ensure_runtime(runtime, executable)
        _run(prerequisites)
        _run(install)
    command, exposed = _expose_command(executable, bin_dir, dry_run=dry_run)
    return {
        "ok": True,
        "command": "bootstrap",
        "executable": str(executable),
        "nextx": str(command),
        "command_exposed": exposed,
        "runtime": str(runtime),
        "source": None,
        "installed": not dry_run,
        "prerequisites_command": prerequisites,
        "install_command": install,
    }


def _runtime_python(runtime: Path) -> Path:
    return runtime / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")


def _human_output(result: dict[str, object]) -> str:
    nextx = str(result.get("nextx") or result.get("executable"))
    runtime = result.get("runtime") or "现有 PATH"
    installed = result.get("installed")
    title = "NextX installer"
    status = "安装完成" if installed else "检查完成（未写入文件）"
    lines = [title, f"状态：{status}", f"CLI：{nextx}", f"Runtime：{runtime}"]
    if result.get("command_exposed") is False:
        lines.append(f"提示：当前入口未覆盖已有命令，请直接使用：{result.get('executable')}")
    lines.extend(
        [
            "下一步：",
            f"  {nextx} setup --runtime {runtime} --yes" if result.get("runtime") else f"  {nextx} setup --yes",
            f"  {nextx} doctor --no-smoke",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, default=Path.home() / ".local" / "share" / "nextx" / "venv")
    parser.add_argument("--source", type=str)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--bin-dir", type=Path, default=Path.home() / ".local" / "bin")
    parser.add_argument("--output", choices=("json", "human"), default="json")
    arguments = parser.parse_args(argv)
    try:
        source = _source_root(arguments.source)
        if arguments.source is None and shutil.which("nextx"):
            source = None
        result = bootstrap(
            runtime=arguments.runtime,
            source=source,
            dry_run=arguments.dry_run,
            bin_dir=arguments.bin_dir,
        )
        if arguments.output == "human":
            print(_human_output(result))
        else:
            print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        if arguments.output == "human":
            print(f"NextX installer failed: {error}", file=sys.stderr)
        else:
            print(json.dumps({"ok": False, "command": "bootstrap", "error": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
