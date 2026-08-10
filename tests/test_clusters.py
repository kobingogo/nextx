from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from nextx.clusters import build_cluster_brief, record_cluster_failure, render_topic_clusters, save_clusters
from nextx.contracts import contract_catalog
from nextx.records import update_frontmatter
from nextx.signals import ingest_signals, signal_path
from nextx.triage import save_triage


NOW = datetime(2026, 8, 10, 3, tzinfo=timezone.utc)


class ClusterBriefTests(unittest.TestCase):
    def test_brief_selects_only_current_ready_triaged_signals_without_writing(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            self._ingest(vault)
            self._save_ready(vault, "x:101")
            self._save_ready(vault, "x:102")
            before = {path.relative_to(vault): path.read_bytes() for path in vault.rglob("*") if path.is_file()}

            brief = build_cluster_brief(vault, now=NOW)

            after = {path.relative_to(vault): path.read_bytes() for path in vault.rglob("*") if path.is_file()}
            self.assertEqual(brief["command"], "cluster-brief")
            self.assertEqual(brief["signal_count"], 2)
            self.assertEqual(
                [item["signal_id"] for item in brief["context"]["signals"]],
                ["x:101", "x:102"],
            )
            self.assertIn("First raw source", brief["context"]["signals"][0]["source"])
            self.assertIn("<nextx-untrusted-data", brief["context"]["signals"][0]["source"])
            self.assertEqual(before, after)

    def test_strategy_changed_ready_triage_is_excluded_and_contract_is_public(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            self._ingest(vault)
            self._save_ready(vault, "x:101")
            (vault / "00. Self").mkdir(exist_ok=True)
            (vault / "00. Self" / "Growth Strategy.md").write_text("A changed strategy.", encoding="utf-8")

            brief = build_cluster_brief(vault, now=NOW)
            catalog = contract_catalog("cluster")

            self.assertEqual(brief["signal_count"], 0)
            self.assertTrue(catalog["ok"])
            self.assertTrue(Path(catalog["contracts"][0]["path"]).is_file())

    def test_save_projects_only_exact_evidence_and_rebuilds_the_topic_view(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            self._ingest(vault)
            self._save_ready(vault, "x:101")
            self._save_ready(vault, "x:102")
            brief = build_cluster_brief(vault, now=NOW)

            result = save_clusters(vault, self._payload(brief), now=NOW)
            view = render_topic_clusters(vault, now=NOW)

            self.assertEqual(result["saved"], 1)
            self.assertEqual(view["status"], "ready")
            self.assertTrue((vault / ".nextx" / "clusters.json").is_file())
            self.assertTrue((vault / ".nextx" / "topic-cluster-history.json").is_file())
            text = (vault / "04. Views" / "Topics" / "Topic Clusters.md").read_text(encoding="utf-8")
            self.assertIn("Reusable AI workflows", text)
            self.assertIn("First raw source", text)

    def test_save_rejects_forged_evidence_without_creating_a_projection(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            self._ingest(vault)
            self._save_ready(vault, "x:101")
            self._save_ready(vault, "x:102")
            payload = self._payload(build_cluster_brief(vault, now=NOW))
            payload["clusters"][0]["evidence"][0]["quote"] = "Forged evidence"

            with self.assertRaises(ValueError):
                save_clusters(vault, payload, now=NOW)

            self.assertFalse((vault / ".nextx" / "clusters.json").exists())

    def test_event_cluster_requires_a_signal_captured_within_72_hours(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            self._ingest(vault)
            self._save_ready(vault, "x:101")
            self._save_ready(vault, "x:102")
            for signal_id in ("x:101", "x:102"):
                update_frontmatter(signal_path(vault, signal_id), {"captured_at": (NOW - timedelta(hours=73)).isoformat()})
            payload = self._payload(build_cluster_brief(vault, now=NOW))
            payload["clusters"][0]["kind"] = "event"

            with self.assertRaisesRegex(ValueError, "72 hours"):
                save_clusters(vault, payload, now=NOW)

    def test_evergreen_cluster_needs_new_evidence_or_14_day_cooldown(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            self._ingest(vault)
            self._save_ready(vault, "x:101")
            self._save_ready(vault, "x:102")
            first = self._payload(build_cluster_brief(vault, now=NOW))
            save_clusters(vault, first, now=NOW)
            retry = self._payload(build_cluster_brief(vault, now=NOW + timedelta(days=1)))

            with self.assertRaisesRegex(ValueError, "14-day cooldown"):
                save_clusters(vault, retry, now=NOW + timedelta(days=1))

    def test_membership_is_unique_and_cluster_id_is_derived_not_agent_supplied(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            self._ingest(vault)
            self._save_ready(vault, "x:101")
            self._save_ready(vault, "x:102")
            payload = self._payload(build_cluster_brief(vault, now=NOW))
            duplicate = json.loads(json.dumps(payload["clusters"][0]))
            duplicate["display_title"] = "Duplicate membership"
            payload["clusters"].append(duplicate)

            with self.assertRaisesRegex(ValueError, "only one Cluster"):
                save_clusters(vault, payload, now=NOW)

            result = save_clusters(vault, self._payload(build_cluster_brief(vault, now=NOW)), now=NOW)
            snapshot = json.loads((vault / ".nextx" / "clusters.json").read_text(encoding="utf-8"))
            self.assertRegex(snapshot["clusters"][0]["cluster_id"], r"^cluster:[0-9a-f]{16}$")
            self.assertEqual(result["cluster_run_id"], snapshot["cluster_run_id"])

    def test_failed_save_state_overrides_an_old_ready_projection_in_the_view(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            self._ingest(vault)
            self._save_ready(vault, "x:101")
            self._save_ready(vault, "x:102")
            payload = self._payload(build_cluster_brief(vault, now=NOW))
            save_clusters(vault, payload, now=NOW)
            record_cluster_failure(vault, payload)

            view = render_topic_clusters(vault, now=NOW)
            self.assertEqual(view["status"], "failed")
            self.assertIn("Last save failed", Path(view["view"]).read_text(encoding="utf-8"))

    def test_integrity_invalid_current_snapshot_is_not_rendered_as_validated(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            self._ingest(vault)
            self._save_ready(vault, "x:101")
            self._save_ready(vault, "x:102")
            save_clusters(vault, self._payload(build_cluster_brief(vault, now=NOW)), now=NOW)
            snapshot_path = vault / ".nextx" / "clusters.json"
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            snapshot["clusters"][0]["display_title"] = "Forged validated Cluster"
            snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

            view = render_topic_clusters(vault, now=NOW)
            text = Path(view["view"]).read_text(encoding="utf-8")

            self.assertEqual(view["status"], "unavailable")
            self.assertEqual(view["cluster_count"], 0)
            self.assertNotIn("Forged validated Cluster", text)
            self.assertIn("No current validated cluster projection", text)

    def _payload(self, brief: dict[str, object]) -> dict[str, object]:
        return {
            "schema_version": 1,
            "account_key": "primary",
            "cluster_run_id": brief["cluster_run_id"],
            "clusters": [
                {
                    "kind": "evergreen",
                    "signal_ids": ["x:101", "x:102"],
                    "display_title": "Reusable AI workflows",
                    "proposition": "Reusable systems beat disposable prompt tricks.",
                    "confidence": "high",
                    "why_now": "Both sources are recent.",
                    "target_reader": "AI builders",
                    "candidate_angle": "Contrast systems with tricks.",
                    "recommended_next_step": "topic_card",
                    "evidence": [
                        {"signal_id": "x:101", "quote": "First raw source", "role": "support", "translation_status": "original"},
                        {"signal_id": "x:102", "quote": "Second raw source", "role": "counter", "translation_status": "original"},
                    ],
                }
            ], "adjacent_candidates": []
        }

    def _ingest(self, vault: Path) -> None:
        items = [
            {
                "source_id": "x:101",
                "platform": "x",
                "source_url": "https://x.com/one/status/101",
                "author_handle": "one",
                "published_at": (NOW - timedelta(hours=3)).isoformat(),
                "text": "First raw source",
                "source_confidence": "high",
            },
            {
                "source_id": "x:102",
                "platform": "x",
                "source_url": "https://x.com/two/status/102",
                "author_handle": "two",
                "published_at": (NOW - timedelta(hours=2)).isoformat(),
                "text": "Second raw source",
                "source_confidence": "high",
            },
            {
                "source_id": "x:103",
                "platform": "x",
                "source_url": "https://x.com/three/status/103",
                "author_handle": "three",
                "published_at": (NOW - timedelta(hours=1)).isoformat(),
                "text": "Untriaged signal",
                "source_confidence": "high",
            },
        ]
        ingest_signals(
            vault,
            {"schema_version": 1, "account_key": "primary", "collector": "grok-build", "retrieved_at": NOW.isoformat(), "items": items},
            collector="grok-build",
            now=NOW,
        )

    def _save_ready(self, vault: Path, signal_id: str) -> None:
        save_triage(
            vault,
            {
                "schema_version": 1,
                "account_key": "primary",
                "signal_id": signal_id,
                "display_title": "A ready Signal",
                "language": "en",
                "content_lane": "builder_core",
                "topic_labels": ["AI"],
                "triage_status": "ready",
                "recommended_action": "topic",
                "triage_factors": {"reader_fit": 5, "evidence": 5, "value_add": 5, "urgency": 5},
                "triage_confidence": "high",
                "summary": "A bounded summary.",
                "target_reader": "Builders",
                "why_relevant": "Relevant to builders.",
                "value_add": "A useful contrast.",
                "risk": "Single-source risk.",
                "deep_dive": False,
                "reason_codes": ["fit"],
            },
            now=NOW,
        )


if __name__ == "__main__":
    unittest.main()
