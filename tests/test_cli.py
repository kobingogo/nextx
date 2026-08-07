from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from nextx.cli import main


FIXTURE = Path(__file__).parent / "fixtures" / "bookmarks.json"
GROK_FIXTURE = Path(__file__).parent / "fixtures" / "grok-signals.json"
DECISION_FIXTURE = Path(__file__).parent / "fixtures" / "decision-do.json"


def run_cli(arguments):
    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = main(arguments)
    return code, stdout.getvalue(), stderr.getvalue()


class CLITests(unittest.TestCase):
    def test_init_returns_json(self):
        with TemporaryDirectory() as tmp:
            code, stdout, stderr = run_cli(["init", "--vault", tmp])

            result = json.loads(stdout)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            self.assertTrue(result["ok"])
            self.assertEqual(result["schema_version"], 1)
            self.assertEqual(result["command"], "init")

    def test_sync_accepts_fixture_without_calling_twitter(self):
        with TemporaryDirectory() as tmp:
            with patch("nextx.cli.fetch_bookmarks") as fetch:
                code, stdout, stderr = run_cli(
                    [
                        "sync-bookmarks",
                        "--vault",
                        tmp,
                        "--input-json",
                        str(FIXTURE),
                    ]
                )

            result = json.loads(stdout)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            self.assertEqual(result["report"]["created"], 2)
            fetch.assert_not_called()

    def test_collect_imports_grok_contract(self):
        with TemporaryDirectory() as tmp:
            code, stdout, stderr = run_cli(
                [
                    "collect",
                    "--vault",
                    tmp,
                    "--source",
                    "grok",
                    "--input-json",
                    str(GROK_FIXTURE),
                ]
            )

            result = json.loads(stdout)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            self.assertEqual(result["report"]["created"], 2)

    def test_add_signal_captures_manual_idea(self):
        with TemporaryDirectory() as tmp:
            code, stdout, stderr = run_cli(
                ["add-signal", "--vault", tmp, "--text", "A manual idea"]
            )

            result = json.loads(stdout)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            self.assertEqual(result["report"]["created"], 1)

    def test_today_renders_obisidian_view(self):
        with TemporaryDirectory() as tmp:
            run_cli(
                [
                    "collect",
                    "--vault",
                    tmp,
                    "--source",
                    "grok",
                    "--input-json",
                    str(GROK_FIXTURE),
                ]
            )

            code, stdout, stderr = run_cli(["today", "--vault", tmp])

            result = json.loads(stdout)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            self.assertEqual(result["automatic_count"], 2)
            self.assertTrue((Path(tmp) / "04. Views" / "Today.md").exists())

    def test_decision_brief_and_save_decision(self):
        with TemporaryDirectory() as tmp:
            run_cli(
                ["collect", "--vault", tmp, "--source", "grok", "--input-json", str(GROK_FIXTURE)]
            )

            brief_code, brief_stdout, _ = run_cli(
                ["decision-brief", "--vault", tmp, "x:3001"]
            )
            save_code, save_stdout, save_stderr = run_cli(
                ["save-decision", "--vault", tmp, "--input-json", str(DECISION_FIXTURE)]
            )

            self.assertEqual(brief_code, 0)
            self.assertIn("topic-engine", json.loads(brief_stdout)["brief"])
            self.assertEqual(save_code, 0)
            self.assertEqual(save_stderr, "")
            self.assertEqual(json.loads(save_stdout)["verdict"], "do")

    def test_expected_failure_returns_json_only_on_stderr(self):
        with TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.json"

            code, stdout, stderr = run_cli(
                [
                    "sync-bookmarks",
                    "--vault",
                    tmp,
                    "--input-json",
                    str(missing),
                ]
            )

            self.assertEqual(code, 1)
            self.assertEqual(stdout, "")
            self.assertFalse(json.loads(stderr)["ok"])

    @patch("nextx.cli.shutil.which", return_value="/usr/local/bin/twitter")
    def test_doctor_without_smoke_does_not_read_bookmarks(self, _which):
        with TemporaryDirectory() as tmp:
            with patch("nextx.cli.fetch_bookmarks") as fetch:
                code, stdout, stderr = run_cli(
                    ["doctor", "--vault", tmp, "--no-smoke"]
                )

            result = json.loads(stdout)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            self.assertEqual(result["checks"]["twitter_binary"], "ready")
            self.assertEqual(result["checks"]["bookmark_smoke"], "skipped")
            fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
