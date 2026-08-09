from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from nextx.decisions import decision_brief, save_decision
from nextx.bookmarks import sync_bookmarks
from nextx.records import read_frontmatter, update_frontmatter
from nextx.signals import ingest_signals, signal_filename


FIXTURE = Path(__file__).parent / "fixtures" / "grok-signals.json"
BOOKMARK_FIXTURE = Path(__file__).parent / "fixtures" / "bookmarks.json"
NOW = datetime(2026, 8, 7, 13, 0, tzinfo=timezone.utc)


def setup_vault(path):
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    ingest_signals(path, payload, collector="grok-build", now=NOW)


def decision_payload(verdict="do"):
    base = {
        "schema_version": 1,
        "account_key": "primary",
        "signal_ids": ["x:3001"],
        "verdict": verdict,
        "reason_code": "timely_self_fit" if verdict == "do" else "not_ready",
        "reason": "A concrete reason.",
    }
    if verdict == "do":
        base.update(
            {
                "angle": "Why local agents change X operations",
                "evidence_sufficient": True,
                "evidence": [
                    {
                        "signal_id": "x:3001",
                        "quote": "A verifiable trend signal.",
                        "source_url": "https://x.com/alpha/status/3001",
                    }
                ],
                "original_value": "Connect the signal to a local decision loop.",
                "risk": "Metrics may change after capture.",
                "recommended_format": "single-post",
                "research_summary": "A verified X post demonstrates the shift.",
                "why_now": "The discussion is active now.",
                "why_self": "It matches the account's agent content pillar.",
                "growth_contract": {
                    "objective": "authority",
                    "target_reader": "Creators building local-first AI workflows.",
                    "expected_action": "Save the method for a later content cycle.",
                    "distribution_target": "Readers following local-agent operations discussions.",
                    "review_at": "2026-08-14T12:00:00+00:00",
                },
            }
        )
    elif verdict == "defer":
        base.update(
            {
                "revisit_at": "2026-08-08T13:00:00+00:00",
                "revisit_reason": "Wait for a concrete implementation example.",
            }
        )
    return base


class DecisionTests(unittest.TestCase):
    def test_bookmark_signal_can_be_used_as_exact_evidence_for_do_decision(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            bookmark_payload = json.loads(BOOKMARK_FIXTURE.read_text(encoding="utf-8"))
            sync_bookmarks(vault, bookmark_payload, now=NOW)
            payload = decision_payload()
            payload["signal_ids"] = ["x:2084556671712477485"]
            payload["evidence"] = [{
                "signal_id": "x:2084556671712477485",
                "quote": "Example bookmarked post",
                "source_url": "https://x.com/example/status/2084556671712477485",
            }]

            result = save_decision(vault, payload, now=NOW)

            self.assertEqual(result["verdict"], "do")

    def test_all_three_verdicts_are_persisted(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            setup_vault(vault)

            for minute, verdict in enumerate(("do", "defer", "kill")):
                result = save_decision(
                    vault,
                    decision_payload(verdict),
                    now=NOW.replace(minute=minute),
                )
                properties, _ = read_frontmatter(Path(result["path"]))
                self.assertEqual(properties["verdict"], verdict)
                self.assertEqual(properties["signal_ids"], ["x:3001"])

    def test_do_requires_angle_evidence_original_value_and_risk(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            setup_vault(vault)
            required = (
                "angle",
                "evidence_sufficient",
                "evidence",
                "original_value",
                "risk",
                "growth_contract",
            )

            for field in required:
                payload = decision_payload("do")
                del payload[field]
                with self.subTest(field=field), self.assertRaises(ValueError):
                    save_decision(vault, payload, now=NOW)

    def test_defer_and_kill_only_need_short_reason(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            setup_vault(vault)

            for verdict in ("defer", "kill"):
                result = save_decision(vault, decision_payload(verdict), now=NOW)
                self.assertTrue(Path(result["path"]).exists())

    def test_missing_signal_and_invalid_verdict_are_rejected(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            setup_vault(vault)
            missing = decision_payload()
            missing["signal_ids"] = ["x:9999"]
            with self.assertRaises(FileNotFoundError):
                save_decision(vault, missing, now=NOW)
            invalid = decision_payload()
            invalid["verdict"] = "maybe"
            with self.assertRaises(ValueError):
                save_decision(vault, invalid, now=NOW)

    def test_decision_brief_hands_selected_signal_to_topic_engine(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            setup_vault(vault)

            result = decision_brief(vault, "x:3001")

            self.assertIn("topic-engine", result["brief"])
            self.assertIn("A verifiable trend signal.", result["brief"])
            self.assertIn("Profile.md", result["brief"])
            self.assertNotIn("# Profile\n", result["brief"])

    def test_identical_agent_retry_reuses_decision_even_at_the_same_timestamp(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            setup_vault(vault)

            first = save_decision(vault, decision_payload(), now=NOW)
            retried = save_decision(vault, decision_payload(), now=NOW)

            self.assertEqual(retried["id"], first["id"])
            self.assertTrue(retried["reused"])
            self.assertEqual(len(list((vault / "02. Decision").glob("decision-*.md"))), 1)

    def test_decision_brief_does_not_initialize_self_files(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            setup_vault(vault)

            decision_brief(vault, "x:3001")

            self.assertFalse((vault / "00. Self" / "Profile.md").exists())

    def test_do_evidence_must_be_exact_and_not_only_low_confidence(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            setup_vault(vault)
            invented = decision_payload()
            invented["evidence"][0]["quote"] = "Not present in the signal."
            with self.assertRaises(ValueError):
                save_decision(vault, invented, now=NOW)

            update_frontmatter(
                vault / "01. Signal" / signal_filename("x:3002"), {"source_confidence": "low"}
            )
            low_only = decision_payload()
            low_only["signal_ids"] = ["x:3002"]
            low_only["evidence"] = [
                {
                    "signal_id": "x:3002",
                    "quote": "ID is derived from the canonical X URL.",
                    "source_url": "https://x.com/beta/status/3002",
                }
            ]
            with self.assertRaises(ValueError):
                save_decision(vault, low_only, now=NOW)

    def test_quote_decision_locks_one_fresh_quote_candidate_and_strategy(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
            payload["items"][0].update(
                {
                    "quote_candidate": True,
                    "quote_window_ends_at": "2026-08-08T10:00:00+00:00",
                }
            )
            ingest_signals(vault, payload, collector="grok-build", now=NOW)
            quote = decision_payload()
            quote.update(
                {
                    "execution_mode": "quote",
                    "recommended_format": "quote-post",
                    "quote_angle_type": "implementation",
                    "relationship_goal": "reader_discovery",
                    "quote_window_ends_at": "2026-08-08T09:00:00+00:00",
                }
            )

            result = save_decision(vault, quote, now=NOW)
            properties, body = read_frontmatter(Path(result["path"]))

            self.assertEqual(properties["execution_mode"], "quote")
            self.assertEqual(properties["quote_source_url"], "https://x.com/alpha/status/3001")
            self.assertEqual(properties["quote_angle_type"], "implementation")
            self.assertIn("## Quote 策略", body)
            brief = decision_brief(vault, "x:3001", execution_mode="quote", now=NOW)
            self.assertIn("Quote Sprint", brief["brief"])
            self.assertIn("quote-post", brief["brief"])

            quote["recommended_format"] = "single-post"
            with self.assertRaises(ValueError):
                save_decision(vault, quote, now=NOW)

    def test_quote_kill_can_close_an_expired_candidate_without_creating_a_draft(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
            payload["items"][0].update(
                {
                    "quote_candidate": True,
                    "quote_window_ends_at": "2026-08-07T12:00:00+00:00",
                }
            )
            ingest_signals(vault, payload, collector="grok-build", now=NOW)
            kill = decision_payload("kill")
            kill["execution_mode"] = "quote"

            result = save_decision(vault, kill, now=NOW)

            self.assertEqual(result["verdict"], "kill")


if __name__ == "__main__":
    unittest.main()
