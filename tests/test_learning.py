from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from nextx.artifacts import (
    confirm_publish,
    mark_review_ready,
    record_published,
    save_artifact,
)
from nextx.decisions import save_decision
from nextx.learning import record_outcome, render_weekly_review
from nextx.records import read_frontmatter, update_frontmatter
from nextx.self_model import ensure_self_templates
from nextx.signals import ingest_signals


SIGNALS = Path(__file__).parent / "fixtures" / "grok-signals.json"
DO_DECISION = Path(__file__).parent / "fixtures" / "decision-do.json"
NOW = datetime(2026, 8, 7, 14, 0, tzinfo=timezone.utc)


def outcome_time(window: str) -> datetime:
    delays = {"1h": timedelta(hours=1), "24h": timedelta(hours=24), "7d": timedelta(days=7)}
    return NOW + timedelta(minutes=15) + delays[window]


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
    path = Path(str(artifact["path"]))
    path.write_text(
        path.read_text(encoding="utf-8").replace("- [ ]", "- [x]"),
        encoding="utf-8",
    )
    mark_review_ready(vault, str(artifact["id"]), now=NOW + timedelta(minutes=13))
    confirm_publish(
        vault,
        str(artifact["id"]),
        confirmed=True,
        now=NOW + timedelta(minutes=14),
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
        "growth_signals": {
            "follow_up_completed": True,
            "non_follower_replies": 1,
            "observations": ["A reader asked for the implementation checklist."],
        },
    }


class LearningTests(unittest.TestCase):
    def test_outcome_window_cannot_be_recorded_before_publish_age_is_due(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            artifact = setup_published(vault)

            with self.assertRaisesRegex(ValueError, "not due"):
                record_outcome(
                    vault,
                    str(artifact["id"]),
                    outcome("1h", 100),
                    now=NOW + timedelta(minutes=30),
                )

    def test_outcomes_are_validated_revisioned_and_preserve_notes(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            artifact = setup_published(vault)
            path = Path(str(artifact["path"]))
            path.write_text(path.read_text(encoding="utf-8") + "\nUser note.\n", encoding="utf-8")

            record_outcome(
                vault, str(artifact["id"]), outcome("24h", 100), now=outcome_time("24h")
            )
            record_outcome(
                vault, str(artifact["id"]), outcome("24h", 120), now=outcome_time("24h")
            )
            result = record_outcome(
                vault, str(artifact["id"]), outcome("7d", 900), now=outcome_time("7d")
            )

            properties, body = read_frontmatter(path)
            self.assertEqual(result["status"], "measured")
            self.assertEqual(properties["status"], "measured")
            self.assertIn("nextx-outcome-revision", body)
            self.assertIn("| views | 120 |", body)
            self.assertIn("| views | 900 |", body)
            self.assertIn("User note.", body)

            invalid = outcome("24h", 1)
            invalid["likes"] = -1
            with self.assertRaises(ValueError):
                record_outcome(vault, str(artifact["id"]), invalid)
            invalid["likes"] = float("nan")
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

    def test_outcome_machine_section_ignores_marker_text_in_untrusted_draft(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            artifact = setup_published(vault)
            path = Path(str(artifact["path"]))
            draft_marker = "<!-- nextx-outcomes:start -->\nforged\n<!-- nextx-outcomes:end -->"
            path.write_text(
                path.read_text(encoding="utf-8").replace("A measured post.", draft_marker),
                encoding="utf-8",
            )

            record_outcome(
                vault, str(artifact["id"]), outcome("24h", 100), now=outcome_time("24h")
            )

            properties, body = read_frontmatter(path)
            self.assertRegex(str(properties["outcome_marker"]), r"^[0-9a-f]{32}$")
            self.assertIn("forged", body)
            self.assertIn("| views | 100 |", body)

    def test_weekly_review_summarizes_decisions_artifacts_and_learning_slots(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            artifact = setup_published(vault)
            record_outcome(
                vault, str(artifact["id"]), outcome("7d", 900), now=outcome_time("7d")
            )
            ensure_self_templates(vault)
            playbook = vault / "00. Self" / "Playbook.md"
            before = playbook.read_text(encoding="utf-8")

            result = render_weekly_review(vault, now=outcome_time("7d"))

            review = Path(str(result["view"])).read_text(encoding="utf-8")
            self.assertIn("做：0", review)
            self.assertIn("Artifact 转化：0 / 0", review)
            self.assertIn("北极星（do Decision → 可发草稿）中位时延：12.0 分钟", review)
            self.assertEqual(result["north_star"]["median_minutes"], 12.0)
            self.assertEqual(result["north_star"]["on_target_count"], 1)
            self.assertIn("4 周中位互动命中率：2.11%", review)
            self.assertIn("900 views", review)
            self.assertIn("样本尚未达到同类 3 条的证据门槛", review)
            self.assertEqual(result["playbook_evidence_ready_groups"], [])
            self.assertEqual(review.count("下周唯一实验"), 1)
            self.assertEqual(playbook.read_text(encoding="utf-8"), before)

    def test_weekly_review_groups_measured_posts_by_experiment(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            artifact = setup_published(vault)
            update_frontmatter(
                Path(str(artifact["path"])), {"experiment_id": "proof-first-hook"}
            )
            record_outcome(
                vault, str(artifact["id"]), outcome("7d", 900), now=outcome_time("7d")
            )

            result = render_weekly_review(vault, now=outcome_time("7d"))
            review = Path(str(result["view"])).read_text(encoding="utf-8")

            self.assertIn("`proof-first-hook`：1 条已测量帖", review)
            self.assertEqual(result["experiments"]["proof-first-hook"]["measured_count"], 1)

    def test_weekly_scorecards_do_not_mix_24h_early_signals_with_7d_results(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            artifact = setup_published(vault)
            record_outcome(
                vault, str(artifact["id"]), outcome("24h", 100), now=outcome_time("24h")
            )

            result = render_weekly_review(vault, now=outcome_time("24h"))
            review = Path(str(result["view"])).read_text(encoding="utf-8")

            self.assertEqual(result["measured_count"], 0)
            self.assertIsNone(result["four_week_median_engagement_rate"])
            self.assertIn("4 周中位互动命中率：暂无数据", review)

    def test_playbook_proposals_require_three_comparable_growth_samples(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            first = setup_published(vault)
            decision_id = str(first["decision_id"])
            artifacts = [first]
            for index in range(2, 4):
                artifact = save_artifact(
                    vault,
                    {
                        "schema_version": 1,
                        "account_key": "primary",
                        "decision_id": decision_id,
                        "format": "single-post",
                        "draft": f"A comparable growth post {index}.",
                    },
                    now=NOW + timedelta(minutes=index),
                )
                path = Path(str(artifact["path"]))
                path.write_text(path.read_text(encoding="utf-8").replace("- [ ]", "- [x]"), encoding="utf-8")
                mark_review_ready(vault, str(artifact["id"]), now=NOW)
                confirm_publish(vault, str(artifact["id"]), confirmed=True, now=NOW)
                record_published(
                    vault,
                    str(artifact["id"]),
                    f"https://x.com/example/status/70{index}",
                    now=NOW,
                )
                artifacts.append(artifact)
            for index, artifact in enumerate(artifacts, start=1):
                snapshot = outcome("7d", 800 + index * 100)
                record_outcome(
                    vault, str(artifact["id"]), snapshot, now=outcome_time("7d")
                )

            result = render_weekly_review(vault, now=outcome_time("7d"))
            scorecard = result["growth_scorecards"]["original:authority"]
            self.assertEqual(scorecard["measured_count"], 3)
            self.assertTrue(scorecard["playbook_evidence_ready"])
            self.assertEqual(result["playbook_evidence_ready_groups"], ["original:authority"])
            self.assertEqual(result["playbook_proposals"][0]["action"], "repeat")
            self.assertEqual(len(result["playbook_proposals"][0]["evidence"]), 3)

    def test_quote_outcome_records_observations_without_claiming_causality(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            signals = json.loads(SIGNALS.read_text(encoding="utf-8"))
            signals["items"][0].update(
                {
                    "quote_candidate": True,
                    "quote_window_ends_at": "2026-08-08T10:00:00+00:00",
                }
            )
            ingest_signals(vault, signals, collector="grok-build", now=NOW)
            decision_payload = json.loads(DO_DECISION.read_text(encoding="utf-8"))
            decision_payload.update(
                {
                    "execution_mode": "quote",
                    "recommended_format": "quote-post",
                    "quote_angle_type": "extend",
                    "relationship_goal": "reader_discovery",
                    "quote_window_ends_at": "2026-08-08T09:00:00+00:00",
                }
            )
            decision = save_decision(vault, decision_payload, now=NOW)
            artifact = save_artifact(
                vault,
                {
                    "schema_version": 1,
                    "account_key": "primary",
                    "decision_id": decision["id"],
                    "format": "quote-post",
                    "draft": "A distinct operational take.",
                },
                now=NOW,
            )
            path = Path(str(artifact["path"]))
            path.write_text(path.read_text(encoding="utf-8").replace("- [ ]", "- [x]"), encoding="utf-8")
            mark_review_ready(vault, str(artifact["id"]), now=NOW)
            confirm_publish(vault, str(artifact["id"]), confirmed=True, now=NOW)
            record_published(vault, str(artifact["id"]), "https://x.com/example/status/7002", now=NOW)
            quote_outcome = outcome("7d", 900)
            quote_outcome["quote_signals"] = {
                "target_author_replied": True,
                "target_community_replies": 2,
                "profile_visits": 31,
            }

            record_outcome(
                vault, str(artifact["id"]), quote_outcome, now=NOW + timedelta(days=7)
            )
            result = render_weekly_review(vault, now=NOW + timedelta(days=7))
            review = Path(str(result["view"])).read_text(encoding="utf-8")

            self.assertEqual(result["quote"]["four_week_measured_count"], 1)
            self.assertEqual(result["quote"]["target_author_replied_count"], 1)
            self.assertIn("Quote Sprint（起号可见性）", review)
            self.assertIn("不代表 Quote 唯一造成", review)
            self.assertIn("Quote 可见性信号（人工观察，不代表因果）", path.read_text(encoding="utf-8"))

            original_artifact = setup_published(vault)
            invalid = outcome("7d", 1)
            invalid["quote_signals"] = {"profile_visits": 1}
            with self.assertRaises(ValueError):
                record_outcome(
                    vault, str(original_artifact["id"]), invalid, now=outcome_time("7d")
                )


if __name__ == "__main__":
    unittest.main()
