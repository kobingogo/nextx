import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from nextx.record_index import indexed_records, resolve_record_path
from nextx.vault import init_vault


def signal_note(signal_id: str, *, account_key: str | None = "primary") -> str:
    account_key_line = (
        f'account_key: "{account_key}"\n' if account_key is not None else ""
    )
    return f'''---
schema_version: 1
{account_key_line}id: "{signal_id}"
type: "signal"
---

# Signal
'''


class RecordIndexTests(unittest.TestCase):
    def test_resolver_falls_back_to_markdown_when_index_is_missing_or_corrupt(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            init_vault(vault)
            expected = vault / "01. Signal" / "readable.md"
            expected.write_text(signal_note("x:42"), encoding="utf-8")
            index = vault / ".nextx" / "index.json"
            index.parent.mkdir(parents=True, exist_ok=True)
            index.write_text("not-json", encoding="utf-8")

            self.assertEqual(
                resolve_record_path(vault, "01. Signal", "signal", "x:42"),
                expected,
            )

    def test_index_is_rebuildable_and_excludes_another_account(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            init_vault(vault)
            primary = vault / "01. Signal" / "primary.md"
            accountless = vault / "01. Signal" / "accountless.md"
            other = vault / "01. Signal" / "other.md"
            primary.write_text(signal_note("x:1"), encoding="utf-8")
            accountless.write_text(signal_note("x:missing", account_key=None), encoding="utf-8")
            other.write_text(signal_note("x:2", account_key="other"), encoding="utf-8")

            records = indexed_records(vault, "01. Signal", "signal")

            self.assertEqual([path for path, _ in records], [primary])
            payload = json.loads((vault / ".nextx" / "index.json").read_text())
            self.assertEqual(payload["schema_version"], 1)
            self.assertIn("primary.md", payload["folders"]["01. Signal"])
            self.assertNotIn("accountless.md", payload["folders"]["01. Signal"])
            self.assertNotIn("other.md", payload["folders"]["01. Signal"])

    def test_identity_mismatch_is_never_returned_from_a_stale_cache(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            init_vault(vault)
            path = vault / "01. Signal" / "same-name.md"
            path.write_text(signal_note("x:1"), encoding="utf-8")
            indexed_records(vault, "01. Signal", "signal")
            path.write_text(signal_note("x:2"), encoding="utf-8")

            with self.assertRaises(FileNotFoundError):
                resolve_record_path(vault, "01. Signal", "signal", "x:1")

    def test_poisoned_cache_cannot_move_another_account_into_primary_results(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            init_vault(vault)
            path = vault / "01. Signal" / "poisoned.md"
            path.write_text(signal_note("x:other", account_key="other"), encoding="utf-8")
            stat = path.stat()
            index = vault / ".nextx" / "index.json"
            index.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "folders": {
                            "01. Signal": {
                                path.name: {
                                    "mtime_ns": stat.st_mtime_ns,
                                    "size": stat.st_size,
                                    "properties": {
                                        "account_key": "primary",
                                        "id": "x:poisoned",
                                        "type": "signal",
                                    },
                                }
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(indexed_records(vault, "01. Signal", "signal"), [])
            refreshed = json.loads(index.read_text(encoding="utf-8"))
            self.assertNotIn("poisoned.md", refreshed["folders"]["01. Signal"])

    def test_resolver_ignores_traversal_cache_entries_and_scans_the_folder(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            init_vault(vault)
            expected = vault / "01. Signal" / "readable.md"
            expected.write_text(signal_note("x:42"), encoding="utf-8")
            outside = vault / "outside.md"
            outside.write_text(signal_note("x:42"), encoding="utf-8")
            index = vault / ".nextx" / "index.json"
            index.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "folders": {
                            "01. Signal": {
                                str(outside): {"properties": {"id": "x:42"}}
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                resolve_record_path(vault, "01. Signal", "signal", "x:42"),
                expected,
            )
