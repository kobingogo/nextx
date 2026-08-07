import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from nextx.analysis import build_analysis_brief
from nextx.signals import ingest_signals


FIXTURE = Path(__file__).parent / "fixtures" / "grok-signals.json"


class AnalysisTests(unittest.TestCase):
    def test_bare_and_prefixed_x_id_build_the_same_bounded_brief(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            ingest_signals(
                vault,
                json.loads(FIXTURE.read_text(encoding="utf-8")),
                collector="grok-build",
            )

            bare = build_analysis_brief(vault, "3001")
            prefixed = build_analysis_brief(vault, "x:3001")

            self.assertEqual(bare["signal_path"], prefixed["signal_path"])
            self.assertIn("事实 / 原帖观点 / 推断", bare["brief"])
            for heading in ("内容结构", "钩子", "传播机制", "可迁移方法", "风险与反证"):
                self.assertIn(heading, bare["brief"])
            self.assertNotIn("01. Signal/", bare["brief"])

    def test_unknown_signal_is_rejected(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                build_analysis_brief(Path(tmp), "9999")


if __name__ == "__main__":
    unittest.main()
