"""Non-invasively read the live wulfram2.exe local-player position from memory.

Uses Win32 ReadProcessMemory (no debugger attach, no process suspend). The
local player's controlled-entity pointer is the global DAT_00677f2c; the entity
position is 3 floats at entity+0xC (per the Ghidra RE). wulfram2.exe has a fixed
image base (0x00400000, no ASLR), so static VAs are runtime VAs.

Usage:  python tools/read_player_pos.py [pid ...]
"""
import ctypes
import os
import struct
import sys
from ctypes import wintypes

# Mirror all output here so an elevated run can hand results back to a
# non-elevated reader (the calling agent/terminal).
OUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "player_pos.txt")
_out_lines = []


def emit(line):
    print(line)
    _out_lines.append(line)

PTR_LOCAL_ENTITY = 0x00677F2C   # DAT_00677f2c: local controlled-entity pointer
OFF_POS = 0x0C                  # entity + 0x0C: position (3 floats)
OFF_VEL = 0x18                  # entity + 0x18: velocity (3 floats)
ENTITY_ID = 0x005B83E4          # DAT_005b83e4: local player's entity id

PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.restype = wintypes.HANDLE
k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
k32.ReadProcessMemory.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
    ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t),
]


def open_proc(pid):
    for mask in (
        PROCESS_VM_READ | PROCESS_QUERY_INFORMATION,
        PROCESS_VM_READ | PROCESS_QUERY_LIMITED_INFORMATION,
        PROCESS_VM_READ,
    ):
        h = k32.OpenProcess(mask, False, pid)
        if h:
            return h, mask
    return None, ctypes.get_last_error()


def read(h, addr, size):
    buf = (ctypes.c_char * size)()
    got = ctypes.c_size_t(0)
    ok = k32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, size, ctypes.byref(got))
    if not ok or got.value != size:
        return None
    return bytes(buf)


def dump(pid):
    h, info = open_proc(pid)
    if not h:
        emit(f"[pid {pid}] OpenProcess failed (err={info})  "
             f"# 5=access denied (run elevated)")
        return
    try:
        eid = read(h, ENTITY_ID, 4)
        eid_v = struct.unpack("<I", eid)[0] if eid else None
        raw = read(h, PTR_LOCAL_ENTITY, 4)
        if not raw:
            emit(f"[pid {pid}] could not read 0x{PTR_LOCAL_ENTITY:08X}")
            return
        ent = struct.unpack("<I", raw)[0]
        emit(f"[pid {pid}] entity_id={eid_v} controlled_entity_ptr=0x{ent:08X}")
        if ent < 0x10000:
            emit(f"[pid {pid}]   pointer looks null/invalid (not in-world?)")
            return
        pos = read(h, ent + OFF_POS, 12)
        vel = read(h, ent + OFF_VEL, 12)
        if pos:
            x, y, z = struct.unpack("<fff", pos)
            emit(f"[pid {pid}]   pos = ({x:.3f}, {y:.3f}, {z:.3f})")
        if vel:
            vx, vy, vz = struct.unpack("<fff", vel)
            emit(f"[pid {pid}]   vel = ({vx:.3f}, {vy:.3f}, {vz:.3f})")
    finally:
        k32.CloseHandle(h)


def find_wulfram_pids():
    """Enumerate running wulfram2.exe PIDs via Toolhelp (no extra deps)."""
    TH32CS_SNAPPROCESS = 0x2

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_char * 260),
        ]

    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    pids = []
    entry = PROCESSENTRY32()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
    if k32.Process32First(snap, ctypes.byref(entry)):
        while True:
            if entry.szExeFile.decode(errors="ignore").lower() == "wulfram2.exe":
                pids.append(entry.th32ProcessID)
            if not k32.Process32Next(snap, ctypes.byref(entry)):
                break
    k32.CloseHandle(snap)
    return pids


if __name__ == "__main__":
    pids = [int(a) for a in sys.argv[1:]] or find_wulfram_pids()
    if not pids:
        emit("No wulfram2.exe processes found.")
    for pid in pids:
        dump(pid)
    try:
        with open(OUT_FILE, "w", encoding="utf-8") as fh:
            fh.write("\n".join(_out_lines) + "\n")
        print(f"\n(results written to {OUT_FILE})")
    except OSError as exc:
        print(f"(could not write {OUT_FILE}: {exc})")
