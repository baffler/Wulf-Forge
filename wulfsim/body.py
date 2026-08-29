"""PhysicsBody -- the subset of the client entity-physics record the integrator touches.

Field names map to wulfram2.exe entity offsets (see EntityPhysics_IntegrateStep @ 0x004f2890):
    +0x0c pos      +0x18 vel      +0x24 accel/force accumulator
    +0x30 euler    +0x3c ang_vel  +0x48 angular accumulator
The accumulators (accel / ang_accel) are zeroed every world tick after integration
(EntityPhysics_RunWorldTick @ 0x004f8550); velocity persists.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .vec3 import Vec3


@dataclass(slots=True)
class PhysicsBody:
    pos: Vec3 = field(default_factory=Vec3)        # +0x0c
    vel: Vec3 = field(default_factory=Vec3)        # +0x18
    accel: Vec3 = field(default_factory=Vec3)      # +0x24  (force/accel accumulator)
    euler: Vec3 = field(default_factory=Vec3)      # +0x30  (pitch, roll, yaw)
    ang_vel: Vec3 = field(default_factory=Vec3)    # +0x3c
    ang_accel: Vec3 = field(default_factory=Vec3)  # +0x48  (torque/ang accumulator)

    # Integration mode flags (EntityPhysics_IntegrateLinear @ 0x004f27a0):
    #   kinematic  == flags[+4] != 0 : pos += vel*dt only, no acceleration term
    #   damping    == flags[+3] != 0 : apply a_eff = a - vel*friction before integrating
    kinematic: bool = False
    damping: bool = True

    # Ground friction k used by the damping branch (chassis tuning, struct +0x78).
    friction: float = 0.0

    sim_time: float = 0.0  # accumulated integrated seconds (+0xb8 on the matrix block)

    def clear_accumulators(self) -> None:
        """End-of-tick clear of force/torque accumulators (RunWorldTick tail)."""
        self.accel.zero()
        self.ang_accel.zero()
