from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from nextx.artifacts import artifact_brief, record_published, save_artifact
from nextx.decisions import save_decision
from nextx.records import read_frontmatter
from nextx.signals import ingest_signals


SIGNALS = Path(__file__).parent / "fixtures" / "grok-signals.json"
DO_DECISION = Path(__file__).parent / "fixtures" / "decision-do.json"
NOW = datetime(2026, 8, 7, 14, 0, tzinfo=timezone.utc)


def setup_decision(vault, verdict="do"):
    signals = json.loads(SIGNALS.read_text(encoding="utf-8"))
    ingest_signals(vault, signals, collector="grok-build", now=NOW)
    payload = json.loads(DO_DECISION.read_text(encoding="utf-8"))
    payload["verdict"] = verdict
    if verdict != "do":
        payload = {
            "schema_version": 1,
            "account_key": "primary",
            "signal_ids": ["x:3001"],
            "verdict": verdict,
            "reason_code": "not_fit",
            "reason": "Not suitable now.",
        }
    return save_decision(vault, payload, now=NOW)


def artifact_payload(decision_id):
    return {
        "schema_version": 1,
        "account_key": "primary",
        "decision_id": decision_id,
        "format": "single-post",
        "draft": "Local agents turn X operations into a decision loop.",
    }


class ArtifactTests(unittest.TestCase):
    def test_only_do_decision_creates_linked_draft(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            decision = setup_decision(vault, "do")

            artifact = save_artifact(vault, artifact_payload(decision["id"]), now=NOW)

            properties, body = read_frontmatter(Path(artifact["path"]))
            self.assertEqual(properties["decision_id"], decision["id"])
            self.assertEqual(properties["signal_ids"], ["x:3001"])
            self.assertEqual(properties["status"], "draft")
            self.assertIn("Local agents", body)

    def test_non_do_decision_and_empty_draft_are_rejected(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            killed = setup_decision(vault, "kill")
            with self.assertRaises(ValueError):
                save_artifact(vault, artifact_payload(killed["id"]), now=NOW)
            done = setup_decision(vault, "do")
            payload = artifact_payload(done["id"])
            payload["draft"] = " "
            with self.assertRaises(ValueError):
                save_artifact(vault, payload, now=NOW)

    def test_artifact_brief_hands_do_decision_to_tweet_writer(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            decision = setup_decision(vault, "do")

            result = artifact_brief(vault, decision["id"])

            self.assertIn("x-tweet-writer", result["brief"])
            self.assertIn("Why local agents", result["brief"])
            self.assertIn("Voice.md", result["brief"])

    def test_record_published_validates_x_url_and_preserves_user_notes(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            decision = setup_decision(vault, "do")
            artifact = save_artifact(vault, artifact_payload(decision["id"]), now=NOW)
            path = Path(artifact["path"])
            path.write_text(path.read_text(encoding="utf-8") + "\nUser note.\n", encoding="utf-8")

            result = record_published(
                vault,
                artifact["id"],
                "https://x.com/example/status/7001",
                now=NOW,
            )

            properties, body = read_frontmatter(path)
            self.assertEqual(result["status"], "published")
            self.assertEqual(properties["status"], "published")
            self.assertEqual(properties["published_url"], "https://x.com/example/status/7001")
            self.assertIn("User note.", body)
            with self.assertRaises(ValueError):
                record_published(vault, artifact["id"], "https://example.com/post/1", now=NOW)


if __name__ == "__main__":
    unittest.main()
