"""Per-class vehicle tick pipeline.

Assembles the ported pieces in the client's per-tick order (Player_UpdateLocalVehicleTick
@ 0x0046af90 -> ApplyThrustForces -> world tick gravity + integrate -> collide/clamp):

    control scalars  ->  thrust/torque  ->  gravity  ->  suspension  ->  integrate  ->  clamp

Tank is fully implemented. Scout/Bomber currently reuse this pipeline with vertical thrust
enabled and softened suspension; their bit-exact lift/aero (MedicVehicle_ApplyThrustAndLift
@ 0x004f6ed0, Vehicle_ApplyAerodynamicForces @ 0x004f15b0) are scheduled for the next phase.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .body import PhysicsBody
from .vec3 import Vec3
from .terrain import HeightMap
from .tuning import compute_control_scalars
from .thrust import apply_thrust
from .gravity import apply_gravity
from . import integrator
from . import suspension


@dataclass(slots=True)
class Inputs:
    throttle: float = 0.0   # +forward / -reverse  [-1, 1]
    strafe: float = 0.0     # +left / -right        [-1, 1]
    turn: float = 0.0       # +ccw / -cw            [-1, 1]
    vertical: float = 0.0   # +up / -down (flyers)  [-1, 1]


VEHICLE_KINDS = ("tank", "scout", "bomber")


@dataclass(slots=True)
class Vehicle:
    kind: str = "tank"
    body: PhysicsBody = field(default_factory=PhysicsBody)

    @property
    def is_flyer(self) -> bool:
        return self.kind in ("scout", "bomber")

    def reset(self, terrain: HeightMap, hover_height: float) -> None:
        self.body = PhysicsBody()
        self.body.pos.set(0.0, 0.0, terrain.height_at(0.0, 0.0) + hover_height)

    def step(self, dt: float, inp: Inputs, t, terrain: HeightMap) -> None:
        """Advance one fixed physics tick. `t` is the Tunables registry (read live)."""
        if dt <= 0.0:
            return
        b = self.body

        # 1. Normalized control scalars (VehicleTuning_ComputeControlScalars).
        cs = compute_control_scalars(
            turn_adjust=t.get("turn_adjust"),
            move_adjust=t.get("move_adjust"),
            strafe_adjust=t.get("strafe_adjust"),
            divisor=t.get("control_divisor"),
        )

        # 2. Thrust + yaw torque (Vehicle_ApplyThrustForces).
        b.friction = t.get("ground_friction")
        b.damping = True
        apply_thrust(b, inp.throttle, inp.strafe, inp.turn, cs,
                     thrust_scale=t.get("thrust_scale"),
                     torque_scale=t.get("torque_scale"),
                     max_thrust=t.get("max_thrust"))

        # Flyer vertical thrust (provisional Medic-lift stand-in).
        if self.is_flyer:
            b.accel.z += inp.vertical * t.get("thrust_scale")

        # 3. Gravity (EntityPhysics_PitchDown): pure downward acceleration.
        apply_gravity(b, t.effective_gravity)

        # 4. Suspension hover (softened for flyers so vertical thrust dominates).
        spring = t.get("hover_spring")
        damp = t.get("hover_damp")
        if self.is_flyer:
            spring *= 0.15
        suspension.apply_suspension(b, terrain, t.get("hover_height"), spring, damp)

        # 5. Integrate linear (EntityPhysics_IntegrateStep -> IntegrateLinear).
        integrator.integrate_step(b, dt)

        # 5b. Integrate yaw (rotation portion of IntegrateStep) with angular damping.
        ang_damp = t.get("angular_damp")
        b.ang_vel.z += b.ang_accel.z * dt
        b.ang_vel.z -= b.ang_vel.z * ang_damp * dt
        b.euler.z += b.ang_vel.z * dt

        # 6. Clamps: horizontal max_velocity, ground penetration, max_altitude ceiling.
        max_v = t.get("max_velocity")
        hs = math.hypot(b.vel.x, b.vel.y)
        if hs > max_v and hs > 0.0:
            s = max_v / hs
            b.vel.x *= s
            b.vel.y *= s

        suspension.clamp_to_ground(b, terrain)
        suspension.clamp_to_ceiling(b, terrain, t.get("max_altitude"))

        # 7. Clear force/torque accumulators (RunWorldTick tail).
        b.clear_accumulators()

    def state(self) -> dict:
        b = self.body
        return {
            "kind": self.kind,
            "pos": [b.pos.x, b.pos.y, b.pos.z],
            "vel": [b.vel.x, b.vel.y, b.vel.z],
            "yaw": b.euler.z,
            "yaw_rate": b.ang_vel.z,
            "speed": math.hypot(b.vel.x, b.vel.y),
            "speed_3d": b.vel.length(),
            "sim_time": b.sim_time,
        }
