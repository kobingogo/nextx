from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from io import StringIO
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from nextx.bookmarks import read_bookmark_health
from nextx.cli import _load_input, main
from nextx.records import update_frontmatter
from nextx.self_model import configure_self
from nextx.signals import ingest_signals, signal_path
from nextx.clusters import build_cluster_brief, save_clusters
from nextx.triage import save_triage
from nextx.twitter_cli import TwitterCLIError


FIXTURE = Path(__file__).parent / "fixtures" / "bookmarks.json"
GROK_FIXTURE = Path(__file__).parent / "fixtures" / "grok-signals.json"
DECISION_FIXTURE = Path(__file__).parent / "fixtures" / "decision-do.json"
TRIAGE_FIXTURE = Path(__file__).parent / "fixtures" / "triage-valid.json"


def run_cli(arguments):
    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = main(arguments)
    return code, stdout.getvalue(), stderr.getvalue()


class CLITests(unittest.TestCase):
    def test_package_and_cli_module_entrypoints_expose_the_same_help(self):
        results = []
        for module in ("nextx", "nextx.cli"):
            result = subprocess.run(
                [sys.executable, "-m", module, "--help"],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("usage:", result.stdout)
            self.assertIn("triage-brief", result.stdout)
            results.append(result.stdout)

        self.assertEqual(results[0], results[1])

    def test_version_returns_a_structured_installed_version(self):
        code, stdout, stderr = run_cli(["version"])

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(json.loads(stdout)["version"], "0.3.0a2")

    def test_setup_and_config_work_without_vault_argument(self):
        with TemporaryDirectory() as tmp:
            config_home = Path(tmp) / "config"
            vault = Path(tmp) / "vault"
            with patch.dict(
                "os.environ",
                {"XDG_CONFIG_HOME": str(config_home), "NEXTX_VAULT": str(vault)},
                clear=True,
            ):
                setup_code, setup_stdout, setup_stderr = run_cli(["setup", "--yes"])
                config_code, config_stdout, config_stderr = run_cli(["config", "--show"])
                today_code, today_stdout, today_stderr = run_cli(["today"])

            self.assertEqual(setup_code, 0)
            self.assertEqual(setup_stderr, "")
            self.assertTrue(json.loads(setup_stdout)["ok"])
            self.assertEqual(config_code, 0)
            self.assertEqual(config_stderr, "")
            self.assertEqual(json.loads(config_stdout)["vault"], str(vault.resolve()))
            self.assertEqual(today_code, 0)
            self.assertEqual(today_stderr, "")
            self.assertTrue(Path(json.loads(today_stdout)["view"]).exists())

    def test_init_returns_json(self):
        with TemporaryDirectory() as tmp:
            code, stdout, stderr = run_cli(["init", "--vault", tmp])

            result = json.loads(stdout)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            self.assertTrue(result["ok"])
            self.assertEqual(result["schema_version"], 1)
            self.assertEqual(result["command"], "init")

    def test_cluster_brief_is_a_read_only_agent_command(self):
        with TemporaryDirectory() as tmp:
            code, stdout, stderr = run_cli(["cluster-brief", "--vault", tmp])

            result = json.loads(stdout)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            self.assertEqual(result["command"], "cluster-brief")
            self.assertEqual(result["signal_count"], 0)

    def test_topic_inbox_exposes_when_no_current_cluster_projection_exists(self):
        with TemporaryDirectory() as tmp:
            code, stdout, stderr = run_cli(["topic-inbox", "--vault", tmp])

            result = json.loads(stdout)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            self.assertEqual(result["command"], "topic-inbox")
            self.assertEqual(result["status"], "unavailable")
            self.assertTrue(Path(result["view"]).is_file())

    def test_topic_brief_persists_only_when_explicitly_invoked_and_save_topic_writes_card(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            self._make_topic_cluster(vault)
            cluster_id = json.loads((vault / ".nextx" / "clusters.json").read_text(encoding="utf-8"))["clusters"][0]["cluster_id"]

            brief_code, brief_stdout, brief_stderr = run_cli(["topic-brief", "--vault", tmp, cluster_id])
            brief = json.loads(brief_stdout)
            self.assertEqual(brief_code, 0)
            self.assertEqual(brief_stderr, "")
            self.assertTrue(Path(brief["handoff_path"]).is_file())
            self.assertIn("topic-engine", brief["brief"])

            input_path = vault / "topic.json"
            input_path.write_text(json.dumps(self._topic_payload(cluster_id)), encoding="utf-8")
            save_code, save_stdout, save_stderr = run_cli(["save-topic", "--vault", tmp, "--input-json", str(input_path)])
            saved = json.loads(save_stdout)
            self.assertEqual(save_code, 0)
            self.assertEqual(save_stderr, "")
            self.assertEqual(saved["command"], "save-topic")
            self.assertTrue(Path(saved["path"]).is_file())

    def test_topic_decision_brief_persists_an_original_topic_handoff(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            self._make_topic_cluster(vault)
            cluster_id = json.loads((vault / ".nextx" / "clusters.json").read_text(encoding="utf-8"))["clusters"][0]["cluster_id"]
            input_path = vault / "topic.json"
            input_path.write_text(json.dumps(self._topic_payload(cluster_id)), encoding="utf-8")
            _, saved_stdout, _ = run_cli(["save-topic", "--vault", tmp, "--input-json", str(input_path)])
            topic_id = json.loads(saved_stdout)["id"]

            code, stdout, stderr = run_cli(["topic-decision-brief", "--vault", tmp, topic_id])

            self.assertEqual((code, stderr), (0, ""))
            result = json.loads(stdout)
            self.assertEqual(result["topic_id"], topic_id)
            self.assertEqual(result["signal_ids"], ["x:801", "x:802"])
            self.assertTrue(Path(result["handoff_path"]).is_file())

    def test_topic_foundation_cli_flow_stays_local_and_requires_no_artifact(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            now = datetime.now(timezone.utc).replace(microsecond=0)
            ingest_signals(
                vault,
                {"schema_version": 1, "account_key": "primary", "collector": "grok-build", "retrieved_at": now.isoformat(), "items": [
                    {"source_id": "x:801", "platform": "x", "source_url": "https://x.com/one/status/801", "author_handle": "one", "published_at": now.isoformat(), "text": "First CLI source", "source_confidence": "high"},
                    {"source_id": "x:802", "platform": "x", "source_url": "https://x.com/two/status/802", "author_handle": "two", "published_at": now.isoformat(), "text": "Second CLI source", "source_confidence": "high"},
                ]},
                collector="grok-build",
                now=now,
            )
            for signal_id in ("x:801", "x:802"):
                save_triage(vault, {
                    "schema_version": 1, "account_key": "primary", "signal_id": signal_id, "display_title": "Ready CLI Signal", "language": "en", "content_lane": "builder_core", "topic_labels": ["AI"], "triage_status": "ready", "recommended_action": "topic", "triage_factors": {"reader_fit": 5, "evidence": 5, "value_add": 5, "urgency": 5}, "triage_confidence": "high", "summary": "Ready.", "target_reader": "Builders", "why_relevant": "Relevant.", "value_add": "Useful.", "risk": "Small sample.", "deep_dive": False, "reason_codes": ["fit"],
                }, now=now)

            brief_code, brief_stdout, brief_stderr = run_cli(["cluster-brief", "--vault", tmp])
            self.assertEqual((brief_code, brief_stderr), (0, ""))
            cluster_payload = {
                "schema_version": 1, "account_key": "primary", "cluster_run_id": json.loads(brief_stdout)["cluster_run_id"],
                "clusters": [{"kind": "evergreen", "signal_ids": ["x:801", "x:802"], "display_title": "CLI workflows", "proposition": "Systems beat tricks.", "confidence": "high", "why_now": "Recent.", "target_reader": "Builders", "candidate_angle": "Systems.", "recommended_next_step": "topic_card", "evidence": [{"signal_id": "x:801", "quote": "First CLI source", "role": "support", "translation_status": "original"}, {"signal_id": "x:802", "quote": "Second CLI source", "role": "counter", "translation_status": "original"}]}], "adjacent_candidates": [],
            }
            cluster_input = vault / "cluster.json"
            cluster_input.write_text(json.dumps(cluster_payload), encoding="utf-8")
            save_cluster_code, save_cluster_stdout, save_cluster_stderr = run_cli(["save-clusters", "--vault", tmp, "--input-json", str(cluster_input)])
            self.assertEqual((save_cluster_code, save_cluster_stderr), (0, ""))
            self.assertEqual(json.loads(save_cluster_stdout)["saved"], 1)
            cluster_id = json.loads((vault / ".nextx" / "clusters.json").read_text(encoding="utf-8"))["clusters"][0]["cluster_id"]

            topic_brief_code, _, topic_brief_stderr = run_cli(["topic-brief", "--vault", tmp, cluster_id])
            self.assertEqual((topic_brief_code, topic_brief_stderr), (0, ""))
            topic_input = vault / "topic.json"
            topic_input.write_text(json.dumps(self._topic_payload(cluster_id)), encoding="utf-8")
            save_topic_code, save_topic_stdout, save_topic_stderr = run_cli(["save-topic", "--vault", tmp, "--input-json", str(topic_input)])
            self.assertEqual((save_topic_code, save_topic_stderr), (0, ""))
            topic_id = json.loads(save_topic_stdout)["id"]

            decision_brief_code, _, decision_brief_stderr = run_cli(["topic-decision-brief", "--vault", tmp, topic_id])
            self.assertEqual((decision_brief_code, decision_brief_stderr), (0, ""))
            decision_payload = json.loads(DECISION_FIXTURE.read_text(encoding="utf-8"))
            decision_payload.update({
                "topic_id": topic_id,
                "signal_ids": ["x:801", "x:802"],
                "evidence": [
                    {"signal_id": "x:801", "quote": "First CLI source", "source_url": "https://x.com/one/status/801"},
                    {"signal_id": "x:802", "quote": "Second CLI source", "source_url": "https://x.com/two/status/802"},
                ],
                "growth_contract": {**decision_payload["growth_contract"], "review_at": (now + timedelta(days=4)).isoformat()},
            })
            decision_input = vault / "decision.json"
            decision_input.write_text(json.dumps(decision_payload), encoding="utf-8")
            save_decision_code, save_decision_stdout, save_decision_stderr = run_cli(["save-decision", "--vault", tmp, "--input-json", str(decision_input)])

            self.assertEqual((save_decision_code, save_decision_stderr), (0, ""))
            self.assertEqual(json.loads(save_decision_stdout)["topic_id"], topic_id)
            self.assertEqual(len(list((vault / "01. Topic").glob("*.md"))), 1)
            self.assertTrue((vault / "04. Views" / "Topics" / "Topic Clusters.md").is_file())
            self.assertTrue((vault / "04. Views" / "Topics" / "Topic Cards.md").is_file())
            self.assertEqual(list((vault / "03. Artifact").glob("*.md")), [])

    def test_argument_errors_are_structured_json(self):
        code, stdout, stderr = run_cli(["not-a-command"])

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertFalse(json.loads(stderr)["ok"])

    def test_sync_accepts_fixture_without_calling_twitter(self):
        with TemporaryDirectory() as tmp:
            with patch("nextx.cli.fetch_bookmarks") as fetch:
                code, stdout, stderr = run_cli(
                    [
                        "sync-bookmarks",
                        "--vault",
                        tmp,
                        "--input-json",
                        str(FIXTURE),
                    ]
                )

            result = json.loads(stdout)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            self.assertEqual(result["report"]["created"], 2)
            fetch.assert_not_called()

    def test_collect_imports_grok_contract(self):
        with TemporaryDirectory() as tmp:
            code, stdout, stderr = run_cli(
                [
                    "collect",
                    "--vault",
                    tmp,
                    "--source",
                    "grok",
                    "--input-json",
                    str(GROK_FIXTURE),
                ]
            )

            result = json.loads(stdout)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            self.assertEqual(result["report"]["created"], 2)

    def test_add_signal_captures_manual_idea(self):
        with TemporaryDirectory() as tmp:
            code, stdout, stderr = run_cli(
                ["add-signal", "--vault", tmp, "--text", "A manual idea"]
            )

            result = json.loads(stdout)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            self.assertEqual(result["report"]["created"], 1)

    def test_signal_usability_migration_cli_previews_by_default_and_applies_explicitly(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp)
            self.make_signal_vault(vault)
            source = signal_path(vault, "x:42")
            legacy = source.with_name("x-42.md")
            source.rename(legacy)

            preview_code, preview_stdout, preview_stderr = run_cli(
                ["migrate-signal-usability", "--vault", tmp]
            )

            preview = json.loads(preview_stdout)
            self.assertEqual(preview_code, 0)
            self.assertEqual(preview_stderr, "")
            self.assertTrue(preview["dry_run"])
            self.assertTrue(legacy.exists())

            apply_code, apply_stdout, apply_stderr = run_cli(
                ["migrate-signal-usability", "--vault", tmp, "--apply"]
            )

            applied = json.loads(apply_stdout)
            self.assertEqual(apply_code, 0)
            self.assertEqual(apply_stderr, "")
            self.assertFalse(applied["dry_run"])
            self.assertEqual(len(applied["migrated"]), 1)
            self.assertFalse(legacy.exists())

    def test_today_renders_obisidian_view(self):
        with TemporaryDirectory() as tmp:
            run_cli(
                [
                    "collect",
                    "--vault",
                    tmp,
                    "--source",
                    "grok",
                    "--input-json",
                    str(GROK_FIXTURE),
                ]
            )

            code, stdout, stderr = run_cli(["today", "--vault", tmp])

            result = json.loads(stdout)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            self.assertEqual(result["automatic_count"], 2)
            self.assertTrue((Path(tmp) / "04. Views" / "Today.md").exists())
            self.assertEqual(len(result["signal_inboxes"]["paths"]), 7)
            self.assertTrue(
                Path(result["signal_inboxes"]["paths"]["needs_triage"]).exists()
            )

    def test_signal_inbox_command_only_rebuilds_disposable_views(self):
        with TemporaryDirectory() as tmp:
            run_cli(
                [
                    "collect",
                    "--vault",
                    tmp,
                    "--source",
                    "grok",
                    "--input-json",
                    str(GROK_FIXTURE),
                ]
            )
            signal = signal_path(Path(tmp), "x:3001")
            before = signal.read_text(encoding="utf-8")

            code, stdout, stderr = run_cli(["signal-inbox", "--vault", tmp])

            result = json.loads(stdout)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            self.assertEqual(result["command"], "signal-inbox")
            self.assertEqual(result["counts"]["needs_triage"], 2)
            self.assertEqual(len(result["paths"]), 7)
            self.assertEqual(signal.read_text(encoding="utf-8"), before)

    def test_decision_brief_and_save_decision(self):
        with TemporaryDirectory() as tmp:
            run_cli(
                ["collect", "--vault", tmp, "--source", "grok", "--input-json", str(GROK_FIXTURE)]
            )

            brief_code, brief_stdout, _ = run_cli(
                ["decision-brief", "--vault", tmp, "x:3001"]
            )
            save_code, save_stdout, save_stderr = run_cli(
                ["save-decision", "--vault", tmp, "--input-json", str(DECISION_FIXTURE)]
            )

            self.assertEqual(brief_code, 0)
            self.assertIn("topic-engine", json.loads(brief_stdout)["brief"])
            self.assertEqual(save_code, 0)
            self.assertEqual(save_stderr, "")
            self.assertEqual(json.loads(save_stdout)["verdict"], "do")

    def test_artifact_brief_save_and_publish_record(self):
        with TemporaryDirectory() as tmp:
            run_cli(
                ["collect", "--vault", tmp, "--source", "grok", "--input-json", str(GROK_FIXTURE)]
            )
            _, decision_stdout, _ = run_cli(
                ["save-decision", "--vault", tmp, "--input-json", str(DECISION_FIXTURE)]
            )
            decision_id = json.loads(decision_stdout)["id"]
            draft_file = Path(tmp) / "artifact.json"
            draft_file.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "account_key": "primary",
                        "decision_id": decision_id,
                        "format": "single-post",
                        "draft": "A validated draft.",
                    }
                ),
                encoding="utf-8",
            )

            brief_code, brief_stdout, _ = run_cli(
                ["artifact-brief", "--vault", tmp, decision_id]
            )
            save_code, save_stdout, _ = run_cli(
                ["save-artifact", "--vault", tmp, "--input-json", str(draft_file)]
            )
            artifact_result = json.loads(save_stdout)
            artifact_id = artifact_result["id"]
            artifact_path = Path(artifact_result["path"])
            artifact_path.write_text(
                artifact_path.read_text(encoding="utf-8").replace("- [ ]", "- [x]"),
                encoding="utf-8",
            )
            ready_code, _, _ = run_cli(
                ["mark-review-ready", "--vault", tmp, artifact_id]
            )
            confirm_code, _, _ = run_cli(
                ["confirm-publish", "--vault", tmp, artifact_id, "--yes"]
            )
            publish_code, publish_stdout, publish_stderr = run_cli(
                [
                    "record-published",
                    "--vault",
                    tmp,
                    artifact_id,
                    "--url",
                    "https://x.com/example/status/7001",
                ]
            )

            self.assertEqual(brief_code, 0)
            self.assertIn("x-tweet-writer", json.loads(brief_stdout)["brief"])
            self.assertTrue(Path(json.loads(brief_stdout)["handoff_path"]).exists())
            self.assertEqual(save_code, 0)
            self.assertEqual(ready_code, 0)
            self.assertEqual(confirm_code, 0)
            self.assertEqual(publish_code, 0)
            self.assertEqual(publish_stderr, "")
            self.assertEqual(json.loads(publish_stdout)["status"], "published")
            update_frontmatter(
                artifact_path,
                {"published_at": (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()},
            )

            outcome_file = Path(tmp) / "outcome.json"
            outcome_file.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "account_key": "primary",
                        "window": "7d",
                        "views": 700,
                        "likes": 30,
                        "replies": 4,
                        "reposts": 6,
                        "bookmarks": 8,
                        "growth_signals": {
                            "follow_up_completed": True,
                            "non_follower_replies": 2,
                            "observations": ["A new reader asked for the template."],
                        },
                    }
                ),
                encoding="utf-8",
            )
            outcome_code, outcome_stdout, _ = run_cli(
                [
                    "record-outcome",
                    "--vault",
                    tmp,
                    artifact_id,
                    "--input-json",
                    str(outcome_file),
                ]
            )
            review_code, review_stdout, _ = run_cli(
                ["weekly-review", "--vault", tmp]
            )

            self.assertEqual(outcome_code, 0)
            self.assertEqual(json.loads(outcome_stdout)["status"], "measured")
            self.assertEqual(review_code, 0)
            self.assertTrue(Path(json.loads(review_stdout)["view"]).exists())

    def test_expected_failure_returns_json_only_on_stderr(self):
        with TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.json"

            code, stdout, stderr = run_cli(
                [
                    "sync-bookmarks",
                    "--vault",
                    tmp,
                    "--input-json",
                    str(missing),
                ]
            )

            self.assertEqual(code, 1)
            self.assertEqual(stdout, "")
            self.assertFalse(json.loads(stderr)["ok"])

    @patch("nextx.cli.shutil.which", return_value="/usr/local/bin/twitter")
    def test_doctor_without_smoke_does_not_read_bookmarks(self, _which):
        with TemporaryDirectory() as tmp:
            with patch("nextx.cli.fetch_bookmarks") as fetch:
                code, stdout, stderr = run_cli(
                    ["doctor", "--vault", tmp, "--no-smoke"]
                )

            result = json.loads(stdout)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            self.assertEqual(result["checks"]["twitter_binary"], "ready")
            self.assertEqual(result["checks"]["bookmark_smoke"], "skipped")
            fetch.assert_not_called()

    @patch("nextx.cli.shutil.which", return_value=None)
    def test_doctor_without_smoke_allows_optional_twitter_to_be_missing(self, _which):
        with TemporaryDirectory() as tmp:
            code, stdout, stderr = run_cli(["doctor", "--vault", tmp, "--no-smoke"])

            result = json.loads(stdout)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            self.assertTrue(result["ok"])
            self.assertEqual(result["checks"]["twitter_binary"], "missing")

    @patch("nextx.preflight.shutil.which", return_value=None)
    def test_preflight_is_read_only_and_reports_missing_dependencies(self, _which):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            code, stdout, stderr = run_cli(
                ["preflight", "--vault", str(vault), "--intent", "daily"]
            )

            result = json.loads(stdout)
            self.assertEqual(code, 1)
            self.assertEqual(stderr, "")
            self.assertFalse(result["ok"])
            self.assertTrue(result["read_only"])
            self.assertFalse(vault.exists())
            self.assertFalse(any("Agent 能力" in blocker for blocker in result["blockers"]))

    @patch("nextx.preflight.shutil.which", return_value="/usr/local/bin/twitter")
    def test_preflight_accepts_verified_skill_path(self, _which):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            run_cli(["setup", "--vault", str(vault), "--yes"])
            self_dir = vault / "00. Self"
            profile = self_dir / "Profile.md"
            profile.write_text(profile.read_text(encoding="utf-8").replace("## 一句话定位\n", "## 一句话定位\n\nLocal-first X operations.\n"), encoding="utf-8")
            voice = self_dir / "Voice.md"
            voice.write_text(voice.read_text(encoding="utf-8").replace("## 真实优秀样本\n", "## 真实优秀样本\n\nA real original sentence.\n"), encoding="utf-8")
            pillars = self_dir / "Pillars.md"
            pillars.write_text(pillars.read_text(encoding="utf-8").replace("1.\n2.\n3.", "1. Product\n2. AI\n3. X" ) + "\nNo spam.\n", encoding="utf-8")
            skills_root = Path(tmp) / "skills"
            for name in ("topic-engine", "x-tweet-writer"):
                target = skills_root / name
                target.mkdir(parents=True)
                (target / "SKILL.md").write_text("---\nname: test\n---\n", encoding="utf-8")

            code, stdout, stderr = run_cli(
                [
                    "preflight", "--vault", str(vault), "--intent", "daily",
                    "--skills-root", str(skills_root),
                ]
            )

            result = json.loads(stdout)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            self.assertTrue(result["ok"])
            self.assertEqual(
                [item["status"] for item in result["checks"]["agents"]],
                ["ready", "ready"],
            )

    @patch("nextx.preflight.shutil.which", return_value=None)
    def test_preflight_uses_bundled_core_when_optional_ayi_skills_are_absent(self, _which):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            configure_self(
                vault,
                {
                    "schema_version": 1,
                    "account_key": "primary",
                    "positioning": "Local-first X operations.",
                    "audience": "Solo builders.",
                    "stage": "冷启动",
                    "pillars": ["Product", "AI", "X"],
                    "boundaries": "No spam.",
                    "voice_samples": ["A real original sentence."],
                },
            )

            code, stdout, stderr = run_cli(
                ["preflight", "--vault", str(vault), "--intent", "daily"]
            )

            result = json.loads(stdout)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            self.assertTrue(result["ok"])
            self.assertEqual(
                [item["selected_capability"] for item in result["checks"]["agents"]],
                ["nextx-core", "nextx-core"],
            )

    def test_preflight_marks_declared_agent_capability_as_unverified(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            run_cli(["init", "--vault", str(vault)])

            code, stdout, stderr = run_cli(
                [
                    "preflight", "--vault", str(vault), "--intent", "collect-grok",
                    "--agent-capability", "grok-build",
                ]
            )

            result = json.loads(stdout)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            self.assertEqual(result["checks"]["agents"][0]["status"], "declared")
            self.assertTrue(any("仅由调用方声明" in warning for warning in result["warnings"]))

    def test_triage_brief_returns_one_signal_and_contract(self):
        with TemporaryDirectory() as tmp:
            vault = self.make_signal_vault(Path(tmp))
            code, stdout, stderr = run_cli(["triage-brief", "x:42", "--vault", str(vault)])

            result = json.loads(stdout)
            self.assertEqual(code, 0)
            self.assertEqual(result["signal_id"], "x:42")
            self.assertTrue(Path(result["contract"]).is_file())
            self.assertIn("A verifiable Signal for quick triage.", stdout)
            self.assertNotIn("x:43", stdout)
            self.assertNotIn("another-signal must not be included", stdout)
            self.assertEqual(stderr, "")

    def test_save_triage_accepts_json_file_and_prints_computed_fields(self):
        with TemporaryDirectory() as tmp:
            vault = self.make_signal_vault(Path(tmp))
            payload = Path(tmp) / "triage.json"
            payload.write_text(json.dumps(self.triage_payload("x:42")), encoding="utf-8")
            code, stdout, stderr = run_cli(
                ["save-triage", "--vault", str(vault), "--input-json", str(payload)]
            )

            result = json.loads(stdout)
            self.assertEqual(code, 0)
            self.assertIn("triage_score", result)
            self.assertNotIn("traceback", stderr.casefold())

    def test_save_triage_accepts_json_from_standard_input(self):
        with TemporaryDirectory() as tmp:
            vault = self.make_signal_vault(Path(tmp))
            with patch("nextx.cli.sys.stdin", StringIO(json.dumps(self.triage_payload("x:42")))):
                code, stdout, stderr = run_cli(
                    ["save-triage", "--vault", str(vault), "--input-json", "-"]
                )

            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            self.assertIn("triage_score", json.loads(stdout))

    def test_triage_commands_return_structured_errors_for_invalid_input_missing_signal_and_lock(self):
        with TemporaryDirectory() as tmp:
            vault = self.make_signal_vault(Path(tmp))
            invalid = Path(tmp) / "invalid.json"
            invalid.write_text("{", encoding="utf-8")
            invalid_code, invalid_stdout, invalid_stderr = run_cli(
                ["save-triage", "--vault", str(vault), "--input-json", str(invalid)]
            )
            missing_code, missing_stdout, missing_stderr = run_cli(
                ["triage-brief", "x:missing", "--vault", str(vault)]
            )

            payload = Path(tmp) / "triage.json"
            payload.write_text(json.dumps(self.triage_payload("x:42")), encoding="utf-8")
            run_cli(["save-triage", "--vault", str(vault), "--input-json", str(payload)])
            update_frontmatter(signal_path(vault, "x:42"), {"triage_locked": True})
            lock_code, lock_stdout, lock_stderr = run_cli(
                ["save-triage", "--vault", str(vault), "--input-json", str(payload)]
            )

            for code, stdout, stderr in (
                (invalid_code, invalid_stdout, invalid_stderr),
                (missing_code, missing_stdout, missing_stderr),
                (lock_code, lock_stdout, lock_stderr),
            ):
                self.assertEqual(code, 1)
                self.assertEqual(stdout, "")
                self.assertFalse(json.loads(stderr)["ok"])

    def test_quote_collection_preflight_accepts_an_authorized_read_only_alternative(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            run_cli(["init", "--vault", str(vault)])

            code, stdout, stderr = run_cli(
                [
                    "preflight", "--vault", str(vault), "--intent", "collect-quote",
                    "--agent-capability", "agent-reach",
                ]
            )

            result = json.loads(stdout)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            self.assertEqual(result["checks"]["agents"][0]["status"], "declared")
            self.assertEqual(result["checks"]["agents"][0]["selected_capability"], "agent-reach")

    def test_contract_catalog_exposes_all_agent_input_schemas(self):
        code, stdout, stderr = run_cli(["contracts"])

        result = json.loads(stdout)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertTrue(result["ok"])
        self.assertEqual(
            {item["name"] for item in result["contracts"]},
            {"self", "collector", "triage", "cluster", "topic", "analysis", "decision", "artifact", "outcome"},
        )
        self.assertTrue(all(Path(item["path"]).is_file() for item in result["contracts"]))

    def test_collector_prompt_exposes_a_runtime_absolute_path(self):
        code, stdout, stderr = run_cli(["collector-prompt", "--source", "grok"])

        result = json.loads(stdout)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertTrue(result["ok"])
        self.assertTrue(Path(result["path"]).is_file())

    def test_quote_sprint_and_quote_brief_are_available_to_agents(self):
        with TemporaryDirectory() as tmp:
            quote_fixture = Path(tmp) / "quote-signals.json"
            payload = json.loads(GROK_FIXTURE.read_text(encoding="utf-8"))
            collected_at = datetime.now(timezone.utc).replace(microsecond=0)
            payload["retrieved_at"] = collected_at.isoformat()
            payload["items"][0].update(
                {
                    "published_at": (collected_at - timedelta(hours=1)).isoformat(),
                    "quote_candidate": True,
                    "quote_window_ends_at": (collected_at + timedelta(hours=6)).isoformat(),
                }
            )
            quote_fixture.write_text(json.dumps(payload), encoding="utf-8")
            run_cli(
                [
                    "collect", "--vault", tmp, "--source", "grok",
                    "--input-json", str(quote_fixture),
                ]
            )

            sprint_code, sprint_stdout, sprint_stderr = run_cli(["quote-sprint", "--vault", tmp])
            brief_code, brief_stdout, brief_stderr = run_cli(["quote-brief", "--vault", tmp, "x:3001"])
            prompt_code, prompt_stdout, prompt_stderr = run_cli(
                ["collector-prompt", "--source", "quote"]
            )

            self.assertEqual(sprint_code, 0)
            self.assertEqual(sprint_stderr, "")
            self.assertEqual(json.loads(sprint_stdout)["selected_count"], 1)
            self.assertEqual(brief_code, 0)
            self.assertEqual(brief_stderr, "")
            self.assertEqual(json.loads(brief_stdout)["execution_mode"], "quote")
            self.assertEqual(prompt_code, 0)
            self.assertEqual(prompt_stderr, "")
            self.assertTrue(Path(json.loads(prompt_stdout)["path"]).is_file())

    def test_reply_sprint_reply_brief_and_growth_loop_are_available_to_agents(self):
        with TemporaryDirectory() as tmp:
            reply_fixture = Path(tmp) / "reply-signals.json"
            payload = json.loads(GROK_FIXTURE.read_text(encoding="utf-8"))
            collected_at = datetime.now(timezone.utc).replace(microsecond=0)
            payload["retrieved_at"] = collected_at.isoformat()
            payload["items"][0].update(
                {
                    "published_at": (collected_at - timedelta(hours=1)).isoformat(),
                    "reply_candidate": True,
                    "reply_window_ends_at": (collected_at + timedelta(hours=6)).isoformat(),
                }
            )
            reply_fixture.write_text(json.dumps(payload), encoding="utf-8")
            run_cli(
                ["collect", "--vault", tmp, "--source", "grok", "--input-json", str(reply_fixture)]
            )

            sprint_code, sprint_stdout, sprint_stderr = run_cli(["reply-sprint", "--vault", tmp])
            brief_code, brief_stdout, brief_stderr = run_cli(["reply-brief", "--vault", tmp, "x:3001"])
            loop_code, loop_stdout, loop_stderr = run_cli(["growth-loop", "--vault", tmp])
            prompt_code, prompt_stdout, prompt_stderr = run_cli(
                ["collector-prompt", "--source", "reply"]
            )

            self.assertEqual(sprint_code, 0)
            self.assertEqual(sprint_stderr, "")
            self.assertEqual(json.loads(sprint_stdout)["selected_count"], 1)
            self.assertEqual(brief_code, 0)
            self.assertEqual(brief_stderr, "")
            self.assertEqual(json.loads(brief_stdout)["execution_mode"], "reply")
            self.assertEqual(loop_code, 0)
            self.assertEqual(loop_stderr, "")
            self.assertEqual(json.loads(loop_stdout)["next_action"]["id"], "configure_self")
            self.assertEqual(prompt_code, 0)
            self.assertEqual(prompt_stderr, "")
            self.assertTrue(Path(json.loads(prompt_stdout)["path"]).is_file())

    def test_stdin_input_and_account_status_are_available_to_agents(self):
        with TemporaryDirectory() as tmp:
            with patch("nextx.cli.sys.stdin", StringIO('{"schema_version":1}')):
                self.assertEqual(_load_input(Path("-")), {"schema_version": 1})
            code, stdout, stderr = run_cli(["account-status", "--vault", tmp])

            result = json.loads(stdout)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            self.assertEqual(result["active_account"], "primary")
            self.assertEqual(result["multi_account_routing"], "not_enabled")

    def test_live_bookmark_failure_is_recorded_in_local_health(self):
        with TemporaryDirectory() as tmp:
            with patch(
                "nextx.cli.fetch_bookmarks",
                side_effect=TwitterCLIError("authentication required"),
            ):
                code, stdout, stderr = run_cli(
                    ["sync-bookmarks", "--vault", tmp, "--limit", "1"]
                )

            self.assertEqual(code, 1)
            self.assertEqual(stdout, "")
            self.assertIn("authentication required", json.loads(stderr)["error"])
            health = read_bookmark_health(Path(tmp))
            self.assertEqual(health["status"], "failed")
            self.assertIn("authentication required", health["last_error"])

    def test_bookmark_dry_run_failure_does_not_create_a_vault_or_health_record(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp) / "new-vault"
            with patch(
                "nextx.cli.fetch_bookmarks",
                side_effect=TwitterCLIError("authentication required"),
            ):
                code, stdout, stderr = run_cli(
                    ["sync-bookmarks", "--vault", str(vault), "--limit", "1", "--dry-run"]
                )

            self.assertEqual(code, 1)
            self.assertEqual(stdout, "")
            self.assertIn("authentication required", json.loads(stderr)["error"])
            self.assertFalse(vault.exists())

    def test_recover_lock_command_reports_an_absent_lock_without_initializing_vault(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp) / "new-vault"

            code, stdout, stderr = run_cli(["recover-lock", "--vault", str(vault)])

            result = json.loads(stdout)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            self.assertEqual(result["status"], "absent")
            self.assertFalse(vault.exists())

    def test_next_step_is_read_only_and_describes_setup_then_self_configuration(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            code, stdout, stderr = run_cli(["next-step", "--vault", str(vault)])
            initial = json.loads(stdout)

            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            self.assertEqual(initial["phase"], "setup_required")
            self.assertTrue(initial["next_action"]["requires_user_confirmation"])
            self.assertFalse(vault.exists())

            run_cli(["setup", "--vault", str(vault), "--yes"])
            code, stdout, _ = run_cli(["next-step", "--vault", str(vault)])
            configured = json.loads(stdout)

            self.assertEqual(code, 0)
            self.assertEqual(configured["phase"], "self_required")
            self.assertEqual(configured["next_action"]["id"], "configure_self")

    def test_configure_self_accepts_agent_json_from_standard_input(self):
        with TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            payload = {
                "schema_version": 1,
                "account_key": "primary",
                "positioning": "A local-first X operator.",
                "audience": "Solo builders.",
                "stage": "冷启动",
                "pillars": ["Agents", "Product", "Writing"],
                "boundaries": "No unverified claims.",
                "voice_samples": ["Make the loop smaller, then make it real."],
            }
            with patch("nextx.cli.sys.stdin", StringIO(json.dumps(payload))):
                code, stdout, stderr = run_cli(
                    ["configure-self", "--vault", str(vault), "--input-json", "-"]
                )

            result = json.loads(stdout)
            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            self.assertTrue(result["ready"])
            self.assertTrue((vault / "00. Self" / "Profile.md").is_file())

    def triage_payload(self, signal_id: str) -> dict[str, object]:
        payload = json.loads(TRIAGE_FIXTURE.read_text(encoding="utf-8"))
        payload["signal_id"] = signal_id
        return payload

    def _make_topic_cluster(self, vault: Path) -> None:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        ingest_signals(
            vault,
            {"schema_version": 1, "account_key": "primary", "collector": "grok-build", "retrieved_at": now.isoformat(), "items": [
                {"source_id": "x:801", "platform": "x", "source_url": "https://x.com/one/status/801", "author_handle": "one", "published_at": now.isoformat(), "text": "First CLI source", "source_confidence": "high"},
                {"source_id": "x:802", "platform": "x", "source_url": "https://x.com/two/status/802", "author_handle": "two", "published_at": now.isoformat(), "text": "Second CLI source", "source_confidence": "high"},
            ]},
            collector="grok-build", now=now,
        )
        for signal_id in ("x:801", "x:802"):
            save_triage(vault, {
                "schema_version": 1, "account_key": "primary", "signal_id": signal_id, "display_title": "Ready CLI Signal", "language": "en", "content_lane": "builder_core", "topic_labels": ["AI"], "triage_status": "ready", "recommended_action": "topic", "triage_factors": {"reader_fit": 5, "evidence": 5, "value_add": 5, "urgency": 5}, "triage_confidence": "high", "summary": "Ready.", "target_reader": "Builders", "why_relevant": "Relevant.", "value_add": "Useful.", "risk": "Small sample.", "deep_dive": False, "reason_codes": ["fit"],
            }, now=now)
        brief = build_cluster_brief(vault, now=now)
        save_clusters(vault, {
            "schema_version": 1, "account_key": "primary", "cluster_run_id": brief["cluster_run_id"],
            "clusters": [{"kind": "evergreen", "signal_ids": ["x:801", "x:802"], "display_title": "CLI workflows", "proposition": "Systems beat tricks.", "confidence": "high", "why_now": "Recent.", "target_reader": "Builders", "candidate_angle": "Systems.", "recommended_next_step": "topic_card", "evidence": [{"signal_id": "x:801", "quote": "First CLI source", "role": "support", "translation_status": "original"}, {"signal_id": "x:802", "quote": "Second CLI source", "role": "counter", "translation_status": "original"}]}], "adjacent_candidates": [],
        }, now=now)

    def _topic_payload(self, cluster_id: str) -> dict[str, object]:
        return {
            "schema_version": 1, "account_key": "primary", "cluster_id": cluster_id, "status": "active", "suggested_mode": "original", "display_title": "CLI durable workflows", "proposition": "Systems beat tricks.", "content_lane": "builder_core", "target_reader": "Builders", "takeaway": "A reusable workflow checklist.", "value_type": "tool", "primary_platform": "x", "secondary_platform": "newsletter", "recommended_angle": "Contrast systems and tricks.", "title_directions": ["Strategy", "Checklist"], "quality_gates": {"human": "Direct observation.", "useful": "Checklist.", "timely": "Evergreen.", "identity_leverage": "Builder perspective."}, "ip_dimensions": {"differentiation": 1, "depth": 1, "perspective": 1, "clarity": 1, "courage": 1, "shareability": 1}, "traffic_dimensions": {"benefit_visibility": 5, "hook_strength": 4, "asset_promise": 5, "actionability": 5}, "ip_band": "S", "traffic_band": "strong_hook", "decision_class": "compound", "why_worth_doing": "Two sources.", "evidence": [{"signal_id": "x:801", "quote": "First CLI source", "role": "support", "translation_status": "original"}, {"signal_id": "x:802", "quote": "Second CLI source", "role": "counter", "translation_status": "original"}], "counterpoint": "Prompts can still help.", "evidence_to_strengthen": "A direct comparison.", "max_risk": "Small sample.", "confidence": "high", "compliance": {"band": "green", "reason": "Method-focused.", "mitigation": ""}, "action_signal_id": None, "revisit_at": None, "notes": "Explicit save.",
        }

    def make_signal_vault(self, vault: Path) -> Path:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        ingest_signals(
            vault,
            {
                "schema_version": 1,
                "account_key": "primary",
                "collector": "grok-build",
                "retrieved_at": now.isoformat(),
                "items": [
                    {
                        "source_id": "x:42",
                        "platform": "x",
                        "source_url": "https://x.com/alpha/status/42",
                        "author_handle": "alpha",
                        "published_at": now.isoformat(),
                        "text": "A verifiable Signal for quick triage.",
                        "source_confidence": "high",
                    },
                    {
                        "source_id": "x:43",
                        "platform": "x",
                        "source_url": "https://x.com/beta/status/43",
                        "author_handle": "beta",
                        "published_at": now.isoformat(),
                        "text": "another-signal must not be included",
                        "source_confidence": "high",
                    },
                ],
            },
            collector="grok-build",
            now=now,
        )
        return vault


if __name__ == "__main__":
    unittest.main()
