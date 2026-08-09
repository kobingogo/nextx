from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from nextx.bookmarks import read_bookmark_health, sync_bookmarks
from nextx.records import read_frontmatter
from nextx.signals import signal_filename
from nextx.vault import read_state


FIXTURE = Path(__file__).parent / "fixtures" / "bookmarks.json"
NOW = datetime(2026, 8, 7, 10, 0, tzinfo=timezone.utc)


def fixture_payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class BookmarkSyncTests(unittest.TestCase):
    def test_sync_creates_two_signals_and_state(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)

            report = sync_bookmarks(vault, fixture_payload(), now=NOW)

            first = vault / "01. Signal" / signal_filename("x:2084556671712477485")
            self.assertEqual(report.created, 2)
            self.assertTrue(first.exists())
            self.assertIn('analysis_status: "pending"', first.read_text(encoding="utf-8"))
            properties, _ = read_frontmatter(first)
            self.assertEqual(properties["schema_version"], 1)
            self.assertEqual(properties["account_key"], "primary")
            self.assertEqual(properties["id"], "x:2084556671712477485")
            self.assertEqual(
                read_state(vault)["seen_ids"],
                ["2084556671712477485", "2084556671712477486"],
            )

    def test_second_sync_is_duplicate_and_preserves_manual_edit(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            sync_bookmarks(vault, fixture_payload(), now=NOW)
            first = vault / "01. Signal" / signal_filename("x:2084556671712477485")
            original = first.read_text(encoding="utf-8") + "\nmanual note\n"
            first.write_text(original, encoding="utf-8")

            report = sync_bookmarks(vault, fixture_payload(), now=NOW)

            self.assertEqual(report.created, 0)
            self.assertEqual(report.duplicates, 2)
            self.assertEqual(first.read_text(encoding="utf-8"), original)

    def test_invalid_item_rejects_whole_batch_before_writes(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            payload = fixture_payload()
            del payload["data"][1]["id"]

            with self.assertRaises(ValueError):
                sync_bookmarks(vault, payload, now=NOW)

            self.assertFalse((vault / "01. Signal").exists())
            self.assertIsNone(read_state(vault)["last_success_at"])

    def test_dry_run_writes_nothing(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)

            report = sync_bookmarks(vault, fixture_payload(), dry_run=True, now=NOW)

            self.assertTrue(report.dry_run)
            self.assertEqual(report.created, 2)
            self.assertFalse(
                (vault / "01. Signal" / signal_filename("x:2084556671712477485")).exists()
            )
            self.assertIsNone(read_state(vault)["last_success_at"])

    def test_explicit_reconciliation_marks_absent_bookmarks_inactive(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            sync_bookmarks(vault, fixture_payload(), now=NOW)
            reduced = fixture_payload()
            reduced["data"] = reduced["data"][:1]
            reduced["snapshot_complete"] = True

            report = sync_bookmarks(
                vault,
                reduced,
                reconcile=True,
                snapshot_complete=True,
                now=NOW.replace(hour=11),
            )
            retained, _ = read_frontmatter(
                vault / "01. Signal" / signal_filename("x:2084556671712477485")
            )
            removed, _ = read_frontmatter(
                vault / "01. Signal" / signal_filename("x:2084556671712477486")
            )

            self.assertEqual(report.refreshed, 1)
            self.assertEqual(report.deactivated, 1)
            self.assertTrue(retained["bookmark_active"])
            self.assertFalse(removed["bookmark_active"])
            self.assertEqual(read_bookmark_health(vault)["status"], "ready")

    def test_reconciliation_rejects_an_unproven_partial_snapshot(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            sync_bookmarks(vault, fixture_payload(), now=NOW)
            reduced = fixture_payload()
            reduced["data"] = reduced["data"][:1]

            with self.assertRaisesRegex(ValueError, "complete snapshot"):
                sync_bookmarks(vault, reduced, reconcile=True, now=NOW.replace(hour=11))


if __name__ == "__main__":
    unittest.main()
