import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from nextx.self_model import ensure_self_templates
from nextx.vault import init_vault


class SelfModelTests(unittest.TestCase):
    def test_templates_and_primary_account_config_are_created(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            init_vault(vault)

            created = ensure_self_templates(vault)

            names = {path.name for path in created}
            self.assertEqual(
                names,
                {"Profile.md", "Voice.md", "Pillars.md", "Monitoring.md", "Playbook.md"},
            )
            config = json.loads((vault / ".nextx" / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(config, {"schema_version": 1, "account_key": "primary"})

    def test_second_bootstrap_preserves_manual_self_edit(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            init_vault(vault)
            ensure_self_templates(vault)
            profile = vault / "00. Self" / "Profile.md"
            profile.write_text(profile.read_text(encoding="utf-8") + "\nMy positioning.\n", encoding="utf-8")

            created = ensure_self_templates(vault)

            self.assertEqual(created, [])
            self.assertIn("My positioning.", profile.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
