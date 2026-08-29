"""Standalone live-memory probe for a running wulfram2.exe (no pymem dependency).

Run this from the SAME context the game was launched in (same user/elevation). It:
  * enables SeDebugPrivilege (best effort),
  * opens wulfram2.exe by name,
  * reads the gravity global (0x5738b8),
  * resolves the local-player object via DAT_00677f2c (its +0xb4 = current object),
  * prints the physics block (pos/vel/accel/euler) under several interpretations so we can
    confirm which pointer hop lands on the entity whose pos looks like real world coords.

Usage:  python live/read_live.py            (auto-find pid by name)
        python live/read_live.py <pid>
"""
from __future__ import annotations

import ctypes
import struct
import sys
from ctypes import wintypes as w

IMAGE_BASE = 0x00400000
GRAVITY = 0x005738b8
PLAYER_GLOBAL = 0x00677f2c   # DAT_00677f2c: local-player object pointer (TeamSlot_FindLocalPlayerObjectSlot)
OBJ_OFFSET = 0xB4            # +0xb4: "current object"

OFFSETS = {"pos": 0x0c, "vel": 0x18, "accel": 0x24, "euler": 0x30, "ang_vel": 0x3c, "ang_accel": 0x48}

k = ctypes.WinDLL("kernel32", use_last_error=True)
adv = ctypes.WinDLL("advapi32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)
k.OpenProcess.restype = w.HANDLE
k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
k.GetCurrentProcess.restype = w.HANDLE
k.ReadProcessMemory.argtypes = [w.HANDLE, w.LPCVOID, w.LPVOID, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]


def enable_debug_priv() -> None:
    class LUID(ctypes.Structure):
        _fields_ = [("lo", w.DWORD), ("hi", ctypes.c_long)]

    class LAA(ctypes.Structure):
        _fields_ = [("Luid", LUID), ("Attr", w.DWORD)]

    class TKP(ctypes.Structure):
        _fields_ = [("count", w.DWORD), ("priv", LAA * 1)]

    adv.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
    hT = w.HANDLE()
    if not adv.OpenProcessToken(k.GetCurrentProcess(), 0x28, ctypes.byref(hT)):
        return
    luid = LUID()
    if not adv.LookupPrivilegeValueW(None, "SeDebugPrivilege", ctypes.byref(luid)):
        return
    tkp = TKP(count=1)
    tkp.priv[0].Luid = luid
    tkp.priv[0].Attr = 0x2
    adv.AdjustTokenPrivileges(hT, False, ctypes.byref(tkp), 0, None, None)


def find_pid(name="wulfram2.exe") -> int | None:
    import subprocess
    out = subprocess.run(["tasklist", "/fi", f"imagename eq {name}", "/fo", "csv", "/nh"],
                         capture_output=True, text=True).stdout
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) >= 2 and parts[0].lower() == name.lower():
            return int(parts[1])
    return None


def module_base(h, pid) -> int:
    arr = (ctypes.c_void_p * 256)()
    need = w.DWORD()
    if psapi.EnumProcessModules(h, arr, ctypes.sizeof(arr), ctypes.byref(need)):
        return arr[0] or IMAGE_BASE
    return IMAGE_BASE


def main() -> None:
    pid = int(sys.argv[1]) if len(sys.argv) > 1 else find_pid()
    if not pid:
        print("wulfram2.exe not running"); return
    enable_debug_priv()
    h = k.OpenProcess(0x10 | 0x1000 | 0x0400, False, pid)  # VM_READ | QLI | QUERY_INFORMATION
    if not h:
        print(f"OpenProcess({pid}) failed err={ctypes.get_last_error()} "
              f"(5 = access denied; run this shell elevated / same integrity as the game)")
        return
    base = module_base(h, pid)
    delta = base - IMAGE_BASE
    print(f"pid={pid} module_base=0x{base:X} (delta=0x{delta:X})")

    def rd(addr, n):
        buf = ctypes.create_string_buffer(n); got = ctypes.c_size_t(0)
        if not k.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, n, ctypes.byref(got)):
            return None
        return buf.raw[:got.value]

    def f1(addr):
        b = rd(addr, 4); return struct.unpack("<f", b)[0] if b else None

    def u32(addr):
        b = rd(addr, 4); return struct.unpack("<I", b)[0] if b else None

    def vec3(addr):
        b = rd(addr, 12); return list(struct.unpack("<3f", b)) if b else None

    print(f"\nLIVE gravity (0x5738b8) = {f1(GRAVITY + delta)}   [sim default 100.0]")

    player_rec = u32(PLAYER_GLOBAL + delta)
    print(f"DAT_00677f2c (player record ptr) = 0x{player_rec:X}" if player_rec else "player record = <unreadable>")

    candidates = []
    if player_rec:
        obj = u32(player_rec + OBJ_OFFSET)
        candidates = [("player_rec", player_rec), ("player_rec+0xb4 deref", obj)]
    for label, ent in candidates:
        if not ent:
            print(f"\n[{label}] = null/unreadable"); continue
        print(f"\n[{label}] entity base = 0x{ent:X}")
        for nm, off in OFFSETS.items():
            print(f"    {nm:9s} (+0x{off:02x}) = {vec3(ent + off)}")


if __name__ == "__main__":
    main()
