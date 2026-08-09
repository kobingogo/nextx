import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / ("install-nextx.cmd" if os.name == "nt" else "install-nextx")


class InstallEntrypointTests(unittest.TestCase):
    def test_root_command_forwards_to_bootstrap_and_emits_agent_json(self):
        with TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    str(INSTALLER),
                    "--json",
                    "--dry-run",
                    "--runtime",
                    str(Path(tmp) / "runtime"),
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

    def test_root_command_defaults_to_human_next_steps(self):
        with TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    str(INSTALLER),
                    "--dry-run",
                    "--runtime",
                    str(Path(tmp) / "runtime"),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("NextX installer", result.stdout)
            self.assertIn("初始化 NextX", result.stdout)
            self.assertIn("nextx next-step", result.stdout)
            self.assertNotIn('"schema_version"', result.stdout)

    def test_root_command_accepts_json_after_other_options_and_locks_source(self):
        with TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    str(INSTALLER),
                    "--dry-run",
                    "--json",
                    "--source",
                    str(Path(tmp) / "untrusted-source"),
                    "--runtime",
                    str(Path(tmp) / "runtime"),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["source"], str(ROOT.resolve()))

    def test_root_command_reports_cross_agent_skill_installation_plan(self):
        with TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    str(INSTALLER),
                    "--json",
                    "--dry-run",
                    "--agents",
                    "all",
                    "--runtime",
                    str(Path(tmp) / "runtime"),
                    "--bin-dir",
                    str(Path(tmp) / "bin"),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["agent_skills"]["selection"], "all")
            self.assertIn(payload["agent_skills"]["skills"]["codex"]["status"], {"would_install", "unchanged"})
            self.assertIn(payload["agent_skills"]["skills"]["claude"]["status"], {"would_install", "unchanged"})
            self.assertEqual(payload["agent_skills"]["skills"]["grok"]["via"], "shared_agent_skills_root")


if __name__ == "__main__":
    unittest.main()
