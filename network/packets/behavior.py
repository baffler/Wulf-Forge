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

        pkt.write_byte(int(h.spawn_related) & 0xFF)
        pkt.write_fixed1616(h.timeout)
        pkt.write_fixed1616(h.dbl_6792F8)
        pkt.write_fixed1616(h.velocity_q)
        pkt.write_fixed1616(h.dbl_679308)
        pkt.write_fixed1616(h.dbl_679310)

        pkt.write_int32(h.total_team_size)
        pkt.write_int32(h.glimpse_ms)
        pkt.write_int32(h.push_ms)

        pkt.write_fixed1616(h.gravity_force)
        pkt.write_int32(h.dword_6791B8)
        pkt.write_int32(h.dword_6791BC)
        pkt.write_fixed1616(h.max_pulse_charge)

        if len(h.unk11) != 11:
            raise ValueError(f"BehaviorHeader.unk11 must be exactly 11 floats, got {len(h.unk11)}")

        for v in h.unk11:
            pkt.write_fixed1616(v)

        pkt.write_byte(int(h.flag1) & 0xFF)
        pkt.write_byte(int(h.flag2) & 0xFF)

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
        vp = cfg.vehicle_physics
        for _ in range(cfg.vehicle_physics_count):
            pkt.write_fixed1616(vp.speed)                 # dBangMinVelocity
            pkt.write_fixed1616(vp.accel)                 # dScrapeMinVelocity

            pkt.write_int32(vp.engine_torque)             # nBangInterval (ms)
            pkt.write_int32(vp.suspension_stiffness)      # nScrapeInterval (ms)

            pkt.write_fixed1616(vp.ground_friction)       # dStartingJetStrength
            pkt.write_fixed1616(vp.turn_rate)             # dMinimumJetStrength
            pkt.write_fixed1616(vp.suspension_dampening)  # dJetResponseCoefficient

            pkt.write_int32(vp.unknown_int_30)            # nMaxWeaponWeight
            pkt.write_int32(vp.mass)                      # nMaxFuel

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
        av = cfg.active_vehicle_physics

        for i in range(cfg.active_vehicles_count):
            if i == 0:
                # TANK (7 fixed-point values = 28 bytes)
                pkt.write_fixed1616(av.turn_adjust)
                pkt.write_fixed1616(av.move_adjust)
                pkt.write_fixed1616(av.strafe_adjust)
                pkt.write_fixed1616(av.max_velocity)
                pkt.write_fixed1616(av.low_fuel_level)
                pkt.write_fixed1616(av.max_altitude)
                pkt.write_fixed1616(av.gravity_pct)

            elif i == 1:
                # SCOUT / MEDIC (9 fixed-point values = 36 bytes)
                pkt.write_fixed1616(av.turn_adjust)
                pkt.write_fixed1616(av.move_adjust)      # forward_move_adjust
                pkt.write_fixed1616(38.0)                # backward_move_adjust
                pkt.write_fixed1616(72.0)                # strafe_adjust
                pkt.write_fixed1616(85.0)                # max_velocity
                pkt.write_fixed1616(av.low_fuel_level)
                pkt.write_fixed1616(4.9)                 # max_altitude
                pkt.write_fixed1616(3.5)                 # max_speed_height_pickup
                pkt.write_fixed1616(av.gravity_pct)

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
                pkt.write_fixed1616(av.low_fuel_level)

        # ----------------------------------------------------------------------
        # FINAL PAYLOAD ASSEMBLY: 0x24 + Body (3,564 bytes total)
        # ----------------------------------------------------------------------
        body = pkt.get_bytes()
        return b"\x24" + body