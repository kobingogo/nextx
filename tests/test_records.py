from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from nextx.records import append_markdown, read_frontmatter, update_frontmatter


class RecordTests(unittest.TestCase):
    def test_frontmatter_values_and_body_round_trip(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "record.md"
            path.write_text(
                '---\nid: "x:1"\nmetrics: {"likes":3}\ntags: ["a","b"]\n---\n# Body\n\nUser text.\n',
                encoding="utf-8",
            )

            properties, body = read_frontmatter(path)

            self.assertEqual(properties["id"], "x:1")
            self.assertEqual(properties["metrics"], {"likes": 3})
            self.assertEqual(properties["tags"], ["a", "b"])
            self.assertEqual(body, "# Body\n\nUser text.\n")

    def test_update_preserves_unknown_property_and_body(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "record.md"
            path.write_text(
                '---\nid: "artifact:1"\ncustom_user_field: "keep"\nstatus: "draft"\n---\nBody stays.\n',
                encoding="utf-8",
            )

            update_frontmatter(path, {"status": "published", "published_url": "https://x.com/u/status/1"})

            properties, body = read_frontmatter(path)
            self.assertEqual(properties["custom_user_field"], "keep")
            self.assertEqual(properties["status"], "published")
            self.assertEqual(properties["published_url"], "https://x.com/u/status/1")
            self.assertEqual(body, "Body stays.\n")

    def test_append_markdown_keeps_existing_text(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "record.md"
            path.write_text("first\n", encoding="utf-8")

            append_markdown(path, "second")

            self.assertEqual(path.read_text(encoding="utf-8"), "first\n\nsecond\n")


if __name__ == "__main__":
    unittest.main()
