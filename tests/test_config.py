import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from nextx.config import (
    default_vault,
    load_user_config,
    config_snapshot,
    resolve_vault,
    setup_vault,
    user_config_path,
)


class ConfigTests(unittest.TestCase):
    def test_default_vault_is_documents_nextx(self):
        self.assertEqual(default_vault(), Path.home() / "Documents" / "NextX")

    def test_resolve_vault_uses_explicit_then_environment_then_config_then_default(self):
        with TemporaryDirectory() as tmp:
            config_home = Path(tmp) / "config"
            configured = Path(tmp) / "configured"
            env_vault = Path(tmp) / "env"
            explicit = Path(tmp) / "explicit"
            config_home.mkdir()
            (config_home / "nextx").mkdir()
            (config_home / "nextx" / "config.json").write_text(
                json.dumps({"schema_version": 1, "vault": str(configured)}),
                encoding="utf-8",
            )
            with patch.dict("os.environ", {"XDG_CONFIG_HOME": str(config_home), "NEXTX_VAULT": str(env_vault)}):
                self.assertEqual(resolve_vault(explicit), explicit.resolve())
                self.assertEqual(resolve_vault(None), env_vault.resolve())
                with patch.dict("os.environ", {"XDG_CONFIG_HOME": str(config_home)}, clear=True):
                    self.assertEqual(resolve_vault(None), configured.resolve())
                with patch.dict("os.environ", {"XDG_CONFIG_HOME": str(Path(tmp) / "empty")}, clear=True):
                    self.assertEqual(resolve_vault(None), default_vault().resolve())

    def test_setup_creates_vault_and_preserves_existing_markdown(self):
        with TemporaryDirectory() as tmp:
            config_home = Path(tmp) / "config"
            vault = Path(tmp) / "vault"
            with patch.dict("os.environ", {"XDG_CONFIG_HOME": str(config_home)}, clear=True):
                first = setup_vault(vault, runtime=Path(tmp) / "runtime")
                profile = vault / "00. Self" / "Profile.md"
                profile.write_text("# 我的定位\n\n已手工填写\n", encoding="utf-8")
                second = setup_vault(vault, runtime=Path(tmp) / "runtime")
                self.assertTrue(first["ok"])
                self.assertTrue(second["ok"])
                self.assertEqual(profile.read_text(encoding="utf-8"), "# 我的定位\n\n已手工填写\n")
                saved = json.loads(user_config_path().read_text(encoding="utf-8"))
                self.assertEqual(Path(saved["vault"]).resolve(), vault.resolve())
                self.assertEqual(Path(saved["runtime"]).resolve(), (Path(tmp) / "runtime").resolve())
                self.assertIn("setup_at", saved)
                repaired = setup_vault(vault)
                preserved = json.loads(user_config_path().read_text(encoding="utf-8"))
                self.assertEqual(Path(preserved["runtime"]).resolve(), (Path(tmp) / "runtime").resolve())
                self.assertEqual(Path(repaired["runtime"]).resolve(), (Path(tmp) / "runtime").resolve())

    def test_config_snapshot_reports_optional_twitter_capability(self):
        with TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {"XDG_CONFIG_HOME": str(Path(tmp) / "config")}, clear=True):
                with patch("nextx.config.shutil.which", return_value=None):
                    snapshot = config_snapshot()
            self.assertEqual(snapshot["twitter_binary"], "missing")

    def test_corrupt_user_config_is_actionable(self):
        with TemporaryDirectory() as tmp:
            config_home = Path(tmp) / "config"
            path = config_home / "nextx" / "config.json"
            path.parent.mkdir(parents=True)
            path.write_text("not json", encoding="utf-8")
            with patch.dict("os.environ", {"XDG_CONFIG_HOME": str(config_home)}, clear=True):
                with self.assertRaisesRegex(ValueError, "config"):
                    load_user_config()

    def test_setup_with_explicit_vault_repairs_corrupt_user_config(self):
        with TemporaryDirectory() as tmp:
            config_home = Path(tmp) / "config"
            path = config_home / "nextx" / "config.json"
            path.parent.mkdir(parents=True)
            path.write_text("not json", encoding="utf-8")
            vault = Path(tmp) / "vault"
            with patch.dict("os.environ", {"XDG_CONFIG_HOME": str(config_home)}, clear=True):
                result = setup_vault(vault)
            self.assertTrue(result["ok"])
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["vault"], str(vault.resolve()))


if __name__ == "__main__":
    unittest.main()
