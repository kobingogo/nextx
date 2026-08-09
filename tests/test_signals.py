from contextlib import contextmanager
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
    migrate_signal_usability,
    signal_filename,
    signal_path,
)


FIXTURE = Path(__file__).parent / "fixtures" / "grok-signals.json"
SCHEMA = Path(__file__).parents[1] / "schemas" / "collector-envelope.v1.json"
NOW = datetime(2026, 8, 7, 11, 0, tzinfo=timezone.utc)


def fixture_payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class SignalTests(unittest.TestCase):
    def write_legacy_signal(
        self,
        vault: Path,
        signal_id: str,
        *,
        display_title: str | None = "Agent workflow evidence",
        account_key: str = "primary",
        aliases: object | None = None,
    ) -> Path:
        directory = vault / "01. Signal"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / str(legacy_signal_filename(signal_id))
        properties = [
            "---",
            'schema_version: 1',
            f"account_key: {json.dumps(account_key)}",
            f"id: {json.dumps(signal_id)}",
            'type: "signal"',
            'platform: "x"',
            'author_handle: "alpha"',
            'published_at: "2026-08-07T10:00:00+00:00"',
        ]
        if display_title is not None:
            properties.append(f"display_title: {json.dumps(display_title)}")
        if aliases is not None:
            properties.append(f"aliases: {json.dumps(aliases)}")
        properties.extend(["---", "", f"# Signal · {signal_id}", ""])
        path.write_text("\n".join(properties), encoding="utf-8")
        return path

    def test_grok_import_normalizes_versioned_signals(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)

            report = ingest_signals(vault, fixture_payload(), collector="grok-build", now=NOW)

            self.assertEqual(report.created, 2)
            first_path = signal_path(vault, "x:3001")
            first, body = read_frontmatter(first_path)
            second, _ = read_frontmatter(signal_path(vault, "x:3002"))
            self.assertEqual(first["schema_version"], 1)
            self.assertEqual(first["account_key"], "primary")
            self.assertEqual(first["collector"], "grok-build")
            self.assertEqual(first["display_title"], "A verifiable trend signal.")
            self.assertEqual(first["triage_status"], "pending")
            self.assertIn("尚未判断。", body)
            self.assertIn("__x__", first_path.name)
            self.assertEqual(second["id"], "x:3002")

    def test_second_import_is_fully_deduplicated(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            ingest_signals(vault, fixture_payload(), collector="grok-build", now=NOW)

            report = ingest_signals(vault, fixture_payload(), collector="grok-build", now=NOW)

            self.assertEqual(report.created, 0)
            self.assertEqual(report.duplicates, 2)

    def test_duplicate_identity_skips_hostile_filename_metadata(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            original = {
                "schema_version": 1,
                "account_key": "primary",
                "collector": "file-import",
                "retrieved_at": NOW.isoformat(),
                "items": [
                    {
                        "source_id": "feed:duplicate",
                        "platform": "rss",
                        "text": "A stable identity already exists.",
                        "source_confidence": "high",
                    }
                ],
            }
            duplicate = {
                **original,
                "items": [
                    {
                        **original["items"][0],
                        "platform": "网" * 64,
                        "author_handle": "作" * 64,
                    }
                ],
            }
            ingest_signals(vault, original, collector="file-import", now=NOW)

            report = ingest_signals(vault, duplicate, collector="file-import", now=NOW)

            self.assertEqual(report.created, 0)
            self.assertEqual(report.duplicates, 1)
            self.assertEqual(len(list((vault / "01. Signal").glob("*.md"))), 1)

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
            canonical = signal_path(vault, "x:3001")
            legacy_name = legacy_signal_filename("x:3001")
            self.assertIsNotNone(legacy_name)
            legacy = vault / "01. Signal" / str(legacy_name)
            canonical.rename(legacy)

            self.assertEqual(signal_path(vault, "x:3001"), legacy)

    def test_explicit_migration_renames_legacy_signal_and_keeps_an_obsidian_alias(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            ingest_signals(vault, fixture_payload(), collector="grok-build", now=NOW)
            source = signal_path(vault, "x:3001")
            canonical = vault / "01. Signal" / signal_filename("x:3001")
            legacy = vault / "01. Signal" / str(legacy_signal_filename("x:3001"))
            source.rename(legacy)

            preview = migrate_signal_filenames(vault)
            result = migrate_signal_filenames(vault, dry_run=False)

            self.assertEqual(len(preview["planned"]), 1)
            self.assertEqual(len(result["migrated"]), 1)
            self.assertFalse(legacy.exists())
            properties, _ = read_frontmatter(canonical)
            self.assertIn("x-3001", properties["aliases"])

    def test_usability_migration_blocks_records_without_display_title(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            path = self.write_legacy_signal(vault, "x:42", display_title=None)

            result = migrate_signal_usability(vault)

            self.assertEqual(result["planned"], [])
            self.assertEqual(result["blocked"][0]["reason"], "missing_display_title")
            self.assertTrue(path.exists())

    def test_usability_migration_previews_then_renames_with_an_alias(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            old = self.write_legacy_signal(
                vault, "x:42", display_title="Agent workflow evidence"
            )

            preview = migrate_signal_usability(vault)

            self.assertTrue(old.exists())
            self.assertIn("Agent-workflow-evidence", preview["planned"][0]["target"])

            applied = migrate_signal_usability(vault, dry_run=False)

            new = Path(applied["migrated"][0]["target"])
            properties, _ = read_frontmatter(new)
            self.assertFalse(old.exists())
            self.assertIn(old.stem, properties["aliases"])
            self.assertEqual(signal_path(vault, "x:42"), new)

    def test_usability_migration_ignores_other_accounts_and_reports_human_path_unchanged(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            other = self.write_legacy_signal(vault, "x:41", account_key="other")
            source = self.write_legacy_signal(vault, "x:42")
            target = Path(migrate_signal_usability(vault)["planned"][0]["target"])
            source.rename(target)

            result = migrate_signal_usability(vault)

            self.assertEqual(result["planned"], [])
            self.assertEqual(result["blocked"], [])
            self.assertEqual(result["conflicts"], [])
            self.assertEqual(result["unchanged"][0]["id"], "x:42")
            self.assertTrue(other.exists())

    def test_usability_migration_reports_existing_target_as_a_conflict(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            source = self.write_legacy_signal(vault, "x:42")
            target = Path(migrate_signal_usability(vault)["planned"][0]["target"])
            target.write_text("occupied", encoding="utf-8")

            result = migrate_signal_usability(vault)

            self.assertFalse(result["ok"])
            self.assertEqual(result["planned"], [])
            self.assertEqual(result["conflicts"][0]["source"], str(source))
            self.assertEqual(result["conflicts"][0]["target"], str(target))

    def test_usability_migration_apply_with_any_conflict_renames_nothing(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            movable = self.write_legacy_signal(vault, "x:41", display_title="Movable")
            conflicted = self.write_legacy_signal(vault, "x:42", display_title="Occupied")
            preview = migrate_signal_usability(vault)
            target = Path(
                next(item["target"] for item in preview["planned"] if item["id"] == "x:42")
            )
            target.write_text("occupied", encoding="utf-8")

            result = migrate_signal_usability(vault, dry_run=False)

            self.assertFalse(result["ok"])
            self.assertEqual(result["migrated"], [])
            self.assertTrue(movable.exists())
            self.assertTrue(conflicted.exists())

    def test_usability_migration_rechecks_every_source_before_first_mutation(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            first = self.write_legacy_signal(vault, "x:41", display_title="First")
            changed = self.write_legacy_signal(vault, "x:42", display_title="Second")
            before_first = first.read_bytes()

            @contextmanager
            def change_source_before_lock_checks(_vault):
                changed.write_text(
                    changed.read_text(encoding="utf-8") + "changed after preview\n",
                    encoding="utf-8",
                )
                yield

            with unittest.mock.patch(
                "nextx.signals.vault_lock", change_source_before_lock_checks
            ):
                with self.assertRaisesRegex(RuntimeError, "changed during migration"):
                    migrate_signal_usability(vault, dry_run=False)

            self.assertEqual(first.read_bytes(), before_first)
            self.assertTrue(first.exists())
            self.assertTrue(changed.exists())

    def test_usability_migration_dry_run_preserves_bytes_and_normalizes_safe_aliases_on_apply(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            source = self.write_legacy_signal(
                vault,
                "x:42",
                aliases=[" kept ", "", 7, "kept", "another"],
            )
            before = source.read_bytes()

            preview = migrate_signal_usability(vault)

            self.assertTrue(preview["dry_run"])
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual({path.name for path in source.parent.iterdir()}, {source.name})

            applied = migrate_signal_usability(vault, dry_run=False)
            properties, _ = read_frontmatter(Path(applied["migrated"][0]["target"]))
            self.assertEqual(properties["aliases"], ["kept", "another", source.stem])

    def test_manual_signal_uses_stable_content_hash(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)

            first = add_manual_signal(vault, "  My private idea  ", now=NOW)
            second = add_manual_signal(vault, "My private idea", now=NOW)

            self.assertEqual(first.created, 1)
            self.assertEqual(second.created, 0)
            self.assertEqual(second.duplicates, 1)
            records = list((vault / "01. Signal").glob("*.md"))
            self.assertEqual(len(records), 1)
            properties, _ = read_frontmatter(records[0])
            self.assertEqual(properties["display_title"], "My private idea")
            self.assertEqual(properties["triage_status"], "pending")

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
            properties, _ = read_frontmatter(signal_path(Path(tmp), "x:3001"))
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
            properties, body = read_frontmatter(signal_path(Path(tmp), "x:3001"))

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
            properties, body = read_frontmatter(signal_path(Path(tmp), "x:3001"))
            self.assertTrue(properties["reply_candidate"])
            self.assertEqual(properties["signal_type"], "reply_candidate")
            self.assertIn("## Reply 机会", body)

            invalid = fixture_payload()
            invalid["items"][0].update({"reply_candidate": True})
            with self.assertRaises(ValueError):
                ingest_signals(Path(tmp) / "invalid", invalid, collector="grok-build", now=NOW)

    def test_same_author_and_title_with_distinct_x_ids_creates_distinct_signals(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            payload = fixture_payload()
            payload["items"] = [
                {
                    **payload["items"][0],
                    "source_id": "x:9001",
                    "source_url": "https://x.com/alpha/status/9001",
                    "text": "The same readable title.",
                },
                {
                    **payload["items"][0],
                    "source_id": "x:9002",
                    "source_url": "https://x.com/alpha/status/9002",
                    "text": "The same readable title.",
                },
            ]

            first = ingest_signals(vault, payload, collector="grok-build", now=NOW)
            second = ingest_signals(
                vault,
                {**payload, "items": payload["items"][:1]},
                collector="grok-build",
                now=NOW,
            )

            self.assertEqual(first.created, 2)
            self.assertEqual(second.created, 0)
            self.assertEqual(second.duplicates, 1)
            self.assertEqual(len(list((vault / "01. Signal").glob("*.md"))), 2)
            self.assertNotEqual(signal_path(vault, "x:9001"), signal_path(vault, "x:9002"))


if __name__ == "__main__":
    unittest.main()
