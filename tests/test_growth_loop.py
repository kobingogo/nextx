from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from nextx.artifacts import (
    artifact_brief,
    confirm_publish,
    mark_review_ready,
    record_published,
    save_artifact,
)
from nextx.decisions import decision_brief, save_decision
from nextx.learning import record_outcome, render_weekly_review
from nextx.records import read_frontmatter
from nextx.self_model import configure_self
from nextx.signals import ingest_signals
from nextx.views import render_growth_loop, render_reply_sprint


NOW = datetime(2026, 8, 8, 8, 0, tzinfo=timezone.utc)


def self_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "account_key": "primary",
        "positioning": "Local-first X operations for solo builders.",
        "audience": "Builders using AI agents.",
        "stage": "冷启动",
        "pillars": ["Agent workflow", "Product systems", "X operations"],
        "boundaries": "不转发未经核验的增长承诺。",
        "voice_samples": ["先把问题做小，再把闭环做实。"],
        "growth_strategy": {
            "stage": "launch",
            "objective": "awareness",
            "target_reader": "正在学习使用 AI Agent 的独立创作者。",
            "profile_promise": "把零散运营动作变成可验证的本地闭环。",
            "cta": "关注并保存下一次决策模板。",
            "weekly_focus": "用高质量回复进入目标读者正在参与的讨论。",
            "lane_allocation": {"discovery": 3, "authority": 1, "conversion": 0},
        },
    }


def reply_envelope() -> dict[str, object]:
    return {
        "schema_version": 1,
        "account_key": "primary",
        "collector": "grok-build",
        "query": "AI agent creator workflow",
        "retrieved_at": NOW.isoformat(),
        "items": [
            {
                "source_id": "x:8001",
                "platform": "x",
                "source_url": "https://x.com/alpha/status/8001",
                "author_handle": "alpha",
                "published_at": "2026-08-08T05:00:00+00:00",
                "text": "Most creator workflows fail because nobody records what changed after publishing.",
                "metrics": {"views": 10_000, "likes": 30, "replies": 8, "reposts": 4, "bookmarks": 6},
                "media": [],
                "source_confidence": "high",
                "discovery_reason": "开放讨论了复盘缺口，可用具体的最小闭环帮助相邻读者判断。",
                "why_today": "讨论仍在进行。",
                "self_fit": 5,
                "novelty": 4,
                "reply_candidate": True,
                "reply_window_ends_at": "2026-08-09T06:00:00+00:00",
            }
        ],
    }


def reply_decision() -> dict[str, object]:
    return {
        "schema_version": 1,
        "account_key": "primary",
        "verdict": "do",
        "execution_mode": "reply",
        "signal_ids": ["x:8001"],
        "reason_code": "open-discussion-strong-fit",
        "reason": "The post names a concrete problem that the account can extend with a verifiable operating step.",
        "angle": "A feedback window is part of the content itself, not an afterthought.",
        "original_value": "Offer a simple 1h/24h/7d loop instead of merely agreeing that measurement matters.",
        "risk": "Do not imply that a workflow guarantees reach or followers.",
        "recommended_format": "reply-post",
        "research_summary": "The source explicitly identifies post-publication learning as the bottleneck.",
        "why_now": "The discussion remains in a short reply window.",
        "why_self": "It directly fits the local operating-system positioning.",
        "evidence_sufficient": True,
        "evidence": [
            {
                "signal_id": "x:8001",
                "quote": "nobody records what changed after publishing.",
                "source_url": "https://x.com/alpha/status/8001",
            }
        ],
        "reply_angle_type": "implementation",
        "relationship_goal": "reader_discovery",
        "reply_window_ends_at": "2026-08-09T05:00:00+00:00",
        "growth_contract": {
            "objective": "awareness",
            "target_reader": "正在学习使用 AI Agent 的独立创作者。",
            "expected_action": "让相邻读者保存这个最小复盘动作，并进入主页理解完整方法。",
            "distribution_target": "@alpha 原帖下正在讨论创作工作流的读者。",
            "review_at": "2026-08-15T08:00:00+00:00",
        },
    }


class GrowthLoopIntegrationTests(unittest.TestCase):
    def test_growth_loop_routes_a_regular_pending_signal_to_decision_before_collecting(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            configure_self(vault, self_payload())
            payload = reply_envelope()
            payload["items"][0].pop("reply_candidate")
            payload["items"][0].pop("reply_window_ends_at")
            ingest_signals(vault, payload, collector="grok-build", now=NOW)

            action = render_growth_loop(vault, now=NOW)["next_action"]

            self.assertEqual(action["id"], "decision_brief")
            self.assertIn("x:8001", action["command"])

    def test_growth_strategy_lane_allocation_changes_the_next_action_order(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            payload = self_payload()
            payload["growth_strategy"]["stage"] = "ramp"
            payload["growth_strategy"]["lane_allocation"] = {
                "discovery": 0, "authority": 1, "conversion": 0
            }
            configure_self(vault, payload)
            ingest_signals(vault, reply_envelope(), collector="grok-build", now=NOW)
            regular = reply_envelope()
            item = regular["items"][0]
            item.update(
                {
                    "source_id": "x:8002",
                    "source_url": "https://x.com/beta/status/8002",
                    "author_handle": "beta",
                }
            )
            item.pop("reply_candidate")
            item.pop("reply_window_ends_at")
            ingest_signals(vault, regular, collector="grok-build", now=NOW)

            result = render_growth_loop(vault, now=NOW)

            self.assertEqual(result["next_action"]["id"], "decision_brief")
            self.assertIn("x:8002", result["next_action"]["command"])
            self.assertEqual(result["lane_targets"]["authority"], 1)

    def test_conversion_strategy_promotes_a_pending_signal_to_conversion_brief(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            payload = self_payload()
            payload["growth_strategy"]["objective"] = "conversion"
            payload["growth_strategy"]["lane_allocation"] = {
                "discovery": 0,
                "authority": 0,
                "conversion": 1,
            }
            configure_self(vault, payload)
            regular = reply_envelope()
            regular["items"][0].pop("reply_candidate")
            regular["items"][0].pop("reply_window_ends_at")
            ingest_signals(vault, regular, collector="grok-build", now=NOW)

            result = render_growth_loop(vault, now=NOW)

            self.assertEqual(result["next_action"]["id"], "conversion_brief")
            self.assertIn("x:8001", result["next_action"]["command"])

    def test_novice_can_run_reply_to_outcome_growth_loop(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            configure_self(vault, self_payload())
            ingest_signals(vault, reply_envelope(), collector="grok-build", now=NOW)

            next_action = render_growth_loop(vault, now=NOW)
            self.assertTrue(next_action["strategy_configured"])
            self.assertEqual(next_action["next_action"]["id"], "reply_sprint")
            sprint = render_reply_sprint(vault, now=NOW)
            self.assertEqual(sprint["selected_ids"], ["x:8001"])
            self.assertIn("Reply Sprint", decision_brief(vault, "x:8001", execution_mode="reply", now=NOW)["brief"])

            decision = save_decision(vault, reply_decision(), now=NOW)
            decision_properties, decision_body = read_frontmatter(Path(str(decision["path"])))
            self.assertEqual(decision_properties["growth_objective"], "awareness")
            self.assertEqual(decision_properties["reply_author_handle"], "alpha")
            self.assertIn("## 增长契约", decision_body)

            self.assertIn("reply-post", artifact_brief(vault, str(decision["id"]), now=NOW)["brief"])
            artifact = save_artifact(
                vault,
                {
                    "schema_version": 1,
                    "account_key": "primary",
                    "decision_id": decision["id"],
                    "format": "reply-post",
                    "draft": "The missing unit is a named review window: 1h for conversation, 24h for signals, 7d for learning. Without it, every post is just a memory.",
                    "asset_manifest": [],
                },
                now=NOW.replace(hour=9),
            )
            artifact_path = Path(str(artifact["path"]))
            properties, body = read_frontmatter(artifact_path)
            self.assertEqual(properties["execution_mode"], "reply")
            self.assertIn("## Reply 原帖", body)
            self.assertIn("## 发布后行动", body)
            self.assertEqual(render_growth_loop(vault, now=NOW)["next_action"]["id"], "review_draft")

            artifact_path.write_text(
                artifact_path.read_text(encoding="utf-8").replace("- [ ]", "- [x]"),
                encoding="utf-8",
            )
            mark_review_ready(vault, str(artifact["id"]), now=NOW)
            confirm_publish(vault, str(artifact["id"]), confirmed=True, now=NOW)
            record_published(vault, str(artifact["id"]), "https://x.com/example/status/8002", now=NOW)
            record_outcome(
                vault,
                str(artifact["id"]),
                {
                    "schema_version": 1,
                    "account_key": "primary",
                    "window": "1h",
                    "views": 100,
                    "likes": 4,
                    "replies": 1,
                    "reposts": 0,
                    "bookmarks": 1,
                    "growth_signals": {"follow_up_completed": True, "non_follower_replies": 1},
                },
                now=NOW + timedelta(hours=1),
            )
            self.assertEqual(
                render_growth_loop(vault, now=NOW + timedelta(hours=2))["next_action"]["id"],
                "collect",
            )
            self.assertEqual(
                render_growth_loop(vault, now=NOW + timedelta(days=7))["next_action"]["id"],
                "record_outcome",
            )
            result = record_outcome(
                vault,
                str(artifact["id"]),
                {
                    "schema_version": 1,
                    "account_key": "primary",
                    "window": "7d",
                    "views": 900,
                    "likes": 30,
                    "replies": 6,
                    "reposts": 3,
                    "bookmarks": 12,
                    "growth_signals": {
                        "follow_up_completed": True,
                        "target_author_replied": True,
                        "non_follower_replies": 2,
                        "observations": ["A non-follower asked for the full template."],
                    },
                },
                now=NOW + timedelta(days=7),
            )
            self.assertEqual(result["status"], "measured")
            review = render_weekly_review(vault, now=NOW + timedelta(days=7))
            scorecard = review["growth_scorecards"]["reply:awareness"]
            self.assertEqual(scorecard["measured_count"], 1)
            self.assertFalse(scorecard["playbook_evidence_ready"])


if __name__ == "__main__":
    unittest.main()
