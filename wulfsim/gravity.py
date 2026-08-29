"""Gravity application -- EntityPhysics_PitchDown (named function in W2VULK).

    accel.z (+0x2c) -= gravity_global * s

Called once per world tick with s = 1.0 (EntityPhysics_RunWorldTick), so the full
gravity acceleration is folded into the z accumulator before integration; the dt
scaling then happens inside the integrator. gravity_global == _DAT_005738b8, set from
the BEHAVIOR header `gravity_accel`.
"""
from __future__ import annotations

from .body import PhysicsBody


def apply_gravity(body: PhysicsBody, gravity: float, s: float = 1.0) -> None:
    body.accel.z -= gravity * s
