from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from nextx.vault import _pid_is_running, init_vault, read_state, recover_vault_lock, vault_lock


class VaultTests(unittest.TestCase):
    def test_init_creates_stable_type_folders_and_state(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)

            init_vault(vault)

            self.assertTrue((vault / "00. Self").is_dir())
            self.assertTrue((vault / "01. Signal").is_dir())
            self.assertTrue((vault / "01. Topic").is_dir())
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

    def test_stale_owned_lock_is_recovered_automatically(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            init_vault(vault)
            lock = vault / ".nextx" / "sync.lock"
            lock.mkdir()
            (lock / "owner.json").write_text(
                '{"schema_version":1,"pid":999999,"hostname":"test-host"}',
                encoding="utf-8",
            )

            with patch("nextx.vault.socket.gethostname", return_value="test-host"), patch(
                "nextx.vault._pid_is_running", return_value=False
            ):
                result = recover_vault_lock(vault)

            self.assertEqual(result["status"], "recovered")
            self.assertEqual(result["reason"], "stale_owner")
            self.assertFalse(lock.exists())

    def test_ownerless_legacy_lock_requires_force(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            init_vault(vault)
            lock = vault / ".nextx" / "sync.lock"
            lock.mkdir()

            with self.assertRaises(RuntimeError):
                recover_vault_lock(vault)
            result = recover_vault_lock(vault, force=True)

            self.assertEqual(result["reason"], "forced_legacy_lock")
            self.assertFalse(lock.exists())

    def test_other_host_lock_is_never_force_removed(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            init_vault(vault)
            lock = vault / ".nextx" / "sync.lock"
            lock.mkdir()
            (lock / "owner.json").write_text(
                '{"schema_version":1,"pid":1,"hostname":"another-host"}',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "another host"):
                recover_vault_lock(vault, force=True)

    def test_windows_pid_probe_does_not_use_posix_signal_zero(self):
        with patch("nextx.vault.os.name", "nt"), patch(
            "nextx.vault._windows_pid_is_running", return_value=True
        ) as probe, patch("nextx.vault.os.kill") as kill:
            self.assertTrue(_pid_is_running(42))

        probe.assert_called_once_with(42)
        kill.assert_not_called()


if __name__ == "__main__":
    unittest.main()
