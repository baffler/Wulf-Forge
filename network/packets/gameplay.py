from __future__ import annotations
from dataclasses import dataclass, field
from network.streams import PacketWriter
from .packet_config import TankPacketConfig
from core.config import get_ticks
from network.packets.base import Packet

@dataclass
class DockingPacket(Packet):
    entity_id: int # or net_id ?
    is_docked: bool

    def serialize(self) -> bytes:
        pkt = PacketWriter()
        pkt.write_int32(get_ticks())
        pkt.write_int32(self.entity_id)
        pkt.write_byte(1 if self.is_docked else 0)
        return b'\x38' + pkt.get_bytes()

@dataclass
class CarryingInfoPacket(Packet):
    player_id: int
    has_cargo: bool
    unk_v2: int
    item_id: int

    def serialize(self) -> bytes:
        pkt = PacketWriter()
        pkt.write_int32(self.player_id)
        pkt.write_byte(1 if self.has_cargo else 0)
        pkt.write_byte(self.unk_v2)
        pkt.write_byte(self.item_id)
        return b'\x29' + pkt.get_bytes()
    
@dataclass
class ResetGamePacket(Packet):
    # 0x3F - RESET_GAME
    def serialize(self) -> bytes:
        return b'\x3F'