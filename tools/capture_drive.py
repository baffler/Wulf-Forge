"""Capture ground-truth driving telemetry from the live wulfram2.exe for physics
calibration (system identification).

Reads the local player's pos/vel/yaw from process memory at a fixed rate and
writes a timestamped CSV. Pair it OFFLINE with the server's [PHYS-SIM] input log
(by timestamp) to build (input_t, state_t, state_{t+1}) training tuples for
tools/fit_physics.py.

Non-invasive (ReadProcessMemory, no debugger). MUST run elevated (the game runs
elevated): open an Administrator terminal and:

    python tools/capture_drive.py            # 60s @ 10Hz -> tools/drive_capture.csv
    python tools/capture_drive.py 120 20     # 120s @ 20Hz

Drive a VARIED route while it runs: accelerate, coast, turn both ways, strafe,
stop. Variety makes the fit well-conditioned.
"""
import os
import struct
import sys
import time

# Reuse the verified memory-read helpers from the position reader.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from read_player_pos import (  # noqa: E402
    k32, read, open_proc, find_wulfram_pids, PTR_LOCAL_ENTITY, OFF_POS, OFF_VEL,
)

OFF_EULER = 0x30          # entity +0x30 euler (pitch, roll, yaw)
OFF_YAW = OFF_EULER + 0x8  # yaw = euler.z (3rd float)

OUT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "drive_capture.csv")


def _vec3(h, addr):
    raw = read(h, addr, 12)
    return struct.unpack("<fff", raw) if raw else None


def main():
    duration = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
    hz = float(sys.argv[2]) if len(sys.argv) > 2 else 10.0
    period = 1.0 / hz

    pids = find_wulfram_pids()
    target = None
    for pid in pids:
        h, _info = open_proc(pid)
        if not h:
            continue
        raw = read(h, PTR_LOCAL_ENTITY, 4)
        ent = struct.unpack("<I", raw)[0] if raw else 0
        if ent >= 0x10000:  # in-world entity pointer
            target = (pid, h)
            break
        k32.CloseHandle(h)
    if not target:
        print("No in-world wulfram2.exe found (spawn first; run elevated). "
              f"err on open if not admin. pids={pids}")
        return
    pid, h = target
    print(f"[capture] pid={pid} -> {OUT_CSV}  ({duration:.0f}s @ {hz:.0f}Hz). Drive now...")

    rows = []
    t0 = time.time()
    next_t = t0
    try:
        while time.time() - t0 < duration:
            now = time.time()
            ent = struct.unpack("<I", read(h, PTR_LOCAL_ENTITY, 4))[0]
            pos = _vec3(h, ent + OFF_POS) if ent >= 0x10000 else None
            vel = _vec3(h, ent + OFF_VEL) if ent >= 0x10000 else None
            yaw_raw = read(h, ent + OFF_YAW, 4) if ent >= 0x10000 else None
            yaw = struct.unpack("<f", yaw_raw)[0] if yaw_raw else 0.0
            if pos and vel:
                rows.append((now, *pos, *vel, yaw))
            next_t += period
            sleep = next_t - time.time()
            if sleep > 0:
                time.sleep(sleep)
    finally:
        k32.CloseHandle(h)

    with open(OUT_CSV, "w", encoding="utf-8") as f:
        f.write("epoch_s,x,y,z,vx,vy,vz,yaw\n")
        for r in rows:
            f.write(",".join(f"{v:.6f}" for v in r) + "\n")
    span = rows[-1][0] - rows[0][0] if rows else 0.0
    print(f"[capture] wrote {len(rows)} samples over {span:.1f}s to {OUT_CSV}")


if __name__ == "__main__":
    main()
