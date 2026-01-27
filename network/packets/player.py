from __future__ import annotations
from network.streams import PacketWriter
from dataclasses import dataclass, field
from network.packets.base import Packet
from core.config import get_ticks

@dataclass
class DeathNoticePacket(Packet):
    """
    Packet 0x1D: DEATH_NOTICE
    """
    player_id: int

    def serialize(self) -> bytes:
        pkt = PacketWriter()
        pkt.write_int32(self.player_id)
        return b'\x1D' + pkt.get_bytes()

@dataclass
class AddToRosterPacket(Packet):
    """
    Packet 0x1A: ADD_TO_ROSTER
    """
    account_id: int
    team: int
    name: str
    nametag: str

    def serialize(self) -> bytes:
        pkt = PacketWriter()
        pkt.write_int32(self.account_id)
        pkt.write_int32(self.team)
        pkt.write_int16(3)           # kills
        pkt.write_int16(5)            # unk14, deaths
        pkt.write_string(self.name)
        pkt.write_string(self.nametag)
        pkt.write_int16(7)           # kills?
        pkt.write_int16(2)            # deaths?
        pkt.write_fixed1616(6.7)      # Score
        pkt.write_int32(9)            # ?

        return b'\x1A' + pkt.get_bytes()

@dataclass
class CommMessagePacket(Packet):
    """
    Packet 0x1F: COMM_MESSAGE
    """
    message_type: int
    source_player_id: int
    chat_scope_id: int
    recepient_id: int
    message: str

    def serialize(self) -> bytes:
        pkt = PacketWriter()
        pkt.write_int16(self.message_type) # Message Class/Type
        pkt.write_int32(self.source_player_id) # Source Player ID
        pkt.write_int16(self.chat_scope_id) # Chat Channel/Scope (0 = Global, 4 = Team, 5 = Command/Console)
        pkt.write_int32(self.recepient_id) # Recipient ID (only used for whispers i believe)
        pkt.write_string(self.message)
        
        return b'\x1F' + pkt.get_bytes()

@dataclass
class UpdateStatsPacket(Packet):
    """
    Packet 0x1C: UPDATE_STATS
        [Type 0x1C]
        [Int32] Account ID
        [Int32] Team ID
        [Int16] Stat 1
        [Int16] Stat 2
        [Int16] Stat 3
        [Int16] Stat 4
        [Int16] Stat 5
        [Double] Value 1
        [Double] Value 2
        [Int32] Extra / Flags
    """
    player_id: int
    team_id: int

    def serialize(self) -> bytes:
        pkt = PacketWriter()
        
        pkt.write_int32(self.player_id)
        pkt.write_int32(6)              # Unknown Int 1
        pkt.write_int16(self.team_id)   # Team ID
        pkt.write_int16(33)             # Unknown Short 1
        
        # 3 Stats (Shorts)
        pkt.write_int16(3)
        pkt.write_int16(5)
        pkt.write_int16(9)
        
        # Fixed Point values
        pkt.write_fixed1616(1.0)
        pkt.write_fixed1616(1.0)
        
        pkt.write_int32(10)           # Extra / Flags
        return b'\x1C' + pkt.get_bytes()