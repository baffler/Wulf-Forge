"""1:1 port of the client linear-integration chain.

  Vec3_IntegratePositionVelocity   0x004f10c0
  EntityPhysics_IntegrateLinear    0x004f27a0
  EntityPhysics_IntegrateStep      0x004f2890
  EntityPhysics_RunWorldTick       0x004f8550

The scheme is exact constant-acceleration integration (not plain Euler):
    pos += vel*dt + 0.5*accel*dt^2
    vel += accel*dt
with an optional friction fold a_eff = accel - vel*friction, and a kinematic mode
that advances position by velocity alone.
"""
from __future__ import annotations

from typing import Optional

from .constants import HALF, TICK_DENOM_MS
from .vec3 import Vec3
from .body import PhysicsBody


def integrate_pos_vel(dt: float, pos: Vec3, vel: Vec3, accel: Optional[Vec3]) -> None:
    """Vec3_IntegratePositionVelocity @ 0x004f10c0.

    accel is None  -> pos += vel*dt (velocity unchanged).
    accel present  -> pos += vel*dt + 0.5*accel*dt^2 ; vel += accel*dt.
    """
    if accel is None:
        pos.x += vel.x * dt
        pos.y += vel.y * dt
        pos.z += vel.z * dt
        return

    half_dt2 = HALF * dt * dt  # 0.5 * dt^2  (_DAT_00564e28 == 0.5)
    pos.x += accel.x * half_dt2 + vel.x * dt
    pos.y += accel.y * half_dt2 + vel.y * dt
    pos.z += accel.z * half_dt2 + vel.z * dt
    vel.x += accel.x * dt
    vel.y += accel.y * dt
    vel.z += accel.z * dt


def integrate_linear(body: PhysicsBody, dt: float) -> None:
    """EntityPhysics_IntegrateLinear @ 0x004f27a0.

    Branches on the body's integration-mode flags exactly as the client does.
    """
    if body.kinematic:  # flags[+4] != 0
        body.pos.x += body.vel.x * dt
        body.pos.y += body.vel.y * dt
        body.pos.z += body.vel.z * dt
        return

    if not body.damping:  # flags[+3] == 0 : accel passed straight through
        accel = body.accel
    else:  # flags[+3] != 0 : a_eff = accel - vel * friction  (k at chassis +0x78)
        k = body.friction
        accel = Vec3(
            body.accel.x - body.vel.x * k,
            body.accel.y - body.vel.y * k,
            body.accel.z - body.vel.z * k,
        )

    integrate_pos_vel(dt, body.pos, body.vel, accel)


def integrate_step(body: PhysicsBody, dt: float) -> None:
    """EntityPhysics_IntegrateStep @ 0x004f2890 (linear portion; rotation handled by the
    vehicle pipeline). No-ops on dt == 0, matching the client guard."""
    if dt == 0.0:
        return
    body.sim_time += dt
    integrate_linear(body, dt)


def ms_to_dt(elapsed_ms: float) -> float:
    """dt = elapsed_ms / 1000.0  (EntityPhysics_RunWorldTick, _DAT_00564f10 == 1000.0)."""
    return elapsed_ms / TICK_DENOM_MS
