from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from nextx.strategy_snapshot import strategy_snapshot_id
from nextx.vault import init_vault


class StrategySnapshotTests(unittest.TestCase):
    def test_same_self_content_has_the_same_snapshot_across_line_endings(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            init_vault(vault)
            profile = vault / "00. Self" / "Profile.md"
            profile.write_text("# Profile\r\nAI workflow\r\n", encoding="utf-8")

            first = strategy_snapshot_id(vault)

            profile.write_text("# Profile\nAI workflow\n", encoding="utf-8")
            self.assertEqual(first, strategy_snapshot_id(vault))

    def test_a_strategy_change_changes_the_snapshot(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            init_vault(vault)
            strategy = vault / "00. Self" / "Growth Strategy.md"
            strategy.write_text("builder core\n", encoding="utf-8")

            first = strategy_snapshot_id(vault)

            strategy.write_text("general AI users\n", encoding="utf-8")
            self.assertNotEqual(first, strategy_snapshot_id(vault))

    def test_missing_files_have_a_stable_snapshot(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            init_vault(vault)

            first = strategy_snapshot_id(vault)

            self.assertEqual(first, strategy_snapshot_id(vault))


if __name__ == "__main__":
    unittest.main()
