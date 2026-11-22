"""パソコン版ドライブ（DriveFS）のローカルDBから、DriveのIDに対応するローカルの相対パスを求める。

DB: %LOCALAPPDATA%\\Google\\DriveFS\\<アカウント番号>\\metadata_sqlite_db（SQLite、読み取り専用で開く）
  items          : stable_id, id(=DriveのID), local_title(=ローカルでの名前), is_folder, trashed, team_drive_stable_id
  stable_parents : item_stable_id → parent_stable_id
  shortcut_details: shortcut_stable_id, target_stable_id
  properties     : root_id（マイドライブのID）

Googleが公開している形式ではないため、パソコン版ドライブの更新で変わる可能性がある。
変わった場合は DriveFSError("DB_FORMAT") を投げ、呼び出し側でエラーとして伝える。
"""

from __future__ import annotations

import glob
import os
import sqlite3
from dataclasses import dataclass

MY_DRIVE_NAMES = ("マイドライブ", "My Drive")
SHARED_DRIVES_NAMES = ("共有ドライブ", "Shared drives")
COMPUTERS_NAMES = ("その他のパソコン", "Other computers", "パソコン", "Computers")
SHORTCUT_TARGETS_DIR = ".shortcut-targets-by-id"
MAX_DEPTH = 200


class DriveFSError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code


@dataclass
class Item:
    stable_id: int
    id: str
    title: str
    is_folder: bool
    trashed: bool
    team_drive: int | None


@dataclass
class Lookup:
    db: str
    root_id: str
    chain: list[Item]  # 最上位 → 対象 の順
    shortcut_targets: set[int]
    root_title: str = ""  # マイドライブのローカルでのフォルダ名（例「マイドライブ」「My Drive」）

    @property
    def item(self) -> Item:
        return self.chain[-1]


def drivefs_dir() -> str:
    return os.environ.get("DRIVE_OPENER_DRIVEFS_DIR") or os.path.join(
        os.environ.get("LOCALAPPDATA", ""), "Google", "DriveFS"
    )


def find_databases(base: str | None = None) -> list[str]:
    base = base or drivefs_dir()
    dbs = glob.glob(os.path.join(base, "*", "metadata_sqlite_db"))
    # 新しく更新されたアカウントを先に
    return sorted(dbs, key=lambda p: os.path.getmtime(p), reverse=True)


def _connect(db: str) -> sqlite3.Connection:
    uri = "file:" + os.path.abspath(db).replace(os.sep, "/") + "?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=3)


def _text(v) -> str:
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    return "" if v is None else str(v)


def lookup(db: str, cloud_id: str) -> Lookup | None:
    """db の中から cloud_id（'root' も可）を探し、最上位までの階層を返す。見つからなければ None。"""
    try:
        con = _connect(db)
    except sqlite3.Error as e:
        raise DriveFSError("DB_OPEN", str(e)) from e
    try:
        row = con.execute("select value from properties where property='root_id'").fetchone()
        root_id = _text(row[0]) if row else ""
        target = root_id if cloud_id == "root" else cloud_id
        if not target:
            return None

        def item_by(col: str, val) -> Item | None:
            r = con.execute(
                "select stable_id, id, local_title, is_folder, trashed, team_drive_stable_id "
                f"from items where {col}=? and coalesce(is_tombstone,0)=0",
                (val,),
            ).fetchone()
            if not r:
                return None
            return Item(r[0], _text(r[1]), _text(r[2]), bool(r[3]), bool(r[4]), r[5])

        item = item_by("id", target)
        if item is None:
            return None
        chain = [item]
        seen = {item.stable_id}
        while True:
            p = con.execute(
                "select parent_stable_id from stable_parents where item_stable_id=? limit 1", (chain[0].stable_id,)
            ).fetchone()
            if not p or p[0] in seen:
                break
            parent = item_by("stable_id", p[0])
            if parent is None or len(chain) > MAX_DEPTH:
                break
            seen.add(parent.stable_id)
            chain.insert(0, parent)

        targets = {r[0] for r in con.execute("select target_stable_id from shortcut_details")}
        root_row = con.execute("select local_title from items where id=?", (root_id,)).fetchone() if root_id else None
        return Lookup(db, root_id, chain, targets, _text(root_row[0]) if root_row else "")
    except sqlite3.Error as e:
        raise DriveFSError("DB_FORMAT", str(e)) from e
    finally:
        con.close()


def find(cloud_id: str, dbs: list[str] | None = None) -> Lookup:
    """全アカウントのDBから探す"""
    dbs = find_databases() if dbs is None else dbs
    if not dbs:
        raise DriveFSError("NO_DRIVEFS")
    errors = []
    for db in dbs:
        try:
            res = lookup(db, cloud_id)
        except DriveFSError as e:
            errors.append(e)
            continue
        if res:
            return res
    if errors and len(errors) == len(dbs):
        raise errors[0]
    raise DriveFSError("NOT_IN_DB")


def candidates(lk: Lookup, containers: list[str] | tuple[str, ...] = ()) -> list[list[str]]:
    """マウント先からの相対パス（名前の配列）の候補。先に書いたものほど優先。

    containers: マウント先の直下で見つけたフォルダ（マイドライブ・隠しフォルダ以外）。
    「共有ドライブ」「その他のパソコン」の名前は Windows の表示言語で変わるため、
    日本語・英語の決め打ちの名前で見つからないときに、これらの中を探す。
    """
    if any(x.trashed for x in lk.chain):
        raise DriveFSError("TRASHED")
    chain = lk.chain
    top = chain[0]
    names = [x.title for x in chain]
    out: list[list[str]] = []

    if top.id == lk.root_id:
        # マイドライブ：最上位の local_title がそのままローカルのフォルダ名
        out.append(names)
        out += [[n] + names[1:] for n in MY_DRIVE_NAMES if n != top.title]
        return out

    if any(x.team_drive for x in chain):
        out += [[sd] + names for sd in SHARED_DRIVES_NAMES]
        out += [[c] + names for c in containers if c not in SHARED_DRIVES_NAMES]

    # 共有アイテムをショートカットでマイドライブに追加したもの
    for i, x in enumerate(chain):
        if x.stable_id in lk.shortcut_targets:
            out.append([SHORTCUT_TARGETS_DIR, x.id] + names[i:])

    # 他のパソコンのバックアップ
    out += [[c] + names for c in COMPUTERS_NAMES]
    out += [[c] + names for c in containers if c not in COMPUTERS_NAMES and c not in SHARED_DRIVES_NAMES]

    if not out:
        raise DriveFSError("SHARED_ITEM")
    return out


def is_shared_only(lk: Lookup) -> bool:
    """ローカルに出てくる経路がない（共有アイテムにあるだけ）"""
    top = lk.chain[0]
    if top.id == lk.root_id or any(x.team_drive for x in lk.chain):
        return False
    return not any(x.stable_id in lk.shortcut_targets for x in lk.chain)
