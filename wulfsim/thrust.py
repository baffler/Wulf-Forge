"""Thrust / torque application -- structural port of Vehicle_ApplyThrustForces @ 0x004f9b10.

The client builds a body-space thrust vector from the pilot inputs scaled by the normalized
control coefficients (VehicleTuning_ComputeControlScalars) and per-chassis scale factors
(struct +0x58 / +0x5c), rotates it to world space (Vec3_RotateAroundAxis), clamps it to a max
thrust magnitude (Math_ClassifyAndCheckResult = vector length), folds in a ground-proximity
factor, and accumulates the result onto the force (+0x24..+0x2c) and torque (+0x48..+0x50)
accumulators. The +0x58/+0x5c scale factors are exposed here as `thrust_scale`/`torque_scale`
tunables pending exact RE of what populates them.
"""
from __future__ import annotations

import math

from .body import PhysicsBody
from .tuning import ControlScalars


def apply_thrust(body: PhysicsBody, throttle: float, strafe_in: float, turn_in: float,
                 cs: ControlScalars, thrust_scale: float, torque_scale: float,
                 max_thrust: float) -> None:
    """Accumulate thrust force (world XY) and yaw torque from pilot input.

    body +X is forward, +Y is left/strafe; yaw is euler.z. Inputs are in [-1, 1].
    """
    # Body-space force: input * normalized control coeff * chassis scale (Vehicle_ApplyThrustForces
    # local_24 = scale * move_in * move_coeff ; local_20 = scale * strafe_in * strafe_coeff).
    fx = thrust_scale * throttle * cs.move
    fy = thrust_scale * strafe_in * cs.strafe

    # Clamp to max thrust magnitude (Math_ClassifyAndCheckResult length clamp).
    mag = math.hypot(fx, fy)
    if max_thrust > 0.0 and mag > max_thrust:
        s = max_thrust / mag
        fx *= s
        fy *= s

    # Rotate body-space force to world by yaw (Vec3_RotateAroundAxis around the up axis).
    yaw = body.euler.z
    c, s = math.cos(yaw), math.sin(yaw)
    body.accel.x += fx * c - fy * s
    body.accel.y += fx * s + fy * c

    # Yaw torque from turn input (local_10 = torque_scale * turn_in * turn_coeff).
    body.ang_accel.z += torque_scale * turn_in * cs.turn
