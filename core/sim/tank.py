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
    def __init__(self, cfg: PacketConfig, ground_z: float = 0.0, terrain=None):
        self.tunables = ServerTunables(cfg)
        # Terrain provides height_at(x, y); defaults to a flat plane until a real
        # map heightmap is loaded via set_terrain().
        self.terrain = terrain if terrain is not None else _FlatTerrain(ground_z)
        self._vehicles: dict[int, Vehicle] = {}

    def set_terrain(self, terrain) -> None:
        """Swap the terrain the sim samples (e.g. the current map's heightmap)."""
        if terrain is not None:
            self.terrain = terrain

    def _vehicle_for(self, ent: GameEntity) -> Vehicle:
        v = self._vehicles.get(ent.net_id)
        if v is None:
            v = Vehicle(kind="tank")
            v.body.pos.set(ent.pos[0], ent.pos[1], ent.pos[2])
            self._vehicles[ent.net_id] = v
        return v

    def forget(self, net_id: int) -> None:
        self._vehicles.pop(net_id, None)

    def _terrain_tilt(self, x: float, y: float, yaw: float) -> tuple[float, float]:
        """Hull pitch/roll that self-levels to the terrain slope under (x, y).

        Samples the terrain gradient and rotates it into the body frame by yaw:
        pitch = tilt along the forward axis, roll = tilt along the right axis.
        (Sign/axis convention is a best-guess vs the client's euler order; flip
        if it tilts the wrong way in-game.)
        """
        d = 2.0
        th = self.terrain.height_at
        gx = (th(x + d, y) - th(x - d, y)) / (2.0 * d)  # slope along world +x
        gy = (th(x, y + d) - th(x, y - d)) / (2.0 * d)  # slope along world +y
        cos_y, sin_y = math.cos(yaw), math.sin(yaw)
        slope_fwd = gx * cos_y + gy * sin_y     # forward axis (cos, sin)
        slope_right = gx * sin_y - gy * cos_y   # right axis (sin, -cos)
        return math.atan(slope_fwd), math.atan(slope_right)

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
        # Self-level the hull to the terrain slope (pitch/roll); yaw from the sim.
        pitch, roll = self._terrain_tilt(b.pos.x, b.pos.y, b.euler.z)
        ent.rot = (pitch, roll, b.euler.z)
        ent.mark_dirty(UpdateMask.POS | UpdateMask.VEL | UpdateMask.ROT)
