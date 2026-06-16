"""Measure how the ported physics drift from the live client.

Method (integrator-isolation mode): each update reads the live entity's pos/vel/accel. From
the PREVIOUS read it predicts the current pos/vel using the ported integrator alone
(pos += vel*dt + 0.5*accel*dt^2 ; vel += accel*dt) over the real elapsed time, then compares
the prediction to what the client actually produced. Because the live accel accumulator already
contains the client's thrust + gravity + suspension for that tick, this validates the
INTEGRATION math in isolation -- a near-zero drift here proves the integrator port is 1:1; any
residual localizes the discrepancy (e.g. a missing 0.5*a*dt^2 term, wrong dt, or read phase).

For end-to-end model validation (thrust/suspension), set mode="full" once those are ported.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from sim.vec3 import Vec3
from sim import integrator
from .attach import GameAttach


def _v(a: list[float]) -> Vec3:
    return Vec3(a[0], a[1], a[2])


def _dist(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


@dataclass
class _Pending:
    pos: list[float]
    vel: list[float]


@dataclass
class DriftTracker:
    attach: GameAttach
    mode: str = "integrator"
    _pending: Optional[_Pending] = field(default=None, repr=False)
    samples: int = 0
    mean_pos_err: float = 0.0
    max_pos_err: float = 0.0
    mean_vel_err: float = 0.0
    max_vel_err: float = 0.0
    last: Optional[dict] = None

    def update(self, dt: float) -> Optional[dict]:
        """Call once per frame with the real elapsed seconds. Returns a drift report or None."""
        if dt <= 0.0 or not self.attach.attached:
            return self.last
        live = self.attach.read_physics()
        if live is None:
            return self.last

        report = None
        if self._pending is not None:
            pos_err = _dist(self._pending.pos, live["pos"])
            vel_err = _dist(self._pending.vel, live["vel"])
            self.samples += 1
            k = self.samples
            self.mean_pos_err += (pos_err - self.mean_pos_err) / k
            self.mean_vel_err += (vel_err - self.mean_vel_err) / k
            self.max_pos_err = max(self.max_pos_err, pos_err)
            self.max_vel_err = max(self.max_vel_err, vel_err)
            report = {
                "mode": self.mode,
                "dt": dt,
                "pos_err": pos_err,
                "vel_err": vel_err,
                "mean_pos_err": self.mean_pos_err,
                "max_pos_err": self.max_pos_err,
                "mean_vel_err": self.mean_vel_err,
                "max_vel_err": self.max_vel_err,
                "samples": self.samples,
                "live_pos": live["pos"],
                "predicted_pos": self._pending.pos,
                "live_speed": _v(live["vel"]).length(),
            }
            self.last = report

        # Predict forward from the current live state over this dt (integrator-isolation).
        pos = _v(live["pos"])
        vel = _v(live["vel"])
        accel = _v(live["accel"])
        integrator.integrate_pos_vel(dt, pos, vel, accel)
        self._pending = _Pending(pos=[pos.x, pos.y, pos.z], vel=[vel.x, vel.y, vel.z])
        return report

    def reset_stats(self) -> None:
        self.samples = 0
        self.mean_pos_err = self.max_pos_err = self.mean_vel_err = self.max_vel_err = 0.0
        self._pending = None
        self.last = None
