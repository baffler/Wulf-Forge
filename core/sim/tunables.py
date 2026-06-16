"""Adapter exposing the server's BEHAVIOR config via the registry interface
that wulfsim.vehicle.Vehicle.step expects (.get(name) / .effective_gravity).

EXACT tunables are pulled from packet_config (the real client values shipped in
the BEHAVIOR 0x24 packet). MODEL knobs are sandbox force/scale models not present
in the packet; they use the phys_sim defaults until decompiled.
"""
from __future__ import annotations

from network.packets.packet_config import PacketConfig

# Sandbox model knobs (mirror phys_sim/tunables.py defaults).
# friction_thrust / friction_idle are RE-confirmed constants (0.1 while thrusting,
# 2.0 while coasting); the *_scale knobs and control_divisor are the fit targets.
_MODEL_DEFAULTS = {
    "control_divisor": 100.0,
    "thrust_scale": 120.0,
    "torque_scale": 100.0,
    "max_thrust": 400.0,
    "hover_spring": 200.0,
    "hover_damp": 28.0,
    "angular_damp": 4.0,
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
