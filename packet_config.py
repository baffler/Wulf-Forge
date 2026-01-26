# packet_config.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Tuple, List

@dataclass(frozen=True, slots=True)
class TankStatsConfig:
    # Whether to send the “vital stats” block
    include_vitals: bool = True

    # Vital stats block values (match your bit widths)
    weapon_id: int = 0          # 5 bits
    health_mult_bits: int = 1   # 10 bits (you were writing 1)
    energy_mult_bits: int = 1   # 10 bits

    # Optional: firing mask, extras etc
    include_firing_mask: bool = False
    firing_mask_13bits: int = 0

    include_extras: bool = False
    extra_a_bits: int = 1       # 8 bits (if enabled)
    extra_b_bits: int = 1       # 8 bits (if enabled)


@dataclass(frozen=True, slots=True)
class TankPacketConfig:
    # Defaults for a tank spawn/update
    unit_type: int = 0
    flags: int = 1

    # Default position/velocity if caller doesn’t specify
    default_pos: tuple[float, float, float] = (100.0, 100.0, 100.0)
    default_vel: tuple[float, float, float] = (0.0, 0.0, 0.0)

    stats: TankStatsConfig = TankStatsConfig()

@dataclass(slots=True)
class UnitDefaults:
    scale: float = 1.0
    regen_or_health_related: float = 100.0
    max_health: int = 100

@dataclass(slots=True)
class VehiclePhysics:
    speed: float = 20.0
    accel: float = 4.0
    engine_torque: int = 700
    suspension_stiffness: int = 550
    ground_friction: float = 0.5
    turn_rate: float = 0.2
    suspension_dampening: float = 2.0
    unknown_int_30: int = 0
    mass: int = 33000

@dataclass(slots=True)
class ActiveVehiclePhysics:
    turn_adjust: float = 4.5
    move_adjust: float = 85.0
    strafe_adjust: float = 69.7
    max_velocity: float = 80.0
    low_fuel_level: float = 2000.0
    max_altitude: float = 5.0 #3.25
    gravity_pct: float = 0.5

# ---------- BEHAVIOR header ----------

@dataclass(slots=True)
class BehaviorHeader:
    spawn_related: int = 0

    timeout: float = 5.0
    dbl_6792F8: float = 100.0
    velocity_q: float = 100.0
    dbl_679308: float = 100.0
    dbl_679310: float = 100.0

    total_team_size: int = 20
    glimpse_ms: int = 25000
    push_ms: int = 35000

    dbl_5738B8: float = 100.0
    dword_6791B8: int = 1
    dword_6791BC: int = 1

    max_pulse_charge: float = 1.0

    # The 11 floats you’re still investigating
    unk11: Tuple[float, ...] = (1.0,) * 11

    flag1: int = 1
    flag2: int = 1

@dataclass(slots=True)
class BehaviorConfig:
    header: BehaviorHeader = field(default_factory=BehaviorHeader)

    # Section 2 (weapons): keep hard-coded for now
    weapons_units_count: int = 4
    weapon_slots_count: int = 13

    # Section 3 (units): configurable defaults, repeated N times
    unit_count: int = 39
    unit_defaults: UnitDefaults = field(default_factory=UnitDefaults)

    # Section 4 (vehicle physics): configurable, repeated N times
    vehicle_physics_count: int = 2
    vehicle_physics: VehiclePhysics = field(default_factory=VehiclePhysics)

    # Section 5 (hardpoints): keep hard-coded for now (count=0 etc.)
    # (no config)

    # Section 6 (active vehicle physics): configurable, repeated N times
    active_vehicles_count: int = 3
    active_vehicle_physics: ActiveVehiclePhysics = field(default_factory=ActiveVehiclePhysics)

    # Final padding target (payload bytes including opcode)
    target_size: int = 3116

@dataclass(frozen=True, slots=True)
class PacketConfig:
    tank: TankPacketConfig = TankPacketConfig()
    behavior: BehaviorConfig = field(default_factory=BehaviorConfig)
