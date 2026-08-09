#!/usr/bin/env python3
"""Install or locate the isolated NextX CLI for the Skill."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen
from uuid import uuid4


DEFAULT_REPOSITORY = "https://github.com/kobingogo/nextx.git"
DEFAULT_REF = "v0.3.0-alpha.2"
MIN_PYTHON = (3, 11)
CACHE_SCHEMA_VERSION = 1
MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
SKILL_MARKER_SCHEMA_VERSION = 1
AGENTS = ("codex", "claude", "grok")


def _home_path() -> Path:
    """Resolve a usable home directory even when a runner clears HOME."""
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


class InstallerArgumentParser(argparse.ArgumentParser):
    """Avoid text-only argparse exits in the installer JSON protocol."""

    def error(self, message: str) -> None:
        raise ValueError(message)


def _source_root(value: Optional[str]) -> Optional[Path]:
    if value:
        return Path(value).expanduser().resolve()
    candidate = Path(__file__).resolve().parents[3]
    return candidate if (candidate / "pyproject.toml").exists() else None


def _python_version(executable: str) -> Optional[Tuple[int, int]]:
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
        if candidate and (_python_version(candidate) or (0, 0)) >= MIN_PYTHON:
            return candidate
    raise RuntimeError("NextX requires Python 3.11 or newer; install it and retry")


def _runtime_executable(
    runtime: Path, *, source_launcher: bool = False, platform: Optional[str] = None
) -> Path:
    if (platform or os.name) == "nt":
        name = "nextx.cmd" if source_launcher else "nextx.exe"
        return runtime / "Scripts" / name
    return runtime / "bin" / "nextx"


def _expose_command(executable: Path, bin_dir: Path, *, dry_run: bool) -> Tuple[Path, bool]:
    command = bin_dir.expanduser().resolve() / executable.name
    if command.exists() or command.is_symlink():
        try:
            return command, command.resolve() == executable.resolve()
        except OSError:
            return command, False
    if not dry_run:
        command.parent.mkdir(parents=True, exist_ok=True)
        command.symlink_to(executable)
    return command, not dry_run


def _run(command: List[str]) -> None:
    subprocess.run(command, check=True)


def _ensure_runtime(runtime: Path, executable: Path) -> None:
    python = _runtime_python(runtime)
    if not executable.exists():
        _run([_find_python(), "-m", "venv", str(runtime)])
    if (_python_version(str(python)) or (0, 0)) < MIN_PYTHON:
        raise RuntimeError(f"NextX runtime uses Python below 3.11: {python}")


def _install_runtime_project(runtime: Path, source: Path) -> None:
    """Install the local project into the isolated runtime, including its declared deps."""
    command = [
        str(_runtime_python(runtime)),
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--upgrade",
        str(source),
    ]
    result = subprocess.run(
        command, check=False, capture_output=True, text=True
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "pip install failed").strip().replace("\n", " ")
        raise RuntimeError(f"NextX dependency installation failed: {detail[:500]}")


def _write_source_launcher(
    executable: Path, runtime: Path, source: Path, *, platform: Optional[str] = None
) -> None:
    runtime_platform = platform or os.name
    python = _runtime_python(runtime, platform=runtime_platform)
    if runtime_platform == "nt":
        text = (
            "@echo off\r\n"
            f'set "PYTHONPATH={source / "src"};%PYTHONPATH%"\r\n'
            f'"{python}" -m nextx %*\r\n'
        )
    else:
        text = f'#!/bin/sh\nPYTHONPATH={shlex.quote(str(source / "src"))}:"$PYTHONPATH" exec {shlex.quote(str(python))} -m nextx "$@"\n'
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_text(text, encoding="utf-8")
    if runtime_platform != "nt":
        executable.chmod(0o755)


def _source_cache_key(repository: str, ref: str) -> str:
    """Separate source checkouts by their full requested identity."""
    return hashlib.sha256(f"{repository}\0{ref}".encode("utf-8")).hexdigest()[:20]


def _source_cache_path(runtime: Path, repository: str, ref: str) -> Path:
    return runtime.parent / "sources" / _source_cache_key(repository, ref)


def _cache_metadata_path(source: Path) -> Path:
    return source / ".nextx-source.json"


def _verify_source_cache(source: Path, repository: str, ref: str) -> None:
    if not (source / "pyproject.toml").is_file():
        raise RuntimeError(
            "NextX source cache is missing pyproject.toml; move it aside and retry: %s"
            % source
        )
    try:
        metadata = json.loads(_cache_metadata_path(source).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(
            "NextX source cache is missing identity metadata; move it aside and retry: %s"
            % source
        ) from error
    if not isinstance(metadata, dict) or (
        metadata.get("schema_version") != CACHE_SCHEMA_VERSION
        or metadata.get("repository") != repository
        or metadata.get("ref") != ref
    ):
        raise RuntimeError(
            "NextX source cache identity does not match the requested repository/ref: %s"
            % source
        )


def _write_source_metadata(source: Path, repository: str, ref: str, transport: str) -> None:
    _cache_metadata_path(source).write_text(
        json.dumps(
            {
                "schema_version": CACHE_SCHEMA_VERSION,
                "repository": repository,
                "ref": ref,
                "transport": transport,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _source_transport(source: Path) -> Optional[str]:
    try:
        metadata = json.loads(_cache_metadata_path(source).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    transport = metadata.get("transport") if isinstance(metadata, dict) else None
    return transport if isinstance(transport, str) else None


def _github_archive_url(repository: str, ref: str) -> Optional[str]:
    """Return a codeload URL only for an unambiguous public GitHub HTTPS repo."""
    parsed = urlparse(repository)
    if parsed.scheme != "https" or parsed.netloc.lower() != "github.com":
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2:
        return None
    owner, name = parts
    if name.endswith(".git"):
        name = name[:-4]
    if not owner or not name:
        return None
    return f"https://codeload.github.com/{owner}/{name}/tar.gz/{quote(ref, safe='')}"


def _extract_archive(data: bytes, destination: Path) -> Path:
    """Extract a GitHub archive without allowing links or path traversal."""
    destination.mkdir(parents=True, exist_ok=False)
    root = destination.resolve()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for member in archive.getmembers():
            member_path = Path(member.name)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise RuntimeError("NextX archive contains an unsafe path")
            if member.issym() or member.islnk() or member.isdev():
                raise RuntimeError("NextX archive contains unsupported link or device entries")
            target = (root / member_path).resolve()
            if not target.is_relative_to(root):
                raise RuntimeError("NextX archive contains an unsafe path")
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    raise RuntimeError("NextX archive contains an unreadable file")
                with source, target.open("wb") as handle:
                    shutil.copyfileobj(source, handle)
            else:
                raise RuntimeError("NextX archive contains an unsupported entry")
    candidates = [
        path.parent
        for path in destination.glob("*/pyproject.toml")
        if path.is_file()
    ]
    if len(candidates) != 1:
        raise RuntimeError("Downloaded NextX archive has an unexpected layout")
    return candidates[0]


def _download_github_source(repository: str, ref: str, destination: Path) -> None:
    url = _github_archive_url(repository, ref)
    if url is None:
        raise RuntimeError(
            "Standalone installation of a non-GitHub repository needs git; install git "
            "or pass --source from a local checkout"
        )
    request = Request(url, headers={"User-Agent": "nextx-installer/0.1"})
    with urlopen(request, timeout=30) as response:
        chunks: List[bytes] = []
        size = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_ARCHIVE_BYTES:
                raise RuntimeError("Downloaded NextX archive exceeds the 50 MiB safety limit")
            chunks.append(chunk)
    archive_root = destination.parent / "archive"
    extracted = _extract_archive(b"".join(chunks), archive_root)
    extracted.replace(destination)
    shutil.rmtree(archive_root)


def _repository_source(
    runtime: Path, repository: str, ref: str, *, dry_run: bool, refresh: bool = False
) -> Tuple[Path, bool]:
    """Materialize a standalone Skill's CLI source without trusting PATH or PyPI."""
    source = _source_cache_path(runtime, repository, ref)
    if source.exists():
        _verify_source_cache(source, repository, ref)
        if not refresh:
            return source, True
        if dry_run:
            return source, True
    if dry_run:
        return source, False
    source.parent.mkdir(parents=True, exist_ok=True)
    staging_root = Path(tempfile.mkdtemp(prefix="nextx-source-", dir=source.parent))
    staging_source = staging_root / "source"
    try:
        git = shutil.which("git")
        if git is not None:
            _run(
                [git, "clone", "--depth", "1", "--branch", ref, repository, str(staging_source)]
            )
            transport = "git"
        else:
            _download_github_source(repository, ref, staging_source)
            transport = "github-archive"
        if not (staging_source / "pyproject.toml").is_file():
            raise RuntimeError("Downloaded NextX source is missing pyproject.toml")
        _write_source_metadata(staging_source, repository, ref, transport)
        backup: Optional[Path] = None
        try:
            if source.exists():
                backup = source.parent / f".{source.name}.previous-{uuid4().hex}"
                source.replace(backup)
            staging_source.replace(source)
        except OSError as error:
            if backup is not None and backup.exists() and not source.exists():
                backup.replace(source)
            if source.exists():
                _verify_source_cache(source, repository, ref)
                return source, True
            raise RuntimeError(f"Could not finalize NextX source cache: {source}") from error
        finally:
            if backup is not None and backup.exists():
                shutil.rmtree(backup, ignore_errors=True)
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)
    return source, False


def _source_revision(source: Path) -> Optional[str]:
    git = shutil.which("git")
    if git is None:
        return None
    try:
        result = subprocess.run(
            [git, "-C", str(source), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def _parse_agents(value: str) -> Tuple[str, set[str]]:
    """Return an installation mode and the explicitly requested Agent names."""
    normalized = value.strip().lower()
    if normalized in {"auto", "all", "none"}:
        return normalized, set(AGENTS) if normalized == "all" else set()
    names = {item.strip() for item in normalized.split(",") if item.strip()}
    unknown = names.difference(AGENTS)
    if not names or unknown:
        supported = ", ".join(("auto", "all", "none", *AGENTS))
        raise ValueError(f"Invalid --agents value {value!r}; use {supported}")
    return "explicit", names


def _probe_agents(home: Path) -> Dict[str, Dict[str, object]]:
    """Detect local Agent homes without treating a missing binary as an error.

    Codex and Grok both discover the open Agent Skills user root.  A desktop
    install need not expose a shell command, so its state directory also counts
    as a useful signal.
    """
    claude_home = Path(os.environ.get("CLAUDE_CONFIG_DIR", home / ".claude")).expanduser()
    state_dirs = {
        "codex": ((home / ".codex").exists() or (home / ".agents").exists()),
        "claude": claude_home.exists(),
        "grok": (home / ".grok").exists(),
    }
    binaries = {name: bool(shutil.which(name)) for name in AGENTS}
    return {
        name: {
            "detected": binaries[name] or state_dirs[name],
            "runtime": "cli" if binaries[name] else ("state_directory" if state_dirs[name] else "not_found"),
        }
        for name in AGENTS
    }


def _detect_agents(home: Path) -> Dict[str, bool]:
    return {
        name: bool(detail["detected"])
        for name, detail in _probe_agents(home).items()
    }


def _agent_skill_paths(home: Path) -> Dict[str, Path]:
    """Return canonical user-level paths documented by each Agent host."""
    claude_home = Path(os.environ.get("CLAUDE_CONFIG_DIR", home / ".claude")).expanduser()
    return {
        # Codex and Grok both discover this open Agent Skills root.
        "shared": home / ".agents" / "skills" / "nextx",
        "claude": claude_home / "skills" / "nextx",
    }


def _skill_marker(target: Path) -> Path:
    return target.parent / f".{target.name}.nextx-skill.json"


def _read_skill_marker(target: Path) -> Optional[Dict[str, object]]:
    try:
        value = json.loads(_skill_marker(target).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or value.get("schema_version") != SKILL_MARKER_SCHEMA_VERSION:
        return None
    return value


def _is_managed_skill_target(target: Path) -> bool:
    marker = _read_skill_marker(target)
    return bool(marker and marker.get("target") == str(target))


def _write_skill_marker(target: Path, source: Path) -> None:
    marker = _skill_marker(target)
    marker.parent.mkdir(parents=True, exist_ok=True)
    temporary = marker.with_name(f".{marker.name}.{uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(
            {
                "schema_version": SKILL_MARKER_SCHEMA_VERSION,
                "target": str(target),
                "source": str(source),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(marker)


def _remove_managed_target(target: Path) -> None:
    """Replace only a target previously marked as installed by NextX."""
    if target.is_symlink() or target.is_file():
        target.unlink()
    elif target.is_dir():
        shutil.rmtree(target)


def _install_skill_target(
    source: Path, target: Path, *, dry_run: bool, force: bool
) -> Dict[str, object]:
    """Expose the full Skill directory without overwriting unrelated work."""
    source = source.resolve()
    target = target.expanduser()
    if not target.is_absolute():
        target = target.absolute()
    if not (source / "SKILL.md").is_file():
        raise RuntimeError(f"NextX canonical Skill is missing SKILL.md: {source}")
    if source == target:
        return {"status": "in_place", "path": str(target), "source": str(source)}

    exists = target.exists() or target.is_symlink()
    if exists:
        marker = _read_skill_marker(target)
        if marker and marker.get("target") == str(target) and marker.get("source") == str(source):
            return {"status": "unchanged", "path": str(target), "source": str(source)}
        try:
            same_source = target.resolve() == source
        except OSError:
            same_source = False
        if same_source:
            return {"status": "unchanged", "path": str(target), "source": str(source)}
        if not force and not _is_managed_skill_target(target):
            return {
                "status": "conflict",
                "path": str(target),
                "source": str(source),
                "message": "Existing Skill is not managed by NextX; leave it untouched or retry with --force-agent-skills.",
            }
    if dry_run:
        return {"status": "would_install", "path": str(target), "source": str(source)}

    target.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        staged = target.parent / f".{target.name}.nextx-stage-{uuid4().hex}"
        staged.symlink_to(source, target_is_directory=True)
        try:
            if exists:
                _remove_managed_target(target)
            staged.replace(target)
        finally:
            if staged.is_symlink():
                staged.unlink()
    else:
        staged = target.parent / f".{target.name}.nextx-stage-{uuid4().hex}"
        def _link_or_copy(source_file: str, target_file: str) -> str:
            try:
                os.link(source_file, target_file)
            except OSError:
                shutil.copy2(source_file, target_file)
            return target_file

        shutil.copytree(source, staged, copy_function=_link_or_copy)
        try:
            if exists:
                _remove_managed_target(target)
            staged.replace(target)
        finally:
            if staged.exists():
                shutil.rmtree(staged)
    _write_skill_marker(target, source)
    return {
        "status": "updated" if exists else "installed",
        "path": str(target),
        "source": str(source),
    }


def _install_agent_skills(
    source_root: Path,
    *,
    agents: str,
    dry_run: bool,
    force: bool,
    home: Optional[Path] = None,
) -> Dict[str, object]:
    """Install one portable Skill into all detected compatible Agent roots."""
    mode, explicit = _parse_agents(agents)
    home = (home or _home_path()).expanduser().resolve()
    probes = _probe_agents(home)
    detected = {name: bool(detail["detected"]) for name, detail in probes.items()}
    requested = explicit if mode in {"all", "explicit"} else {
        name for name, available in detected.items() if available
    }
    if mode == "none":
        requested = set()

    paths = _agent_skill_paths(home)
    skill_source = source_root / "skills" / "nextx"
    if not skill_source.is_dir():
        statuses = {
            name: {
                "detected": detected[name],
                "runtime": probes[name]["runtime"],
                "status": "source_unavailable" if name in requested else "not_requested",
            }
            for name in AGENTS
        }
        return {
            "selection": mode if mode != "explicit" else sorted(explicit),
            "detected": detected,
            "skills": statuses,
            "onboarding_prompt": "初始化 NextX",
        }

    shared_result: Optional[Dict[str, object]] = None
    if requested.intersection({"codex", "grok"}):
        shared_result = _install_skill_target(
            skill_source, paths["shared"], dry_run=dry_run, force=force
        )
    claude_result: Optional[Dict[str, object]] = None
    if "claude" in requested:
        claude_result = _install_skill_target(
            skill_source, paths["claude"], dry_run=dry_run, force=force
        )

    statuses: Dict[str, Dict[str, object]] = {}
    for name in ("codex", "grok"):
        if name in requested and shared_result is not None:
            statuses[name] = {
                "detected": detected[name],
                "runtime": probes[name]["runtime"],
                "via": "shared_agent_skills_root",
                **shared_result,
            }
        else:
            statuses[name] = {
                "detected": detected[name],
                "runtime": probes[name]["runtime"],
                "status": "not_detected" if mode == "auto" else "not_requested",
            }
    if "claude" in requested and claude_result is not None:
        statuses["claude"] = {
            "detected": detected["claude"],
            "runtime": probes["claude"]["runtime"],
            **claude_result,
        }
    else:
        statuses["claude"] = {
            "detected": detected["claude"],
            "runtime": probes["claude"]["runtime"],
            "status": "not_detected" if mode == "auto" else "not_requested",
        }

    return {
        "selection": mode if mode != "explicit" else sorted(explicit),
        "detected": detected,
        "probes": probes,
        "skills": statuses,
        "onboarding_prompt": "初始化 NextX",
    }


def bootstrap(
    *,
    runtime: Path,
    source: Optional[Path],
    dry_run: bool,
    bin_dir: Path,
    repository: str = DEFAULT_REPOSITORY,
    ref: str = DEFAULT_REF,
    agents: str = "auto",
    force_agent_skills: bool = False,
    agent_home: Optional[Path] = None,
    refresh_source: bool = False,
) -> Dict[str, object]:
    runtime = runtime.expanduser().resolve()
    standalone = source is None
    if source is None:
        source, source_cached = _repository_source(
            runtime, repository, ref, dry_run=dry_run, refresh=refresh_source
        )
    else:
        source_cached = False
    source = source.expanduser().resolve()
    if not dry_run and not (source / "pyproject.toml").exists():
        raise RuntimeError(f"NextX source does not contain pyproject.toml: {source}")
    executable = _runtime_executable(runtime, source_launcher=True)
    if not dry_run:
        _ensure_runtime(runtime, executable)
        _install_runtime_project(runtime, source)
        _write_source_launcher(executable, runtime, source)
    command, exposed = _expose_command(executable, bin_dir, dry_run=dry_run)
    agent_skills = _install_agent_skills(
        source,
        agents=agents,
        dry_run=dry_run,
        force=force_agent_skills,
        home=agent_home,
    )
    return {
        "ok": True,
        "command": "bootstrap",
        "executable": str(executable),
        "nextx": str(command),
        "recommended_command": str(command if exposed else executable),
        "command_exposed": exposed,
        "runtime": str(runtime),
        "source": str(source),
        "installed": not dry_run,
        "mode": "repository" if standalone else "source",
        "repository": repository if standalone else None,
        "ref": ref if standalone else None,
        "source_cached": source_cached,
        "upgrade_requested": refresh_source,
        "source_revision": _source_revision(source) if not dry_run else None,
        "source_transport": _source_transport(source) if standalone and not dry_run else None,
        "dependencies": ["nextx-workbench"],
        "source_command": [str(_runtime_python(runtime)), "-m", "nextx"],
        "agent_skills": agent_skills,
    }


def _runtime_python(runtime: Path, *, platform: Optional[str] = None) -> Path:
    runtime_platform = platform or os.name
    return runtime / ("Scripts" if runtime_platform == "nt" else "bin") / (
        "python.exe" if runtime_platform == "nt" else "python"
    )


def _human_output(result: Dict[str, object]) -> str:
    nextx = str(
        result.get("recommended_command")
        or result.get("nextx")
        or result.get("executable")
    )
    runtime = result.get("runtime") or "现有 PATH"
    installed = result.get("installed")
    title = "NextX installer"
    status = "安装完成" if installed else "检查完成（未写入文件）"
    lines = [title, f"状态：{status}", f"CLI：{nextx}", f"Runtime：{runtime}"]
    if result.get("command_exposed") is False:
        lines.append(f"提示：当前入口未覆盖已有命令，请直接使用：{result.get('executable')}")
    agent_skills = result.get("agent_skills")
    if isinstance(agent_skills, dict):
        skills = agent_skills.get("skills")
        if isinstance(skills, dict):
            installed = [
                name
                for name, detail in skills.items()
                if isinstance(detail, dict)
                and detail.get("status") in {"installed", "updated", "unchanged", "in_place"}
            ]
            conflicts = [
                name
                for name, detail in skills.items()
                if isinstance(detail, dict) and detail.get("status") == "conflict"
            ]
            if installed:
                lines.append(f"Agent Skill：已为 {', '.join(installed)} 配置 NextX 对话能力")
            config_only = [
                name
                for name, detail in skills.items()
                if isinstance(detail, dict)
                and detail.get("status") in {"installed", "updated", "unchanged", "in_place"}
                and detail.get("runtime") == "state_directory"
            ]
            if config_only:
                lines.append(
                    "Agent 运行时：%s 仅发现配置目录，未在 PATH 找到 CLI；"
                    "请在对应桌面/CLI 的新会话中确认 NextX 已出现。" % ", ".join(config_only)
                )
            if conflicts:
                lines.append(
                    "Agent Skill：%s 已存在非 NextX 管理的同名 Skill；"
                    "如需替换，请重试并加 --force-agent-skills。" % ", ".join(conflicts)
                )
    lines.extend(
        [
            "下一步：",
            "在已安装的 Codex、Claude Code 或 Grok Build 对话中直接说：初始化 NextX",
            "（Agent 会先创建/检查本地 Vault，再向你收集定位、内容柱、禁区和真实声纹。）",
            _display_command([nextx, "next-step"]),
        ]
    )
    return "\n".join(lines)


def _display_command(arguments: List[str]) -> str:
    rendered = (
        subprocess.list2cmdline(arguments)
        if os.name == "nt"
        else shlex.join(arguments)
    )
    return f"  {rendered}"


def _reexec_with_supported_python() -> None:
    if sys.version_info >= MIN_PYTHON:
        return
    python = _find_python()
    os.execv(python, [python, str(Path(__file__).resolve())] + sys.argv[1:])


def main(argv: Optional[List[str]] = None) -> int:
    parser = InstallerArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, default=_home_path() / ".local" / "share" / "nextx" / "venv")
    parser.add_argument("--source", type=str)
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--ref", default=DEFAULT_REF)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--upgrade",
        action="store_true",
        help="Refresh a standalone repository cache to the requested ref before reinstalling",
    )
    parser.add_argument("--bin-dir", type=Path, default=_home_path() / ".local" / "bin")
    parser.add_argument(
        "--agents",
        default="auto",
        help="Install Skill for detected agents: auto (default), all, none, or comma-separated codex,claude,grok",
    )
    parser.add_argument(
        "--force-agent-skills",
        action="store_true",
        help="Replace an existing same-name Skill only when explicitly requested",
    )
    parser.add_argument("--output", choices=("json", "human"), default="json")
    parser.add_argument("--json", action="store_const", const="json", dest="output")
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(errors="backslashreplace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(errors="backslashreplace")
        _reexec_with_supported_python()
        arguments = parser.parse_args(argv)
        source = _source_root(arguments.source)
        result = bootstrap(
            runtime=arguments.runtime,
            source=source,
            dry_run=arguments.dry_run,
            bin_dir=arguments.bin_dir,
            repository=arguments.repository,
            ref=arguments.ref,
            agents=arguments.agents,
            force_agent_skills=arguments.force_agent_skills,
            refresh_source=arguments.upgrade,
        )
        if arguments.output == "human":
            print(_human_output(result))
        else:
            print(json.dumps(result, ensure_ascii=True))
        return 0
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        output = arguments.output if "arguments" in locals() else "json"
        if output == "human":
            print(f"NextX installer failed: {error}", file=sys.stderr)
        else:
            print(json.dumps({"ok": False, "command": "bootstrap", "error": str(error)}, ensure_ascii=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
