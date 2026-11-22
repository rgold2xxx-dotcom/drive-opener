"""python -m unittest discover -s tests"""

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import make_release_notes as rn  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")


class ReleaseNotesTest(unittest.TestCase):
    def run_main(self, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            code = rn.main(list(args))
        return code, out.getvalue()

    def test_title(self):
        self.assertEqual(rn.title("1.2.0"), "Drive Opener host app 1.2.0 / ホスト 1.2.0")

    def test_build_with_changes(self):
        body = rn.build("1.2.0", "## What's new\n\n- A\n\n## 変更点\n\n- あ\n", "https://example.com/r")
        self.assertTrue(body.startswith("**Drive Opener host app 1.2.0 / Drive Opener ホスト 1.2.0**"))
        self.assertIn("- A", body)
        self.assertIn("- あ", body)
        self.assertIn("`DriveOpenerSetup-1.2.0.exe`", body)
        self.assertIn("https://example.com/r/blob/main/README.en.md", body)
        self.assertIn("https://example.com/r/blob/main/README.md", body)
        # 英語の案内が日本語の案内より先
        self.assertLess(body.index("See the [README]"), body.index("インストール方法"))
        self.assertIn("not code-signed", body)
        self.assertIn("コード署名がありません", body)

    def test_missing_notes_warns_on_manual_run(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "out.md")
            code, log = self.run_main("--version", "9.9.9", "--out", out, "--notes-dir", d)
            self.assertEqual(code, 0)
            self.assertIn("::warning::", log)
            body = open(out, encoding="utf-8").read()
            self.assertIn("## Files / ファイル", body)
            self.assertNotIn("What's new", body)

    def test_missing_notes_fails_on_tag(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "out.md")
            code, log = self.run_main("--version", "9.9.9", "--out", out, "--notes-dir", d, "--require")
            self.assertEqual(code, 1)
            self.assertIn("::error::", log)
            self.assertFalse(os.path.exists(out))

    def test_bad_version(self):
        with tempfile.TemporaryDirectory() as d:
            code, log = self.run_main("--version", "1.2", "--out", os.path.join(d, "o.md"))
            self.assertEqual(code, 1)

    def test_published_notes_file_has_both_languages(self):
        # 見本として残した release-notes/1.1.0.md が英語・日本語の両方を持つ
        path = os.path.join(ROOT, "release-notes", "1.1.0.md")
        text = open(path, encoding="utf-8").read()
        self.assertIn("## What's new", text)
        self.assertIn("## 変更点", text)
        self.assertLess(text.index("## What's new"), text.index("## 変更点"))

    def test_notes_exist_for_current_version(self):
        # host/drive_opener.py の VERSION の変更点ファイルがある（タグの前に書き忘れないため）
        src = open(os.path.join(ROOT, "host", "drive_opener.py"), encoding="utf-8").read()
        import re

        version = re.search(r'^VERSION = "([0-9.]+)"', src, re.M).group(1)
        self.assertTrue(os.path.exists(os.path.join(ROOT, "release-notes", f"{version}.md")),
                        f"release-notes/{version}.md がない")


if __name__ == "__main__":
    unittest.main()
