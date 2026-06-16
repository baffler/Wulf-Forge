"""Per-player Tank simulation: integrate the client's inputs into authoritative state.

Wraps wulfsim.vehicle.Vehicle (the exact decompiled Tank pipeline). Terrain is a flat
stand-in for now (real heightmap sampling deferred per the design spec). One Vehicle is
kept per entity net_id; each step reads the entity's actions and writes pos/vel/yaw back.
"""
from __future__ import annotations

import math

from network.packets.packet_config import PacketConfig
from core.entity import GameEntity, UpdateMask
from core.sim.tunables import ServerTunables
from core.sim.inputs import controls_from_actions
from wulfsim.vehicle import Vehicle

# Maximum physics sub-step. The stiff hover suspension PD (spring ~200) is
# numerically unstable under explicit Euler at the coarse 10Hz server tick
# (dt=0.1) -- it locks into a perpetual bounce. Integrating the tick as small
# sub-steps (~0.01s, matching the client's render-rate integration) keeps it
# stable. Physics constants are unchanged; only the timestep is subdivided.
_SUB_DT = 0.01


class _FlatTerrain:
    """Minimal HeightMap stand-in: constant ground height."""
    def __init__(self, ground_z: float = 0.0):
        self.ground_z = ground_z

    def height_at(self, x: float, y: float) -> float:
        return self.ground_z


class TankSim:
    def __init__(self, cfg: PacketConfig, ground_z: float = 0.0):
        self.tunables = ServerTunables(cfg)
        self.terrain = _FlatTerrain(ground_z)
        self._vehicles: dict[int, Vehicle] = {}

    def _vehicle_for(self, ent: GameEntity) -> Vehicle:
        v = self._vehicles.get(ent.net_id)
        if v is None:
            v = Vehicle(kind="tank")
            v.body.pos.set(ent.pos[0], ent.pos[1], ent.pos[2])
            self._vehicles[ent.net_id] = v
        return v

    def forget(self, net_id: int) -> None:
        self._vehicles.pop(net_id, None)

    def step(self, ent: GameEntity, dt: float) -> None:
        v = self._vehicle_for(ent)
        b = v.body
        # The entity is the single source of truth for the transform. Re-seed the
        # body's pos/vel from it each tick so external writes (jump impulse,
        # teleport, spawn reposition) are honored rather than clobbered. The cached
        # body still persists yaw/angular state and sim_time across ticks.
        b.pos.set(ent.pos[0], ent.pos[1], ent.pos[2])
        b.vel.set(ent.vel[0], ent.vel[1], ent.vel[2])
        inp = controls_from_actions(ent.actions)
        # Sub-step the tick so the stiff suspension PD stays numerically stable.
        if dt > 0.0:
            n = max(1, math.ceil(dt / _SUB_DT))
            sub = dt / n
            for _ in range(n):
                v.step(sub, inp, self.tunables, self.terrain)
        ent.pos = (b.pos.x, b.pos.y, b.pos.z)
        ent.vel = (b.vel.x, b.vel.y, b.vel.z)
        ent.rot = (ent.rot[0], ent.rot[1], b.euler.z)
        ent.mark_dirty(UpdateMask.POS | UpdateMask.VEL | UpdateMask.ROT)
