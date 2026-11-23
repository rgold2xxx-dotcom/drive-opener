"""Windows のショートカット（.lnk）のリンク先を読む。リンク先を開いたり、探し直したり（Resolve）はしない。"""

from __future__ import annotations

import os


def read_target(lnk: str) -> str | None:
    """リンク先のパス。読めなければ None"""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD), ("d", ctypes.c_ubyte * 8)]

    def guid(a: int) -> GUID:  # {xxxxxxxx-0000-0000-C000-000000000046}
        return GUID(a, 0, 0, (ctypes.c_ubyte * 8)(0xC0, 0, 0, 0, 0, 0, 0, 0x46))

    clsid_shell_link, iid_shell_link, iid_persist_file = guid(0x00021401), guid(0x000214F9), guid(0x0000010B)
    ole32 = ctypes.WinDLL("ole32")
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole32.CoInitializeEx.restype = ctypes.c_long
    ole32.CoCreateInstance.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)
    ]
    ole32.CoCreateInstance.restype = ctypes.c_long

    def method(obj, index, *argtypes):
        vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        fn = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(vtable[index])
        return lambda *args: fn(obj, *args)

    link, persist = ctypes.c_void_p(), ctypes.c_void_p()
    initialized = ole32.CoInitializeEx(None, 2) >= 0  # COINIT_APARTMENTTHREADED
    try:
        if ole32.CoCreateInstance(
            ctypes.byref(clsid_shell_link), None, 1, ctypes.byref(iid_shell_link), ctypes.byref(link)
        ) < 0:
            return None
        query = method(link, 0, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))  # IUnknown::QueryInterface
        if query(ctypes.byref(iid_persist_file), ctypes.byref(persist)) < 0:
            return None
        load = method(persist, 5, ctypes.c_wchar_p, wintypes.DWORD)  # IPersistFile::Load（読み取り専用）
        if load(os.path.abspath(lnk), 0) < 0:
            return None
        buf = ctypes.create_unicode_buffer(1024)
        get_path = method(link, 3, ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)  # IShellLinkW::GetPath
        if get_path(buf, len(buf), None, 0) != 0:
            return None
        return buf.value or None
    finally:
        for obj in (persist, link):
            if obj:
                method(obj, 2)()  # Release
        if initialized:
            ole32.CoUninitialize()
