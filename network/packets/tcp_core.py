from __future__ import annotations
from network.streams import PacketWriter

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
