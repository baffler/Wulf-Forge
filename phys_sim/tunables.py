"""Shared live tunable registry -- the single source of truth for the whole sandbox.

Both the REST API (api/server.py) and the on-screen sliders (ui/sliders.py) read and mutate
THIS object; the physics tick reads it every frame. That mirrors the client model: the server
ships one BEHAVIOR(0x24) packet of tunables into globals, and the physics loop reads them each
frame (see docs/server-settings-and-tank-physics.md).

Each tunable is tagged EXACT (drives bit-exact ported math) or MODEL (drives a structural model
whose exact constant scaling is not yet decompiled -- the knobs you dial in live).
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, asdict
from typing import Optional

import os
import tomllib


@dataclass
class Tunable:
    name: str
    value: float
    lo: float
    hi: float
    group: str
    kind: str          # "EXACT" | "MODEL"
    info: str = ""


# Defaults seeded from packets.toml / packet_config.py (the real client values) plus the
# sandbox model knobs. Ranges are chosen for comfortable live tuning.
_DEFS: list[Tunable] = [
    # --- Global (EXACT: gravity is a pure downward acceleration) ---
    Tunable("gravity_accel", 100.0, 0.0, 400.0, "Global", "EXACT", "BEHAVIOR header gravity_accel (0x5738b8)"),
    Tunable("gravity_pct",     1.0, 0.0,   2.0, "Global", "EXACT", "per-class gravity multiplier; effective g = gravity_accel*gravity_pct"),

    # --- Chassis (Section 4) ---
    Tunable("ground_friction", 0.8, 0.0,   5.0, "Chassis", "EXACT", "linear velocity damping fold in EntityPhysics_IntegrateLinear"),
    # Binary thrust-gated friction (RE Vehicle_UpdateThrustFx @ 0x004f9700): k=0.1 thrusting, 2.0 coasting.
    Tunable("friction_thrust", 0.1, 0.0, 5.0, "Chassis", "EXACT", "linear damping k while thrust active"),
    Tunable("friction_idle",   2.0, 0.0, 8.0, "Chassis", "EXACT", "linear damping k while coasting (hard stop on release)"),
    Tunable("mass",        33000.0, 1000.0, 60000.0, "Chassis", "MODEL", "hull mass (Tank 33000 / Scout 13000)"),
    Tunable("suspension_stiffness", 550.0, 0.0, 2000.0, "Chassis", "MODEL", "informational; hover shaped by hover_spring"),
    Tunable("suspension_dampening", 1.3, 0.0,  10.0, "Chassis", "MODEL", "informational; hover shaped by hover_damp"),

    # --- Pilot authority (Section 6) ---
    Tunable("turn_adjust",   4.5, 0.0, 200.0, "Pilot", "EXACT", "slot1 turn authority (normalized /control_divisor, negated)"),
    Tunable("move_adjust",  85.0, 0.0, 200.0, "Pilot", "EXACT", "slot2 move authority (normalized /control_divisor)"),
    Tunable("strafe_adjust",69.7, 0.0, 200.0, "Pilot", "EXACT", "slot3 strafe authority (normalized /control_divisor, negated)"),
    Tunable("control_divisor",100.0, 1.0, 400.0, "Pilot", "EXACT", "runtime divisor in VehicleTuningSlot_GetScaledValue"),
    Tunable("max_velocity", 80.0, 1.0, 300.0, "Pilot", "MODEL", "horizontal speed clamp"),
    Tunable("hover_height",  9.75, 0.5,  60.0, "Pilot", "MODEL", "target ride height above terrain"),
    Tunable("max_altitude", 60.0, 2.0, 400.0, "Pilot", "MODEL", "ceiling above terrain (Collision_CheckEntityAgainstCeiling)"),

    # --- Suspension model (sim) ---
    Tunable("hover_spring", 200.0, 0.0, 1200.0, "Suspension", "MODEL", "PD spring gain toward hover_height"),
    Tunable("hover_damp",    28.0, 0.0, 200.0, "Suspension", "MODEL", "PD vertical damping"),

    # --- Thrust model (sim) ---
    Tunable("thrust_scale", 120.0, 0.0, 600.0, "Thrust", "MODEL", "chassis force scale (+0x58 analogue)"),
    Tunable("torque_scale", 100.0, 0.0, 600.0, "Thrust", "MODEL", "yaw torque scale (+0x5c analogue)"),
    Tunable("max_thrust",   400.0, 0.0, 2000.0, "Thrust", "MODEL", "thrust magnitude clamp"),
    Tunable("angular_damp",   4.0, 0.0,  40.0, "Thrust", "MODEL", "yaw angular velocity damping"),
]


class Tunables:
    """Thread-safe live tunable store."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._defs = {t.name: Tunable(**asdict(t)) for t in _DEFS}
        self._defaults = {t.name: t.value for t in _DEFS}

    # -- load/seed --
    def load_overrides(self, toml_path: str) -> None:
        if not os.path.exists(toml_path):
            return
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
        overrides = data.get("tunables", {}) if isinstance(data, dict) else {}
        with self._lock:
            for k, v in overrides.items():
                if k in self._defs:
                    self._defs[k].value = float(v)
                    self._defaults[k] = float(v)

    # -- access --
    def get(self, name: str) -> float:
        with self._lock:
            return self._defs[name].value

    def set(self, name: str, value: float) -> Tunable:
        with self._lock:
            t = self._defs[name]
            t.value = max(t.lo, min(t.hi, float(value)))
            return Tunable(**asdict(t))

    def snapshot(self) -> dict[str, float]:
        with self._lock:
            return {k: t.value for k, t in self._defs.items()}

    def describe(self) -> list[dict]:
        with self._lock:
            return [asdict(t) for t in self._defs.values()]

    def reset(self) -> None:
        with self._lock:
            for k, v in self._defaults.items():
                self._defs[k].value = v

    def has(self, name: str) -> bool:
        return name in self._defs

    @property
    def effective_gravity(self) -> float:
        with self._lock:
            return self._defs["gravity_accel"].value * self._defs["gravity_pct"].value
