# network/packets.py
import struct
from config import Config, get_ticks
from .streams import PacketWriter
# We import compressors to ensure logic matches, though we might use raw bits 
from .compressor import COMPRESSOR_POS, COMPRESSOR_VEL

class PacketFactory:
    """
    Constructs raw packet bodies (OpCode + Payload).
    """

    # --- UDP TRANSPORT LAYER ---

    @staticmethod
    def udp_handshake(player_id):
        # Packet 0x03
        pkt = PacketWriter()
        pkt.write_int32(get_ticks())
        pkt.write_int32(player_id)
        
        # Stream Definitions (4 Streams)
        pkt.write_int32(4) 
        # 0: Unreliable, 1: Reliable, 2: Meta, 3: Game Data
        pkt.write_string("Unreliable"); pkt.write_int32(1); pkt.write_int32(0)
        pkt.write_string("Reliable");   pkt.write_int32(1); pkt.write_int32(1)
        pkt.write_string("Stream 2");   pkt.write_int32(1); pkt.write_int32(2)
        pkt.write_string("Game Data");  pkt.write_int32(1); pkt.write_int32(3)

        # Configs (Priorities)
        pkt.write_int32(4)
        for i in range(4):
            pkt.write_int32(i); pkt.write_int32(1)

        return b'\x03' + pkt.get_bytes()

    @staticmethod
    def udp_ack(subcmd):
        # Packet 0x02 (Generic / Handshake ACK)
        pkt = PacketWriter()
        pkt.write_byte(subcmd)
        pkt.write_int32(get_ticks())
        return b'\x02' + pkt.get_bytes()

    @staticmethod
    def udp_reliable_ack(sequence_num, packet_id):
        # Packet 0x02 (Standard ACK for reliable packets)
        pkt = PacketWriter()
        pkt.write_byte(0x01)       # SubCmd 1 (Standard ACK)
        pkt.write_byte(packet_id)  # The packet type we are ACKing
        pkt.write_int16(sequence_num)
        return b'\x02' + pkt.get_bytes()
        
    @staticmethod
    def udp_set_start(stream_id, seq):
        # Packet 0x04 (Unpause Stream)
        pkt = PacketWriter()
        pkt.write_byte(stream_id)
        pkt.write_int16(seq)
        return b'\x04' + pkt.get_bytes()
    
    @staticmethod
    def hello(subcmd, version=None, udp_port=None, session_key=None):
        pkt = PacketWriter()
        pkt.write_byte(subcmd)
        
        if subcmd == 0x00 and version is not None:
            pkt.write_int32(version)
        elif subcmd == 0x01 and udp_port is not None:
            pkt.write_int16(udp_port)
            pkt.write_int16(1) # IP Count
            pkt.write_string(Config.HOST)
        elif subcmd == 0x02 and session_key is not None:
            pkt.write_string(session_key)
            
        return b'\x13' + pkt.get_bytes()

    @staticmethod
    def login_status(code, is_donor=True):
        pkt = PacketWriter()
        pkt.write_byte(1 if is_donor else 0)
        pkt.write_byte(code)
        return b'\x22' + pkt.get_bytes()

    @staticmethod
    def motd(message):
        pkt = PacketWriter()
        pkt.write_string(message)
        return b'\x23' + pkt.get_bytes()

    @staticmethod
    def player_info(player_id, is_guest=False):
        # Packet 0x17
        pid = struct.pack(">I", player_id)
        flag = b'\x01' if is_guest else b'\x00'
        return b'\x17' + pid + flag

    @staticmethod
    def team_info():
        # Packet 0x28 - Hardcoded teams for now
        pkt = PacketWriter()
        # Team 1
        pkt.write_byte(1)
        pkt.write_string("Crimson Federation"); pkt.write_string("Red Team")
        pkt.write_string("Crimson Base"); pkt.write_string("The red team.")
        pkt.write_string("Azure Alliance Wins!")
        # Team 2
        pkt.write_byte(2)
        pkt.write_string("Azure Alliance"); pkt.write_string("Blue Team")
        pkt.write_string("Crimson Base"); pkt.write_string("The blue team.")
        pkt.write_string("Crimson Federation Wins!")
        return b'\x28' + pkt.get_bytes()

    @staticmethod
    def world_stats():
        # Packet 0x16
        pkt = PacketWriter()
        pkt.write_string("survival")      # Map Name
        pkt.write_byte(1)               # Unused
        pkt.write_byte(1)               # Map ID
        pkt.write_fixed1616(1.0)        # Value
        return b'\x16' + pkt.get_bytes()

    @staticmethod
    def game_clock():
        # Packet 0x2F
        pkt = PacketWriter()
        pkt.write_int32(get_ticks())
        pkt.write_byte(0x01)   # Active
        pkt.write_int32(1)     # Phase
        pkt.write_int32(30000) # Length
        return b'\x2F' + pkt.get_bytes()

    @staticmethod
    def add_to_roster(account_id, name, nametag, team):
        # Packet 0x1A
        pkt = PacketWriter()
        pkt.write_int32(account_id)
        pkt.write_int32(team)
        pkt.write_int16(0); pkt.write_int16(0) # Kills/Deaths placeholder
        pkt.write_string(name)
        pkt.write_string(nametag)
        pkt.write_int16(0); pkt.write_int16(0)
        pkt.write_fixed1616(0.0) # Score
        pkt.write_int32(0)
        return b'\x1A' + pkt.get_bytes()
    
    @staticmethod
    def update_stats(account_id, team_id):
        # Packet 0x1C
        pkt = PacketWriter()
        pkt.write_int32(account_id)
        pkt.write_int32(6); pkt.write_int16(team_id); pkt.write_int16(33)
        pkt.write_int16(3); pkt.write_int16(5); pkt.write_int16(9)
        pkt.write_fixed1616(100.0); pkt.write_fixed1616(100.0)
        pkt.write_int32(10)
        return b'\x1C' + pkt.get_bytes()

    @staticmethod
    def tank_packet(net_id, unit_type, pos, vel, flags=1, no_stats=False):
        # Packet 0x18
        pkt = PacketWriter()
        pkt.write_int32(get_ticks())
        
        # Vital Stats Block
        has_stats = 0 if no_stats else 1
        pkt.write_bits(has_stats, 1)
        
        if has_stats:
            pkt.write_bits(0, 5)    # Weapon ID
            pkt.write_bits(1, 10)   # Health 100%
            pkt.write_bits(1, 10)   # Energy 100%

        pkt.write_int32(unit_type)
        pkt.write_int32(net_id)
        pkt.write_byte(flags)
        pkt.write_vector3(*pos)
        pkt.write_vector3(*vel)
        
        return b'\x18' + pkt.get_bytes()

    @staticmethod
    def behavior():
        # Packet 0x24 - The Big One. Ported from your main.py logic.
        pkt = PacketWriter()
        
        # -- Header --
        pkt.write_byte(0) # spawn_related
        pkt.write_fixed1616(5.0); pkt.write_fixed1616(100.0)
        pkt.write_fixed1616(100.0); pkt.write_fixed1616(100.0)
        pkt.write_fixed1616(100.0)
        pkt.write_int32(20)    # TeamSize
        pkt.write_int32(25000); pkt.write_int32(35000) # Timers
        pkt.write_fixed1616(100.0)
        pkt.write_int32(1); pkt.write_int32(1)
        pkt.write_fixed1616(1.0)
        
        for _ in range(11): pkt.write_fixed1616(1.0) # 11 Floats
        pkt.write_byte(1); pkt.write_byte(1) # Flags
        
        # -- Weapon Configs (4 Units * 13 Slots) --
        for u in range(4):
            for i in range(13):
                pkt.write_byte(0); pkt.write_byte(0); pkt.write_byte(0)
                pkt.write_byte(0); pkt.write_byte(0) # 5 Bools
                pkt.write_fixed1616(1.0) # Targeting Cone
                pkt.write_int32(0); pkt.write_int32(0); pkt.write_int32(0)
                pkt.write_int32(0); pkt.write_int32(0) # 5 Ints
                pkt.write_fixed1616(100.0); pkt.write_fixed1616(1000.0)
                pkt.write_fixed1616(500.0); pkt.write_fixed1616(1.0) # 4 Floats
                
        # -- Entity Definitions (39 Units) --
        for i in range(39):
            pkt.write_fixed1616(1.0); pkt.write_fixed1616(100.0); pkt.write_int32(100)
            
        # -- Vehicle Physics (2 Vehicles) --
        for c in range(2):
            pkt.write_fixed1616(20.0); pkt.write_fixed1616(4.0)
            pkt.write_int32(700); pkt.write_int32(550)
            pkt.write_fixed1616(1.0); pkt.write_fixed1616(0.2); pkt.write_fixed1616(2.0)
            pkt.write_int32(0); pkt.write_int32(33000)

        # -- Hardpoints (Helper Function Logic Inline) --
        # Tank (Weapons 0, Thrusters 0), Scout (Weapons 0, Thrusters 0)
        for _ in range(4):
            pkt.write_int32(0) # Count
            pkt.write_fixed1616(0.0) # Property Value

        # -- Active Vehicle Physics (3 Vehicles) --
        for _ in range(3):
            pkt.write_fixed1616(4.5); pkt.write_fixed1616(85.0)
            pkt.write_fixed1616(69.7); pkt.write_fixed1616(80.0)
            pkt.write_fixed1616(2000.0); pkt.write_fixed1616(3.25)
            pkt.write_fixed1616(1.0)
            
        # Padding to hit target size (Optional, but good for safety)
        # Your previous code padded to 3116. PacketWriter auto-sizes, so we assume OK.
        # If strict size needed:
        current_len = len(pkt.get_bytes())
        if current_len < 3116: pkt.write_bytes(b'\x00' * (3116 - current_len))

        return b'\x24' + pkt.get_bytes()

    @staticmethod
    def process_translation():
        # Packet 0x32
        pkt = PacketWriter()
        # Scalars (0-15)
        defaults = [(16, 0, "1000.0", "2000.0")] * 16
        # Specific overrides
        defaults[1] = (5, 0, "0.0", "0.0") # Weapon ID
        defaults[5] = (10, 0, "1.0", "1.0") # Health
        defaults[8] = (10, 0, "1.0", "1.0") # Energy
        defaults[13] = (8, 0, "1.0", "1.0")
        defaults[14] = (8, 0, "1.0", "1.0")
        
        for cfg in defaults:
            pkt.write_int32(cfg[0]); pkt.write_int32(0)
            pkt.write_int32(cfg[1])
            pkt.write_string(cfg[2]); pkt.write_string(cfg[3])
            
        # Vectors (16-27)
        vec_templates = [
            (4, 16, "4096.0", "8192.0"), # Pos
            (4, 14, "200.0", "400.0"),   # Vel
            (4, 12, "1.0", "2.0"),       # Rot
            (4, 12, "10.0", "20.0")      # Spin
        ]
        for bank in range(3):
            for t in vec_templates:
                pkt.write_int32(t[0]); pkt.write_int32(0)
                pkt.write_int32(t[1])
                pkt.write_string(t[2]); pkt.write_string(t[3])
                
        return b'\x32' + pkt.get_bytes()

    @staticmethod
    def chat_message(msg, source_id=0, target_id=0):
        # Packet 0x1F
        pkt = PacketWriter()
        pkt.write_int16(0) # Target Type
        pkt.write_int32(target_id)
        pkt.write_int16(0) # Source Type
        pkt.write_int32(source_id)
        pkt.write_string(msg)
        return b'\x1F' + pkt.get_bytes()