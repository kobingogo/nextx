from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SkillContractTests(unittest.TestCase):
    def test_phase_one_commands_and_contract_are_documented(self):
        skill_text = (ROOT / "skills" / "nextx" / "SKILL.md").read_text(encoding="utf-8")
        contracts_text = (
            ROOT / "skills" / "nextx" / "references" / "contracts.md"
        ).read_text(encoding="utf-8")
        operations_text = (ROOT / "docs" / "OPERATIONS.md").read_text(encoding="utf-8")
        getting_started_text = (
            ROOT / "docs" / "GETTING_STARTED.md"
        ).read_text(encoding="utf-8")

        self.assertIn("triage-input.v1.json", contracts_text)
        self.assertIn("contracts --name triage", skill_text)
        self.assertIn("triage-brief", skill_text)
        self.assertIn("save-triage", skill_text)
        self.assertIn("migrate-signal-usability", operations_text)
        self.assertIn("signal-inbox", getting_started_text)

    def test_topic_foundation_commands_and_contracts_are_documented(self):
        skill_text = (ROOT / "skills" / "nextx" / "SKILL.md").read_text(encoding="utf-8")
        contracts_text = (
            ROOT / "skills" / "nextx" / "references" / "contracts.md"
        ).read_text(encoding="utf-8")
        operations_text = (ROOT / "docs" / "OPERATIONS.md").read_text(encoding="utf-8")
        getting_started_text = (
            ROOT / "docs" / "GETTING_STARTED.md"
        ).read_text(encoding="utf-8")

        self.assertIn("cluster-input.v1.json", contracts_text)
        self.assertIn("topic-input.v1.json", contracts_text)
        self.assertIn("cluster-brief", skill_text)
        self.assertIn("save-topic", skill_text)
        self.assertIn("topic-decision-brief", operations_text)
        self.assertIn("Cluster Brief", getting_started_text)
