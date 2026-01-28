# network/packets/hello_tcp.py
from __future__ import annotations
from dataclasses import dataclass
from enum import IntEnum
from network.packets.base import Packet
from network.streams import PacketWriter

# C#-style Enum for readability
class HelloSubCmd(IntEnum):
    VERSION_CHECK = 0x00
    UDP_CONFIG    = 0x01
    SESSION_KEY   = 0x02
    VERIFIED      = 0x03

@dataclass
class HelloPacket(Packet):
    """
    Packet 0x13: HELLO
    Multiplexed packet that handles Version, UDP setup, Auth, and Final ACK.
    """
    sub_cmd: int | HelloSubCmd
    
    # Optional fields (default values allow us to omit them when not needed)
    version: int = 0x4E89          # Default for SubCmd 0
    udp_port: int = 2627           # Default for SubCmd 1
    ip_address: str = "127.0.0.1"  # Default for SubCmd 1
    session_key: str = ""          # Default for SubCmd 2

    def serialize(self) -> bytes:
        print(f"[SEND] HELLO 0x13: {self.sub_cmd}")
        pkt = PacketWriter()
        
        # 1. Write the Sub-Command (Common to all)
        pkt.write_byte(self.sub_cmd)

        # 2. Branch based on Sub-Command
        if self.sub_cmd == HelloSubCmd.VERSION_CHECK:
            # [Int] Version
            pkt.write_int32(self.version) 
            
        elif self.sub_cmd == HelloSubCmd.UDP_CONFIG:
            # [Short] Port, [Short] Count, [String] IP
            pkt.write_int16(self.udp_port)
            pkt.write_int16(1) # IP Count (Hardcoded to 1 for now)
            pkt.write_string(self.ip_address)
            
        elif self.sub_cmd == HelloSubCmd.SESSION_KEY:
            # [String] Session Key
            pkt.write_string(self.session_key)
            
        elif self.sub_cmd == HelloSubCmd.VERIFIED:
            # No payload, just the sub-command
            pass

        return b'\x13' + pkt.get_bytes()

    # --- Factory Methods ---

    @classmethod
    def create_version(cls, version: int = 0x4E89) -> HelloPacket:
        return cls(sub_cmd=HelloSubCmd.VERSION_CHECK, version=version)

    @classmethod
    def create_udp_config(cls, port: int, host: str = "127.0.0.1") -> HelloPacket:
        return cls(sub_cmd=HelloSubCmd.UDP_CONFIG, udp_port=port, ip_address=host)

    @classmethod
    def create_key(cls, key: str) -> HelloPacket:
        return cls(sub_cmd=HelloSubCmd.SESSION_KEY, session_key=key)

    @classmethod
    def create_verified(cls) -> HelloPacket:
        return cls(sub_cmd=HelloSubCmd.VERIFIED)