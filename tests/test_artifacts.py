from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from nextx.artifacts import (
    artifact_brief,
    confirm_publish,
    mark_review_ready,
    record_published,
    save_artifact,
)
from nextx.decisions import save_decision
from nextx.records import read_frontmatter, update_frontmatter
from nextx.signals import ingest_signals, signal_filename


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
        if verdict == "defer":
            payload.update(
                {
                    "revisit_at": "2026-08-08T14:00:00+00:00",
                    "revisit_reason": "Wait for a concrete implementation example.",
                }
            )
    return save_decision(vault, payload, now=NOW)


def artifact_payload(decision_id):
    return {
        "schema_version": 1,
        "account_key": "primary",
        "decision_id": decision_id,
        "format": "single-post",
        "draft": "Local agents turn X operations into a decision loop.",
    }


def ready_for_publication(vault, artifact_id, path):
    body = path.read_text(encoding="utf-8")
    path.write_text(body.replace("- [ ]", "- [x]"), encoding="utf-8")
    mark_review_ready(vault, artifact_id, now=NOW)
    return confirm_publish(vault, artifact_id, confirmed=True, now=NOW)


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

    def test_artifact_format_must_match_original_decision_recommendation(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            signals = json.loads(SIGNALS.read_text(encoding="utf-8"))
            ingest_signals(vault, signals, collector="grok-build", now=NOW)
            decision_payload = json.loads(DO_DECISION.read_text(encoding="utf-8"))
            decision_payload["recommended_format"] = "thread"
            decision = save_decision(vault, decision_payload, now=NOW)

            with self.assertRaisesRegex(ValueError, "recommended_format"):
                save_artifact(vault, artifact_payload(decision["id"]), now=NOW)

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

    def test_identical_agent_retry_reuses_artifact_even_at_the_same_timestamp(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            decision = setup_decision(vault, "do")
            payload = artifact_payload(decision["id"])

            first = save_artifact(vault, payload, now=NOW)
            retried = save_artifact(vault, payload, now=NOW)

            self.assertEqual(retried["id"], first["id"])
            self.assertTrue(retried["reused"])
            self.assertEqual(len(list((vault / "03. Artifact").glob("artifact-*.md"))), 1)

    def test_artifact_brief_does_not_initialize_self_files(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            decision = setup_decision(vault, "do")

            artifact_brief(vault, decision["id"])

            self.assertFalse((vault / "00. Self" / "Profile.md").exists())

    def test_record_published_validates_x_url_and_preserves_user_notes(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            decision = setup_decision(vault, "do")
            artifact = save_artifact(vault, artifact_payload(decision["id"]), now=NOW)
            path = Path(artifact["path"])
            path.write_text(path.read_text(encoding="utf-8") + "\nUser note.\n", encoding="utf-8")
            ready_for_publication(vault, artifact["id"], path)

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

    def test_publication_requires_checklist_and_explicit_confirmation(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            decision = setup_decision(vault, "do")
            artifact = save_artifact(vault, artifact_payload(decision["id"]), now=NOW)
            path = Path(artifact["path"])

            with self.assertRaises(ValueError):
                mark_review_ready(vault, artifact["id"], now=NOW)
            path.write_text(
                path.read_text(encoding="utf-8").replace("- [ ]", "- [x]"),
                encoding="utf-8",
            )
            mark_review_ready(vault, artifact["id"], now=NOW)
            with self.assertRaises(ValueError):
                confirm_publish(vault, artifact["id"], confirmed=False, now=NOW)
            with self.assertRaises(ValueError):
                record_published(
                    vault, artifact["id"], "https://x.com/example/status/7001", now=NOW
                )
            confirm_publish(vault, artifact["id"], confirmed=True, now=NOW)

    def test_draft_text_cannot_satisfy_the_publish_checklist(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            decision = setup_decision(vault, "do")
            payload = artifact_payload(decision["id"])
            payload["draft"] = "\n".join(
                (
                    "A post that happens to quote a checklist:",
                    "- [x] 事实与链接已核验",
                    "- [x] 声纹和禁区已检查",
                    "- [x] 用户已确认发布",
                )
            )
            artifact = save_artifact(vault, payload, now=NOW)

            with self.assertRaises(ValueError):
                mark_review_ready(vault, artifact["id"], now=NOW)

    def test_experiment_metadata_flows_from_do_decision_to_artifact(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            signals = json.loads(SIGNALS.read_text(encoding="utf-8"))
            ingest_signals(vault, signals, collector="grok-build", now=NOW)
            payload = json.loads(DO_DECISION.read_text(encoding="utf-8"))
            payload["experiment"] = {
                "id": "proof-first-hook",
                "hypothesis": "A proof-first hook increases saves and reposts.",
                "metric": "engagement_rate",
            }
            decision = save_decision(vault, payload, now=NOW)

            artifact = save_artifact(vault, artifact_payload(decision["id"]), now=NOW)
            properties, _ = read_frontmatter(Path(artifact["path"]))

            self.assertEqual(properties["experiment_id"], "proof-first-hook")
            self.assertIn("proof-first hook", properties["experiment_hypothesis"])

    def test_quote_artifact_is_locked_to_the_decision_source_and_qt_format(self):
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
                    "relationship_goal": "author_dialogue",
                    "quote_window_ends_at": "2026-08-08T09:00:00+00:00",
                }
            )
            decision = save_decision(vault, decision_payload, now=NOW)
            artifact_payload = {
                "schema_version": 1,
                "account_key": "primary",
                "decision_id": decision["id"],
                "format": "quote-post",
                "draft": "The missing operating detail is the feedback loop.",
            }

            artifact = save_artifact(vault, artifact_payload, now=NOW)
            properties, body = read_frontmatter(Path(artifact["path"]))

            self.assertEqual(properties["execution_mode"], "quote")
            self.assertEqual(properties["quote_signal_id"], "x:3001")
            self.assertEqual(properties["quote_source_url"], "https://x.com/alpha/status/3001")
            self.assertIn("## Quote 原帖", body)
            self.assertIn("QT 模式", artifact_brief(vault, decision["id"], now=NOW)["brief"])

            artifact_payload["format"] = "single-post"
            with self.assertRaises(ValueError):
                save_artifact(vault, artifact_payload, now=NOW)

    def test_quote_artifact_rejects_an_expired_or_retargeted_decision(self):
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
                    "quote_angle_type": "translate",
                    "relationship_goal": "credibility",
                    "quote_window_ends_at": "2026-08-08T09:00:00+00:00",
                }
            )
            decision = save_decision(vault, decision_payload, now=NOW)
            artifact_payload = {
                "schema_version": 1,
                "account_key": "primary",
                "decision_id": decision["id"],
                "format": "quote-post",
                "draft": "A distinct translation of the implication.",
            }

            with self.assertRaises(ValueError):
                save_artifact(
                    vault,
                    artifact_payload,
                    now=datetime(2031, 1, 1, tzinfo=timezone.utc),
                )

            update_frontmatter(
                vault / "01. Signal" / signal_filename("x:3001"),
                {"source_url": "https://x.com/other/status/3001", "author_handle": "other"},
            )
            with self.assertRaises(ValueError):
                save_artifact(vault, artifact_payload, now=NOW)

    def test_thread_pack_and_asset_manifest_are_persisted_as_one_publishable_package(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            decision = setup_decision(vault, "do")
            update_frontmatter(Path(str(decision["path"])), {"recommended_format": "thread"})
            payload = {
                "schema_version": 1,
                "account_key": "primary",
                "decision_id": decision["id"],
                "format": "thread",
                "draft": "A complete Thread package.",
                "thread_pack": {
                    "posts": ["1/ The first claim.", "2/ The operational proof."],
                    "cta": "Save this loop before your next post.",
                },
                "asset_manifest": [
                    {
                        "role": "cover",
                        "purpose": "Make the thread premise scannable in the feed.",
                        "prompt": "A minimal local-first growth-loop cover diagram.",
                        "alt_text": "A loop from signal to decision, content, feedback, and learning.",
                    }
                ],
            }

            artifact = save_artifact(vault, payload, now=NOW)
            properties, body = read_frontmatter(Path(str(artifact["path"])))

            self.assertEqual(properties["thread_post_count"], 2)
            self.assertEqual(properties["asset_count"], 1)
            self.assertIn("## Thread Pack", body)
            self.assertIn("## 资产清单", body)
            self.assertIn("## 发布后行动", body)

            invalid = dict(payload)
            invalid.pop("thread_pack")
            with self.assertRaises(ValueError):
                save_artifact(vault, invalid, now=NOW)


if __name__ == "__main__":
    unittest.main()
