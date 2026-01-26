from __future__ import annotations
from network.streams import PacketWriter
from dataclasses import dataclass, field
from network.packets.base import Packet
from core.config import get_ticks

# ----------------------------
# HELLO / UDP LINK
# ----------------------------

def hello_udp_config(udp_port: int, ip_address: str) -> bytes:
    """
    Packet 0x13: HELLO (Subcmd 1 - UDP config)
      [0x13][0x01][int16 udp_port][int16 ip_count][string ip]
    """
    pkt = PacketWriter()
    pkt.write_byte(0x01)
    pkt.write_int16(udp_port)
    pkt.write_int16(1)
    pkt.write_string(ip_address)
    return b"\x13" + pkt.get_bytes()

def hello_final() -> bytes:
    """Packet 0x13: HELLO subcmd 3"""
    return b"\x13\x03"

def identified_udp() -> bytes:
    """Packet 0x4D: IDENTIFIED_UDP"""
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
class GameClockPacket(Packet):
    def serialize(self) -> bytes:
        print(f"[SEND] GAME_CLOCK 0x2F")
        pkt = PacketWriter()
        pkt.write_int32(get_ticks())
        pkt.write_byte(0x01) # Is active or enabled? not sure
        pkt.write_int32(1) # Maybe Phase flag (0 = Push, 1 = Glimpse), 0 or 1
        pkt.write_int32(30000) # Length of next Push/Glimpse (in Ms)
        return b'\x2F' + pkt.get_bytes()