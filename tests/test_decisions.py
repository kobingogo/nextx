from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from nextx.decisions import decision_brief, save_decision
from nextx.records import read_frontmatter
from nextx.signals import ingest_signals


FIXTURE = Path(__file__).parent / "fixtures" / "grok-signals.json"
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
                "original_value": "Connect the signal to a local decision loop.",
                "risk": "Metrics may change after capture.",
                "recommended_format": "single-post",
                "research_summary": "A verified X post demonstrates the shift.",
                "why_now": "The discussion is active now.",
                "why_self": "It matches the account's agent content pillar.",
            }
        )
    return base


class DecisionTests(unittest.TestCase):
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
            required = ("angle", "evidence_sufficient", "original_value", "risk")

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


if __name__ == "__main__":
    unittest.main()
