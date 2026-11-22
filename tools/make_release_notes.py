"""リリースの説明文（英語・日本語）を組み立てる。GitHub Actions（.github/workflows/release.yml）から使う。

  python tools/make_release_notes.py --version 1.2.0 --out dist/RELEASE_NOTES.md [--require]

- 版ごとの変更点は release-notes/<版>.md に英語・日本語で書く（英語を先に）
- その前後に、共通の文（見出し・ファイルの説明・README へのリンク・コード署名がない旨）を英語・日本語で付ける
- 変更点のファイルがないとき：--require（タグを打ったとき）ならエラーで止める。付けないとき（手動実行）は警告を出し、共通の文だけで組み立てる
"""

from __future__ import annotations

import argparse
import os
import re
import sys

DEFAULT_REPO_URL = "https://github.com/rgold2xxx-dotcom/drive-opener"
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def title(version: str) -> str:
    return f"Drive Opener host app {version} / ホスト {version}"


def build(version: str, changes: str | None, repo_url: str = DEFAULT_REPO_URL) -> str:
    readme_en = f"{repo_url}/blob/main/README.en.md"
    readme_ja = f"{repo_url}/blob/main/README.md"
    parts = [f"**Drive Opener host app {version} / Drive Opener ホスト {version}**", ""]
    if changes and changes.strip():
        parts += [changes.strip(), ""]
    parts += [
        "## Files / ファイル",
        "",
        "- `DriveOpenerSetup.exe`: always the latest version / 常に最新版",
        f"- `DriveOpenerSetup-{version}.exe`: this version / この版",
        "- `SHA256SUMS.txt`: SHA-256 checksums / SHA-256",
        "",
        f"See the [README]({readme_en}) for installation steps and what to do if Windows shows a warning. "
        "This installer is not code-signed.",
        "",
        f"インストール方法と警告が出たときの進め方は [README]({readme_ja}) を見てください。"
        "このインストーラーにはコード署名がありません。",
        "",
    ]
    return "\n".join(parts)


def notes_path(version: str, notes_dir: str) -> str:
    return os.path.join(notes_dir, f"{version}.md")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--version", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--notes-dir", default="release-notes")
    ap.add_argument("--require", action="store_true", help="変更点のファイルがなければエラーにする（タグのとき）")
    ap.add_argument("--repo-url", default=None)
    args = ap.parse_args(argv)

    if not VERSION_RE.match(args.version):
        print(f"::error::バージョンの形式が正しくありません: {args.version}")
        return 1
    repo_url = args.repo_url
    if not repo_url and os.environ.get("GITHUB_REPOSITORY"):
        repo_url = f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{os.environ['GITHUB_REPOSITORY']}"
    repo_url = repo_url or DEFAULT_REPO_URL

    path = notes_path(args.version, args.notes_dir)
    changes = None
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig") as f:
            changes = f.read()
    if not changes or not changes.strip():
        msg = f"{path} がありません（または空です）。タグを打つ前に、変更点を英語・日本語で書いてください"
        if args.require:
            print(f"::error::{msg}")
            return 1
        print(f"::warning::{msg}")

    body = build(args.version, changes, repo_url)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
