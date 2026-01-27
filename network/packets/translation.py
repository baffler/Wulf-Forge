from __future__ import annotations
from dataclasses import dataclass, field
from network.streams import PacketWriter
from .packet_config import TankPacketConfig
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

        # --- CONFIGURATION DEFAULTS ---
        
        # 1. SCALARS (Indices 0-15)
        # Default for generic scalars: High precision, wide range just in case.
        # Format: (Precision_Header_Bits, Max_Total_Bits, Max_String, Range_String)
        scalar_configs = []
        default_scalar = (16, 0, "1000.0", "2000.0") 

        for _ in range(16):
            scalar_configs.append(default_scalar)

        # --- SCALAR OVERRIDES (Known Indices) ---

        # Index 1: Weapon ID 
        # Logic: Uses precision_header_bits to read a raw integer ID.
        # Setting to 5 bits (32 possible weapons). Max/Range are ignored by client.
        scalar_configs[1] = (5, 0, "0.0", "0.0")

        # Index 5: Health Multiplier
        # Logic: Reads X bits, then unpacks float 0.0-1.0.
        scalar_configs[5] = (10, 0, "1.0", "1.0")

        # Index 8: Energy Multiplier
        # Logic: Same as health.
        scalar_configs[8] = (10, 0, "1.0", "1.0")
        
        # Index 13 & 14: Extra Vital Stats (A & B)
        # Logic: Same as health.
        scalar_configs[13] = (8, 0, "1.0", "1.0")
        scalar_configs[14] = (8, 0, "1.0", "1.0")


        # 2. VECTORS (Indices 16-27)
        # Organized as 3 Banks of 4 Vectors (Pos, Vel, Rot, Spin).
        # Format: (Header_Bits, Max_Total_Bits, Max_String, Range_String)
        
        # Use the same "High Quality" config for all 3 banks for now (Testing Mode).
        # Position: Max 4096, Range 8192 (Min -4096)
        # Velocity: Max 200, Range 400 (Min -200) - Adjusted for likely speeds
        # Rotation: Max 1.0, Range 2.0 (Min -1.0)
        # Spin: Max 10.0, Range 20.0 (Min -10.0)
        
        vector_templates = [
            (4, 16, "4096.0", "8192.0"), # Slot 0: Position
            (4, 14, "200.0",  "400.0"),  # Slot 1: Velocity
            (4, 12, "1.0",    "2.0"),    # Slot 2: Rotation
            (4, 12, "10.0",   "20.0")    # Slot 3: Spin
        ]

        # --- WRITING THE PACKET ---

        # LOOP 1: Write Scalars (0-15)
        for i in range(16):
            cfg = scalar_configs[i]
            write_config_entry(pkt, cfg)

        # LOOP 2: Write Vector Banks (16-27)
        # 3 Banks (High, Med, Low Detail)
        for bank in range(3):
            # Inner Loop: 4 Vectors per Bank
            for vec_idx in range(4):
                # For now, we use the same template for all banks
                cfg = vector_templates[vec_idx]
                write_config_entry(pkt, cfg)
        
        # The client code calls Weapon_Slot_Constructor here
        # Then sends ACK2 (Command 0x33, Subcommand 2).
        
        return b'\x32' + pkt.get_bytes()
    
def write_config_entry(pkt, cfg):
    """Helper to write a single TranslationConfig entry"""
    fixed_bits, max_total, max_str, range_str = cfg
    
    # 1. Fixed ID Bits / Precision Header Bits
    pkt.write_int32(fixed_bits)
    
    # 2. Padding (The "Missing" Int)
    pkt.write_int32(0)
    
    # 3. Max Total Bits (Resolution)
    pkt.write_int32(max_total)
    
    # 4. Max Value (String)
    pkt.write_string(max_str)
    
    # 5. Range Value (String)
    pkt.write_string(range_str)