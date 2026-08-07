from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from nextx.records import read_frontmatter
from nextx.signals import add_manual_signal, ingest_signals


FIXTURE = Path(__file__).parent / "fixtures" / "grok-signals.json"
SCHEMA = Path(__file__).parents[1] / "schemas" / "collector-envelope.v1.json"
NOW = datetime(2026, 8, 7, 11, 0, tzinfo=timezone.utc)


def fixture_payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class SignalTests(unittest.TestCase):
    def test_grok_import_normalizes_versioned_signals(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)

            report = ingest_signals(vault, fixture_payload(), collector="grok-build", now=NOW)

            self.assertEqual(report.created, 2)
            first, _ = read_frontmatter(vault / "01. Signal" / "x-3001.md")
            second, _ = read_frontmatter(vault / "01. Signal" / "x-3002.md")
            self.assertEqual(first["schema_version"], 1)
            self.assertEqual(first["account_key"], "primary")
            self.assertEqual(first["collector"], "grok-build")
            self.assertEqual(second["id"], "x:3002")

    def test_second_import_is_fully_deduplicated(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            ingest_signals(vault, fixture_payload(), collector="grok-build", now=NOW)

            report = ingest_signals(vault, fixture_payload(), collector="grok-build", now=NOW)

            self.assertEqual(report.created, 0)
            self.assertEqual(report.duplicates, 2)

    def test_manual_signal_uses_stable_content_hash(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)

            first = add_manual_signal(vault, "  My private idea  ", now=NOW)
            second = add_manual_signal(vault, "My private idea", now=NOW)

            self.assertEqual(first.created, 1)
            self.assertEqual(second.created, 0)
            self.assertEqual(second.duplicates, 1)
            self.assertEqual(len(list((vault / "01. Signal").glob("manual-*.md"))), 1)

    def test_invalid_batch_writes_nothing(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            payload = fixture_payload()
            payload["items"][1]["source_confidence"] = "certain"

            with self.assertRaises(ValueError):
                ingest_signals(vault, payload, collector="grok-build", now=NOW)

            self.assertFalse((vault / "01. Signal").exists())

    def test_dry_run_writes_nothing(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)

            report = ingest_signals(
                vault, fixture_payload(), collector="grok-build", dry_run=True, now=NOW
            )

            self.assertTrue(report.dry_run)
            self.assertEqual(report.created, 2)
            self.assertFalse((vault / "01. Signal").exists())

    def test_public_schema_required_fields_match_parser_contract(self):
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

        self.assertEqual(
            set(schema["required"]),
            {"schema_version", "account_key", "collector", "retrieved_at", "items"},
        )
        self.assertEqual(
            set(schema["properties"]["items"]["items"]["required"]),
            {"platform", "text", "source_confidence"},
        )


if __name__ == "__main__":
    unittest.main()
