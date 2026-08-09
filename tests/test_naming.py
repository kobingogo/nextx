from datetime import datetime, timezone
import unittest

from nextx.naming import human_signal_filename, signal_display_title


class NamingTests(unittest.TestCase):
    def test_x_name_is_readable_and_keeps_the_full_tweet_id(self):
        name = human_signal_filename(
            signal_id="x:2086237980872847443",
            platform="x",
            author_handle="swyx",
            observed_at="2026-08-09T01:02:03+00:00",
            display_title="Agent 工作流正在从工具变成基础设施",
        )
        self.assertEqual(
            name,
            "2026-08-09__x__swyx__Agent-工作流正在从工具变成基础设施__2086237980872847443.md",
        )

    def test_non_x_name_uses_a_short_identity_hash_and_never_uses_path_separators(self):
        name = human_signal_filename(
            signal_id="feed:alpha",
            platform="web/rss",
            author_handle="../author",
            observed_at="2026-08-09T01:02:03Z",
            display_title='../../A:*?"<>| title',
        )
        self.assertNotIn("/", name)
        self.assertNotIn("..", name)
        self.assertRegex(name, r"__[0-9a-f]{8}\.md$")

    def test_filename_components_remove_obsidian_wikilink_controls(self):
        name = human_signal_filename(
            signal_id="x:42",
            platform="x#feed",
            author_handle="author^block",
            observed_at="2026-08-09T01:02:03Z",
            display_title="Title [[alias]] #heading ^reference",
        )

        self.assertFalse(any(control in name for control in "#^[]"))

    def test_filename_fits_the_portable_utf8_limit(self):
        name = human_signal_filename(
            signal_id="feed:long",
            platform="网页",
            author_handle="作者",
            observed_at="2026-08-09T01:02:03Z",
            display_title="很长的中文标题" * 100,
        )
        self.assertLessEqual(len(name.encode("utf-8")), 240)

    def test_capture_title_is_deterministic_and_bounded(self):
        self.assertEqual(
            signal_display_title("\n  First   useful line  \nsecond"),
            "First useful line",
        )
        self.assertLessEqual(len(signal_display_title("字" * 500)), 100)


if __name__ == "__main__":
    unittest.main()
