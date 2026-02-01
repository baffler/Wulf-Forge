from __future__ import annotations
from dataclasses import dataclass, field
from network.streams import PacketWriter
from .packet_config import TankPacketConfig
from core.config import get_ticks
from network.packets.base import Packet 

@dataclass
class TankPacket(Packet):
    net_id: int
    tank_cfg: TankPacketConfig = field(repr=False) # specific config for this packet type
    
    # Optional overrides (default to None so we can fallback to config)
    unit_type: int | None = None
    team_id: int | None = None
    pos: tuple[float, float, float] | None = None
    rot: tuple[float, float, float] | None = None

    def serialize(self) -> bytes:
        # 1. Resolve Defaults
        # We prefer the instance value; if None, fallback to the config object
        _unit_type = self.unit_type if self.unit_type is not None else self.tank_cfg.unit_type
        _team_id = self.team_id if self.team_id is not None else self.tank_cfg.team_id
        _pos = self.pos if self.pos is not None else self.tank_cfg.default_pos
        _rot = self.rot if self.rot is not None else self.tank_cfg.default_rot

        # 2. Build the Payload
        pkt = PacketWriter()
        pkt.write_int32(get_ticks())

        stats = self.tank_cfg.stats
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

        pkt.write_int32(_unit_type)
        pkt.write_int32(self.net_id)
        pkt.write_byte(_team_id)
        pkt.write_vector3(_pos[0], _pos[1], _pos[2])
        pkt.write_vector3(_rot[0], _rot[1], _rot[2])

        # 3. Return with Opcode (0x18)
        return b"\x18" + pkt.get_bytes()