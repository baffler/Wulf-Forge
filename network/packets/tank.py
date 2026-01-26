# packets/tank.py
from __future__ import annotations
from config import get_ticks
from network.streams import PacketWriter
from packet_config import TankPacketConfig

def build_tank_payload(
    net_id: int,
    *,
    tank_cfg: TankPacketConfig,
    unit_type: int | None = None,
    flags: int | None = None,
    pos: tuple[float, float, float] | None = None,
    vel: tuple[float, float, float] | None = None,
) -> bytes:
    unit_type = tank_cfg.unit_type if unit_type is None else unit_type
    flags = tank_cfg.flags if flags is None else flags
    pos = tank_cfg.default_pos if pos is None else pos
    vel = tank_cfg.default_vel if vel is None else vel

    pkt = PacketWriter()
    pkt.write_int32(get_ticks())

    stats = tank_cfg.stats
    pkt.write_bits(1 if stats.include_vitals else 0, 1)

    if stats.include_vitals:
        pkt.write_bits(stats.weapon_id, 5)
        pkt.write_bits(stats.health_mult_bits, 10)
        pkt.write_bits(stats.energy_mult_bits, 10)

        if stats.include_firing_mask:
            pkt.write_bits(stats.firing_mask_13bits, 13)

        if stats.include_extras:
            pkt.write_bits(stats.extra_a_bits, 8)
            pkt.write_bits(stats.extra_b_bits, 8)

    pkt.write_int32(unit_type)
    pkt.write_int32(net_id)
    pkt.write_byte(flags)
    pkt.write_vector3(pos[0], pos[1], pos[2])
    pkt.write_vector3(vel[0], vel[1], vel[2])

    return b"\x18" + pkt.get_bytes()
