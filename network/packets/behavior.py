# network/packets/behavior.py
from __future__ import annotations

from typing import Tuple
from network.streams import PacketWriter
from packet_config import BehaviorConfig


def build_behavior_payload(cfg: BehaviorConfig) -> bytes:
    """
    Builds packet 0x24 payload (includes opcode as first byte).
    Keeps weapons + hardpoints logic intact for now,
    but exposes header, units, vehicle physics, and active vehicle physics via cfg.
    """
    pkt = PacketWriter()

    # --------------------------
    # SECTION 1: HEADER
    # --------------------------
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

    pkt.write_fixed1616(h.dbl_5738B8)
    pkt.write_int32(h.dword_6791B8)
    pkt.write_int32(h.dword_6791BC)
    pkt.write_fixed1616(h.max_pulse_charge)

    if len(h.unk11) != 11:
        raise ValueError(f"BehaviorHeader.unk11 must be exactly 11 floats, got {len(h.unk11)}")

    for v in h.unk11:
        pkt.write_fixed1616(v)

    pkt.write_byte(int(h.flag1) & 0xFF)
    pkt.write_byte(int(h.flag2) & 0xFF)

    # --------------------------
    # SECTION 2: WEAPONS (unchanged, hard-coded)
    # --------------------------
    for _u in range(cfg.weapons_units_count):
        for _i in range(cfg.weapon_slots_count):
            # 5 bool bytes
            pkt.write_byte(0)
            pkt.write_byte(0)
            pkt.write_byte(0)
            pkt.write_byte(0)
            pkt.write_byte(0)

            # targeting cone
            pkt.write_fixed1616(1.0)

            # 5 ints
            pkt.write_int32(0)
            pkt.write_int32(0)
            pkt.write_int32(0)
            pkt.write_int32(0)
            pkt.write_int32(0)

            # 4 fixeds
            pkt.write_fixed1616(100.0)
            pkt.write_fixed1616(1000.0)
            pkt.write_fixed1616(500.0)
            pkt.write_fixed1616(1.0)

    # --------------------------
    # SECTION 3: UNITS (configurable defaults)
    # --------------------------
    ud = cfg.unit_defaults
    for _ in range(cfg.unit_count):
        pkt.write_fixed1616(ud.scale)
        pkt.write_fixed1616(ud.regen_or_health_related)
        pkt.write_int32(ud.max_health)

    # --------------------------
    # SECTION 4: VEHICLE PHYSICS (configurable)
    # --------------------------
    vp = cfg.vehicle_physics
    for _ in range(cfg.vehicle_physics_count):
        pkt.write_fixed1616(vp.speed)
        pkt.write_fixed1616(vp.accel)

        pkt.write_int32(vp.engine_torque)
        pkt.write_int32(vp.suspension_stiffness)

        pkt.write_fixed1616(vp.ground_friction)
        pkt.write_fixed1616(vp.turn_rate)
        pkt.write_fixed1616(vp.suspension_dampening)

        pkt.write_int32(vp.unknown_int_30)
        pkt.write_int32(vp.mass)

    # --------------------------
    # SECTION 5: HARDPOINTS (unchanged for now)
    # --------------------------
    _write_hardpoint_block(pkt, count=0, is_thruster=False)
    _write_hardpoint_block(pkt, count=0, is_thruster=True)
    _write_hardpoint_block(pkt, count=0, is_thruster=False)
    _write_hardpoint_block(pkt, count=0, is_thruster=True)

    # --------------------------
    # SECTION 6: ACTIVE VEHICLE PHYSICS (configurable)
    # --------------------------
    av = cfg.active_vehicle_physics
    for _ in range(cfg.active_vehicles_count):
        pkt.write_fixed1616(av.turn_adjust)
        pkt.write_fixed1616(av.move_adjust)
        pkt.write_fixed1616(av.strafe_adjust)
        pkt.write_fixed1616(av.max_velocity)
        pkt.write_fixed1616(av.low_fuel_level)
        pkt.write_fixed1616(av.max_altitude)
        pkt.write_fixed1616(av.gravity_pct)

    # --------------------------
    # FINAL: PADDING TO TARGET
    # --------------------------
    body = pkt.get_bytes()
    payload = b"\x24" + body

    padding_needed = cfg.target_size - len(payload)
    if padding_needed > 0:
        payload += b"\x00" * padding_needed

    return payload


def _write_hardpoint_block(pkt: PacketWriter, count: int, is_thruster: bool) -> None:
    pkt.write_int32(count)

    if count > 0:
        for i in range(count):
            z_offset = -2.0 if is_thruster else 2.0
            x_offset = 1.5 if (count > 1 and i == 1) else -1.5 if (count > 1) else 0.0

            pkt.write_fixed1616(float(x_offset))
            pkt.write_fixed1616(0.5)
            pkt.write_fixed1616(float(z_offset))

            pkt.write_fixed1616(0.0)
            pkt.write_fixed1616(0.0)
            pkt.write_fixed1616(-1.0 if is_thruster else 1.0)

            pkt.write_int32(1)

    pkt.write_fixed1616(0.0)
