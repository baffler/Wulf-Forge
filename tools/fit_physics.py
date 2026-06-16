"""Physics calibration: replay recorded inputs through the sim over the real map
and fit the runtime scales so the simulated trajectory matches ground truth.

Inputs:
  - tools/drive_capture.csv      ground-truth pos/vel/yaw (from capture_drive.py)
  - logs/wulf-forge-*.log        the matching run's [PHYS-SIM] input lines

It aligns the server's logged control inputs onto the ground-truth timeline,
loads the map heightmap, and:
  * REPLAY (default): open-loop replays the inputs from the first ground-truth
    state through wulfsim and reports how far the sim trajectory drifts.
  * FIT (--fit): optimizes thrust_scale/torque_scale/max_thrust/control_divisor/
    angular_damp via teacher-forced one-step prediction (scipy), then reports the
    open-loop drift before/after and prints the fitted constants.

Usage:
  python tools/fit_physics.py                 # replay with current defaults
  python tools/fit_physics.py --fit           # calibrate, print fitted params
  python tools/fit_physics.py --fit --map crossroads --log logs/wulf-forge-XXX.log
"""
from __future__ import annotations

import argparse
import csv
import glob
import math
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from scipy.optimize import differential_evolution, minimize

from network.packets.packet_config import PacketConfig
from core.sim.tunables import ServerTunables
from core.sim.terrain import load_map_heightmap
from core.sim.tank import _FlatTerrain
from wulfsim.vehicle import Vehicle, Inputs

_SUB_DT = 0.01

# Fit targets: (name, lo, hi). friction/gravity/control coeffs are RE-fixed.
FIT_PARAMS = [
    ("thrust_scale", 10.0, 600.0),
    ("torque_scale", 5.0, 600.0),
    ("max_thrust", 10.0, 2000.0),
    ("control_divisor", 10.0, 400.0),
    ("angular_damp", 0.2, 40.0),
]

_PHYS_RE = re.compile(
    r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d+).*?in\(thr=([-+0-9.]+) turn=([-+0-9.]+) str=([-+0-9.]+)"
)


class FitTunables:
    """ServerTunables with a few keys overridden by the candidate params."""
    def __init__(self, base: ServerTunables, overrides: dict):
        self._base = base
        self._ov = overrides

    def get(self, name: str) -> float:
        return self._ov[name] if name in self._ov else self._base.get(name)

    @property
    def effective_gravity(self) -> float:
        return self._base.effective_gravity


def load_capture(path: str):
    rows = list(csv.DictReader(open(path)))
    t = np.array([float(r["epoch_s"]) for r in rows])
    pos = np.array([[float(r["x"]), float(r["y"]), float(r["z"])] for r in rows])
    vel = np.array([[float(r["vx"]), float(r["vy"]), float(r["vz"])] for r in rows])
    yaw = np.unwrap(np.array([float(r["yaw"]) for r in rows]))
    return t, pos, vel, yaw


def load_inputs(path: str):
    ts, thr, turn, strafe = [], [], [], []
    for line in open(path, encoding="utf-8", errors="replace"):
        m = _PHYS_RE.search(line)
        if not m:
            continue
        ts.append(datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S.%f").timestamp())
        thr.append(float(m.group(2)))
        turn.append(float(m.group(3)))
        strafe.append(float(m.group(4)))
    return np.array(ts), np.array(thr), np.array(turn), np.array(strafe)


def pick_log(capture_t, explicit):
    if explicit:
        return explicit
    cap_lo, cap_hi = capture_t[0], capture_t[-1]
    best, best_overlap = None, -1.0
    for f in sorted(glob.glob("logs/wulf-forge-*.log")):
        its, *_ = load_inputs(f)
        if len(its) < 10:
            continue
        overlap = min(cap_hi, its[-1]) - max(cap_lo, its[0])
        if overlap > best_overlap:
            best, best_overlap = f, overlap
    return best


def align_inputs(cap_t, its, thr, turn, strafe):
    """Forward-fill each ground-truth sample with the most recent input <= t."""
    idx = np.searchsorted(its, cap_t, side="right") - 1
    idx = np.clip(idx, 0, len(its) - 1)
    return thr[idx], turn[idx], strafe[idx]


def _new_vehicle(pos, vel, yaw, yaw_rate):
    v = Vehicle(kind="tank")
    v.body.pos.set(*pos)
    v.body.vel.set(*vel)
    v.body.euler.z = yaw
    v.body.ang_vel.z = yaw_rate
    return v


def _advance(v, dt, inp, tun, terrain):
    n = max(1, math.ceil(dt / _SUB_DT))
    sub = dt / n
    for _ in range(n):
        v.step(sub, inp, tun, terrain)


def onestep_loss(params, base, terrain, cap_t, pos, vel, yaw, thr, turn, strafe):
    """Teacher-forced one-step prediction error of (x, y, yaw)."""
    tun = FitTunables(base, dict(zip([p[0] for p in FIT_PARAMS], params)))
    err = 0.0
    n = len(cap_t)
    for i in range(1, n - 1):
        dt = cap_t[i + 1] - cap_t[i]
        if dt <= 0 or dt > 0.5:
            continue
        yaw_rate = (yaw[i] - yaw[i - 1]) / max(cap_t[i] - cap_t[i - 1], 1e-3)
        v = _new_vehicle(pos[i], vel[i], yaw[i], yaw_rate)
        _advance(v, dt, Inputs(throttle=thr[i], strafe=strafe[i], turn=turn[i]), tun, terrain)
        dx = v.body.pos.x - pos[i + 1][0]
        dy = v.body.pos.y - pos[i + 1][1]
        dyaw = math.atan2(math.sin(v.body.euler.z - yaw[i + 1]),
                          math.cos(v.body.euler.z - yaw[i + 1]))
        err += dx * dx + dy * dy + (12.0 * dyaw) ** 2  # weight yaw (rad) into world units
    return err / max(n, 1)


def open_loop_loss(params, base, terrain, cap_t, pos, vel, yaw, thr, turn, strafe):
    """Mean open-loop trajectory drift (the production metric: no resync)."""
    return open_loop_drift(params, base, terrain, cap_t, pos, vel, yaw, thr, turn, strafe)[0]


def open_loop_drift(params, base, terrain, cap_t, pos, vel, yaw, thr, turn, strafe):
    """Replay inputs open-loop from the first state; mean horizontal drift (units)."""
    tun = FitTunables(base, dict(zip([p[0] for p in FIT_PARAMS], params)))
    yaw_rate0 = (yaw[1] - yaw[0]) / max(cap_t[1] - cap_t[0], 1e-3)
    v = _new_vehicle(pos[0], vel[0], yaw[0], yaw_rate0)
    drift = []
    for i in range(len(cap_t) - 1):
        dt = cap_t[i + 1] - cap_t[i]
        if dt <= 0 or dt > 0.5:
            continue
        _advance(v, dt, Inputs(throttle=thr[i], strafe=strafe[i], turn=turn[i]), tun, terrain)
        drift.append(math.hypot(v.body.pos.x - pos[i + 1][0], v.body.pos.y - pos[i + 1][1]))
    return float(np.mean(drift)), float(np.max(drift))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capture", default="tools/drive_capture.csv")
    ap.add_argument("--log", default=None)
    ap.add_argument("--map", default=None, help="map name for terrain (default: from config)")
    ap.add_argument("--fit", action="store_true")
    args = ap.parse_args()

    cap_t, pos, vel, yaw = load_capture(args.capture)
    log = pick_log(cap_t, args.log)
    if not log:
        print("No matching server log with [PHYS-SIM] lines found.")
        return
    its, thr_l, turn_l, str_l = load_inputs(log)
    overlap = min(cap_t[-1], its[-1]) - max(cap_t[0], its[0])
    print(f"capture: {len(cap_t)} samples / {cap_t[-1]-cap_t[0]:.1f}s")
    print(f"log:     {log}  ({len(its)} input lines, overlap {overlap:.1f}s)")
    if overlap < 5.0:
        print("WARNING: <5s overlap between capture and log -- timestamps may not match.")
    thr, turn, strafe = align_inputs(cap_t, its, thr_l, turn_l, str_l)

    cfg = PacketConfig()
    map_name = args.map or "crossroads"
    terrain = load_map_heightmap(map_name) or _FlatTerrain(0.0)
    print(f"terrain: {type(terrain).__name__} (map={map_name})")

    base = ServerTunables(cfg)
    defaults = [base.get(p[0]) for p in FIT_PARAMS]
    bounds = [(p[1], p[2]) for p in FIT_PARAMS]
    data = (base, terrain, cap_t, pos, vel, yaw, thr, turn, strafe)

    md, xd = open_loop_drift(defaults, *data)
    print(f"\nDEFAULT params {dict(zip([p[0] for p in FIT_PARAMS], [round(d,2) for d in defaults]))}")
    print(f"  open-loop drift: mean {md:.1f}u  max {xd:.1f}u")

    if not args.fit:
        print("\n(replay only; pass --fit to calibrate)")
        return

    print("\nfitting: one-step DE (global) -> open-loop Nelder-Mead polish...")
    # One-step DE gives a fast, well-conditioned global start; then polish on the
    # ACTUAL open-loop trajectory drift (what matters for a no-resync server).
    de = differential_evolution(
        onestep_loss, bounds, args=data, maxiter=40, tol=1e-3, seed=1, polish=False,
    )
    candidates = [de.x]
    # Polish from the DE result AND from the current defaults, keep the best.
    for x0 in (de.x, np.array(defaults)):
        nm = minimize(open_loop_loss, x0, args=data, method="Nelder-Mead",
                      options={"xatol": 1e-2, "fatol": 1e-3, "maxiter": 1500})
        candidates.append(nm.x)
    best = min(candidates, key=lambda x: open_loop_loss(x, *data))
    best = np.clip(best, [b[0] for b in bounds], [b[1] for b in bounds])
    fitted = dict(zip([p[0] for p in FIT_PARAMS], best))
    mdf, xdf = open_loop_drift(best, *data)
    print("\n=== FITTED params ===")
    for k, val in fitted.items():
        print(f"  {k:16} {val:8.3f}")
    print(f"  open-loop drift: mean {mdf:.1f}u  max {xdf:.1f}u   (was mean {md:.1f}u)")
    print("\nApply these in core/sim/tunables.py _MODEL_DEFAULTS to make the server match.")


if __name__ == "__main__":
    main()
