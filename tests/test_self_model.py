import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from nextx.self_model import configure_self, ensure_self_templates, growth_strategy, self_readiness
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
                {
                    "Profile.md",
                    "Voice.md",
                    "Pillars.md",
                    "Monitoring.md",
                    "Growth Strategy.md",
                    "Playbook.md",
                },
            )
            config = json.loads((vault / ".nextx" / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(config["schema_version"], 1)
            self.assertEqual(config["account_key"], "primary")
            self.assertEqual(
                config["accounts"]["primary"], {"status": "active", "storage": "this_vault"}
            )

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

    def test_readiness_identifies_the_missing_editorial_inputs(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)

            initial = self_readiness(vault)
            self.assertFalse(initial["ready"])
            self.assertIn("尚未初始化", initial["missing"][0])
            self.assertFalse((vault / "00. Self").exists())
            ensure_self_templates(vault)

            profile = vault / "00. Self" / "Profile.md"
            profile.write_text(
                profile.read_text(encoding="utf-8").replace(
                    "## 一句话定位\n", "## 一句话定位\n\nLocal AI tools for solo operators.\n"
                ),
                encoding="utf-8",
            )
            voice = vault / "00. Self" / "Voice.md"
            voice.write_text(
                voice.read_text(encoding="utf-8").replace(
                    "## 真实优秀样本\n", "## 真实优秀样本\n\nA real sentence written by the operator.\n"
                ),
                encoding="utf-8",
            )
            pillars = vault / "00. Self" / "Pillars.md"
            pillars.write_text(
                pillars.read_text(encoding="utf-8").replace("1.\n2.\n3.", "1. AI workflow\n2. Product strategy\n3. X operations")
                + "\nNo recycled growth hacks.\n",
                encoding="utf-8",
            )

            self.assertTrue(self_readiness(vault)["ready"])

    def test_readiness_without_initialization_never_writes_templates(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp) / "uninitialized"

            result = self_readiness(vault, initialize=False)

            self.assertFalse(result["ready"])
            self.assertFalse(vault.exists())

    def test_account_registry_refuses_mixed_account_configuration(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            init_vault(vault)
            (vault / ".nextx" / "config.json").write_text(
                '{"schema_version":1,"account_key":"primary","accounts":{"secondary":{}}}',
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                ensure_self_templates(vault)

    def test_explicit_conversational_configuration_populates_self_and_preserves_templates(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            result = configure_self(
                vault,
                {
                    "schema_version": 1,
                    "account_key": "primary",
                    "positioning": "Local-first X operations for solo builders.",
                    "audience": "Builders using AI agents.",
                    "stage": "冷启动",
                    "pillars": ["Agent workflow", "Product systems", "X operations"],
                    "boundaries": "不转发未经核验的增长承诺。",
                    "voice_samples": ["先把问题做小，再把闭环做实。"],
                    "goals": "稳定产出一条高质量帖。",
                    "growth_strategy": {
                        "stage": "launch",
                        "objective": "awareness",
                        "target_reader": "Builders using AI agents.",
                        "profile_promise": "Turn local operations into an evidence-backed loop.",
                        "cta": "Save the next decision template.",
                        "weekly_focus": "Add useful replies before increasing original posts.",
                        "lane_allocation": {"discovery": 3, "authority": 1, "conversion": 0},
                    },
                },
            )

            self.assertTrue(result["ready"])
            self.assertIn("Local-first X operations", (vault / "00. Self" / "Profile.md").read_text(encoding="utf-8"))
            self.assertIn("1. Agent workflow", (vault / "00. Self" / "Pillars.md").read_text(encoding="utf-8"))
            self.assertIn("先把问题做小", (vault / "00. Self" / "Voice.md").read_text(encoding="utf-8"))
            self.assertTrue(result["growth_ready"])
            self.assertEqual(growth_strategy(vault)["objective"], "awareness")
            self.assertIn("本周唯一目标：awareness", (vault / "00. Self" / "Growth Strategy.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
