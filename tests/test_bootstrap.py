import importlib.util
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "skills" / "nextx" / "scripts" / "bootstrap.py"


def bootstrap_module():
    spec = importlib.util.spec_from_file_location("nextx_bootstrap", BOOTSTRAP)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class BootstrapTests(unittest.TestCase):
    @staticmethod
    def _github_archive(contents: str = "[project]\nname='nextx'\n") -> bytes:
        stream = BytesIO()
        encoded = contents.encode("utf-8")
        with tarfile.open(fileobj=stream, mode="w:gz") as archive:
            entry = tarfile.TarInfo("nextx-main/pyproject.toml")
            entry.size = len(encoded)
            archive.addfile(entry, BytesIO(encoded))
        return stream.getvalue()

    def test_dry_run_reports_source_install_without_writing_runtime(self):
        with TemporaryDirectory() as tmp:
            runtime = Path(tmp) / "runtime"
            result = subprocess.run(
                [
                    sys.executable,
                    str(BOOTSTRAP),
                    "--dry-run",
                    "--source",
                    str(ROOT),
                    "--runtime",
                    str(runtime),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["command"], "bootstrap")
            self.assertEqual(payload["source"], str(ROOT.resolve()))
            self.assertEqual(payload["mode"], "source")
            self.assertEqual(payload["dependencies"], ["nextx-workbench"])
            self.assertFalse(runtime.exists())

    def test_source_bootstrap_creates_callable_launcher(self):
        with TemporaryDirectory() as tmp:
            runtime = Path(tmp) / "runtime"
            bin_dir = Path(tmp) / "bin"
            result = subprocess.run(
                [
                    sys.executable,
                    str(BOOTSTRAP),
                    "--source",
                    str(ROOT),
                    "--runtime",
                    str(runtime),
                    "--bin-dir",
                    str(bin_dir),
                    "--agents",
                    "none",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["command"], "bootstrap")
            self.assertEqual(payload["nextx"], str(bin_dir.resolve() / "nextx"))
            help_result = subprocess.run(
                [payload["nextx"], "--help"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(help_result.returncode, 0, help_result.stderr)
            self.assertIn("setup", help_result.stdout)
            runtime_python = runtime / ("Scripts" if os.name == "nt" else "bin") / (
                "python.exe" if os.name == "nt" else "python"
            )
            package_check = subprocess.run(
                [str(runtime_python), "-c", "import importlib.metadata; print(importlib.metadata.version('nextx-workbench'))"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(package_check.returncode, 0, package_check.stderr)
            self.assertEqual(package_check.stdout.strip(), "0.3.0a2")

    def test_human_output_uses_runtime_when_global_command_collides(self):
        with TemporaryDirectory() as tmp:
            runtime = Path(tmp) / "runtime"
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            (bin_dir / "nextx").write_text("not nextx", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(BOOTSTRAP),
                    "--dry-run",
                    "--source",
                    str(ROOT),
                    "--runtime",
                    str(runtime),
                    "--bin-dir",
                    str(bin_dir),
                    "--output",
                    "human",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(str(runtime / "bin" / "nextx") + " next-step", result.stdout)
            self.assertNotIn(str(bin_dir / "nextx") + " next-step", result.stdout)

    def test_windows_source_launcher_is_a_cmd_file(self):
        with TemporaryDirectory() as tmp:
            module = bootstrap_module()
            executable = module._runtime_executable(
                Path(tmp), source_launcher=True, platform="nt"
            )
            module._write_source_launcher(executable, Path(tmp), ROOT, platform="nt")
            self.assertEqual(executable.suffix, ".cmd")
            self.assertTrue(executable.read_text(encoding="utf-8").startswith("@echo off"))

    def test_standalone_dry_run_uses_repository_source_not_path(self):
        with TemporaryDirectory() as tmp:
            module = bootstrap_module()
            runtime = Path(tmp) / "runtime"
            result = module.bootstrap(
                runtime=runtime,
                source=None,
                dry_run=True,
                bin_dir=Path(tmp) / "bin",
            )
            self.assertEqual(result["mode"], "repository")
            self.assertEqual(result["repository"], module.DEFAULT_REPOSITORY)
            self.assertEqual(result["ref"], module.DEFAULT_REF)
            self.assertEqual(
                result["source"],
                str(module._source_cache_path(runtime.resolve(), module.DEFAULT_REPOSITORY, module.DEFAULT_REF)),
            )
            self.assertFalse(result["source_cached"])
            self.assertIsNotNone(result["runtime"])

    def test_agent_skill_installation_links_shared_and_claude_roots(self):
        with TemporaryDirectory() as tmp:
            module = bootstrap_module()
            home = Path(tmp) / "home"
            for directory in (".codex", ".claude", ".grok"):
                (home / directory).mkdir(parents=True)

            result = module._install_agent_skills(
                ROOT,
                agents="auto",
                dry_run=False,
                force=False,
                home=home,
            )

            shared = home / ".agents" / "skills" / "nextx"
            claude = home / ".claude" / "skills" / "nextx"
            self.assertEqual(result["skills"]["codex"]["status"], "installed")
            self.assertEqual(result["skills"]["grok"]["status"], "installed")
            self.assertEqual(result["skills"]["claude"]["status"], "installed")
            self.assertTrue((shared / "SKILL.md").samefile(ROOT / "skills" / "nextx" / "SKILL.md"))
            self.assertTrue((claude / "SKILL.md").samefile(ROOT / "skills" / "nextx" / "SKILL.md"))
            self.assertTrue((shared.parent / ".nextx.nextx-skill.json").is_file())
            self.assertTrue((claude.parent / ".nextx.nextx-skill.json").is_file())

            repeated = module._install_agent_skills(
                ROOT,
                agents="auto",
                dry_run=False,
                force=False,
                home=home,
            )
            self.assertEqual(repeated["skills"]["codex"]["status"], "unchanged")
            self.assertEqual(repeated["skills"]["claude"]["status"], "unchanged")

    def test_agent_skill_installation_preserves_unmanaged_same_name_skill(self):
        with TemporaryDirectory() as tmp:
            module = bootstrap_module()
            home = Path(tmp) / "home"
            target = home / ".agents" / "skills" / "nextx"
            target.mkdir(parents=True)
            (target / "SKILL.md").write_text("manual skill", encoding="utf-8")

            result = module._install_agent_skills(
                ROOT,
                agents="codex",
                dry_run=False,
                force=False,
                home=home,
            )

            self.assertEqual(result["skills"]["codex"]["status"], "conflict")
            self.assertEqual((target / "SKILL.md").read_text(encoding="utf-8"), "manual skill")

    def test_agent_selection_rejects_unknown_agent(self):
        module = bootstrap_module()
        with self.assertRaisesRegex(ValueError, "Invalid --agents"):
            module._parse_agents("codex,unknown")

    def test_agent_probe_distinguishes_cli_from_existing_configuration(self):
        with TemporaryDirectory() as tmp:
            module = bootstrap_module()
            home = Path(tmp) / "home"
            (home / ".claude").mkdir(parents=True)
            with patch.object(module.shutil, "which", return_value=None):
                probes = module._probe_agents(home)

            self.assertFalse(probes["codex"]["detected"])
            self.assertEqual(probes["codex"]["runtime"], "not_found")
            self.assertTrue(probes["claude"]["detected"])
            self.assertEqual(probes["claude"]["runtime"], "state_directory")

    @unittest.skipIf(os.name == "nt", "POSIX wrapper is covered by non-Windows CI")
    def test_installed_skill_wrapper_resolves_its_own_script_directory(self):
        with TemporaryDirectory() as tmp:
            module = bootstrap_module()
            copied_skill = Path(tmp) / "nextx"
            shutil.copytree(ROOT / "skills" / "nextx", copied_skill)
            wrapper = copied_skill / "scripts" / "install-nextx"
            runtime = Path(tmp) / "runtime"
            result = subprocess.run(
                [
                    str(wrapper),
                    "--dry-run",
                    "--runtime",
                    str(runtime),
                    "--bin-dir",
                    str(Path(tmp) / "bin"),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["mode"], "repository")
            self.assertEqual(
                payload["source"],
                str(module._source_cache_path(runtime.resolve(), module.DEFAULT_REPOSITORY, module.DEFAULT_REF)),
            )

    def test_repository_cache_is_keyed_and_verified_by_repository_and_ref(self):
        with TemporaryDirectory() as tmp:
            module = bootstrap_module()
            runtime = Path(tmp) / "runtime"
            source = module._source_cache_path(runtime, "https://example.invalid/a.git", "v1")
            source.mkdir(parents=True)
            (source / "pyproject.toml").write_text("[project]\nname='nextx'\n", encoding="utf-8")
            module._write_source_metadata(source, "https://example.invalid/a.git", "v1", "git")

            cached, was_cached = module._repository_source(
                runtime, "https://example.invalid/a.git", "v1", dry_run=False
            )
            alternate, alternate_cached = module._repository_source(
                runtime, "https://example.invalid/a.git", "v2", dry_run=True
            )

            self.assertTrue(was_cached)
            self.assertEqual(cached, source)
            self.assertFalse(alternate_cached)
            self.assertNotEqual(alternate, source)

    def test_standalone_dry_run_reports_a_requested_cache_upgrade_without_writing(self):
        with TemporaryDirectory() as tmp:
            module = bootstrap_module()
            runtime = Path(tmp) / "runtime"
            source = module._source_cache_path(runtime, module.DEFAULT_REPOSITORY, module.DEFAULT_REF)
            source.mkdir(parents=True)
            (source / "pyproject.toml").write_text("[project]\nname='nextx'\n", encoding="utf-8")
            module._write_source_metadata(source, module.DEFAULT_REPOSITORY, module.DEFAULT_REF, "git")

            result = module.bootstrap(
                runtime=runtime,
                source=None,
                dry_run=True,
                bin_dir=Path(tmp) / "bin",
                refresh_source=True,
                agents="none",
            )

            self.assertTrue(result["source_cached"])
            self.assertTrue(result["upgrade_requested"])
            self.assertTrue(source.exists())

    def test_github_archive_fallback_url_rejects_ambiguous_repositories(self):
        module = bootstrap_module()

        self.assertEqual(
            module._github_archive_url("https://github.com/kobingogo/nextx.git", "release/v1"),
            "https://codeload.github.com/kobingogo/nextx/tar.gz/release%2Fv1",
        )
        self.assertIsNone(module._github_archive_url("git@github.com:kobingogo/nextx.git", "main"))

    def test_github_archive_fallback_installs_when_git_is_unavailable(self):
        class Response:
            def __init__(self, data):
                self.data = data
                self.sent = False

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self, _size):
                if self.sent:
                    return b""
                self.sent = True
                return self.data

        with TemporaryDirectory() as tmp:
            module = bootstrap_module()
            runtime = Path(tmp) / "runtime"
            repository = "https://github.com/example/nextx.git"
            with patch.object(module.shutil, "which", return_value=None), patch.object(
                module, "urlopen", return_value=Response(self._github_archive())
            ):
                source, cached = module._repository_source(runtime, repository, "main", dry_run=False)

            self.assertFalse(cached)
            self.assertTrue((source / "pyproject.toml").is_file())
            self.assertEqual(module._source_transport(source), "github-archive")

    @unittest.skipUnless(shutil.which("git"), "git is required for repository bootstrap")
    def test_standalone_repository_bootstrap_clones_and_runs_cli(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repository = tmp_path / "repository"
            shutil.copytree(
                ROOT,
                repository,
                ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", "*.pyc"),
            )
            for command in (
                ["git", "init", "-q", "--initial-branch=stable", str(repository)],
                ["git", "-C", str(repository), "config", "user.email", "test@example.invalid"],
                ["git", "-C", str(repository), "config", "user.name", "NextX test"],
                ["git", "-C", str(repository), "add", "."],
                ["git", "-C", str(repository), "commit", "-qm", "standalone fixture"],
            ):
                subprocess.run(command, check=True)

            module = bootstrap_module()
            result = module.bootstrap(
                runtime=tmp_path / "runtime",
                source=None,
                dry_run=False,
                bin_dir=tmp_path / "bin",
                repository=repository.as_uri(),
                ref="stable",
                agents="none",
            )

            self.assertEqual(result["mode"], "repository")
            self.assertFalse(result["source_cached"])
            self.assertTrue(result["source_revision"])
            self.assertEqual(result["source_transport"], "git")
            help_result = subprocess.run(
                [str(result["nextx"]), "--help"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(help_result.returncode, 0, help_result.stderr)
            self.assertIn("preflight", help_result.stdout)


if __name__ == "__main__":
    unittest.main()
