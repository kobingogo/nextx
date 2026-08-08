import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "install-nextx"


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
            self.assertIn("nextx setup", result.stdout)
            self.assertNotIn('"schema_version"', result.stdout)


if __name__ == "__main__":
    unittest.main()
