import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "skills" / "nextx" / "scripts" / "bootstrap.py"


class BootstrapTests(unittest.TestCase):
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
            self.assertEqual(payload["dependencies"], [])
            self.assertFalse(runtime.exists())

    def test_source_bootstrap_creates_callable_launcher(self):
        with TemporaryDirectory() as tmp:
            runtime = Path(tmp) / "runtime"
            result = subprocess.run(
                [
                    sys.executable,
                    str(BOOTSTRAP),
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
            help_result = subprocess.run(
                [payload["executable"], "--help"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(help_result.returncode, 0, help_result.stderr)
            self.assertIn("setup", help_result.stdout)


if __name__ == "__main__":
    unittest.main()
