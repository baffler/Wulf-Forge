"""Hover suspension + ceiling clamp.

The client keeps the hover-tank a fixed ride height above the terrain via a spring/damper
contact response shaped by `suspension_stiffness` / `suspension_dampening` (resolved inside
CollisionContact_ResolveAll @ 0x004f8510 after the ground test Collision_CheckObjectGroundHeight
@ 0x00500f60). The exact spring constant scaling is not yet decompiled, so this is modeled as a
PD controller in the acceleration domain with live-tunable spring/damp gains -- the values you
dial in via the sliders/REST. `max_altitude` enforcement mirrors Collision_CheckEntityAgainstCeiling
@ 0x004fb050.
"""
from __future__ import annotations

from .body import PhysicsBody
from .terrain import HeightMap


def apply_suspension(body: PhysicsBody, terrain: HeightMap, hover_height: float,
                     spring: float, damp: float) -> None:
    """Add a PD hover acceleration toward (ground + hover_height) onto accel.z.

    At equilibrium the spring term supplies the upward acceleration that cancels gravity
    (the hull rests slightly compressed), exactly as a physical suspension would.
    """
    ground = terrain.height_at(body.pos.x, body.pos.y)
    target = ground + hover_height
    err = target - body.pos.z
    body.accel.z += spring * err - damp * body.vel.z


def clamp_to_ground(body: PhysicsBody, terrain: HeightMap, min_clearance: float = 0.25) -> None:
    """Hard floor: never let the hull sink through terrain (ground-penetration response)."""
    floor = terrain.height_at(body.pos.x, body.pos.y) + min_clearance
    if body.pos.z < floor:
        body.pos.z = floor
        if body.vel.z < 0.0:
            body.vel.z = 0.0


def clamp_to_ceiling(body: PhysicsBody, terrain: HeightMap, max_altitude: float) -> None:
    """max_altitude enforcement (Collision_CheckEntityAgainstCeiling): clamp absolute Z
    ceiling = ground + max_altitude and kill upward velocity on contact."""
    ceiling = terrain.height_at(body.pos.x, body.pos.y) + max_altitude
    if body.pos.z > ceiling:
        body.pos.z = ceiling
        if body.vel.z > 0.0:
            body.vel.z = 0.0
