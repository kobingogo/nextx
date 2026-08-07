from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from nextx.vault import init_vault, read_state, vault_lock


class VaultTests(unittest.TestCase):
    def test_init_creates_stable_type_folders_and_state(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)

            init_vault(vault)

            self.assertTrue((vault / "00. Self").is_dir())
            self.assertTrue((vault / "01. Signal").is_dir())
            self.assertTrue((vault / "02. Decision").is_dir())
            self.assertTrue((vault / "03. Artifact").is_dir())
            self.assertTrue((vault / "04. Views").is_dir())
            self.assertEqual(read_state(vault)["seen_ids"], [])

    def test_existing_lock_fails_immediately(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            init_vault(vault)

            with vault_lock(vault):
                with self.assertRaises(RuntimeError):
                    with vault_lock(vault):
                        pass


if __name__ == "__main__":
    unittest.main()
