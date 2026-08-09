from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from nextx.records import update_frontmatter
from nextx.signal_views import render_signal_inboxes
from nextx.strategy_snapshot import strategy_snapshot_id
from nextx.vault import atomic_write_text, init_vault


NOW = datetime(2026, 8, 9, 3, tzinfo=timezone.utc)


class SignalViewTests(unittest.TestCase):
    def test_routes_every_classification_and_renders_readable_cards(self):
        with TemporaryDirectory() as tmp:
            vault = self.make_triaged_vault(Path(tmp))

            result = render_signal_inboxes(vault, now=NOW)
            root = vault / "04. Views" / "Signals"
            immediate = (root / "Immediate Action.md").read_text(encoding="utf-8")
            productivity = (root / "AI Productivity.md").read_text(encoding="utf-8")
            archived = (root / "Archived.md").read_text(encoding="utf-8")
            needs = (root / "Needs Triage.md").read_text(encoding="utf-8")

            self.assertEqual(result["counts"]["immediate_action"], 2)
            self.assertEqual(result["counts"]["archived"], 1)
            self.assertEqual(result["counts"]["needs_triage"], 2)
            self.assertEqual(result["counts"]["builder_core"], 1)
            self.assertEqual(result["counts"]["ai_productivity"], 2)
            self.assertEqual(result["counts"]["ai_content"], 1)
            self.assertEqual(result["counts"]["adjacent_exploration"], 1)
            self.assertIn("Agent 工作流正在进入基础设施阶段", immediate)
            self.assertIn("@builder · x", immediate)
            self.assertIn("quote", immediate)
            self.assertIn("87", immediate)
            self.assertIn("high", immediate)
            self.assertIn("与 Builder 读者当前需求直接相关", immediate)
            self.assertIn("价值增量", immediate)
            self.assertIn("单一案例不能代表市场", immediate)
            self.assertIn((NOW + timedelta(hours=3)).isoformat(), immediate)
            self.assertIn("Reply 也进入即时行动", immediate)
            self.assertIn("Reply 也进入即时行动", productivity)
            self.assertNotIn("x:quote", immediate)
            self.assertIn("低价值重复信息", archived)
            self.assertIn("等待快速判断", needs)
            self.assertIn("证据冲突待复核", needs)
            self.assertNotIn("另一个账号的内容", repr(result))
            self.assertTrue(
                all(isinstance(path, str) for path in result["paths"].values())
            )

    def test_strategy_stale_and_unknown_or_invalid_triage_go_to_needs_triage(self):
        with TemporaryDirectory() as tmp:
            vault = self.make_triaged_vault(Path(tmp), include_baseline=False)
            stale = self.add_record(
                vault, "stale", title="策略已变化", lane="builder_core"
            )
            self.add_record(vault, "unknown", title="未知内容赛道", lane="unexpected")
            invalid = self.add_record(
                vault, "invalid", title="无效评分", lane="ai_content"
            )
            update_frontmatter(invalid, {"triage_score": True})
            (vault / "00. Self" / "Growth Strategy.md").write_text(
                "changed", encoding="utf-8"
            )

            render_signal_inboxes(vault, now=NOW)
            root = vault / "04. Views" / "Signals"
            needs = (root / "Needs Triage.md").read_text(encoding="utf-8")
            builder = (root / "Builder Core.md").read_text(encoding="utf-8")

            self.assertIn("策略已变化", needs)
            self.assertIn("未知内容赛道", needs)
            self.assertIn("无效评分", needs)
            self.assertNotIn(stale.stem, builder)

    def test_mismatched_score_or_invalid_factors_fail_closed_into_needs_triage(self):
        mutations = (
            ("score-mismatch", {"triage_score": 71}),
            (
                "invalid-factors",
                {
                    "triage_factors": {
                        "reader_fit": True,
                        "evidence": 4,
                        "value_add": 3,
                        "urgency": 2,
                    }
                },
            ),
        )
        for name, changes in mutations:
            with self.subTest(name=name):
                with TemporaryDirectory() as tmp:
                    vault = self.make_triaged_vault(
                        Path(tmp), include_baseline=False
                    )
                    record = self.add_record(
                        vault,
                        name,
                        title=name,
                        lane="builder_core",
                        score=70,
                    )
                    update_frontmatter(record, changes)

                    result = render_signal_inboxes(vault, now=NOW)
                    root = vault / "04. Views" / "Signals"
                    needs = (root / "Needs Triage.md").read_text(encoding="utf-8")
                    builder = (root / "Builder Core.md").read_text(encoding="utf-8")

                    self.assertEqual(result["counts"]["needs_triage"], 1)
                    self.assertIn(name, needs)
                    self.assertNotIn(name, builder)

    def test_malformed_ready_action_window_fails_closed_into_needs_triage(self):
        with TemporaryDirectory() as tmp:
            vault = self.make_triaged_vault(Path(tmp), include_baseline=False)
            malformed = self.add_record(
                vault,
                "bad-window",
                title="无效行动窗口",
                lane="builder_core",
                action="quote",
            )
            update_frontmatter(malformed, {"quote_window_ends_at": "not-a-time"})

            render_signal_inboxes(vault, now=NOW)
            root = vault / "04. Views" / "Signals"
            needs = (root / "Needs Triage.md").read_text(encoding="utf-8")
            builder = (root / "Builder Core.md").read_text(encoding="utf-8")

            self.assertIn("无效行动窗口", needs)
            self.assertNotIn("无效行动窗口", builder)

    def test_ineligible_or_expired_quote_never_enters_immediate_action(self):
        for name, eligible, deadline in (
            ("ineligible", False, NOW + timedelta(hours=3)),
            ("expired", True, NOW - timedelta(seconds=1)),
        ):
            with self.subTest(name=name):
                with TemporaryDirectory() as tmp:
                    vault = self.make_triaged_vault(
                        Path(tmp), include_baseline=False
                    )
                    self.add_record(
                        vault,
                        name,
                        title=f"{name} quote",
                        lane="builder_core",
                        action="quote",
                        eligible=eligible,
                        deadline=deadline,
                    )

                    result = render_signal_inboxes(vault, now=NOW)
                    immediate = (
                        vault / "04. Views" / "Signals" / "Immediate Action.md"
                    ).read_text(encoding="utf-8")

                    self.assertEqual(result["counts"]["immediate_action"], 0)
                    self.assertIn("暂无", immediate)

    def test_raw_legacy_hash_is_never_used_as_the_primary_card_label(self):
        with TemporaryDirectory() as tmp:
            vault = self.make_triaged_vault(Path(tmp), include_baseline=False)
            digest = "a" * 64
            path = self.add_record(
                vault,
                digest,
                title="临时标题",
                lane=None,
                status="pending",
                action=None,
                score=None,
                confidence=None,
                eligible=None,
            )
            text = path.read_text(encoding="utf-8")
            text = "\n".join(
                line
                for line in text.splitlines()
                if not line.startswith("display_title:") and not line.startswith("id:")
            ) + "\n"
            path.write_text(text, encoding="utf-8")

            render_signal_inboxes(vault, now=NOW)
            needs = (
                vault / "04. Views" / "Signals" / "Needs Triage.md"
            ).read_text(encoding="utf-8")

            self.assertNotIn(f"|{digest}]]", needs)
            self.assertIn(f"[[{digest}|未命名 Signal]]", needs)

    def test_sorting_uses_deadline_for_immediate_and_score_for_lanes(self):
        with TemporaryDirectory() as tmp:
            vault = self.make_triaged_vault(Path(tmp), include_baseline=False)
            self.add_record(
                vault,
                "later-high",
                title="稍晚高分",
                lane="builder_core",
                action="quote",
                score=98,
                factors={
                    "reader_fit": 5,
                    "evidence": 5,
                    "value_add": 5,
                    "urgency": 4,
                },
                deadline=NOW + timedelta(hours=5),
            )
            self.add_record(
                vault,
                "sooner-low",
                title="更早低分",
                lane="builder_core",
                action="reply",
                score=40,
                factors={
                    "reader_fit": 2,
                    "evidence": 2,
                    "value_add": 2,
                    "urgency": 2,
                },
                deadline=NOW + timedelta(hours=1),
            )

            render_signal_inboxes(vault, now=NOW)
            root = vault / "04. Views" / "Signals"
            immediate = (root / "Immediate Action.md").read_text(encoding="utf-8")
            lane = (root / "Builder Core.md").read_text(encoding="utf-8")

            self.assertLess(immediate.index("更早低分"), immediate.index("稍晚高分"))
            self.assertLess(lane.index("稍晚高分"), lane.index("更早低分"))

    def make_triaged_vault(self, vault: Path, *, include_baseline: bool = True) -> Path:
        init_vault(vault)
        self_root = vault / "00. Self"
        (self_root / "Profile.md").write_text("AI builders", encoding="utf-8")
        (self_root / "Pillars.md").write_text("AI workflows", encoding="utf-8")
        (self_root / "Growth Strategy.md").write_text("Grow authority", encoding="utf-8")
        if not include_baseline:
            return vault
        self.add_record(
            vault,
            "quote",
            title="Agent 工作流正在进入基础设施阶段",
            lane="builder_core",
            action="quote",
            score=87,
            factors={
                "reader_fit": 5,
                "evidence": 4,
                "value_add": 4,
                "urgency": 4,
            },
            deadline=NOW + timedelta(hours=3),
        )
        self.add_record(
            vault,
            "reply",
            title="Reply 也进入即时行动",
            lane="ai_productivity",
            action="reply",
            deadline=NOW + timedelta(hours=2),
        )
        self.add_record(
            vault, "productivity", title="生产力实践", lane="ai_productivity"
        )
        self.add_record(vault, "content", title="内容工作流", lane="ai_content")
        self.add_record(vault, "adjacent", title="相邻探索", lane="adjacent_exploration")
        self.add_record(
            vault,
            "filtered",
            title="低价值重复信息",
            lane="builder_core",
            status="filtered",
            action="archive",
            eligible=False,
        )
        self.add_record(
            vault,
            "pending",
            title="等待快速判断",
            lane=None,
            status="pending",
            action=None,
            score=None,
            confidence=None,
            eligible=None,
        )
        self.add_record(
            vault,
            "review",
            title="证据冲突待复核",
            lane="ai_content",
            status="needs_review",
            eligible=False,
        )
        self.add_record(
            vault,
            "other",
            title="另一个账号的内容",
            lane="builder_core",
            account_key="other",
        )
        return vault

    def add_record(
        self,
        vault: Path,
        record_id: str,
        *,
        title: str,
        lane: str | None,
        status: str = "ready",
        action: str | None = "topic",
        score: int | None = 70,
        factors: dict[str, object] | None = None,
        confidence: str | None = "high",
        eligible: bool | None = True,
        deadline: datetime | None = None,
        account_key: str = "primary",
    ) -> Path:
        deadline = deadline or NOW + timedelta(hours=6)
        values: dict[str, object] = {
            "schema_version": 1,
            "account_key": account_key,
            "id": f"x:{record_id}",
            "type": "signal",
            "platform": "x",
            "author_handle": "builder",
            "captured_at": (NOW - timedelta(minutes=10)).isoformat(),
            "display_title": title,
            "triage_status": status,
            "triage_factors": factors
            or {"reader_fit": 4, "evidence": 4, "value_add": 3, "urgency": 2},
            "why_relevant": "与 Builder 读者当前需求直接相关",
            "value_add": "价值增量：解释工具与基础设施的边界",
            "risk": "单一案例不能代表市场",
        }
        optional = {
            "content_lane": lane,
            "recommended_action": action,
            "triage_score": score,
            "triage_confidence": confidence,
            "triage_action_eligible": eligible,
        }
        values.update(
            {key: value for key, value in optional.items() if value is not None}
        )
        if action in {"quote", "reply"}:
            values[f"{action}_candidate"] = True
            values[f"{action}_window_ends_at"] = deadline.isoformat()
        if status != "pending":
            values["strategy_snapshot_id"] = strategy_snapshot_id(vault)
            values["triage_version"] = 1
        path = vault / "01. Signal" / f"{record_id}.md"
        frontmatter = "\n".join(
            f"{key}: {json.dumps(value, ensure_ascii=False, separators=(',', ':'))}"
            for key, value in values.items()
        )
        atomic_write_text(path, f"---\n{frontmatter}\n---\n\nOriginal evidence.\n")
        return path


if __name__ == "__main__":
    unittest.main()
