from __future__ import annotations
from dataclasses import dataclass, field
from network.streams import PacketWriter
from .packet_config import TankPacketConfig
from core.config import get_ticks
from network.packets.base import Packet 

@dataclass
class TankPacket(Packet):
    net_id: int
    sequence_id: int
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
        pkt.write_int32(self.sequence_id if self.sequence_id is not None else get_ticks())

        stats = self.tank_cfg.stats
        # Local-vehicle-state presence bit. The client (Net_HandleTankSpawn
        # @0x0046d260 -> Net_DecodeVehicleState @0x0047d4b0) treats the body of
        # this block as chassis_type / throttle_level / turn_level / terrain
        # fields whose bit widths are runtime-quantized, so we cannot emit a
        # correct payload from static config. Keep the bit 0 and let the server's
        # world snapshots carry real vehicle state. See TankStatsConfig.
        if stats.send_vehicle_state:
            raise NotImplementedError(
                "Tank-spawn vehicle-state block uses runtime-quantized bit widths "
                "(Net_DecodeVehicleState); it cannot be serialized from static "
                "config. Leave send_vehicle_state=False."
            )
        pkt.write_bits(0, 1)

        pkt.write_int32(_unit_type)
        pkt.write_int32(self.net_id)
        pkt.write_byte(_team_id)
        pkt.write_vector3(_pos[0], _pos[1], _pos[2])
        pkt.write_vector3(_rot[0], _rot[1], _rot[2])

        # 3. Return with Opcode (0x18)
        return b"\x18" + pkt.get_bytes()