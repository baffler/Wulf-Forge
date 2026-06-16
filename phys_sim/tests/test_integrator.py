"""Golden tests pinning the integrator to the decompiled constant-acceleration math.

These assert the exact arithmetic of Vec3_IntegratePositionVelocity (0x004f10c0) and
EntityPhysics_IntegrateLinear (0x004f27a0): pos += v*dt + 0.5*a*dt^2 ; v += a*dt, plus
the friction fold and the kinematic branch.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sim.vec3 import Vec3
from sim.body import PhysicsBody
from sim import integrator, gravity
from sim.tuning import get_scaled_value, compute_control_scalars


def approx(a, b, tol=1e-6):
    return abs(a - b) <= tol


def test_pos_vel_with_accel():
    pos = Vec3(0.0, 0.0, 0.0)
    vel = Vec3(1.0, 2.0, 3.0)
    acc = Vec3(0.0, 0.0, -10.0)
    dt = 0.5
    integrator.integrate_pos_vel(dt, pos, vel, acc)
    # pos += v*dt + 0.5*a*dt^2
    assert approx(pos.x, 1.0 * dt)
    assert approx(pos.y, 2.0 * dt)
    assert approx(pos.z, 3.0 * dt + 0.5 * (-10.0) * dt * dt)  # 1.5 - 1.25 = 0.25
    # v += a*dt
    assert approx(vel.x, 1.0)
    assert approx(vel.y, 2.0)
    assert approx(vel.z, 3.0 + (-10.0) * dt)  # -2.0


def test_pos_vel_no_accel_leaves_velocity():
    pos = Vec3(5.0, 0.0, 0.0)
    vel = Vec3(2.0, 0.0, 0.0)
    integrator.integrate_pos_vel(0.25, pos, vel, None)
    assert approx(pos.x, 5.0 + 2.0 * 0.25)
    assert approx(vel.x, 2.0)  # unchanged


def test_integrate_linear_friction_fold():
    body = PhysicsBody(vel=Vec3(10.0, 0.0, 0.0), accel=Vec3(0.0, 0.0, 0.0),
                       damping=True, friction=0.8)
    dt = 0.1
    integrator.integrate_linear(body, dt)
    # a_eff = a - v*k = (0 - 10*0.8) = -8 on x
    a_eff = -8.0
    assert approx(body.pos.x, 10.0 * dt + 0.5 * a_eff * dt * dt)
    assert approx(body.vel.x, 10.0 + a_eff * dt)


def test_integrate_linear_kinematic():
    body = PhysicsBody(vel=Vec3(4.0, 0.0, 0.0), accel=Vec3(99.0, 0.0, 0.0), kinematic=True)
    integrator.integrate_linear(body, 0.5)
    assert approx(body.pos.x, 4.0 * 0.5)   # accel ignored
    assert approx(body.vel.x, 4.0)          # velocity unchanged


def test_gravity_then_integrate():
    body = PhysicsBody()
    g = 100.0
    gravity.apply_gravity(body, g, 1.0)        # accel.z -= 100
    assert approx(body.accel.z, -100.0)
    integrator.integrate_step(body, 0.1)
    assert approx(body.vel.z, -100.0 * 0.1)    # -10
    assert approx(body.pos.z, 0.5 * (-100.0) * 0.1 * 0.1)  # -0.5


def test_ms_to_dt():
    assert approx(integrator.ms_to_dt(1000.0), 1.0)
    assert approx(integrator.ms_to_dt(16.0), 0.016)


def test_scaled_value_clamps():
    # 85 / 100 = 0.85 -> in range
    assert approx(get_scaled_value(85.0, 100.0), 0.85)
    # 85 / 10 = 8.5 -> clamp to 1.0
    assert approx(get_scaled_value(85.0, 10.0), 1.0)
    # negative below -1 clamps to -1
    assert approx(get_scaled_value(-50.0, 10.0), -1.0)


def test_control_scalars_negation():
    cs = compute_control_scalars(turn_adjust=4.5, move_adjust=85.0, strafe_adjust=69.7,
                                 divisor=100.0)
    assert approx(cs.move, 0.85)
    assert approx(cs.turn, -0.045)    # negated
    assert approx(cs.strafe, -0.697)  # negated


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
