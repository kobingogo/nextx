from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from nextx.signals import add_manual_signal, ingest_signals
from nextx.vault import atomic_write_text, init_vault
from nextx.views import render_today


BASE = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)


def collector_payload(count=14):
    items = []
    for index in range(count):
        author = "crowded" if index < 5 else f"author{index}"
        items.append(
            {
                "source_id": f"x:{5000 + index}",
                "platform": "x",
                "source_url": f"https://x.com/{author}/status/{5000 + index}",
                "author_handle": author,
                "published_at": (BASE + timedelta(minutes=index)).isoformat(),
                "text": f"Signal {index}",
                "metrics": {"views": index * 10},
                "media": [],
                "source_confidence": "high",
                "discovery_reason": "test",
            }
        )
    return {
        "schema_version": 1,
        "account_key": "primary",
        "collector": "grok-build",
        "retrieved_at": BASE.isoformat(),
        "items": items,
    }


class ViewTests(unittest.TestCase):
    def test_today_caps_auto_manual_and_author_and_excludes_decided(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            ingest_signals(vault, collector_payload(), collector="grok-build", now=BASE)
            for index in range(3):
                add_manual_signal(
                    vault,
                    f"manual {index}",
                    now=BASE + timedelta(minutes=20 + index),
                )
            init_vault(vault)
            atomic_write_text(
                vault / "02. Decision" / "decision-existing.md",
                '---\nid: "decision:existing"\ntype: "decision"\nverdict: "kill"\nsignal_ids: ["x:5013"]\n---\nAlready decided.\n',
            )

            result = render_today(vault, now=BASE + timedelta(hours=1))

            self.assertLessEqual(result["automatic_count"], 10)
            self.assertEqual(result["manual_count"], 2)
            self.assertNotIn("x:5013", result["selected_ids"])
            selected_text = (vault / "04. Views" / "Today.md").read_text(encoding="utf-8")
            self.assertLessEqual(selected_text.count("@crowded"), 2)

    def test_rebuild_only_replaces_view_not_source(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            ingest_signals(vault, collector_payload(1), collector="grok-build", now=BASE)
            signal = vault / "01. Signal" / "x-5000.md"
            signal.write_text(signal.read_text(encoding="utf-8") + "\nmanual source note\n", encoding="utf-8")

            render_today(vault, now=BASE)
            view = vault / "04. Views" / "Today.md"
            view.write_text("temporary view edit", encoding="utf-8")
            render_today(vault, now=BASE)

            self.assertNotEqual(view.read_text(encoding="utf-8"), "temporary view edit")
            self.assertIn("manual source note", signal.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
