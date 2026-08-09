# -*- coding: utf-8 -*-

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from nextx.clusters import build_cluster_brief, save_clusters
from nextx.records import update_frontmatter
from nextx.signals import ingest_signals, signal_path
from nextx.topics import build_topic_brief, read_topic, save_topic, topic_path
from nextx.triage import save_triage


NOW = datetime(2026, 8, 10, 3, tzinfo=timezone.utc)


class TopicCardTests(unittest.TestCase):
    def test_topic_brief_exposes_only_selected_cluster_evidence(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            cluster_id = self._cluster(vault)
            unrelated = signal_path(vault, "x:103").read_text(encoding="utf-8")

            brief = build_topic_brief(vault, cluster_id)

            self.assertEqual(brief["cluster_id"], cluster_id)
            self.assertIn("topic-engine", brief["brief"])
            self.assertIn("P3", brief["brief"])
            self.assertIn("First raw source", brief["brief"])
            self.assertNotIn(unrelated, brief["brief"])
            self.assertIn("Profile.md", brief["brief"])
            self.assertIn("不要写推文正文", brief["brief"])

    def test_topic_brief_keeps_raw_quotes_inside_untrusted_data_only(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            cluster_id = self._cluster(vault)

            brief = build_topic_brief(vault, cluster_id)["brief"]
            quote_at = brief.index("First raw source")

            self.assertEqual(brief.count("First raw source"), 1)
            prefix = brief[:quote_at]
            self.assertGreater(prefix.count("<nextx-untrusted-data"), prefix.count("</nextx-untrusted-data>"))

    def test_topic_brief_treats_cluster_metadata_as_untrusted_too(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            cluster_id = self._cluster(vault)
            snapshot_path = vault / ".nextx" / "clusters.json"
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            snapshot["clusters"][0]["display_title"] = "First raw source"
            snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

            brief = build_topic_brief(vault, cluster_id)["brief"]
            positions = [index for index in range(len(brief)) if brief.startswith("First raw source", index)]

            self.assertGreaterEqual(len(positions), 2)
            for quote_at in positions:
                prefix = brief[:quote_at]
                self.assertGreater(prefix.count("<nextx-untrusted-data"), prefix.count("</nextx-untrusted-data>"))

    def test_tampered_run_matching_cluster_cannot_be_promoted(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            cluster_id = self._cluster(vault)
            snapshot_path = vault / ".nextx" / "clusters.json"
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            forged_members = ["x:101", "x:103"]
            snapshot["clusters"][0]["signal_ids"] = forged_members
            snapshot["clusters"][0]["cluster_id"] = "cluster:" + hashlib.sha256(
                "\n".join([snapshot["cluster_run_id"], *sorted(forged_members)]).encode("utf-8")
            ).hexdigest()[:16]
            snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
            forged_id = snapshot["clusters"][0]["cluster_id"]

            with self.assertRaisesRegex(ValueError, "current"):
                build_topic_brief(vault, forged_id)
            with self.assertRaisesRegex(ValueError, "current"):
                save_topic(vault, self._payload(forged_id), now=NOW)

    def test_failed_current_cluster_run_cannot_build_or_save_a_topic(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            cluster_id = self._cluster(vault)
            snapshot = json.loads((vault / ".nextx" / "clusters.json").read_text(encoding="utf-8"))
            (vault / ".nextx" / "cluster-status.json").write_text(
                json.dumps({"status": "failed", "cluster_run_id": snapshot["cluster_run_id"]}),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "failed"):
                build_topic_brief(vault, cluster_id)
            with self.assertRaisesRegex(ValueError, "failed"):
                save_topic(vault, self._payload(cluster_id), now=NOW)

    def test_save_topic_is_explicit_and_cluster_rebuild_cannot_overwrite_it(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            cluster_id = self._cluster(vault)

            created = save_topic(vault, self._payload(cluster_id), now=NOW)
            path = Path(created["path"])
            before = path.read_text(encoding="utf-8")
            replacement = self._cluster_payload(build_cluster_brief(vault, now=NOW))
            replacement["clusters"] = []
            save_clusters(vault, replacement, now=NOW)

            self.assertRegex(created["id"], r"^topic:[0-9a-f]{16}$")
            self.assertTrue(path.is_file())
            self.assertEqual(path.read_text(encoding="utf-8"), before)
            self.assertEqual(topic_path(vault, created["id"]), path)
            _, properties, body = read_topic(vault, created["id"])
            self.assertEqual(properties["cluster_id"], cluster_id)
            self.assertIn("First raw source", body)
            self.assertTrue((vault / "04. Views" / "Topics" / "Topic Cards.md").is_file())

    def test_save_rejects_invalid_compliance_and_non_member_action_signal(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            cluster_id = self._cluster(vault)
            red = self._payload(cluster_id)
            red["compliance"] = {"band": "red", "reason": "Unsafe", "mitigation": ""}
            with self.assertRaisesRegex(ValueError, "red"):
                save_topic(vault, red, now=NOW)

            yellow = self._payload(cluster_id)
            yellow["compliance"] = {"band": "yellow", "reason": "Needs care", "mitigation": ""}
            with self.assertRaisesRegex(ValueError, "mitigation"):
                save_topic(vault, yellow, now=NOW)

            quote = self._payload(cluster_id)
            quote["suggested_mode"] = "quote"
            quote["action_signal_id"] = "x:103"
            with self.assertRaisesRegex(ValueError, "action_signal_id"):
                save_topic(vault, quote, now=NOW)

    def test_exact_evidence_retries_and_payload_collision_are_safe(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            cluster_id = self._cluster(vault)
            payload = self._payload(cluster_id)
            first = save_topic(vault, payload, now=NOW)
            retry = save_topic(vault, json.loads(json.dumps(payload)), now=NOW)
            self.assertEqual(retry["id"], first["id"])
            self.assertTrue(retry["reused"])

            changed = json.loads(json.dumps(payload))
            changed["takeaway"] = "A different reader takeaway."
            with self.assertRaisesRegex(ValueError, "overwrite"):
                save_topic(vault, changed, now=NOW)

            forged = self._payload(cluster_id)
            forged["evidence"][0]["quote"] = "Invented quote"
            with self.assertRaisesRegex(ValueError, "exact text"):
                save_topic(vault, forged, now=NOW)

    def test_topic_filename_is_safe_for_hostile_titles(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            cluster_id = self._cluster(vault)
            payload = self._payload(cluster_id)
            payload["display_title"] = "../ unsafe / title : * ?"

            result = save_topic(vault, payload, now=NOW)

            path = Path(result["path"])
            self.assertEqual(path.parent, vault.resolve() / "01. Topic")
            self.assertNotIn("/", path.name)
            self.assertNotIn("..", path.name)

    def _payload(self, cluster_id: str) -> dict[str, object]:
        return {
            "schema_version": 1,
            "account_key": "primary",
            "cluster_id": cluster_id,
            "status": "active",
            "suggested_mode": "original",
            "display_title": "Durable AI workflow systems",
            "proposition": "Reusable systems beat disposable prompt tricks.",
            "content_lane": "builder_core",
            "target_reader": "AI builders",
            "takeaway": "A checklist for turning prompt tricks into reusable systems.",
            "value_type": "tool",
            "primary_platform": "x",
            "secondary_platform": "newsletter",
            "recommended_angle": "Contrast systems with tricks.",
            "title_directions": ["Strategic system angle", "Practical checklist angle"],
            "quality_gates": {
                "human": "The user has direct workflow observations.",
                "useful": "Readers get a reusable checklist.",
                "timely": "The evidence is recent and evergreen.",
                "identity_leverage": "It fits a builder workflow perspective.",
            },
            "ip_dimensions": {
                "differentiation": 1,
                "depth": 1,
                "perspective": 1,
                "clarity": 1,
                "courage": 1,
                "shareability": 1,
            },
            "traffic_dimensions": {
                "benefit_visibility": 5,
                "hook_strength": 4,
                "asset_promise": 5,
                "actionability": 5,
            },
            "ip_band": "S",
            "traffic_band": "strong_hook",
            "decision_class": "compound",
            "why_worth_doing": "Two independent sources support it.",
            "evidence": [
                {"signal_id": "x:101", "quote": "First raw source", "role": "support", "translation_status": "original"},
                {"signal_id": "x:102", "quote": "Second raw source", "role": "counter", "translation_status": "original"},
            ],
            "counterpoint": "A prompt can still be useful when it is documented.",
            "evidence_to_strengthen": "A first-person workflow comparison.",
            "max_risk": "The evidence is still a small sample.",
            "confidence": "high",
            "compliance": {"band": "green", "reason": "Method-focused and non-deceptive.", "mitigation": ""},
            "action_signal_id": None,
            "revisit_at": None,
            "notes": "Explicitly promoted after review.",
        }

    def _cluster(self, vault: Path) -> str:
        self._ingest(vault)
        self._ready(vault, "x:101")
        self._ready(vault, "x:102")
        result = save_clusters(vault, self._cluster_payload(build_cluster_brief(vault, now=NOW)), now=NOW)
        return json.loads((vault / ".nextx" / "clusters.json").read_text(encoding="utf-8"))["clusters"][0]["cluster_id"]

    def _cluster_payload(self, brief: dict[str, object]) -> dict[str, object]:
        return {
            "schema_version": 1, "account_key": "primary", "cluster_run_id": brief["cluster_run_id"],
            "clusters": [{
                "kind": "evergreen", "signal_ids": ["x:101", "x:102"],
                "display_title": "Reusable AI workflows", "proposition": "Reusable systems beat disposable prompt tricks.",
                "confidence": "high", "why_now": "Both sources are recent.", "target_reader": "AI builders",
                "candidate_angle": "Contrast systems with tricks.", "recommended_next_step": "topic_card",
                "evidence": [
                    {"signal_id": "x:101", "quote": "First raw source", "role": "support", "translation_status": "original"},
                    {"signal_id": "x:102", "quote": "Second raw source", "role": "counter", "translation_status": "original"},
                ],
            }], "adjacent_candidates": [],
        }

    def _ingest(self, vault: Path) -> None:
        items = [
            {"source_id": "x:101", "platform": "x", "source_url": "https://x.com/one/status/101", "author_handle": "one", "published_at": (NOW - timedelta(hours=3)).isoformat(), "text": "First raw source", "source_confidence": "high"},
            {"source_id": "x:102", "platform": "x", "source_url": "https://x.com/two/status/102", "author_handle": "two", "published_at": (NOW - timedelta(hours=2)).isoformat(), "text": "Second raw source", "source_confidence": "high"},
            {"source_id": "x:103", "platform": "x", "source_url": "https://x.com/three/status/103", "author_handle": "three", "published_at": (NOW - timedelta(hours=1)).isoformat(), "text": "unrelated signal text", "source_confidence": "high"},
        ]
        ingest_signals(vault, {"schema_version": 1, "account_key": "primary", "collector": "grok-build", "retrieved_at": NOW.isoformat(), "items": items}, collector="grok-build", now=NOW)

    def _ready(self, vault: Path, signal_id: str) -> None:
        save_triage(vault, {
            "schema_version": 1, "account_key": "primary", "signal_id": signal_id,
            "display_title": "A ready Signal", "language": "en", "content_lane": "builder_core", "topic_labels": ["AI"],
            "triage_status": "ready", "recommended_action": "topic", "triage_factors": {"reader_fit": 5, "evidence": 5, "value_add": 5, "urgency": 5},
            "triage_confidence": "high", "summary": "A bounded summary.", "target_reader": "Builders", "why_relevant": "Relevant to builders.",
            "value_add": "A useful contrast.", "risk": "Single-source risk.", "deep_dive": False, "reason_codes": ["fit"],
        }, now=NOW)


if __name__ == "__main__":
    unittest.main()
