from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from nextx.signals import add_manual_signal, ingest_signals, signal_filename
from nextx.records import update_frontmatter
from nextx.decisions import save_decision
from nextx.vault import atomic_write_text, init_vault
from nextx.views import render_quote_sprint, render_today


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
                '---\naccount_key: "primary"\nid: "decision:existing"\ntype: "decision"\nverdict: "kill"\nsignal_ids: ["x:5013"]\n---\nAlready decided.\n',
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
            signal = vault / "01. Signal" / signal_filename("x:5000")
            signal.write_text(signal.read_text(encoding="utf-8") + "\nmanual source note\n", encoding="utf-8")

            render_today(vault, now=BASE)
            view = vault / "04. Views" / "Today.md"
            view.write_text("temporary view edit", encoding="utf-8")
            render_today(vault, now=BASE)

            self.assertNotEqual(view.read_text(encoding="utf-8"), "temporary view edit")
            self.assertIn("manual source note", signal.read_text(encoding="utf-8"))

    def test_derived_index_is_rebuildable_and_invalidates_changed_files(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            ingest_signals(vault, collector_payload(2), collector="grok-build", now=BASE)

            render_today(vault, now=BASE)
            index = vault / ".nextx" / "index.json"
            self.assertTrue(index.exists())

            signal = vault / "01. Signal" / signal_filename("x:5000")
            update_frontmatter(signal, {"author_handle": "edited-author"})
            render_today(vault, now=BASE)
            self.assertIn(
                "@edited-author",
                (vault / "04. Views" / "Today.md").read_text(encoding="utf-8"),
            )

            index.write_text("[]", encoding="utf-8")
            render_today(vault, now=BASE)
            self.assertTrue(index.exists())

    def test_deferred_signal_returns_only_when_its_revisit_time_is_due(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            ingest_signals(vault, collector_payload(1), collector="grok-build", now=BASE)
            decision = save_decision(
                vault,
                {
                    "schema_version": 1,
                    "account_key": "primary",
                    "signal_ids": ["x:5000"],
                    "verdict": "defer",
                    "reason_code": "need_evidence",
                    "reason": "Wait for primary evidence.",
                    "revisit_at": (BASE + timedelta(hours=2)).isoformat(),
                    "revisit_reason": "Check whether a primary source appears.",
                },
                now=BASE,
            )
            self.assertEqual(decision["verdict"], "defer")

            early = render_today(vault, now=BASE + timedelta(hours=1))
            due = render_today(vault, now=BASE + timedelta(hours=3))

            self.assertNotIn("x:5000", early["selected_ids"])
            self.assertIn("x:5000", due["selected_ids"])
            self.assertIn("复访已到期", (vault / "04. Views" / "Today.md").read_text(encoding="utf-8"))

    def test_today_prefers_self_fit_and_deduplicates_same_content(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            payload = collector_payload(3)
            payload["items"][0].update({"self_fit": 0, "novelty": 0, "text": "Same repeated signal"})
            payload["items"][1].update({"self_fit": 5, "novelty": 4, "text": "Same repeated signal", "why_today": "A stronger angle emerged."})
            payload["items"][2].update({"self_fit": 1, "novelty": 0})
            ingest_signals(vault, payload, collector="grok-build", now=BASE)

            result = render_today(vault, now=BASE + timedelta(hours=1))
            view = (vault / "04. Views" / "Today.md").read_text(encoding="utf-8")

            self.assertIn("x:5001", result["selected_ids"])
            self.assertNotIn("x:5000", result["selected_ids"])
            self.assertIn("优先级", view)
            self.assertIn("A stronger angle emerged.", view)

    def test_today_keeps_reply_candidates_in_the_reply_sprint_lane(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            ingest_signals(vault, collector_payload(1), collector="grok-build", now=BASE)
            update_frontmatter(
                vault / "01. Signal" / signal_filename("x:5000"),
                {
                    "reply_candidate": True,
                    "reply_window_ends_at": (BASE + timedelta(days=1)).isoformat(),
                },
            )

            result = render_today(vault, now=BASE)

            self.assertNotIn("x:5000", result["selected_ids"])

    def test_views_ignore_records_from_another_account(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            ingest_signals(vault, collector_payload(1), collector="grok-build", now=BASE)
            update_frontmatter(
                vault / "01. Signal" / signal_filename("x:5000"), {"account_key": "other"}
            )

            result = render_today(vault, now=BASE)

            self.assertEqual(result["selected_ids"], [])

    def test_quote_sprint_caps_candidates_per_author_and_skips_expired(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            payload = collector_payload(8)
            payload["retrieved_at"] = (BASE + timedelta(minutes=15)).isoformat()
            for index, item in enumerate(payload["items"]):
                item.update(
                    {
                        "quote_candidate": True,
                        "quote_window_ends_at": (BASE + timedelta(hours=6)).isoformat(),
                        "self_fit": 5,
                        "novelty": 3,
                    }
                )
                if index == 0:
                    item["quote_window_ends_at"] = (BASE + timedelta(minutes=30)).isoformat()
            ingest_signals(vault, payload, collector="grok-build", now=BASE)

            result = render_quote_sprint(vault, now=BASE + timedelta(hours=1))
            view = (vault / "04. Views" / "Quote Sprint.md").read_text(encoding="utf-8")

            self.assertEqual(result["selected_count"], 3)
            self.assertEqual(result["expired_count"], 1)
            self.assertNotIn("x:5000", result["selected_ids"])
            self.assertIn("每位作者最多：1 条", view)


if __name__ == "__main__":
    unittest.main()
