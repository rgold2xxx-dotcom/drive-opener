"""Drive Opener のネイティブメッセージングホスト。

拡張から Drive のID を受け取り、パソコン版ドライブのローカルDB（drivefs.py）でローカルのパスを求め、
explorer.exe で開く。それ以外のことはしない。

受け付けるメッセージ:
  { "type": "ping" }
  { "type": "open",    "id": "<DriveのID>" | "root" }   … エクスプローラーで開く
  { "type": "resolve", "id": "<DriveのID>" | "root" }   … パスを返すだけ（コピー用）

通信: 標準入出力。先頭4バイト（リトルエンディアン）が長さ、続いて UTF-8 の JSON。
"""

from __future__ import annotations

import json
import os
import re
import string
import struct
import subprocess
import sys
import unicodedata
from typing import Callable

import drivefs

VERSION = "1.0.0"
MAX_MESSAGE = 1024 * 1024
MAX_NAME = 1024
DRIVE_LABEL = "Google Drive"

ID_RE = re.compile(r"^(root|[A-Za-z0-9_-]{10,200})$")
INVALID_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
DRIVE_SPEC = re.compile(r"^[A-Za-z]:")
DUP_SUFFIX = re.compile(r"^(?P<base>.*?) \((?P<n>\d+)\)(?P<ext>\.[^.]*)?$")


class BadRequest(Exception):
    pass


# ---------------------------------------------------------------- 通信


def read_message(stream) -> dict | None:
    raw_len = stream.read(4)
    if not raw_len:
        return None
    if len(raw_len) < 4:
        raise BadRequest("truncated length header")
    (length,) = struct.unpack("<I", raw_len)
    if length > MAX_MESSAGE:
        raise BadRequest("message too large")
    data = stream.read(length)
    if len(data) < length:
        raise BadRequest("truncated message")
    try:
        msg = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise BadRequest(f"invalid json: {e}") from e
    if not isinstance(msg, dict):
        raise BadRequest("message must be an object")
    return msg


def write_message(stream, msg: dict) -> None:
    data = json.dumps(msg, ensure_ascii=False).encode("utf-8")
    stream.write(struct.pack("<I", len(data)))
    stream.write(data)
    stream.flush()


# ---------------------------------------------------------------- 名前の検査と照合


def validate_name(name, field: str) -> str:
    """1階層分の名前として安全か検査する（DBから来た名前にも適用する）"""
    if not isinstance(name, str) or not name:
        raise BadRequest(f"{field}: must be a non-empty string")
    if len(name) > MAX_NAME:
        raise BadRequest(f"{field}: too long")
    if "\x00" in name:
        raise BadRequest(f"{field}: contains NUL")
    parts = re.split(r"[\\/]", name)
    if any(p in (".", "..") for p in parts):
        raise BadRequest(f"{field}: contains '..'")
    if DRIVE_SPEC.match(name) and (len(name) == 2 or name[2] in "\\/"):
        raise BadRequest(f"{field}: contains a drive specifier")
    if name.startswith(("\\\\", "//")):
        raise BadRequest(f"{field}: UNC path")
    return name


def normalize_name(name: str) -> str:
    """ローカル名への変換を近似する（DBの名前と実際の名前がずれたときの照合用）"""
    n = unicodedata.normalize("NFC", name)
    n = INVALID_CHARS.sub("_", n)
    n = n.rstrip(" .")
    return n


def match_key(name: str) -> str:
    return normalize_name(name).casefold()


def is_plain_component(name: str) -> bool:
    """そのまま1階層として結合してよい名前か"""
    return not INVALID_CHARS.search(name) and name not in (".", "..") and name == name.rstrip(" .")


def match_child(
    parent: str, name: str, want_dir: bool | None = None, file_like: bool = False, listdir=os.listdir
) -> str | None:
    """parent 直下で name に当たる実在のエントリ名を返す。特定できなければ None。

    file_like: 拡張子を考慮した照合（連番・拡張子違い）をする
    """

    def kind_ok(entry: str) -> bool:
        if want_dir is None:
            return True
        return os.path.isdir(os.path.join(parent, entry)) == want_dir

    # 1. 完全一致
    if is_plain_component(name):
        p = os.path.join(parent, name)
        if os.path.lexists(p) and kind_ok(name):
            return name

    try:
        entries = list(listdir(parent))
    except OSError:
        return None

    # 2. 正規化した名前で照合
    key = match_key(name)
    hits = [e for e in entries if match_key(e) == key and kind_ok(e)]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        exact = [e for e in hits if unicodedata.normalize("NFC", e) == unicodedata.normalize("NFC", name)]
        return exact[0] if len(exact) == 1 else None

    # 3. 同名の連番 "name (1)" / "name (1).ext"
    stem, ext = os.path.splitext(normalize_name(name)) if file_like else (normalize_name(name), "")
    dups = []
    for e in entries:
        m = DUP_SUFFIX.match(e)
        if not m or not kind_ok(e):
            continue
        if m.group("base").casefold() == stem.casefold() and (m.group("ext") or "").casefold() == ext.casefold():
            dups.append(e)
    if len(dups) == 1:
        return dups[0]

    # 4. ファイルは拡張子違いを許す
    if file_like:
        stems = [e for e in entries if match_key(os.path.splitext(e)[0]) == key and kind_ok(e)]
        if len(stems) == 1:
            return stems[0]
    return None


# ---------------------------------------------------------------- マウント先


def get_volume_label(root: str) -> str | None:
    if os.name != "nt":
        return None
    import ctypes

    buf = ctypes.create_unicode_buffer(261)
    ok = ctypes.windll.kernel32.GetVolumeInformationW(ctypes.c_wchar_p(root), buf, 261, None, None, None, None, 0)
    return buf.value if ok else None


def find_mounts(label_fn: Callable[[str], str | None] = get_volume_label) -> list[dict]:
    mounts = []
    if os.name != "nt":
        return mounts
    import ctypes

    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    for i, letter in enumerate(string.ascii_uppercase):
        if not bitmask & (1 << i):
            continue
        root = f"{letter}:\\"
        label = label_fn(root)
        if label and label.startswith(DRIVE_LABEL):
            mounts.append({"path": root, "label": label})
    return mounts


# ---------------------------------------------------------------- パス解決


def is_inside(child: str, base: str) -> bool:
    c = os.path.normcase(os.path.realpath(child))
    b = os.path.normcase(os.path.realpath(base))
    try:
        return os.path.commonpath([c, b]) == b
    except ValueError:
        return False


def locate(mount: str, parts: list[str], last_is_folder: bool, listdir=os.listdir) -> tuple[str, int, bool]:
    """mount から parts をたどる。(たどれたパス, たどれた深さ, 全部たどれたか)"""
    cur = mount
    for i, part in enumerate(parts):
        validate_name(part, f"part[{i}]")
        last = i == len(parts) - 1
        if last and not last_is_folder:
            name = match_child(cur, part, want_dir=None, file_like=True, listdir=listdir)
        else:
            name = match_child(cur, part, want_dir=True, listdir=listdir)
        if name is None:
            return cur, i, False
        cur = os.path.join(cur, name)
    return cur, len(parts), True


def resolve_id(cloud_id, *, mounts_fn=None, dbs=None, listdir=os.listdir) -> dict:
    """ID → { ok, path, select(bool), partial } またはエラー"""
    if not isinstance(cloud_id, str) or not ID_RE.match(cloud_id):
        raise BadRequest("id: invalid")
    try:
        lk = drivefs.find(cloud_id, dbs)
        cands = drivefs.candidates(lk)
    except drivefs.DriveFSError as e:
        return {"ok": False, "code": e.code, "detail": str(e) if str(e) != e.code else "", "path": None}

    mounts = [m["path"] for m in (mounts_fn or find_mounts)() if os.path.isdir(m["path"])]
    if not mounts:
        return {"ok": False, "code": "NO_MOUNT", "path": None}

    is_folder = lk.item.is_folder
    best = None  # (mount, path, depth, complete, n_parts)
    for mount in mounts:
        for parts in cands:
            path, depth, complete = locate(mount, parts, is_folder, listdir=listdir)
            if best is None or depth > best[2] or (complete and not best[3]):
                best = (mount, path, depth, complete, len(parts))
            if complete:
                break
        if best and best[3]:
            break

    mount, path, depth, complete, _ = best
    if not complete and depth <= 1 and drivefs.is_shared_only(lk):
        return {"ok": False, "code": "SHARED_ITEM", "path": None}
    if depth == 0:
        return {"ok": False, "code": "NOT_FOUND", "path": None, "partial": True}
    if not is_inside(path, mount) or not os.path.exists(path):
        raise BadRequest("resolved path escapes the mount")
    return {
        "ok": complete,
        "code": None if complete else "NOT_FOUND",
        "path": path,
        "select": complete and not is_folder,
        "partial": not complete,
    }


def open_in_explorer(path: str, select: bool) -> None:
    # 引数リストで渡す（shell は使わない）。explorer.exe は成功しても 1 を返すことがあるので待たない
    args = ["explorer.exe", "/select,", path] if select else ["explorer.exe", path]
    subprocess.Popen(args, close_fds=True)


# ---------------------------------------------------------------- メイン


def handle(msg: dict, *, opener=None, mounts_fn=None, dbs=None, listdir=os.listdir) -> dict:
    t = msg.get("type")
    if t == "ping":
        return {
            "ok": True,
            "version": VERSION,
            "mounts": (mounts_fn or find_mounts)(),
            "accounts": len(drivefs.find_databases() if dbs is None else dbs),
        }
    if t in ("open", "resolve"):
        r = resolve_id(msg.get("id"), mounts_fn=mounts_fn, dbs=dbs, listdir=listdir)
        if t == "open" and r.get("path"):
            (opener or open_in_explorer)(r["path"], bool(r.get("select")))
        out = {k: v for k, v in r.items() if v is not None and k != "select"}
        return out
    raise BadRequest(f"unknown type: {t!r}")


def log_error(text: str) -> None:
    try:
        d = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "DriveOpener")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "host.log")
        if os.path.exists(p) and os.path.getsize(p) > 256 * 1024:
            os.replace(p, p + ".1")
        with open(p, "a", encoding="utf-8") as f:
            from datetime import datetime

            f.write(f"{datetime.now().isoformat(timespec='seconds')} {text}\n")
    except OSError:
        pass


def main() -> int:
    if os.name == "nt":
        import msvcrt

        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    stdin, stdout = sys.stdin.buffer, sys.stdout.buffer
    while True:
        try:
            msg = read_message(stdin)
        except BadRequest as e:
            write_message(stdout, {"ok": False, "code": "BAD_REQUEST", "detail": str(e)})
            return 1
        if msg is None:
            return 0
        try:
            res = handle(msg)
        except BadRequest as e:
            res = {"ok": False, "code": "BAD_REQUEST", "detail": str(e)}
        except Exception as e:  # noqa: BLE001  予期しない失敗も応答は返す
            log_error(f"error: {e!r}")
            res = {"ok": False, "code": "INTERNAL", "detail": str(e)}
        write_message(stdout, res)


if __name__ == "__main__":
    sys.exit(main())
