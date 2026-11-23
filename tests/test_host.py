"""python -m unittest discover -s tests"""

import io
import os
import sqlite3
import struct
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "host"))
import drive_opener as h  # noqa: E402
import drivefs  # noqa: E402
import shortcut  # noqa: E402


def make_tree(base, paths):
    for p in paths:
        full = os.path.join(base, *p.split("/"))
        if p.endswith("/"):
            os.makedirs(full, exist_ok=True)
        else:
            os.makedirs(os.path.dirname(full), exist_ok=True)
            open(full, "w").close()


# DriveFS の metadata_sqlite_db を模したDB（使う列だけ）
SCHEMA = """
create table properties (property text primary key, value blob);
create table items (stable_id integer primary key, id text, local_title text, is_folder integer,
                    trashed integer, team_drive_stable_id integer, is_tombstone integer, mime_type text);
create table stable_parents (item_stable_id integer, parent_stable_id integer, local_title_hash integer);
create table shortcut_details (shortcut_stable_id integer, target_stable_id integer, target_mime_type text);
"""

ROOT = "0AROOTxxxxxxxxxx"
# stable_id, id, title, is_folder, trashed, team_drive, parent
ITEMS = [
    (1, ROOT, "マイドライブ", 1, 0, None, None),
    (2, "1Year2026xxxxxx", "2026", 1, 0, None, 1),
    (3, "1Mitsumorixxxxx", "見積", 1, 0, None, 2),
    (4, "1FileXlsxxxxxxx", "見積書.xlsx", 0, 0, None, 3),
    (5, "1Gdocxxxxxxxxxx", "メモ.gdoc", 0, 0, None, 3),
    (6, "1NotSyncedxxxxx", "未同期", 1, 0, None, 2),
    (7, "1Trashedxxxxxxx", "捨てた", 1, 1, None, 1),
    (10, "1SharedTopxxxxx", "他人のフォルダ", 1, 0, None, None),
    (11, "1SharedSubxxxxx", "中", 1, 0, None, 10),
    (20, "1OrphanTopxxxxx", "共有だけ", 1, 0, None, None),
    (21, "1ShortcutLnkxxx", "他人のフォルダ.lnk", 0, 0, None, 1),
    (30, "0ATeamDrivexxxx", "営業部", 1, 0, 30, None),
    (31, "1TeamSubxxxxxxx", "2026", 1, 0, 30, 30),
    (40, "1PCRootxxxxxxxx", "My Laptop", 1, 0, None, None),
    (41, "1PCSubxxxxxxxxx", "Documents", 1, 0, None, 40),
    (50, "1EvilNamexxxxxx", "..", 1, 0, None, 1),
]
SHORTCUTS = [(21, 10, "application/vnd.google-apps.folder")]

TREE = [
    "マイドライブ/2026/見積/見積書.xlsx",
    "マイドライブ/2026/見積/メモ.gdoc",
    "マイドライブ/他人のフォルダ.lnk",
    ".shortcut-targets-by-id/1SharedTopxxxxx/他人のフォルダ/中/",
    "共有ドライブ/営業部/2026/",
    "その他のパソコン/My Laptop/Documents/",
]


def make_db(path):
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.execute("insert into properties values ('root_id', ?)", (ROOT.encode(),))
    for sid, cid, title, folder, trashed, td, parent in ITEMS:
        con.execute("insert into items values (?,?,?,?,?,?,0,'')", (sid, cid, title, folder, trashed, td))
        if parent:
            con.execute("insert into stable_parents values (?,?,0)", (sid, parent))
    con.executemany("insert into shortcut_details values (?,?,?)", SHORTCUTS)
    con.commit()
    con.close()


class MessageTest(unittest.TestCase):
    def test_roundtrip(self):
        buf = io.BytesIO()
        h.write_message(buf, {"type": "ping", "名前": "営業部"})
        raw = buf.getvalue()
        (n,) = struct.unpack("<I", raw[:4])
        self.assertEqual(n, len(raw) - 4)
        self.assertEqual(h.read_message(io.BytesIO(raw)), {"type": "ping", "名前": "営業部"})

    def test_eof_and_bad(self):
        self.assertIsNone(h.read_message(io.BytesIO(b"")))
        with self.assertRaises(h.BadRequest):
            h.read_message(io.BytesIO(b"\x01\x00"))
        with self.assertRaises(h.BadRequest):
            h.read_message(io.BytesIO(struct.pack("<I", 3) + b"abc"))
        with self.assertRaises(h.BadRequest):
            h.read_message(io.BytesIO(struct.pack("<I", 10_000_000)))

    def test_unknown_type(self):
        with self.assertRaises(h.BadRequest):
            h.handle({"type": "exec", "cmd": "calc"})


class NameTest(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(h.normalize_name('a/b:c*?"<>|'), "a_b_c______")
        self.assertEqual(h.normalize_name("末尾 . "), "末尾")
        self.assertEqual(h.normalize_name("か\u3099"), "が")

    def test_reject(self):
        for bad in ["..", "a/../b", "..\\x", "C:", "C:\\Windows", "\\\\server\\share", "", "a\x00b", 1, None]:
            with self.assertRaises(h.BadRequest, msg=repr(bad)):
                h.validate_name(bad, "x")
        for ok in ["a..b", "見積:最終", "..hidden"]:
            self.assertEqual(h.validate_name(ok, "x"), ok)

    def test_match(self):
        with tempfile.TemporaryDirectory() as d:
            make_tree(d, ["a_b/", "dup (1)/", "memo.gdoc", "report (1).pdf"])
            self.assertEqual(h.match_child(d, "a/b", want_dir=True), "a_b")
            self.assertEqual(h.match_child(d, "dup", want_dir=True), "dup (1)")
            self.assertIsNone(h.match_child(d, "memo.gdoc", want_dir=True))
            self.assertEqual(h.match_child(d, "memo", file_like=True), "memo.gdoc")
            self.assertEqual(h.match_child(d, "report.pdf", file_like=True), "report (1).pdf")


class ResolveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mount = os.path.join(self.tmp.name, "G")
        make_tree(self.mount, TREE)
        self.db = os.path.join(self.tmp.name, "metadata_sqlite_db")
        make_db(self.db)
        self.opened = []

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, type_, id_):
        return h.handle(
            {"type": type_, "id": id_},
            mounts_fn=lambda: [{"path": self.mount, "label": "Google Drive"}],
            dbs=[self.db],
            opener=lambda p, sel: self.opened.append((os.path.relpath(p, self.mount), sel)),
        )

    def rel(self, r):
        return os.path.relpath(r["path"], self.mount)

    def test_root_and_folder(self):
        r = self.call("open", "root")
        self.assertTrue(r["ok"])
        self.assertEqual(self.opened[-1], ("マイドライブ", False))
        r = self.call("open", "1Mitsumorixxxxx")
        self.assertEqual(self.opened[-1], (os.path.join("マイドライブ", "2026", "見積"), False))

    def test_file_is_selected(self):
        self.call("open", "1FileXlsxxxxxxx")
        self.assertEqual(self.opened[-1], (os.path.join("マイドライブ", "2026", "見積", "見積書.xlsx"), True))
        r = self.call("resolve", "1Gdocxxxxxxxxxx")
        self.assertTrue(r["ok"])
        self.assertTrue(r["path"].endswith("メモ.gdoc"))

    def test_resolve_does_not_open(self):
        r = self.call("resolve", "1Year2026xxxxxx")
        self.assertTrue(r["ok"])
        self.assertEqual(self.opened, [])

    def test_shortcut_target(self):
        r = self.call("resolve", "1SharedSubxxxxx")
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.rel(r), os.path.join(".shortcut-targets-by-id", "1SharedTopxxxxx", "他人のフォルダ", "中"))

    def test_shared_drive_and_computers(self):
        self.assertEqual(self.rel(self.call("resolve", "1TeamSubxxxxxxx")), os.path.join("共有ドライブ", "営業部", "2026"))
        self.assertEqual(self.rel(self.call("resolve", "1PCSubxxxxxxxxx")), os.path.join("その他のパソコン", "My Laptop", "Documents"))

    def test_errors(self):
        self.assertEqual(self.call("resolve", "1OrphanTopxxxxx")["code"], "SHARED_ITEM")
        self.assertEqual(self.call("resolve", "1Trashedxxxxxxx")["code"], "TRASHED")
        self.assertEqual(self.call("resolve", "1Unknownxxxxxxx")["code"], "NOT_IN_DB")
        r = self.call("open", "1NotSyncedxxxxx")
        self.assertEqual((r["ok"], r["code"], r["partial"]), (False, "NOT_FOUND", True))
        self.assertEqual(self.opened[-1], (os.path.join("マイドライブ", "2026"), False))
        r = h.handle({"type": "resolve", "id": "root"}, mounts_fn=lambda: [], dbs=[self.db])
        self.assertEqual(r["code"], "NO_MOUNT")
        r = h.handle({"type": "resolve", "id": "root"}, mounts_fn=lambda: [], dbs=[])
        self.assertEqual(r["code"], "NO_DRIVEFS")

    def test_bad_ids_and_names(self):
        for bad in ["../../etc", "short", "", None, 123, "a" * 300, "root; calc"]:
            with self.assertRaises(h.BadRequest, msg=repr(bad)):
                self.call("open", bad)
        # DBの名前に ".." があっても外へは出ない
        with self.assertRaises(h.BadRequest):
            self.call("open", "1EvilNamexxxxxx")
        self.assertEqual(self.opened, [])

    def test_db_format_change(self):
        bad = os.path.join(self.tmp.name, "broken_db")
        con = sqlite3.connect(bad)  # items テーブルがない＝形式が変わった
        con.executescript("create table properties (property text, value blob); insert into properties values ('root_id', 'x');")
        con.close()
        r = h.handle({"type": "resolve", "id": "root"}, mounts_fn=lambda: [], dbs=[bad])
        self.assertEqual(r["code"], "DB_FORMAT")


class OtherLanguageFolderTest(unittest.TestCase):
    """「共有ドライブ」「その他のパソコン」が日本語・英語以外の名前（例：ドイツ語の Windows）でも見つける"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mount = os.path.join(self.tmp.name, "G")
        self.db = os.path.join(self.tmp.name, "metadata_sqlite_db")
        make_db(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, id_):
        return h.handle(
            {"type": "resolve", "id": id_},
            mounts_fn=lambda: [{"path": self.mount, "label": "Google Drive"}],
            dbs=[self.db],
        )

    def rel(self, r):
        return os.path.relpath(r["path"], self.mount)

    def test_discovered_containers(self):
        make_tree(self.mount, [
            "マイドライブ/2026/",
            "Geteilte Ablagen/営業部/2026/",
            "Andere Computer/My Laptop/Documents/",
            ".shortcut-targets-by-id/",
        ])
        self.assertEqual(self.rel(self.call("1TeamSubxxxxxxx")), os.path.join("Geteilte Ablagen", "営業部", "2026"))
        self.assertEqual(self.rel(self.call("1PCSubxxxxxxxxx")), os.path.join("Andere Computer", "My Laptop", "Documents"))

    def test_my_drive_is_not_a_container(self):
        # マイドライブの中に同じ名前のフォルダがあっても、そちらを開かない
        make_tree(self.mount, ["マイドライブ/My Laptop/Documents/"])
        r = self.call("1PCSubxxxxxxxxx")
        self.assertFalse(r["ok"])
        self.assertNotEqual(r.get("path") and self.rel(r), os.path.join("マイドライブ", "My Laptop", "Documents"))

    def test_discover_skips_hidden_and_my_drive(self):
        make_tree(self.mount, ["マイドライブ/", "My Drive/", ".Encrypted/", "$RECYCLE.BIN/", "Andere Computer/", "Geteilte Ablagen/"])
        open(os.path.join(self.mount, "desktop.ini"), "w").close()
        found = h.discover_containers(self.mount, {"マイドライブ", "My Drive"})
        self.assertEqual(found, ["Andere Computer", "Geteilte Ablagen"])


@unittest.skipUnless(os.name == "nt", "Windows のみ")
class MirrorTest(unittest.TestCase):
    """ミラーリング：マウント先には「マイドライブ.lnk」だけがあり、実体は別の場所にある"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mount = os.path.join(self.tmp.name, "G")
        self.mirror = os.path.join(self.tmp.name, "mirror")
        make_tree(self.mount, ["マイドライブ.lnk", "共有ドライブ/営業部/2026/", "その他のパソコン/", ".shortcut-targets-by-id/"])
        make_tree(self.mirror, ["2026/見積/見積書.xlsx"])
        self.db = os.path.join(self.tmp.name, "metadata_sqlite_db")
        make_db(self.db)
        self.target = self.mirror
        self.opened = []

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, type_, id_):
        return h.handle(
            {"type": type_, "id": id_},
            mounts_fn=lambda: [{"path": self.mount, "label": "Google Drive"}],
            dbs=[self.db],
            opener=lambda p, sel: self.opened.append((p, sel)),
            read_target=lambda lnk: self.target,
        )

    def test_root(self):
        r = self.call("open", "root")
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.opened, [(self.mirror, False)])

    def test_folder_and_file(self):
        r = self.call("resolve", "1Mitsumorixxxxx")
        self.assertEqual((r["ok"], r["path"]), (True, os.path.join(self.mirror, "2026", "見積")))
        self.call("open", "1FileXlsxxxxxxx")
        self.assertEqual(self.opened, [(os.path.join(self.mirror, "2026", "見積", "見積書.xlsx"), True)])

    def test_partial(self):
        r = self.call("open", "1NotSyncedxxxxx")
        self.assertEqual((r["ok"], r["code"]), (False, "NOT_FOUND"))
        self.assertEqual(self.opened, [(os.path.join(self.mirror, "2026"), False)])

    def test_shared_drive_still_works(self):
        r = self.call("resolve", "1TeamSubxxxxxxx")
        self.assertEqual((r["ok"], r["path"]), (True, os.path.join(self.mount, "共有ドライブ", "営業部", "2026")))

    def test_bad_targets_are_not_opened(self):
        for bad in (None, "", "relative", r"\\server\share", os.path.join(self.tmp.name, "missing"), self.db):
            self.target = bad
            r = self.call("open", "root")
            self.assertEqual((r["ok"], r["code"]), (False, "NOT_FOUND"), repr(bad))
            self.assertNotIn("path", r)
        self.assertEqual(self.opened, [])

    def test_name_cannot_escape(self):
        with self.assertRaises(h.BadRequest):
            self.call("open", "1EvilNamexxxxxx")
        self.assertEqual(self.opened, [])

    def test_real_folder_wins(self):
        make_tree(self.mount, ["マイドライブ/"])
        self.assertEqual(self.call("resolve", "root")["path"], os.path.join(self.mount, "マイドライブ"))

    def test_read_real_lnk(self):
        lnk = os.path.join(self.tmp.name, "x.lnk")
        script = "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:T_LNK);$s.TargetPath=$env:T_DST;$s.Save()"
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            env={**os.environ, "T_LNK": lnk, "T_DST": self.mirror}, check=True, capture_output=True,
        )
        self.assertTrue(os.path.samefile(shortcut.read_target(lnk), self.mirror))
        self.assertIsNone(shortcut.read_target(os.path.join(self.tmp.name, "none.lnk")))
        self.assertIsNone(shortcut.read_target(self.db))


if __name__ == "__main__":
    unittest.main()
