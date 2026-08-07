from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from nextx.artifacts import record_published, save_artifact
from nextx.decisions import save_decision
from nextx.learning import record_outcome, render_weekly_review
from nextx.records import read_frontmatter, update_frontmatter
from nextx.self_model import ensure_self_templates
from nextx.signals import ingest_signals


SIGNALS = Path(__file__).parent / "fixtures" / "grok-signals.json"
DO_DECISION = Path(__file__).parent / "fixtures" / "decision-do.json"
NOW = datetime(2026, 8, 7, 14, 0, tzinfo=timezone.utc)


def setup_published(vault: Path) -> dict[str, object]:
    ingest_signals(
        vault,
        json.loads(SIGNALS.read_text(encoding="utf-8")),
        collector="grok-build",
        now=NOW,
    )
    decision = save_decision(
        vault,
        json.loads(DO_DECISION.read_text(encoding="utf-8")),
        now=NOW,
    )
    artifact = save_artifact(
        vault,
        {
            "schema_version": 1,
            "account_key": "primary",
            "decision_id": decision["id"],
            "format": "single-post",
            "draft": "A measured post.",
        },
        now=NOW + timedelta(minutes=12),
    )
    record_published(
        vault,
        str(artifact["id"]),
        "https://x.com/example/status/7001",
        now=NOW + timedelta(minutes=15),
    )
    return artifact


def outcome(window: str, views: int) -> dict[str, object]:
    return {
        "schema_version": 1,
        "account_key": "primary",
        "window": window,
        "views": views,
        "likes": 10,
        "replies": 2,
        "reposts": 3,
        "bookmarks": 4,
    }


class LearningTests(unittest.TestCase):
    def test_outcomes_are_validated_replaced_and_preserve_notes(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            artifact = setup_published(vault)
            path = Path(str(artifact["path"]))
            path.write_text(path.read_text(encoding="utf-8") + "\nUser note.\n", encoding="utf-8")

            record_outcome(vault, str(artifact["id"]), outcome("24h", 100), now=NOW)
            record_outcome(vault, str(artifact["id"]), outcome("24h", 120), now=NOW)
            result = record_outcome(vault, str(artifact["id"]), outcome("7d", 900), now=NOW)

            properties, body = read_frontmatter(path)
            self.assertEqual(result["status"], "measured")
            self.assertEqual(properties["status"], "measured")
            self.assertEqual(body.count('\"window\":\"24h\"'), 1)
            self.assertIn("| views | 120 |", body)
            self.assertIn("| views | 900 |", body)
            self.assertIn("User note.", body)

            invalid = outcome("24h", 1)
            invalid["likes"] = -1
            with self.assertRaises(ValueError):
                record_outcome(vault, str(artifact["id"]), invalid)

    def test_unpublished_artifact_and_unknown_window_are_rejected(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            artifact = setup_published(vault)
            path = Path(str(artifact["path"]))
            update_frontmatter(path, {"status": "draft"})
            with self.assertRaises(ValueError):
                record_outcome(vault, str(artifact["id"]), outcome("24h", 1))
            update_frontmatter(path, {"status": "published"})
            with self.assertRaises(ValueError):
                record_outcome(vault, str(artifact["id"]), outcome("30d", 1))

    def test_weekly_review_summarizes_decisions_artifacts_and_learning_slots(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            artifact = setup_published(vault)
            record_outcome(vault, str(artifact["id"]), outcome("7d", 900), now=NOW)
            ensure_self_templates(vault)
            playbook = vault / "00. Self" / "Playbook.md"
            before = playbook.read_text(encoding="utf-8")

            result = render_weekly_review(vault, now=NOW)

            review = Path(str(result["view"])).read_text(encoding="utf-8")
            self.assertIn("做：1", review)
            self.assertIn("Artifact 转化：1 / 1", review)
            self.assertIn("草稿时延中位数：12.0 分钟", review)
            self.assertIn("900 views", review)
            self.assertEqual(review.count("候选 Playbook "), 5)
            self.assertEqual(review.count("下周唯一实验"), 1)
            self.assertEqual(playbook.read_text(encoding="utf-8"), before)


if __name__ == "__main__":
    unittest.main()
