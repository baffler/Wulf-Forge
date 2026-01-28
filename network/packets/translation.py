from __future__ import annotations
from dataclasses import dataclass, field
from network.streams import PacketWriter
from network.translation_config import GLOBAL_CONFIGS
from core.config import get_ticks
from network.packets.base import Packet 

@dataclass
class TranslationPacket(Packet):
    """
    Packet 0x32: TRANSLATION (Configuration)
    Configures the floating-point quantization table.
    """

    def serialize(self) -> bytes:
        pkt = PacketWriter()

        # Iterate through the Source of Truth
        for cfg in GLOBAL_CONFIGS:
            # 1. Fixed ID / Header Bits
            pkt.write_int32(cfg['head'])
            
            # 2. Padding (Ignored by client)
            pkt.write_int32(0)
            
            # 3. Max Total Bits (Resolution)
            pkt.write_int32(cfg['total'])
            
            # 4. Max Value (String)
            pkt.write_string(cfg['max'])
            
            # 5. Range Value (String)
            pkt.write_string(cfg['range'])
        
        # The client code calls Weapon_Slot_Constructor here
        # Then sends ACK2 (Command 0x33, Subcommand 2).
        
        return b'\x32' + pkt.get_bytes()