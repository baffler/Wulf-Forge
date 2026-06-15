from __future__ import annotations
from network.streams import PacketReader, PacketWriter
from dataclasses import dataclass
from network.packets.base import Packet
from core.config import get_ticks

@dataclass(frozen=True, slots=True)
class ReincarnateRequest:
    sequence: int
    length: int
    is_team_switch: bool
    team_id: int = 0
    unit_id: int = 0
    repair_pad_id: int = 0
    extra_x: int = 0
    extra_y: int = 0

    @property
    def selected_entry_id(self) -> int:
        return self.unit_id

    @property
    def base_id(self) -> int:
        return self.repair_pad_id

def parse_reincarnate_request(payload: bytes) -> ReincarnateRequest:
    """
    Parse client opcode 0x25 payloads.

    Mode 0 is [selectedEntryId][baseId][x][y] in observed client logs.
    The historical field names are kept for compatibility with callers/tests.
    Mode 1 is [teamId][0].
    """
    reader = PacketReader(payload)
    reader.read_byte()
    sequence = reader.read_int16()
    length = reader.read_int16()
    mode = reader.read_byte()
    first_value = reader.read_int32()
    second_value = reader.read_int32()

    if mode == 1:
        return ReincarnateRequest(
            sequence=sequence,
            length=length,
            is_team_switch=True,
            team_id=first_value,
        )

    return ReincarnateRequest(
        sequence=sequence,
        length=length,
        is_team_switch=False,
        unit_id=first_value,
        repair_pad_id=second_value,
        extra_x=reader.read_int32(),
        extra_y=reader.read_int32(),
    )

@dataclass
class ReincarnatePacket(Packet):
    """
    Packet 0x25: REINCARNATE
    """
    code: int
    message: str = ""

    def serialize(self) -> bytes:
        pkt = PacketWriter()
        pkt.write_byte(self.code)
        pkt.write_string(self.message)
        return b'\x25' + pkt.get_bytes()

@dataclass
class BirthNoticePacket(Packet):
    """
    Packet 0x1E: BIRTH
    """
    player_id: int

    def serialize(self) -> bytes:
        pkt = PacketWriter()
        pkt.write_int32(self.player_id)
        pkt.write_int32(1) # Unknown
        return b'\x1E' + pkt.get_bytes()

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
class RemoveFromRosterPacket(Packet):
    """
    Packet 0x1B: REMOVE_FROM_ROSTER
    """
    account_id: int

    def serialize(self) -> bytes:
        pkt = PacketWriter()
        pkt.write_int32(self.account_id)
        return b'\x1B' + pkt.get_bytes()

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
        pkt.write_int32(0)            # unknown/account metadata
        pkt.write_int16(self.team)
        pkt.write_int16(2)            # color/stat slot
        pkt.write_string(self.name)
        pkt.write_string(self.nametag)
        pkt.write_int16(2)           # kills?
        pkt.write_int16(2)            # deaths?
        pkt.write_fixed1616(6.9)      # Score
        pkt.write_int32(2)            # ?

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
        [Int32] Unknown
        [Int16] Stat 1
        [Int16] Team ID
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
