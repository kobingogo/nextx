import json
import subprocess
import unittest
from unittest.mock import patch

from nextx.twitter_cli import TwitterCLIError, fetch_bookmarks


class RecordingRunner:
    def __init__(self, result):
        self.result = result
        self.commands = []

    def __call__(self, command, **kwargs):
        self.commands.append((command, kwargs))
        return self.result


class TwitterCLITests(unittest.TestCase):
    @patch("nextx.twitter_cli.shutil.which", return_value="/usr/local/bin/twitter")
    def test_fetch_bookmarks_uses_read_only_json_command(self, _which):
        payload = {"ok": True, "data": []}
        runner = RecordingRunner(
            subprocess.CompletedProcess([], 0, stdout=json.dumps(payload), stderr="")
        )

        result = fetch_bookmarks(50, runner=runner)

        self.assertEqual(result, payload)
        self.assertEqual(
            runner.commands[0][0],
            ["twitter", "bookmarks", "-n", "50", "--json"],
        )
        self.assertTrue(runner.commands[0][1]["capture_output"])

    @patch("nextx.twitter_cli.shutil.which", return_value=None)
    def test_missing_binary_has_actionable_error(self, _which):
        with self.assertRaisesRegex(TwitterCLIError, "twitter-cli is not installed"):
            fetch_bookmarks(50)

    @patch("nextx.twitter_cli.shutil.which", return_value="/usr/local/bin/twitter")
    def test_nonzero_exit_is_rejected(self, _which):
        runner = RecordingRunner(
            subprocess.CompletedProcess([], 1, stdout="", stderr="authentication required")
        )

        with self.assertRaisesRegex(TwitterCLIError, "authentication required"):
            fetch_bookmarks(50, runner=runner)

    @patch("nextx.twitter_cli.shutil.which", return_value="/usr/local/bin/twitter")
    def test_malformed_json_is_rejected(self, _which):
        runner = RecordingRunner(
            subprocess.CompletedProcess([], 0, stdout="not-json", stderr="")
        )

        with self.assertRaisesRegex(TwitterCLIError, "invalid JSON"):
            fetch_bookmarks(50, runner=runner)


if __name__ == "__main__":
    unittest.main()
