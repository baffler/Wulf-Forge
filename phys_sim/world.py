"""SimWorld -- coordinates tunables + terrain + vehicle behind a fixed-timestep loop.

The physics runs at a fixed tick (decoupled from render frame rate) via an accumulator,
matching the client's fixed-tick integration (EntityPhysics_RunWorldTick feeds an integer
millisecond delta; dt = ms/1000). Render/API layers call advance() / read state(); they never
touch the pure sim integrators directly.
"""
from __future__ import annotations

import threading

from tunables import Tunables
from sim.terrain import HeightMap
from sim.vehicle import Vehicle, Inputs, VEHICLE_KINDS

TICK_HZ = 60.0
TICK_DT = 1.0 / TICK_HZ
_MAX_STEPS_PER_FRAME = 8  # avoid spiral-of-death if a frame stalls


class SimWorld:
    def __init__(self, tunables: Tunables | None = None) -> None:
        self.tunables = tunables or Tunables()
        self.terrain = HeightMap()
        self.vehicle = Vehicle(kind="tank")
        self._accum = 0.0
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self.vehicle.reset(self.terrain, self.tunables.get("hover_height"))
            self._accum = 0.0

    def set_vehicle(self, kind: str) -> bool:
        if kind not in VEHICLE_KINDS:
            return False
        with self._lock:
            self.vehicle.kind = kind
            self.vehicle.reset(self.terrain, self.tunables.get("hover_height"))
            self._accum = 0.0
        return True

    def advance(self, frame_dt: float, inp: Inputs) -> int:
        """Consume real frame time, run as many fixed ticks as fit. Returns ticks run."""
        with self._lock:
            self._accum += frame_dt
            steps = 0
            while self._accum >= TICK_DT and steps < _MAX_STEPS_PER_FRAME:
                self.vehicle.step(TICK_DT, inp, self.tunables, self.terrain)
                self._accum -= TICK_DT
                steps += 1
            if steps == _MAX_STEPS_PER_FRAME:
                self._accum = 0.0  # drop backlog
            return steps

    def state(self) -> dict:
        with self._lock:
            return self.vehicle.state()
