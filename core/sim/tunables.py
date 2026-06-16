"""Adapter exposing the server's BEHAVIOR config via the registry interface
that wulfsim.vehicle.Vehicle.step expects (.get(name) / .effective_gravity).

EXACT tunables are pulled from packet_config (the real client values shipped in
the BEHAVIOR 0x24 packet). MODEL knobs are sandbox force/scale models not present
in the packet; they use the phys_sim defaults until decompiled.
"""
from __future__ import annotations

from network.packets.packet_config import PacketConfig

# Sandbox model knobs. friction_thrust / friction_idle are RE-confirmed constants
# (0.1 thrusting / 2.0 coasting). The *_scale knobs, control_divisor and
# angular_damp are CALIBRATED via tools/fit_physics.py against a recorded drive
# (crossroads capture, 2026-06-15) by minimizing open-loop trajectory drift:
# mean drift 695u (uncalibrated) -> 141u (one-step fit) -> 79u (open-loop fit).
# Re-run the fit on a fresh/longer capture to refine.
_MODEL_DEFAULTS = {
    "control_divisor": 372.336,
    "thrust_scale": 46.016,
    "torque_scale": 280.355,
    "max_thrust": 1317.781,
    "hover_spring": 200.0,
    "hover_damp": 28.0,
    "angular_damp": 2.824,
    "friction_thrust": 0.1,
    "friction_idle": 2.0,
}


class ServerTunables:
    def __init__(self, cfg: PacketConfig):
        avp = cfg.behavior.active_vehicle_physics
        vp = cfg.behavior.vehicle_physics
        self._gravity_force = cfg.behavior.header.gravity_force
        self._gravity_pct = avp.gravity_pct
        self._exact = {
            "gravity_accel": self._gravity_force,
            "gravity_pct": avp.gravity_pct,
            "ground_friction": vp.ground_friction,
            "turn_adjust": avp.turn_adjust,
            "move_adjust": avp.move_adjust,
            "strafe_adjust": avp.strafe_adjust,
            "max_velocity": avp.max_velocity,
            "hover_height": avp.tank_hover_height,
            "max_altitude": avp.max_altitude,
        }

    def get(self, name: str) -> float:
        if name in self._exact:
            return self._exact[name]
        return _MODEL_DEFAULTS[name]

    @property
    def effective_gravity(self) -> float:
        return self._gravity_force * self._gravity_pct
