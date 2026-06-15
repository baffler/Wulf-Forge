# network/packet_config.py
from __future__ import annotations
from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any, Type, TypeVar, Tuple, cast, get_type_hints
import os
import tomllib

# Create a generic type variable
T = TypeVar("T")

# ---------------------------------------------------------
#  HELPER: Recursive Unpacker
# ---------------------------------------------------------
def unpack(dataclass_type: Type[T], data: dict[str, Any]) -> T:
    """
    Recursively unpacks a dictionary into a dataclass.
    """
    # 1. Defensive check: If it's not a dataclass, just return the raw data.
    # We cast to T because Pylance complains that 'dict' isn't 'T', 
    # but logically we shouldn't hit this if used correctly.
    if not is_dataclass(dataclass_type):
        return cast(T, data)

    #  Use get_type_hints to resolve string annotations into actual Classes
    # (e.g. converts the string "BehaviorConfig" -> class BehaviorConfig)
    resolved_types = get_type_hints(dataclass_type)
    
    # We still need the field names to filter out bad keys
    valid_field_names = {f.name for f in fields(dataclass_type)}
    
    clean_data = {}

    for key, value in data.items():
        if key not in valid_field_names:
            continue
        
        # Get the actual class
        target_type = resolved_types[key]

        # Case 1: Nested Dataclass
        if is_dataclass(target_type) and isinstance(value, dict):
            # Recursively unpack the nested section
            nested_class = cast(Type[Any], target_type)
            clean_data[key] = unpack(nested_class, value)
        
        # Case 2: Tuple conversion (TOML arrays are lists)
        elif isinstance(value, list) and (str(target_type).startswith("typing.Tuple") or target_type is tuple):
            clean_data[key] = tuple(value)
            
        # Case 3: Standard value
        else:
            clean_data[key] = value

    # 2. Return the instantiated class
    return dataclass_type(**clean_data)

# ---------------------------------------------------------
#  DATACLASSES
# ---------------------------------------------------------

@dataclass(frozen=True, slots=True)
class TankStatsConfig:
    # GHIDRA-VERIFIED (2026-06): the TANK-spawn (0x18) "stats" bit-block is NOT
    # weapon/health/energy "vitals". The client decodes it via
    # Net_HandleTankSpawn (0x0046d260) -> Net_DecodeVehicleState (0x0047d4b0) as
    # the shared local-vehicle-state codec: a 1-bit presence flag, then
    # chassis_type / throttle_level / turn_level / a terrain-indexed field
    # (+ optional altitude & secondary). The sub-field BIT WIDTHS are runtime
    # values pulled from a quantizer-range descriptor
    # (DAT_00678134 +0x40/+0x140/+0x200), so they cannot be reproduced from
    # static config. The old weapon_id(5)/health_mult_bits(10)/energy_mult_bits(10)
    # layout was a mis-identification and desynced the rest of the packet whenever
    # enabled. The only statically-correct option is to omit the block (presence
    # bit = 0); the server's world snapshots populate real vehicle state anyway.
    send_vehicle_state: bool = False

@dataclass(frozen=True, slots=True)
class TankPacketConfig:
    unit_type: int = 0
    team_id: int = 1
    default_pos: Tuple[float, float, float] = (100.0, 100.0, 100.0)
    default_rot: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    stats: TankStatsConfig = field(default_factory=TankStatsConfig)

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
    # GHIDRA: per-type int32 at struct offset 0x30 (read in VehicleInfo_LoadGlobalState
    # 0x004e5ce0, right before the 0x34 field). NOT a physics value -- it is a Mu
    # (in-game currency) budget/capacity: read by Loadout_ComputeAffordableCount
    # (0x004265b4) as the funds that weapon/loadout costs are subtracted from, and
    # rendered as the right-hand term of the refuel-pad "%3d Mu / %3d Mu" overlay
    # (Pad_DrawRefuelOverlay 0x00426bc1). (Renamed from the placeholder unknown_int_30.)
    mu_budget: int = 0
    # NOTE: the 0x34 field below is read by VehicleInfo_GetRespawnCost (0x004e5d9c)
    # and returned as a cost/timer, so "mass" may actually be a respawn cost; kept
    # as `mass` pending dedicated verification.
    mass: int = 33000

@dataclass(slots=True)
class ActiveVehiclePhysics:
    turn_adjust: float = 4.5
    move_adjust: float = 85.0 # move_forward_adjust
    move_backward_adjust: float = 38.0
    strafe_adjust: float = 69.7
    max_velocity: float = 80.0
    low_fuel_level: float = 2000.0
    hover_height: float | None = None
    max_altitude: float = 9.75
    max_speed_height_pickup: float = 3.5
    gravity_pct: float = 0.5
    jet_reaction_width: float = 2.0
    jet_reaction_length: float = 2.0
    jet_reaction_z: float = -0.5
    jet_reaction_normal_z: float = -0.75
    # GHIDRA: trailing per-surface float (stored at surface+0x90, read by
    # JetReactionSurface_ReadPacked 0x004df500). JetReactionSurface_UpdateForObject
    # (0x004de840) uses it as the denominator that normalizes averaged ground
    # clearance into a 0..1 hover factor -- i.e. a reference/scale HEIGHT, not a
    # horizontal range. (Renamed from the misleading `jet_reaction_range`.)
    jet_reaction_height_scale: float = 5.0

    @property
    def tank_hover_height(self) -> float:
        if self.hover_height is not None:
            return self.hover_height
        return self.max_altitude

@dataclass(slots=True)
class BehaviorHeader:
    spawn_related: int = 0
    timeout: float = 5.0
    dbl_6792F8: float = 10.0
    velocity_q: float = 10.0
    dbl_679308: float = 10.0
    dbl_679310: float = 10.0
    total_team_size: int = 20
    glimpse_ms: int = 25000
    push_ms: int = 35000
    gravity_force: float = 100.0 # Gravity Force
    dword_6791B8: int = 1
    dword_6791BC: int = 1
    max_pulse_charge: float = 1.0
    unk11: Tuple[float, ...] = (1.0,) * 11
    flag1: int = 1
    flag2: int = 1

@dataclass(slots=True)
class BehaviorConfig:
    header: BehaviorHeader = field(default_factory=BehaviorHeader)
    weapons_units_count: int = 4
    weapon_slots_count: int = 13
    unit_count: int = 39
    unit_defaults: UnitDefaults = field(default_factory=UnitDefaults)
    vehicle_physics_count: int = 2
    vehicle_physics: VehiclePhysics = field(default_factory=VehiclePhysics)
    active_vehicles_count: int = 3
    active_vehicle_physics: ActiveVehiclePhysics = field(default_factory=ActiveVehiclePhysics)

@dataclass(frozen=True, slots=True)
class PacketConfig:
    tank: TankPacketConfig = field(default_factory=TankPacketConfig)
    behavior: BehaviorConfig = field(default_factory=BehaviorConfig)

    @classmethod
    def load(cls, filename: str = "packets.toml") -> PacketConfig:
        if not os.path.exists(filename):
            print(f"[WARN] {filename} not found. Using internal defaults.")
            return cls()

        with open(filename, "rb") as f:
            data = tomllib.load(f)

        # returns PacketConfig
        return unpack(cls, data)
