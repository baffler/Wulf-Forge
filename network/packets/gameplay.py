from __future__ import annotations
from dataclasses import dataclass, field
from network.streams import PacketWriter
from .packet_config import TankPacketConfig
from core.config import get_ticks
from network.packets.base import Packet

# TODO: Add loop to delete more than 1 object at a time
@dataclass
class DeleteObjectPacket(Packet):
    net_id: int

    def serialize(self) -> bytes:
        pkt = PacketWriter()
        pkt.write_int32(get_ticks())
        pkt.write_byte(1) # 1 Object
        pkt.write_int32(self.net_id)
        pkt.write_byte(1) # True
        return b'\x15' + pkt.get_bytes()

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
    """CARRYING_INFO (server->client opcode 0x29).

    Wire layout read by Net_HandleCarryingInfo @ 0x0046e190 (wulfram2.exe):
        int32 entityId, byte hasCargo, byte cargoType, byte unk_v2
    cargoType is the carried unit/buildable type; unk_v2 is the team/colour
    variant index for the carried-cargo model.
    """
    player_id: int
    has_cargo: bool
    cargo_type: int
    variant: int = 0

    def serialize(self) -> bytes:
        pkt = PacketWriter()
        pkt.write_int32(self.player_id)
        pkt.write_byte(1 if self.has_cargo else 0)
        pkt.write_byte(self.cargo_type & 0xFF)
        pkt.write_byte(self.variant & 0xFF)
        return b'\x29' + pkt.get_bytes()


@dataclass
class DropRequestPacket(Packet):
    """DROP_REQUEST (client->server opcode 0x2B, reliable).

    Body is a single int32: 1 = deploy carried cargo as a structure, 0 = drop
    it loose. Sent by deploy_cargo @ 0x0045de40 / drop_cargo @ 0x0045de00.
    Decode-only on the server; provided for symmetry/testing.
    """
    deploy: bool

    def serialize(self) -> bytes:
        pkt = PacketWriter()
        pkt.write_int32(1 if self.deploy else 0)
        return b'\x2B' + pkt.get_bytes()
    
@dataclass
class ResetGamePacket(Packet):
    # 0x3F - RESET_GAME
    def serialize(self) -> bytes:
        return b'\x3F'