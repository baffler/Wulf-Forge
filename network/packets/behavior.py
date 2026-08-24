# network/packets/behavior.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence
from network.packets.base import Packet
from network.streams import PacketWriter
from .packet_config import BehaviorConfig

# ==============================================================================
# CANONICAL HOVER JET SHAPE GEOMETRY (Extracted from collision meshes)
# Coordinate system: +X Forward, +Y Right (Starboard), +Z Up
# Format: (X, Y, Z, NormalX, NormalY, NormalZ, Flag)
# ==============================================================================

# Tank Red (tank_1_s) - Ground Contact Plane Z = -1.3065
TANK_RED_JET_POINTS: list[tuple[float, float, float, float, float, float, int]] = [
    (+3.3345, -2.5985, -1.3065,  0.0, 0.0, -1.0, 0),  # 0: Front-Left
    (+3.3345, +2.5985, -1.3065,  0.0, 0.0, -1.0, 0),  # 1: Front-Right
    (-4.6045, -2.5985, -1.3065,  0.0, 0.0, -1.0, 0),  # 2: Rear-Left
    (-4.6045, +2.5985, -1.3065,  0.0, 0.0, -1.0, 0),  # 3: Rear-Right
]

# Tank Blue (tank_2_s) - Ground Contact Plane Z = -1.1500
TANK_BLUE_JET_POINTS: list[tuple[float, float, float, float, float, float, int]] = [
    (+2.8860, -2.4765, -1.1500,  0.0, 0.0, -1.0, 0),  # 0: Front-Left
    (+2.8860, +2.4765, -1.1500,  0.0, 0.0, -1.0, 0),  # 1: Front-Right
    (-4.5620, -2.4765, -1.1500,  0.0, 0.0, -1.0, 0),  # 2: Rear-Left
    (-4.5620, +2.4765, -1.1500,  0.0, 0.0, -1.0, 0),  # 3: Rear-Right
]

# Medic / Scout Red (scout_1_s) - Ground Contact Plane Z = -1.4337
SCOUT_RED_JET_POINTS: list[tuple[float, float, float, float, float, float, int]] = [
    (+1.8584, -4.1416, -1.4337,  0.0, 0.0, -1.0, 0),  # 0: Front-Left
    (+1.8584, +4.1416, -1.4337,  0.0, 0.0, -1.0, 0),  # 1: Front-Right
    (-2.0708, -4.1416, -1.4337,  0.0, 0.0, -1.0, 0),  # 2: Rear-Left
    (-2.0708, +4.1416, -1.4337,  0.0, 0.0, -1.0, 0),  # 3: Rear-Right
]

# Medic / Scout Blue (scout_2_s) - Ground Contact Plane Z = -1.2271
SCOUT_BLUE_JET_POINTS: list[tuple[float, float, float, float, float, float, int]] = [
    (+1.1738, -3.8948, -1.2271,  0.0, 0.0, -1.0, 0),  # 0: Front-Left
    (+1.1738, +3.8948, -1.2271,  0.0, 0.0, -1.0, 0),  # 1: Front-Right
    (-5.5488, -3.8948, -1.2271,  0.0, 0.0, -1.0, 0),  # 2: Rear-Left
    (-5.5488, +3.8948, -1.2271,  0.0, 0.0, -1.0, 0),  # 3: Rear-Right
]


def _write_jet_shape_block(
    pkt: PacketWriter,
    points: Sequence[tuple[float, ...]],
    trailing_scalar: float = 0.0,
) -> None:
    """
    Serializes one variable-length vehicle jet shape block.
    Wire size: 8 + 28 * point_count bytes.
    """
    pkt.write_int32(len(points))

    for pt in points:
        # Local Point Coordinates (Fixed 16.16)
        pkt.write_fixed1616(pt[0])
        pkt.write_fixed1616(pt[1])
        pkt.write_fixed1616(pt[2])

        # Local Thrust Direction Normal (Fixed 16.16, default: downward -Z)
        pkt.write_fixed1616(pt[3] if len(pt) > 3 else 0.0)
        pkt.write_fixed1616(pt[4] if len(pt) > 4 else 0.0)
        pkt.write_fixed1616(pt[5] if len(pt) > 5 else -1.0)

        # Legacy Flag (Int32)
        pkt.write_int32(int(pt[6]) if len(pt) > 6 else 0)

    # Trailing Scalar (Fixed 16.16)
    pkt.write_fixed1616(trailing_scalar)


@dataclass
class BehaviorPacket(Packet):
    """
    0x24 BEHAVIOR Packet: Overwrites process-wide gameplay, weapon, entity,
    vehicle physics, hover jet shapes, and concrete model tails on the client.
    """
    cfg: BehaviorConfig = field(repr=False)

    def serialize(self) -> bytes:
        pkt = PacketWriter()
        cfg = self.cfg

        # ----------------------------------------------------------------------
        # SECTION 1: HEADER (95 bytes)
        # ----------------------------------------------------------------------
        h = cfg.header

        pkt.write_byte(int(h.allow_immediate_respawn) & 0xFF)
        pkt.write_fixed1616(h.session_timeout_secs)
        pkt.write_fixed1616(h.reserved_6792f8)
        pkt.write_fixed1616(h.shadow_caster_ray_length)
        pkt.write_fixed1616(h.reserved_679308)
        pkt.write_fixed1616(h.reserved_679310)

        pkt.write_int32(h.chat_category_msg_cap)
        pkt.write_int32(h.keepalive_interval_a_ms)
        pkt.write_int32(h.keepalive_interval_b_ms)

        pkt.write_fixed1616(h.gravity_accel)
        pkt.write_int32(h.map_marker_base_height)
        pkt.write_int32(h.reserved_6791bc)
        pkt.write_fixed1616(h.pulse_charge_warn_threshold)

        # Former "unk11" block: 11 fixed16.16 floats in the exact order
        # Net_HandleBehavior (0x0046dc00) deserializes them. Order is load-bearing.
        pkt.write_fixed1616(h.building_wedge_radius)  # 0x679180
        pkt.write_fixed1616(h.deploy_backup_radius)   # 0x679184
        pkt.write_fixed1616(h.target_bar_extent)      # 0x679188
        pkt.write_fixed1616(h.reserved_3)             # 0x67918c (dead)
        pkt.write_fixed1616(h.factory_arc_inner)      # 0x679190
        pkt.write_fixed1616(h.factory_arc_outer)      # 0x679194
        pkt.write_fixed1616(h.reserved_6)             # 0x679198 (dead)
        pkt.write_fixed1616(h.radar_arc_inner)        # 0x67919c
        pkt.write_fixed1616(h.radar_arc_outer)        # 0x6791a0
        pkt.write_fixed1616(h.silo_wedge_radius)      # 0x6791a4
        pkt.write_fixed1616(h.target_lock_delay)      # 0x6791ac

        pkt.write_byte(int(h.friendly_fire_enabled) & 0xFF)
        pkt.write_byte(int(h.reserved_6792c4) & 0xFF)

        # ----------------------------------------------------------------------
        # SECTION 2: WEAPONS (4 tables * 13 slots * 45 bytes = 2340 bytes)
        # ----------------------------------------------------------------------
        for _u in range(cfg.weapons_units_count):
            for _i in range(cfg.weapon_slots_count):
                # 5 applicability channel bool bytes
                pkt.write_byte(0)
                pkt.write_byte(0)
                pkt.write_byte(0)
                pkt.write_byte(0)
                pkt.write_byte(0)

                # Auto-aim forward-dot threshold
                pkt.write_fixed1616(1.0)

                # 5 integer fields (cooldown, load, etc.)
                pkt.write_int32(0)
                pkt.write_int32(0)
                pkt.write_int32(0)
                pkt.write_int32(0)
                pkt.write_int32(0)

                # 4 fixed-point fields (base range, random range add, scatter factor, etc.)
                pkt.write_fixed1616(100.0)
                pkt.write_fixed1616(1000.0)
                pkt.write_fixed1616(500.0)
                pkt.write_fixed1616(1.0)

        # ----------------------------------------------------------------------
        # SECTION 3: ENTITY DEFINITIONS (39 records * 12 bytes = 468 bytes)
        # ----------------------------------------------------------------------
        ud = cfg.unit_defaults
        for _ in range(cfg.unit_count):
            pkt.write_fixed1616(ud.scale)
            pkt.write_fixed1616(ud.regen_or_health_related)
            pkt.write_int32(ud.max_health)

        # ----------------------------------------------------------------------
        # SECTION 4: GENERIC VEHICLE BEHAVIOR (2 records * 36 bytes = 72 bytes)
        # ----------------------------------------------------------------------
        # Wire order: Tank (type 0), Medic / Scout (type 1)
        vehicle_profiles = (cfg.vehicle_physics, cfg.scout_vehicle_physics)
        for profile_index in range(cfg.vehicle_physics_count):
            vp = vehicle_profiles[min(profile_index, len(vehicle_profiles) - 1)]
            pkt.write_fixed1616(vp.bang_min_velocity)
            pkt.write_fixed1616(vp.scrape_min_velocity)
            pkt.write_int32(vp.bang_interval_ms)
            pkt.write_int32(vp.scrape_interval_ms)
            pkt.write_fixed1616(vp.starting_jet_strength)
            pkt.write_fixed1616(vp.minimum_jet_strength)
            pkt.write_fixed1616(vp.jet_response_coefficient)
            pkt.write_int32(vp.max_weapon_weight)
            pkt.write_int32(vp.max_fuel)

        # ----------------------------------------------------------------------
        # SECTION 5: TEAM-SPECIFIC VEHICLE JET SHAPES (4 blocks = 480 bytes)
        # ----------------------------------------------------------------------
        # Fixed wire order: Tank Red, Tank Blue, Medic/Scout Red, Medic/Scout Blue.
        # Neutral aliases Red client-side after reading.
        _write_jet_shape_block(pkt, TANK_RED_JET_POINTS)
        _write_jet_shape_block(pkt, TANK_BLUE_JET_POINTS)
        _write_jet_shape_block(pkt, SCOUT_RED_JET_POINTS)
        _write_jet_shape_block(pkt, SCOUT_BLUE_JET_POINTS)

        # ----------------------------------------------------------------------
        # SECTION 6: CONCRETE VEHICLE MODEL TAIL (108 bytes total)
        # ----------------------------------------------------------------------
        # Registry order: Tank (7 fields), Medic/Scout (9 fields), Bomber (11 fields)
        tank = cfg.active_vehicle_physics
        medic = cfg.medic_vehicle_physics

        for i in range(cfg.active_vehicles_count):
            if i == 0:
                # TANK (7 fixed-point values = 28 bytes)
                pkt.write_fixed1616(tank.turn_adjust)
                pkt.write_fixed1616(tank.move_adjust)
                pkt.write_fixed1616(tank.strafe_adjust)
                pkt.write_fixed1616(tank.max_velocity)
                pkt.write_fixed1616(tank.low_fuel_level)
                pkt.write_fixed1616(tank.tank_hover_height)
                pkt.write_fixed1616(tank.gravity_pct)

            elif i == 1:
                # SCOUT / MEDIC (9 fixed-point values = 36 bytes)
                pkt.write_fixed1616(medic.turn_adjust)
                pkt.write_fixed1616(medic.move_forward_adjust)
                pkt.write_fixed1616(medic.move_backward_adjust)
                pkt.write_fixed1616(medic.strafe_adjust)
                pkt.write_fixed1616(medic.max_velocity)
                pkt.write_fixed1616(medic.low_fuel_level)
                pkt.write_fixed1616(medic.max_altitude)
                pkt.write_fixed1616(medic.max_speed_height_pickup)
                pkt.write_fixed1616(medic.gravity_pct)

            elif i == 2:
                # BOMBER (11 fixed-point values = 44 bytes)
                pkt.write_fixed1616(-2.5132741233144)    # ax_mag
                pkt.write_fixed1616(2.35619449060725)    # ay_mag
                pkt.write_fixed1616(80.0)                # forward_mag
                pkt.write_fixed1616(45.0)                # low_airspeed
                pkt.write_fixed1616(0.5)                 # angfac
                pkt.write_fixed1616(70.0)                # turn_low
                pkt.write_fixed1616(110.0)               # turn_high
                pkt.write_fixed1616(340.0)               # turn_zero
                pkt.write_fixed1616(1000.0)              # very_high
                pkt.write_fixed1616(1800.0)              # ceiling
                pkt.write_fixed1616(tank.low_fuel_level)

        # ----------------------------------------------------------------------
        # FINAL PAYLOAD ASSEMBLY: 0x24 + Body (3,564 bytes total)
        # ----------------------------------------------------------------------
        body = pkt.get_bytes()
        return b"\x24" + body
