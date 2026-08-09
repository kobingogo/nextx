from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from nextx.records import read_frontmatter
from nextx.signals import (
    add_manual_signal,
    ingest_signals,
    legacy_signal_filename,
    migrate_signal_filenames,
    signal_filename,
    signal_path,
)


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
            first, _ = read_frontmatter(vault / "01. Signal" / signal_filename("x:3001"))
            second, _ = read_frontmatter(vault / "01. Signal" / signal_filename("x:3002"))
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

    def test_distinct_non_x_ids_that_share_a_slug_keep_distinct_records(self):
        """A filesystem-safe name must never merge two valid source identities."""
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            payload = {
                "schema_version": 1,
                "account_key": "primary",
                "collector": "file-import",
                "retrieved_at": NOW.isoformat(),
                "items": [
                    {
                        "source_id": "feed:a",
                        "platform": "rss",
                        "text": "First independent feed item.",
                        "source_confidence": "high",
                    },
                    {
                        "source_id": "feed-a",
                        "platform": "rss",
                        "text": "Second independent feed item.",
                        "source_confidence": "high",
                    },
                ],
            }

            report = ingest_signals(vault, payload, collector="file-import", now=NOW)

            records = list((vault / "01. Signal").glob("*.md"))
            self.assertEqual(report.created, 2)
            self.assertEqual(report.duplicates, 0)
            self.assertEqual(len(records), 2)
            self.assertEqual(
                {read_frontmatter(path)[0]["id"] for path in records},
                {"feed:a", "feed-a"},
            )

    def test_legacy_filename_is_resolved_only_when_frontmatter_id_matches(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            ingest_signals(vault, fixture_payload(), collector="grok-build", now=NOW)
            canonical = vault / "01. Signal" / signal_filename("x:3001")
            legacy_name = legacy_signal_filename("x:3001")
            self.assertIsNotNone(legacy_name)
            legacy = vault / "01. Signal" / str(legacy_name)
            canonical.rename(legacy)

            self.assertEqual(signal_path(vault, "x:3001"), legacy)

    def test_explicit_migration_renames_legacy_signal_and_keeps_an_obsidian_alias(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            ingest_signals(vault, fixture_payload(), collector="grok-build", now=NOW)
            canonical = vault / "01. Signal" / signal_filename("x:3001")
            legacy = vault / "01. Signal" / str(legacy_signal_filename("x:3001"))
            canonical.rename(legacy)

            preview = migrate_signal_filenames(vault)
            result = migrate_signal_filenames(vault, dry_run=False)

            self.assertEqual(len(preview["planned"]), 1)
            self.assertEqual(len(result["migrated"]), 1)
            self.assertFalse(legacy.exists())
            properties, _ = read_frontmatter(canonical)
            self.assertIn("x-3001", properties["aliases"])

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

    def test_x_signal_requires_consistent_canonical_source_and_timestamps(self):
        with TemporaryDirectory() as tmp:
            payload = fixture_payload()
            payload["items"][0]["source_url"] = "https://x.com/alpha/status/9999"
            with self.assertRaises(ValueError):
                ingest_signals(Path(tmp), payload, collector="grok-build", now=NOW)

    def test_collector_priority_fields_are_bounded_and_persisted(self):
        with TemporaryDirectory() as tmp:
            payload = fixture_payload()
            payload["items"][0].update(
                {"self_fit": 4, "novelty": 3, "why_today": "A fresh primary source appeared."}
            )
            ingest_signals(Path(tmp), payload, collector="grok-build", now=NOW)
            properties, _ = read_frontmatter(
                Path(tmp) / "01. Signal" / signal_filename("x:3001")
            )
            self.assertEqual(properties["self_fit"], 4)
            self.assertEqual(properties["novelty"], 3)
            self.assertEqual(properties["why_today"], "A fresh primary source appeared.")
            self.assertRegex(properties["content_fingerprint"], r"^[0-9a-f]{16}$")

            payload = fixture_payload()
            payload["items"][0]["self_fit"] = 6
            with self.assertRaises(ValueError):
                ingest_signals(Path(tmp) / "invalid", payload, collector="grok-build", now=NOW)

            payload = fixture_payload()
            payload["items"][0]["published_at"] = "2026-08-07"
            with self.assertRaises(ValueError):
                ingest_signals(Path(tmp), payload, collector="grok-build", now=NOW)

    def test_quote_candidate_requires_a_time_bounded_verified_x_post(self):
        with TemporaryDirectory() as tmp:
            payload = fixture_payload()
            payload["items"][0].update(
                {
                    "quote_candidate": True,
                    "quote_window_ends_at": "2026-08-08T10:00:00+00:00",
                }
            )

            ingest_signals(Path(tmp), payload, collector="grok-build", now=NOW)
            properties, body = read_frontmatter(
                Path(tmp) / "01. Signal" / signal_filename("x:3001")
            )

            self.assertTrue(properties["quote_candidate"])
            self.assertEqual(properties["signal_type"], "quote_candidate")
            self.assertIn("决策窗口截止：2026-08-08T10:00:00+00:00", body)

            invalid = fixture_payload()
            invalid["items"][0].update({"quote_candidate": True})
            with self.assertRaises(ValueError):
                ingest_signals(Path(tmp) / "invalid", invalid, collector="grok-build", now=NOW)

            invalid = fixture_payload()
            invalid["items"][0]["quote_window_ends_at"] = "2026-08-08T10:00:00+00:00"
            with self.assertRaises(ValueError):
                ingest_signals(Path(tmp) / "invalid-window", invalid, collector="grok-build", now=NOW)

            stale = fixture_payload()
            stale["items"][0].update(
                {
                    "published_at": "2026-08-04T09:00:00+00:00",
                    "quote_candidate": True,
                    "quote_window_ends_at": "2026-08-08T10:00:00+00:00",
                }
            )
            with self.assertRaises(ValueError):
                ingest_signals(Path(tmp) / "stale", stale, collector="grok-build", now=NOW)

            overlong = fixture_payload()
            overlong["items"][0].update(
                {
                    "quote_candidate": True,
                    "quote_window_ends_at": "2026-08-10T10:00:01+00:00",
                }
            )
            with self.assertRaises(ValueError):
                ingest_signals(Path(tmp) / "overlong", overlong, collector="grok-build", now=NOW)

            payload = fixture_payload()
            payload["items"][0]["source_url"] = None
            with self.assertRaises(ValueError):
                ingest_signals(Path(tmp), payload, collector="grok-build", now=NOW)

    def test_reply_candidate_uses_the_same_verified_time_window_boundary(self):
        with TemporaryDirectory() as tmp:
            payload = fixture_payload()
            payload["items"][0].update(
                {
                    "reply_candidate": True,
                    "reply_window_ends_at": "2026-08-08T10:00:00+00:00",
                }
            )
            ingest_signals(Path(tmp), payload, collector="grok-build", now=NOW)
            properties, body = read_frontmatter(
                Path(tmp) / "01. Signal" / signal_filename("x:3001")
            )
            self.assertTrue(properties["reply_candidate"])
            self.assertEqual(properties["signal_type"], "reply_candidate")
            self.assertIn("## Reply 机会", body)

            invalid = fixture_payload()
            invalid["items"][0].update({"reply_candidate": True})
            with self.assertRaises(ValueError):
                ingest_signals(Path(tmp) / "invalid", invalid, collector="grok-build", now=NOW)


if __name__ == "__main__":
    unittest.main()
