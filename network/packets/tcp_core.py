from __future__ import annotations
from network.streams import PacketWriter
from dataclasses import dataclass, field
from network.packets.base import Packet
from core.config import get_ticks

# ----------------------------
# Startup/Login Packets
# ----------------------------

@dataclass
class PlayerInfoPacket(Packet):
    """
    Packet 0x17: PLAYER
    [Type 0x17]
    [4 Bytes] Player ID (local_4)
    [1 Byte]  Is Guest
    """

    player_id:int
    player_guest_flag:bool
    
    def serialize(self) -> bytes:
        pkt = PacketWriter()
        pkt.write_int32(self.player_id)
        pkt.write_byte(self.player_guest_flag)
        return b'\x17' + pkt.get_bytes()

@dataclass
class LoginStatusPacket(Packet):
    """
    Sends packet 0x22 (Login Status).
    Structure: [22] [DonorFlag] [StatusCode]
    """
    is_donor: bool
    code: int

    def serialize(self) -> bytes:
        pkt = PacketWriter()
        # Convert bool to 1 or 0
        pkt.write_byte(1 if self.is_donor else 0)
        pkt.write_byte(self.code)
        return b'\x22' + pkt.get_bytes()

@dataclass
class IdentifiedUdpPacket(Packet):
    """Packet 0x4D: IDENTIFIED_UDP"""
    def serialize(self) -> bytes:
        return b"\x4D"

@dataclass
class MotdPacket(Packet):
    """
    Packet 0x23: MOTD
    Format: [Type 0x23] [String]
    """
    message: str = ""

    def serialize(self) -> bytes:
        pkt = PacketWriter()
        pkt.write_string(self.message)
        return b'\x23' + pkt.get_bytes()
    
@dataclass
class BpsReplyPacket(Packet):
    """
    Packet 0x4E: BPS_RESPONSE
    Structure from process_bps_request:
    [Type 0x4E]
    [Int32] Rate Value - Echo back the requested rate
    [Byte]  Approved   - Send 1 (True) to bypass the paywall
    """

    requested_rate:int
    
    def serialize(self) -> bytes:
        pkt = PacketWriter()
        pkt.write_int32(self.requested_rate)
        pkt.write_byte(1)
        return b'\x4E' + pkt.get_bytes()
    
@dataclass
class GameClockPacket(Packet):
    def serialize(self) -> bytes:
        pkt = PacketWriter()
        pkt.write_int32(get_ticks())
        pkt.write_byte(0x01) # Is active or enabled? not sure
        pkt.write_int32(1) # Maybe Phase flag (0 = Push, 1 = Glimpse), 0 or 1
        pkt.write_int32(30000) # Length of next Push/Glimpse (in Ms)
        return b'\x2F' + pkt.get_bytes()
    
@dataclass
class WorldStatsPacket(Packet):
    """
    Packet 0x16: WORLD_STATS
    Triggers 'set_current_world' in the client.
    Structure:
    [Type 0x16]
    [String] Map Name
    [Byte]   Unused Flag (local_d)
    [Byte]   Map ID (local_e)
    [4 Bytes] Value (local_8) -> Converted to float
    """
    map_name: str = "tron"
    
    def serialize(self) -> bytes:
        pkt = PacketWriter()
        pkt.write_string(self.map_name) # Map Name
        pkt.write_byte(1)             # Unused Flag?
        pkt.write_byte(1)             # Map ID?
        pkt.write_fixed1616(1.0)      # Some float?
        return b'\x16' + pkt.get_bytes()
    
@dataclass
class TeamInfoPacket(Packet):
    """
    Packet 0x28: TEAM_INFO
    Matches decompilation of process_team_info:
      - Reads Byte (Team 1 ID)
      - Reads 5 Strings (Team 1 Data)
      - Reads Byte (Team 2 ID)
      - Reads 5 Strings (Team 2 Data)
    """

    def serialize(self) -> bytes:
        pkt = PacketWriter()
        # --- TEAM 1 (Red) ---
        pkt.write_byte(1)                        # ID
        pkt.write_string("Crimson_Federation")   # Name?
        pkt.write_string("Crimson Federation")   # Team Name
        pkt.write_string("Crimson Base")         # Base Name?
        pkt.write_string("The red team.")        # Description?
        pkt.write_string("Crimson Federation Wins!") # Win Message?

        # --- TEAM 2 (Blue) ---
        pkt.write_byte(2)                        # ID
        pkt.write_string("Azure_Alliance")       # Name?
        pkt.write_string("Azure Alliance")       # Team Name
        pkt.write_string("Crimson Base")         # Base Name?
        pkt.write_string("The blue team.")       # Description?
        pkt.write_string("Crimson Federation Wins!") # Win Message?
        return b'\x28' + pkt.get_bytes()
    
@dataclass
class PingRequestPacket(Packet):
    # PING_REQUEST 0x0B
    def serialize(self) -> bytes:
        pkt = PacketWriter()
        pkt.write_int32(get_ticks())
        return b'\x0B' + pkt.get_bytes()