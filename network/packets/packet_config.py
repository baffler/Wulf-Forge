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
    include_vitals: bool = True
    weapon_id: int = 0          
    health_mult_bits: int = 1   
    energy_mult_bits: int = 1   
    include_firing_mask: bool = False
    firing_mask_13bits: int = 0
    include_extras: bool = False
    extra_a_bits: int = 1       
    extra_b_bits: int = 1       

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
    unknown_int_30: int = 0
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
    jet_reaction_range: float = 5.0

    @property
    def tank_hover_height(self) -> float:
        if self.hover_height is not None:
            return self.hover_height
        return self.max_altitude

@dataclass(slots=True)
class BehaviorHeader:
    # Scalars parsed (in this order) by Net_HandleBehavior (0x0046dc00). Names below
    # reflect each destination global's verified consumer; addresses noted inline.
    allow_immediate_respawn: int = 0   # 0x67916d (bool): EntrySelect_ConfirmEntrySelection gates instant (re)spawn
    session_timeout_secs: float = 5.0  # 0x679170: Game_LeaveWorld/ResetSession deadline = now + value*ticks_per_sec
    reserved_6792f8: float = 10.0      # 0x6792f8: parsed but unused (dead slot)
    shadow_caster_ray_length: float = 10.0  # 0x679300: Shadow_ClipCasterRayToTerrain ray extension distance (was "velocity_q")
    reserved_679308: float = 10.0      # 0x679308: parsed but unused (dead slot)
    reserved_679310: float = 10.0      # 0x679310: parsed but unused (dead slot)
    chat_category_msg_cap: int = 20    # 0x67917c: Chat_CategoryAtLimit per-category message cap (was "total_team_size")
    keepalive_interval_a_ms: int = 25000  # 0x6791b0: Net_TickReliableTimeout keepalive interval A (ms) (was "glimpse_ms")
    keepalive_interval_b_ms: int = 35000  # 0x6791b4: Net_TickReliableTimeout keepalive interval B (ms) (was "push_ms")
    gravity_accel: float = 100.0       # 0x5738b8: vertical gravity acceleration (Fx_UpdateAllParticles, EntityPhysics_PitchDown, ...)
    map_marker_base_height: int = 1     # 0x6791b8: world Z for map-cell markers (MapPanel_SpawnCellMarkerParticle); int32 on wire (was "dword_6791B8")
    reserved_6791bc: int = 1           # 0x6791bc: parsed but unused (dead slot)
    pulse_charge_warn_threshold: float = 1.0  # 0x6792a0: Hud_DrawPulseCannonGauge low-charge color threshold (was "max_pulse_charge")
    # --- The former "unk11" block: 11 fixed16.16 floats read consecutively by
    #     Net_HandleBehavior (0x0046dc00) into globals 0x679180..0x6791a4, then
    #     0x6791ac (the parser skips 0x6791a8). Names reflect each global's
    #     verified consumer; see comments for address + reader. ---
    building_wedge_radius: float = 1.0  # 0x679180: Map_DrawBuildingIcon cone-wedge length; also deploy primary radius
    deploy_backup_radius: float = 1.0   # 0x679184: Deploy_EvaluateCellPlacement backup-cell probe radius
    target_bar_extent: float = 1.0      # 0x679188: ObjectScreen_DrawObjectMarker HUD status/range-bar param
    reserved_3: float = 1.0             # 0x67918c: written, no readers (dead)
    factory_arc_inner: float = 1.0      # 0x679190: Map_DrawFactoryIcon arc-wedge near radius
    factory_arc_outer: float = 1.0      # 0x679194: Map_DrawFactoryIcon arc-wedge far radius
    reserved_6: float = 1.0             # 0x679198: written, no readers (dead)
    radar_arc_inner: float = 1.0        # 0x67919c: Map_DrawRadarIcon arc-wedge near radius
    radar_arc_outer: float = 1.0        # 0x6791a0: Map_DrawRadarIcon arc-wedge far radius
    silo_wedge_radius: float = 1.0      # 0x6791a4: Map_DrawSiloIcon cone-wedge length
    target_lock_delay: float = 1.0      # 0x6791ac: Target_IsCandidateEligible lock-on eligibility delay (seconds)
    friendly_fire_enabled: int = 1      # 0x6791c0 (bool): Interp_HandlePrimaryWeaponCooldownExpiry; 0 = same-team hits suppressed (was "flag1")
    reserved_6792c4: int = 1            # 0x6792c4 (bool): parsed but unused (dead slot) (was "flag2")

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
