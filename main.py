import sys
import time
import socket
import struct
import threading
import struct

from network.streams import PacketWriter, PacketReader
from network.udp_handler import UDPHandler

HOST = "127.0.0.1"
PORT = 2627
SESSION_KEY = "WulframSessionKey123"

udp_sock = None

startedRepairHeartbeat = False

# --- EVENT FLAGS ---
# This is how the UDP thread tells the Main thread "I heard the client!"
udp_root_received = threading.Event()

udp_client_addr = None
udp_client_addr_lock = threading.Lock()

def to_fixed(value):
    return int(round(value * 65536.0))

# TODO: put in a helper module
SERVER_START = time.monotonic()

def get_ticks():
    return int((time.monotonic() - SERVER_START) * 1000) & 0xFFFFFFFF

# --- 1. Pretty Print / Logging Helpers ---

# UDP: This is what the server receives and will process (Client -> Server)
def get_udp_packet_name_recv(type_byte):
    names = {
        0x02: "D_ACK",
        0x03: "D_HANDSHAKE",
        0x08: "HELLO_ACK (UDP)",
        0x09: "ACTION_DUMP (UDP)",
        0x0A: "ACTION_UPDATE (UDP)",
        0x0B: "PING_REQUEST (UDP)",
        0x0C: "WEAPONS? (UDP)",
        0x0D: "ACK_WPNS? (UDP)",
        0x0E: "PRIORITY2? (UDP)",
        0x10: "RESENDS? (UDP)",
        0x11: "UNKNOWN? (0x11 UDP)",
        0x12: "GRAPH_REPONSE? (UDP)",
        0x13: "SESSION_KEY (UDP)",
        0x14: "IGNORE? (UDP)",
        0x19: "TANK_RESEND_REQUEST (UDP)",
        0x36: "STRING_VALUE (UDP)",
        0x40: "??? (UDP)",
        0x4C: "ROUTING_PING (UDP)"
    }
    return names.get(type_byte, "UNKNOWN NOT LISTED (UDP)")

# UDP: This is what the server sends and the client will process (Server -> Client)
def get_udp_packet_name_send(type_byte):
    names = {
        0x08: "D_HANDSHAKE (UDP)",
        0x09: "ROOT (UDP)",
        0x0A: "VOICE (UDP)",
        0x0B: "PRIORITY (UDP)",
        0x0C: "WEAPONS (UDP)",
        0x0D: "ACK_WPNS (UDP)",
        0x0E: "PRIORITY2 (UDP)",
        0x10: "RESENDS (UDP)",
        0x11: "UNKNOWN (0x11 UDP)",
        0x12: "GRAPH_REPONSE (UDP)",
        0x13: "GRAPH_DATA",
        0x14: "IGNORE",
    }
    return names.get(type_byte, "UNKNOWN NOT LISTED (UDP)")
    

def get_packet_name(type_byte):
    # Unsure of these...
    #   FUN_00509ac0(0x20,3); (0x25,3); (0x26,1); (0x2b,1); (0x2e,3);(0x35,1);
    #   FUN_00509ac0(0x3a,3); (0x3b,3); (0x33,3); (0x19,1); (0x40,0); (0x42,3);
    #   FUN_00509ac0(0x46,3); (0x49,3); (0x4a,3); (0x4f,3);
    
    # 0-7 = Service Layer Events?
    names = {
        0x00: "STREAM_CHECK (0x00 TCP)",
        0x01: "D_IGNORE (0x01 TCP)",
        0x02: "D_ACK (0x02 TCP)",
        0x03: "UNKNOWN (0x03 TCP)",
        0x04: "D_SET_START (0x04 TCP)",
        0x05: "UNKNOWN (0x05 TCP)",
        0x06: "UNKNOWN (0x06 TCP)",
        0x07: "UNKNOWN (0x07 TCP)",
        0x08: "ROOT (TCP)",
        0x09: "ACTION_DUMP (Client?) (0x09 TCP)",
        0x0A: "ACTION_UPDATE (Client?) (0x0A TCP)",
        0x0B: "PING_REQUEST",
        0x0C: "PING",
        0x0D: "TRANSIENT_ARRAY",
        0x0E: "UPDATE_ARRAY",
        0x0F: "VIEW_UPDATE",
        0x10: "RESENDS? (TCP)",
        0x11: "HUD_MESSAGE",
        0x12: "LAG_FIX",
        0x13: "HELLO (TCP)",
        0x14: "HIDE_OBJECT",
        0x15: "DELETE_OBJECT",
        0x16: "WORLD_STATS",
        0x17: "PLAYER",
        0x18: "TANK",
        0x19: "TANK_RESEND_REQUEST (Client?) (0x19 TCP)",
        0x1A: "ADD_TO_ROSTER",
        0x1B: "REMOVE_FROM_ROSTER",
        0x1C: "UPDATE_STATS",
        0x1D: "DEATH_NOTICE",
        0x1E: "BIRTH_NOTICE",
        0x1F: "COMM_MESSAGE",
        0x20: "COMM_MESSAGE_REQUEST (Client?) (0x20 TCP)",
        0x21: "LOGIN_REQUEST (SERVER)",
        0x22: "LOGIN_STATUS",
        0x23: "MOTD",
        0x24: "BEHAVIOR",
        0x25: "REINCARNATE",
        0x26: "UNKNOWN (RETARGET?) (Client?) (0x26 TCP)",
        0x27: "SHIP_STATUS",
        0x28: "TEAM_INFO",
        0x29: "CARRYING_INFO",
        0x2A: "UPLINK_INFO",
        0x2B: "DROP_REQUEST (Client?) (0x2B TCP)",
        0x2C: "SPACEMAP_UPDATE",
        0x2D: "SUPPLY_SHIP_INFO",
        0x2E: "WEAPON_DEMAND (Client?) (0x2E TCP)",
        0x2F: "GAME_CLOCK",
        0x30: "WARP_STATUS",
        0x31: "CONTINUOUS_SOUND",
        0x32: "PROCESS_TRANSLATION",
        0x33: "ACK2 (0x33 TCP)",
        0x34: "MODEM",
        0x35: "UNKNOWN (VIEWPOINT_INFO?) (Client?) (0x35 TCP)",
        0x36: "STRING_VALUE",
        0x37: "VERSION_ERROR",
        0x38: "DOCKING",
        0x39: "WANT_UPDATES",
        0x3A: "BEACON_REQUEST (Beacon Stream?) (Client?) (0x3A TCP)",
        0x3B: "BEACON_MODIFY (Beacon Stream?) (Client?) (0x3B TCP)",
        0x3C: "BEACON_STATUS (Client?) (0x3C TCP)",
        0x3D: "BEACON_DELETE (Client?) (0x3D TCP)",
        0x3E: "LOAD_STATUS",
        0x3F: "RESET_GAME",
        0x40: "UNKNOWN (0x40 TCP)",
        0x41: "SHUTDOWN",
        0x42: "SQUAD_CREATE (0x42 TCP)",
        0x43: "SQUAD_RESULT (0x43)",
        0x44: "SQUAD_DEFINITION (0x44)",
        0x45: "SQUAD_DEFINITION (0x45)",
        0x46: "SQUAD_INVITE (0x46)",
        0x47: "SQUAD_OUST (0x47 TCP)",
        0x48: "SQUAD_INVITE_REMOVAL (0x48)",
        0x49: "SQUAD_ANSWER_INVITE (0x49 TCP)",
        0x4A: "SQUAD_COMMAND (0x4A TCP)",
        0x4B: "REQUEST_ACCOUNT_HANDLE",
        0x4C: "ROUTING_PING",
        0x4D: "IDENTIFIED_UDP",
        0x4E: "BPS~",
        0x4F: "KUDOS",
        0x50: "MILTAB",
        0x51: "VOICE_RESP",
        0x52: "LOGIN_INFO",
        0x53: "VIDEO_MSG",
        0x55: "DEBUG_COORDS (Client?)",
    }
    return names.get(type_byte, "UNKNOWN NOT LISTED (TCP)")

def log_packet(direction, payload, show_ascii=True):
    """
    Pretty prints a packet payload.
    direction: "SEND" or "RECV"
    payload: The raw bytes of the packet body (Type + Data)
    """
    if not payload:
        return

    pkt_type = payload[0]
    pkt_len = len(payload) + 2 # +2 for the header we don't see here
    pkt_name = get_packet_name(pkt_type)
    
    # Pack the length into 2 bytes, Big-Endian (>H)
    header = struct.pack(">H", pkt_len)
    hex_str = header.hex().upper() + payload.hex().upper()
    
    # ASCII decoding: Replace non-printable chars with '.'
    ascii_str = ""
    if show_ascii:
        safe_chars = []
        for byte in payload:
            if 32 <= byte <= 126: # Printable ASCII range
                safe_chars.append(chr(byte))
            else:
                safe_chars.append('.')
        ascii_str = "".join(safe_chars)
        
    # Format the output
    print(f"[{direction}] {pkt_name:<12} (0x{pkt_type:02X}) | Len={pkt_len:<3} | Body={hex_str}")
    if show_ascii:
        print(f"       Ascii='{ascii_str}'")
    print("-" * 60)

# --- 2. Helper Function to Send Any Packet ---
def send_packet(sock: socket.socket, payload: bytes, show_ascii=True, do_log=True):
    """
    Wraps a raw payload with the 2-byte Big-Endian length header 
    and sends it to the client.
    """
    try:
        # Calculate total length (Header is 2 bytes + Body length)
        packet_len = len(payload) + 2
        
        # Pack the length into 2 bytes, Big-Endian (>H)
        header = struct.pack(">H", packet_len)
        
        # Send Header + Body
        sock.sendall(header + payload)
        
        # Log it using our new function
        if do_log:
            log_packet("SEND", payload, show_ascii)
    except socket.error as e:
        print(f"[ERROR] Failed to send packet: {e}")
    
def handle_hello_packet(sock, body: bytes) -> bool:
    """
    Returns True if handled (and caller should keep waiting for login packets).
    body includes: [type][...]
    """
    if len(body) < 2:
        return False

    pkt_type = body[0]
    if pkt_type != 0x13:
        print("ERROR!! handle_hello_packet: packet type != 0x13")
        return False

    subcmd = body[1]

    # HELLO subcmd 0: Version
    if subcmd == 0x00:
        if len(body) >= 6:
            version = struct.unpack(">I", body[2:6])[0]
            print(f">>> Client HELLO(version) = 0x{version:08X}")
            # Optionally enforce version here
        else:
            print(">>> Client HELLO(version) malformed")
        # You can optionally re-send your server hello here, but usually not required:
        # send_hello(sock)
        return True

    # HELLO subcmd 1: UDP config request/ack (depends on protocol)
    if subcmd == 0x01:
        print(">>> Client HELLO(UDP) received")
        return True

    # HELLO subcmd 2: Session key request (this is the one you're missing)
    if subcmd == 0x02:
        print(">>> Client HELLO(SessionKey request) -> sending hello_key now")
        send_hello_key(sock)
        return True

    print(f">>> Client HELLO unknown subcmd=0x{subcmd:02X}")
    return True
        
def send_packet_udp(sock: socket.socket, addr: tuple, payload: bytes, show_ascii=True):
    """
    Wraps a raw payload with the 2-byte Big-Endian length header 
    and sends it to the specific UDP address.
    """
    try:
        # Calculate total length (Header is 2 bytes + Body length)
        packet_len = len(payload) + 2
        
        # Pack the length into 2 bytes, Big-Endian (>H)
        header = struct.pack(">H", packet_len)
        
        # Send Header + Body via UDP
        sock.sendto(header + payload, addr)
        
        # Log it (distinguish as UDP-SEND)
        log_packet("UDP-SEND", payload, show_ascii)
        
    except Exception as e:
        print(f"[ERROR] UDP Send failed: {e}")

# --- 3. Specific Packet Functions ---

# === UDP ===
"""
def handle_d_handshake(sock, addr, data):
    #Parses Client's D_HANDSHAKE (0x03) and replies with D_ACK (0x02).
    print(f"\n[UDP] Processing D_HANDSHAKE (0x03) from {addr}...")
    
    # We need a Reader to parse the incoming data
    # (Assuming you have a PacketReader class similar to PacketWriter)
    reader = PacketReader(data) # Skip the 0x03 type byte if your reader doesn't
    
    try:
        # 1. Timestamp / Sequence
        timestamp = reader.read_int32()
        
        # 2. Connection ID (Session)
        conn_id = reader.read_int32()
        
        # 3. Stream Definitions
        stream_count = reader.read_int32()
        print(f"    > Timestamp: {timestamp}, ConnID: {conn_id}, Streams: {stream_count}")
        
        for _ in range(stream_count):
            stream_name = reader.read_string()
            id_count = reader.read_int32()
            
            # Skip the IDs (we don't strictly need them to emulate the server)
            # The client sends a list of Packet IDs belonging to this stream
            for _ in range(id_count):
                reader.read_int32() 
                
            print(f"    > Stream: '{stream_name}' (IDs: {id_count})")
            
        # 4. Initial Sequence Numbers (We can mostly ignore this for emulation)
        seq_count = reader.read_int32()
        # ... logic to read seqs would go here ...
        
        print("[UDP] D_HANDSHAKE Parsed. Sending D_ACK...")
        send_d_ack(sock, addr)
        
    except Exception as e:
        print(f"[ERROR] Failed to parse D_HANDSHAKE: {e}")
        # Send ACK anyway to try and force the connection
        send_d_ack(sock, addr)

"""

def send_d_ack_WIP(sock, addr):
    """
    Packet 0x02: D_ACK (UDP)
    Response to D_HANDSHAKE.
    Structure: [Type 0x02] [Byte: 0] [Int32: Timestamp]
    """
    pkt = PacketWriter()
    
    # 1. Status Byte (0 = OK)
    pkt.write_byte(0)
    
    # 2. Server Timestamp (Milliseconds)
    tick = get_ticks()
    pkt.write_int32(tick)
    
    payload = b'\x02' + pkt.get_bytes()
    
    # Send via UDP
    # Note: Use your existing send_packet_udp wrapper if available
    sock.sendto(payload, addr)
    print(f"[UDP] Sent D_ACK (0x02) to {addr}")

"""
def send_udp_d_handshake(udpsock: socket.socket, addr: tuple):
    #Handshake-layer D_HANDSHAKE (UDP). We don't know the full payload format yet
    
    val_param = struct.pack(">I", 1000)
    
    payload = b'\x08' + val_param
    
    udpsock.sendto(payload, addr)
    print(f"[UDP] SEND -> {addr} HELLO_ACK (0x08) Len={len(payload)}")
"""

# === TCP ===
def send_login_status(sock: socket.socket, code: int, is_donor: bool):
    """
    Sends packet 0x22 (Login Status).
    Structure: [22] [DonorFlag] [StatusCode]
    """
    packet_type = b'\x22'
    
    # Convert bool to 1 or 0, then pack as a single byte
    donor_byte = struct.pack("B", 1 if is_donor else 0)
    
    # Pack the status code as a single byte
    code_byte = struct.pack("B", code)
    
    # Combine them
    payload = packet_type + donor_byte + code_byte
    
    send_packet(sock, payload)
    
def send_motd(sock, message):
    """
    Packet 0x23: MOTD
    Format: [Type 0x23] [String]
    """
    pkt = PacketWriter()
    pkt.write_string(message)
    
    payload = b'\x23' + pkt.get_bytes()
    send_packet(sock, payload)
    
def send_world_stats(sock):
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
    pkt = PacketWriter()
    
    pkt.write_string("tron")      # Map Name
    pkt.write_byte(1)             # Unused Flag (local_d)
    pkt.write_byte(1)             # Map ID (local_e)
    pkt.write_int32(100)          # Value (local_8)
    
    payload = b'\x16' + pkt.get_bytes()
    send_packet(sock, payload)
   
def send_tank_packet(sock, net_id, unit_type, pos, vel, flags=1):
    print(f"[SEND] TANK (0x18) ID={net_id} Type={unit_type}")
    
    pkt = PacketWriter()

    pkt.write_int32(1337) # Player ID
    
    # 2. Optional Header (1 Bit)
    pkt.write_bits(0, 1) 
    
    # 3. Unit Type (Int32) - Note: This will handle the unaligned write internally!
    pkt.write_int32(unit_type)
    
    # 4. Net ID (Int32)
    pkt.write_int32(net_id)
    
    # 5. Flags (Byte)
    pkt.write_byte(flags)
    
    # 6. Position (Vector3 - Fixed 16.16)
    pkt.write_vector3(pos[0], pos[1], pos[2])
    
    # 7. Velocity (Vector3 - Fixed 16.16)
    pkt.write_vector3(vel[0], vel[1], vel[2])
    
    # Get the final aligned bytes
    payload = b'\x18' + pkt.get_bytes()
    
    send_packet(sock, payload)
    

def send_repair_packet_WIP(sock):
    """
    Packet 0x0E: UPDATE_ARRAY (Repair)
    Updates Entity 1337 with 100% Health and Energy.
    """
    print("[SEND] UPDATE_ARRAY (0x0E) - Sending REPAIR...")
    pkt = PacketWriter()
    
    # --- HEADER ---
    # 1. PlayerID / Tick Count (Int32)
    pkt.write_int32(1337)
    
    # 2. Turret State Header (1 Bit)
    # 0 = No turret data follows.
    pkt.write_bits(0, 1)
    
    # 3. Entity Count (8 Bits)
    # We are updating 1 entity.
    pkt.write_bits(1, 8)
    
    # --- ENTITY 1 ---
    
    # 4. Net ID (Int32)
    # Since PacketWriter handles bits, this writes 32 bits into the stream.
    pkt.write_int32(1337)
    
    # 5. Flag A (1 Bit)
    pkt.write_bits(0, 1)
    
    # 6. Update Mask (10 Bits)
    # We want Bit 5 (Energy) and Bit 7 (Health).
    # Mask: 0010100000 (Binary) = 160 (Decimal)
    # We leave Bit 0 (Physics) OFF to avoid sending position data.
    mask = (1 << 5) | (1 << 7)
    pkt.write_bits(mask, 10)
    
    # 7. Input ID (5 Bits) - [CRITICAL]
    # The code reads an index for the Input Table. 
    # Since you have ~28 inputs, this is likely 5 bits.
    #pkt.write_bits(0, 8) 
    
    # --- DATA PAYLOAD ---
    # The read order is determined by the mask (Right to Left / LSB to MSB)
    
    # Bit 5: Energy (8 Bits)
    # Sending 255 = 100% (or Max defined in Behavior packet)
    pkt.write_bits(255, 8)
    
    # Bit 7: Health (8 Bits)
    # Sending 255 = 100%
    pkt.write_bits(255, 8)
    
    payload = b'\x0E' + pkt.get_bytes()
    #send_packet(sock, payload)
    #send_packet_udp(sock, udp_client_addr, payload)

def send_update_array_empty(sock):
    """
    Packet 0x0E: UPDATE_ARRAY (Empty)
    """
    pkt = PacketWriter()
    
    tick = get_ticks()
    pkt.write_int32(tick)         # Sequence/Tick
    
    pkt.write_bits(0, 1)          # Optional Header Flag (0)
    pkt.write_bits(0, 8)          # Entry Count (0) -> Empty List
    
    payload = b'\x0E' + pkt.get_bytes()
    
    # Debug view
    # bin_str = "_".join(f"{b:08b}" for b in payload)
    # print(f"[DEBUG] UpdateArray Payload (Bits) ={bin_str}")

    send_packet(sock, payload)

def send_update_stats(sock, account_id, team_id=1):
    """
    Packet 0x1C: UPDATE_STATS

    Wire Structure (from process_update_stats):
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

    All fields have defaults so you can change only what you need.
    """
    pkt = PacketWriter()
    
    pkt.write_int32(account_id)
    pkt.write_int32(6)            # Unknown Int 1
    pkt.write_int16(team_id)      # Team ID
    pkt.write_int16(33)           # Unknown Short 1
    
    # 3 Stats (Shorts)
    pkt.write_int16(3)
    pkt.write_int16(5)
    pkt.write_int16(9)
    
    # Fixed Point values
    pkt.write_fixed1616(100.0)
    pkt.write_fixed1616(100.0)
    
    pkt.write_int32(10)           # Extra / Flags
    
    payload = b'\x1C' + pkt.get_bytes()
    send_packet(sock, payload)

def send_team_info(sock):
    """
    Packet 0x28: TEAM_INFO
    Matches decompilation of process_team_info:
      - Reads Byte (Team 1 ID)
      - Reads 5 Strings (Team 1 Data)
      - Reads Byte (Team 2 ID)
      - Reads 5 Strings (Team 2 Data)
    """

    pkt = PacketWriter()

    # --- TEAM 1 (Red) ---
    pkt.write_byte(1)                        # ID
    pkt.write_string("Crimson Federation")   # Name
    pkt.write_string("Red Team")             # Team Name
    pkt.write_string("Crimson Base")         # Base Name
    pkt.write_string("The red team.")        # Description
    pkt.write_string("Azure Alliance Wins!") # Win Message

    # --- TEAM 2 (Blue) ---
    pkt.write_byte(2)                        # ID
    pkt.write_string("Azure Alliance")       # Name
    pkt.write_string("Blue Team")            # Team Name
    pkt.write_string("Crimson Base")         # Base Name
    pkt.write_string("The blue team.")       # Description
    pkt.write_string("Crimson Federation Wins!") # Win Message

    payload = b'\x28' + pkt.get_bytes()
    send_packet(sock, payload)

def send_add_to_roster(sock, account_id, name, nametag="DEV", team=2):
    """
    Packet 0x1A: ADD_TO_ROSTER
    """
    print(f"[SEND] ADD_TO_ROSTER (0x1A) - Adding {name}")
    pkt = PacketWriter()

    pkt.write_int32(account_id)
    pkt.write_int32(team)
    pkt.write_int16(3)           # kills
    pkt.write_int16(5)            # unk14, deaths
    pkt.write_string(name)
    pkt.write_string(nametag)
    pkt.write_int16(7)           # kills?
    pkt.write_int16(2)            # deaths?
    pkt.write_fixed1616(6.7)      # Score
    pkt.write_int32(9)            # ?

    payload = b'\x1A' + pkt.get_bytes()
    send_packet(sock, payload)

def send_player_info(sock):
    """
    Packet 0x17: PLAYER
    [Type 0x17]
    [4 Bytes] Player ID (local_4)
    [1 Byte]  Is Guest?
    """
    
    # 1. Player ID (4 Bytes) - Use struct.pack(">I") for Big-Endian Int
    # Let's give ourselves ID 1
    player_id = struct.pack(">I", 1337)
    
    # 2. Flag (1 Byte) - local_5
    # The code says: DAT_005b8393 = local_5 != '\0';
    # This sets a global boolean. 0 (User) 1 (Guest)
    player_guest_flag = b'\x00'

    payload = b'\x17' + player_id + player_guest_flag
    send_packet(sock, payload)
    
def send_login_info(sock):
    """
    Packet 0x52 (82): Seems to be something about if you can't login, like banned
    Structure from process_login_info:
    [String] Username (DAT_00678c5c)
    [Int]    User ID (DAT_00678c58)
    [Int]    Permissions? (DAT_00678c60)
    [String] Message (DAT_00678c64)
    """
    pkt = PacketWriter()
    
    pkt.write_string("baff")
    pkt.write_int32(1337)         # User ID
    pkt.write_int32(0)            # Permissions
    pkt.write_string("YOU ARE BANNED")
    
    payload = b'\x52' + pkt.get_bytes()
    send_packet(sock, payload)

def send_hello_final(sock):
    """
    Packet 0x13: HELLO
    Case 3: Verified
    Structure: [Type 0x13] [SubCmd 0x03]
    """

    # SubCmd = 3
    subcmd = b'\x03'
    
    payload = b'\x13' + subcmd
    send_packet(sock, payload)

def send_hello(sock):
    """
    Packet 0x13: HELLO
    Case 0: Version Check
    Structure: [Type 0x13] [SubCmd 0x00] [Int: Version]
    """

    # SubCmd = 0
    subcmd = b'\x00'
    # Version = 0x4E89 (20105) from your decompilation
    version = struct.pack(">i", 0x4E89)
    
    payload = b'\x13' + subcmd + version
    send_packet(sock, payload)
    
def send_hello_key(sock):
    """
    Packet 0x13: HELLO (Subcommand 2 - Encryption/Session Setup)
    Structure: [Type 0x13] [SubCmd 0x02] [String: SessionKey]
    """
    pkt = PacketWriter()
    
    pkt.write_byte(0x02)          # SubCmd
    pkt.write_string(SESSION_KEY)
    
    payload = b'\x13' + pkt.get_bytes()
    send_packet(sock, payload)
    
def send_hello_udp(sock, udp_port, ip_address="127.0.0.1"):
    """
    Packet 0x13: HELLO (Subcmd 1 - UDP Configuration)
    Structure:
    [Type 0x13]
    [SubCmd 0x01]
    [Short] UDP Port (e.g., 2627)
    [Short] Count (Number of IPs)
    [String] IP Address
    """
    print(f"[SEND] HELLO UDP Config (0x13) - SubCmd 1 (UDP Config: {ip_address}:{udp_port})")
    pkt = PacketWriter()
    
    pkt.write_byte(0x01)          # SubCmd
    pkt.write_int16(udp_port)
    pkt.write_int16(1)            # IP Count
    pkt.write_string(ip_address)
    
    payload = b'\x13' + pkt.get_bytes()
    send_packet(sock, payload)

def send_identified_udp(sock):
    print("[SEND] IDENTIFIED_UDP (0x4D) - Link Confirmed")
    payload = b'\x4D' 
    send_packet(sock, payload)

def send_bps_reply(sock, requested_rate):
    """
    Packet 0x4E: BPS_RESPONSE
    Structure from process_bps_request:
    [Type 0x4E]
    [Int32] Rate Value (local_4) - We echo back the requested rate
    [Byte]  Approved (local_5)   - We send 1 (True) to bypass the paywall
    """
    print(f"[SEND] BPS_RESPONSE (0x4E) - Approving Rate {requested_rate}")
    
    # 1. Rate (4 Bytes)
    rate_bytes = struct.pack(">I", requested_rate)
    
    # 2. Approved Flag (1 Byte) - CRITICAL: Must be 1
    approved_flag = b'\x01'
    
    payload = b'\x4E' + rate_bytes + approved_flag
    send_packet(sock, payload)
    
def send_account_request(sock):
    """
    Packet 0x4b: REQUEST_ACCOUNT_HANDLE
    Structure: [Type] [String: Prompt]
    """
    pkt = PacketWriter()
    pkt.write_string("Please Login")
    
    payload = b'\x4b' + pkt.get_bytes()
    send_packet(sock, payload)

def send_chat_message(sock, message, source_id=0, target_id=0):
    """
    Sends a chat message to the client using the structure found in process_comm_message.
    Structure: [Short] [Int] [Short] [Int] [String]
    """
    print(f"[SEND] Sending Chat (0x20): '{message}'")
    pkt = PacketWriter()
    
    pkt.write_int16(0)            # Target Type
    pkt.write_int32(target_id)
    pkt.write_int16(0)            # Source Type
    pkt.write_int32(source_id)
    pkt.write_string(message)
    
    payload = b'\x1F' + pkt.get_bytes()
    send_packet(sock, payload)
    
def send_reincarnate(sock, code: int, message: str):
    """
    Sends the Reincarnate response (Server -> Client).
    Structure: [OpCode 0x25] [Byte code] [String message]
    
    Recv: (Client ->) [0x25] [int (Team ID)] [int (?)]
    """
    print(f"[SEND] Sending ReIncarnate (0x25): code={code} '{message}'")
    pkt = PacketWriter()
    
    pkt.write_byte(code)
    pkt.write_string(message)
    
    payload = b'\x25' + pkt.get_bytes()
    send_packet(sock, payload)


import struct

def send_behavior_packet(sock):
    """
    Packet 0x24: BEHAVIOR_UPDATE
    Target Size: 3116 bytes (Payload)
    """
    print("[SEND] Behavior Packet (0x24) - Robust Structure...")
    packet_type = b'\x24'

    # --- SECTION 1: HEADER (123 Bytes) ---
    # Based on your previous snippet
    # [Byte] [5 Dbl] [3 Int] [1 Dbl] [2 Int] [1 Dbl] [11 Flt] [Byte] [Byte]
    h_flag0 = b'\x00' # some kind of team switch or spawn flag, it checks if != 0
    # 1: Construction Timeout
    # 2: Unknown
    # 3: Velocity?
    # 4: 
    h_doubles_1 = struct.pack(">5i", 
        to_fixed(5.0), 
        to_fixed(100.0), 
        to_fixed(100.0), 
        to_fixed(100.0), 
        to_fixed(100.0),
    )
    h_maxTeamSize = struct.pack(">i", 20) # TotalTeamSize
    # Glimpse Timer Length Ms, Push Timer Length Ms
    h_ints_1 = struct.pack(">2i", 25000, 35000) # Glimpse, Push
    h_double_2 = struct.pack(">i", to_fixed(100.0))
    h_ints_2 = struct.pack(">2i", 1, 1)

    # Pulse Cannon value?
    h_double_3 = struct.pack(">i", to_fixed(100.0))

    # 1: Some move velocity thing
    # 2: Some move velocity thing
    h_floats = struct.pack(">11i", 
                            to_fixed(100.0), 
                            to_fixed(100.0), 
                            to_fixed(100.0), 
                            to_fixed(100.0),
                            to_fixed(100.0), 
                            to_fixed(100.0), 
                            to_fixed(100.0), 
                            to_fixed(100.0),
                            to_fixed(100.0), 
                            to_fixed(100.0), 
                            to_fixed(100.0), 
                           )
    h_flag2 = b'\x01' # behaviorFlag1
    h_flag3 = b'\x01' # behaviorFlag2

    header = h_flag0 + h_doubles_1 + h_maxTeamSize + h_ints_1 + h_double_2 + h_ints_2 + h_double_3 + h_floats + h_flag2 + h_flag3

    # --- SECTION 2: ARRAY 1 (Unknown List - likely Surfaces or Ammo) ---
    # Structure: Linked List -> Fixed Array of 13 Items (1144 / 88 = 13)
    # We assume 1 Linked List Node. If the client desyncs, this might be 2.
    array1_payload = b''
    
    # 5 Bools, 1 Float, 5 Ints, 4 Floats = 45 Bytes per item
    # 13 items * 45 bytes = 585 Bytes total
    for i in range(13):
        # 5 Bools (read as bytes)
        a1_bools = b'\x01\x01\x01\x01\x01'
        # 1 Float (ReadDouble32 reads 4 bytes on wire)
        a1_float1 = struct.pack(">f", 1.0)
        # 5 Ints
        a1_ints = struct.pack(">5i", 100, 100, 100, 100, 100)
        # 4 Floats
        a1_floats = struct.pack(">4f", 1.0, 1.0, 1.0, 1.0)
        
        array1_payload += a1_bools + a1_float1 + a1_ints + a1_floats

    # --- SECTION 3: ARRAY 2 (Entity Definitions) ---
    # Structure: Loop 0 to 40 (41 items)
    # Data: Scale (Float), Unknown (Float), IsEnabled (Int) = 12 Bytes per item
    # Total: 41 * 12 = 492 Bytes
    array2_payload = b''
    
    for i in range(41):
        # Scale (1.0), Unknown (0.0), Enabled (1)
        # Note: ReadDouble32 reads 4 bytes (float) from packet
        a2_item = struct.pack(">ff i", 1.0, 1000.0, 1)
        array2_payload += a2_item

    # --- SECTION 4: PADDING (For Array 3) ---
    # Calculate current size
    current_size = len(packet_type) + len(header) + len(array1_payload) + len(array2_payload)
    target_size = 3118 # User said 3116 + 2 bytes length? Or 3116 payload? Adjusting to 3116 payload.
    
    # Adjust target if you meant 3116 TOTAL including length header. 
    # Usually send_packet handles length, so let's aim for 3116 payload bytes.
    padding_needed = 3116 - current_size
    
    if padding_needed < 0:
        print(f"[ERROR] Payload already too large! {current_size} > 3116")
        padding = b''
    else:
        print(f"[DEBUG] Padding with {padding_needed} bytes for Array 3")
        padding = b'\x00' * padding_needed

    # --- COMBINE ---
    payload = packet_type + header + array1_payload + array2_payload + padding

    print(f"[DEBUG] Final Sizes -> Header: {len(header)}, Array1: {len(array1_payload)}, Array2: {len(array2_payload)}, Padding: {len(padding)}")
    print(f"[DEBUG] Total Payload Size: {len(payload)} bytes")
    
    send_packet(sock, payload)

def send_behavior_packet_old(sock):
    """
    Packet 0x24: BEHAVIOR_UPDATE
    This needs to be exactly 3116 bytes (3118 with the 2 bytes for packet length)
    """
    print("[SEND] Behavior Packet (0x24) - Payload without Array 3...")
    packet_type = b'\x24'

    # --- SECTION 1: HEADER (123 Bytes) ---
    # [Byte] [5 Dbl] [3 Int] [1 Dbl] [2 Int] [1 Dbl] [11 Flt] [Byte] [Byte]
    h_flag0 = b'\x01' 
    h_doubles_1 = struct.pack(">5d", 60.0, 1.0, 1.0, 1.0, 1.0) 
    h_maxTeamSize = struct.pack("i", 20)
    h_ints_1 = struct.pack(">2i", 1, 1)
    h_double_2 = struct.pack(">d", 1.0)
    h_ints_2 = struct.pack(">2i", 1, 1)
    h_double_3 = struct.pack(">d", 1.0)
    h_floats = struct.pack(">11f", 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0)
    h_flag2 = b'\x01'
    h_flag3 = b'\x01'

    header = h_flag0 + h_doubles_1 + h_maxTeamSize + h_ints_1 + h_double_2 + h_ints_2 + h_double_3 + h_floats + h_flag2 + h_flag3
    
    padding = b'\x00' * 2992

    # --- COMBINE ---
    payload = packet_type + header + padding
    
    # Expected Size: 1 + 123 + 3380 + 780 + 0 = 4284 bytes
    print(f"[DEBUG] Behavior Payload Size: {len(payload)} bytes")
    send_packet(sock, payload)

def send_behavior_packet2(sock):
    """
    Packet 0x24: BEHAVIOR_UPDATE
    This needs to be exactly 3116 bytes (3118 with the 2 bytes for packet length)
    """
    print("[SEND] Behavior Packet (0x24) - Payload without Array 3...")
    packet_type = b'\x24' 

    # --- SECTION 1: HEADER (123 Bytes) ---
    # [Byte] [5 Dbl] [3 Int] [1 Dbl] [2 Int] [1 Dbl] [11 Flt] [Byte] [Byte]
    h_flag0 = b'\x01' 
    h_doubles_1 = struct.pack(">5d", 1.0, 1.0, 1.0, 1.0, 1.0) 
    h_ints_1 = struct.pack(">3i", 1, 1, 1)
    h_double_2 = struct.pack(">d", 1.0)
    h_ints_2 = struct.pack(">2i", 1, 1)
    h_double_3 = struct.pack(">d", 1.0)
    h_floats = struct.pack(">11f", 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0)
    h_flag2 = b'\x01'
    h_flag3 = b'\x01'

    header = h_flag0 + h_doubles_1 + h_ints_1 + h_double_2 + h_ints_2 + h_double_3 + h_floats + h_flag2 + h_flag3

    # --- SECTION 2: ARRAY 1 (Weapon Systems) ---
    # 4 Nodes * 13 Items = 52 Items
    # Size: 52 * 65 bytes
    # Active Bools set to FALSE (0) to avoid Null Pointer Crash
    array1 = bytearray()
    item_blob = (
        b'\x00\x00\x00\x00\x00' +                # 5 Bools (FALSE)
        struct.pack(">d", 0.0) +                 # 1 Double
        struct.pack(">5i", 0, 0, 0, 0, 0) +      # 5 Ints
        struct.pack(">4d", 0.0, 0.0, 0.0, 0.0)   # 4 Doubles
    )
    
    padding = b'\x00' * 2992
    
    # 13 items
    #for _ in range(4 * 13):
        #array1.extend(item_blob)

    # --- SECTION 3: ARRAY 2 (Entity Definitions) ---
    # 39 Items * 20 bytes
    #array2 = bytearray()
    #def_blob = struct.pack(">ddi", 0.0, 0.0, 0)
    #for _ in range(4):
        #array2.extend(def_blob)

    # --- SECTION 4: ARRAY 3 (Vehicles) ---
    # TESTING: Sending Empty Array (0 bytes)
    # If the client list is empty, this is correct.
    #array3 = b'' 

    # --- COMBINE ---
    payload = packet_type + header + padding
    
    # Expected Size: 1 + 123 + 3380 + 780 + 0 = 4284 bytes
    print(f"[DEBUG] Behavior Payload Size: {len(payload)} bytes")
    send_packet(sock, payload)

def send_birth_notice(sock, net_id=1):
    """
    Packet 0x1e (30): BIRTH_NOTICE
    Structure from process_login_info:
    [Int]    User ID
    [Int]    Net or Entity ID
    """
    p_userid   = struct.pack(">I", 1337)
    p_net_id    = struct.pack(">I", net_id)
    
    payload = b'\x1E' + p_userid + p_net_id
    send_packet(sock, payload)

def send_view_update_health(sock, player_id, net_id, x, y, z):
    print(f"[SEND] VIEW_UPDATE (Alive) ID={net_id}")
    pkt = PacketWriter() # Assuming your bit-writer helper

    # 1. Packet Header (Implicit or Explicit depending on wrapper)
    # 2. Player ID (matches 'myPlayerID_from_update_array')
    pkt.write_int32(player_id)

    # 3. Turret State (1 Bit) -> 0 (No update)
    pkt.write_bits(0, 1)

    # 4. Count (8 Bits) -> Updating 1 entity
    pkt.write_bits(1, 8)

    # --- ENTITY START ---
    
    # 5. Net ID (32 Bits)
    pkt.write_int32(net_id)

    # 6. Local Player Optimization (1 Bit) -> 1 (Yes, this is me)
    pkt.write_bits(1, 1)

    # 7. UPDATE MASK (10 Bits)
    # Bit 2: Position (1)
    # Bit 6: Energy (1)
    # Bit 8: Health (1)
    # Binary: 0101000100 -> Decimal 324
    pkt.write_bits(324, 10)

    # --- THE MISSING LINK ---
    # The client ALWAYS reads this Index to know which Config Slot to use for vectors.
    # Reads 'Config[0].id_1' bits. You set this to 16 in TRANSLATION.
    # We will send '0' (Use Config Slot 0 for vectors).
    pkt.write_bits(0, 16)

    # --- DATA PAYLOAD (Order is Fixed by Shift Logic) ---

    # [Bit 2] Position Vector (The Crash Fix)
    # Logic: Read Header(id_1 bits) -> Size = Header + id_2
    # Your TRANSLATION: id_1=16, id_2=0.
    #pkt.write_bits(16, 16)      # Header: Tells client "Read 16 bits next"
    #pkt.write_fixed1616(x)        # X (16 bits)
    #pkt.write_fixed1616(y)        # Y (16 bits)
    #pkt.write_fixed1616(z)        # Z (16 bits)

    # WARNING: write_fixed1616 usually writes 32 bits (16 int, 16 frac).
    # Since we told the client to read 16 bits, we MUST write exactly 16 bits.
    # Let's manually pack them as 16-bit integers (Shorts).
    # Range is usually -32768 to 32767. 
    pkt.write_bits(int(x), 16) 
    pkt.write_bits(int(y), 16)
    pkt.write_bits(int(z), 16)

    # [Bit 6] Energy
    # Reads bits determined by Config[5].id_1 (You set to 16)
    pkt.write_bits(65535, 16)   # 100% Energy (1.0 in 16-bit fixed)

    # [Bit 8] Health
    # Reads bits determined by Config[8].id_1 (You set to 16)
    pkt.write_bits(65535, 16)   # 100% Health (1.0 in 16-bit fixed)

    # --- ENTITY END ---
    
    payload = b'\x0E' + pkt.get_bytes()
    #send_packet(sock, payload)

def send_process_translation(sock):
    """
    Packet 0x32: PROCESS_TRANSLATION
    Initializes the Input Compression Table (dword_678134).
    The client expects exactly 28 definitions.
    """
    # 28 Definitions to match the client's hardcoded loop (16 + 12)
    # We will generate generic definitions for all 28 slots.
    # ID: 0..27
    # Bits: 16 (Standard precision)
    # Min/Max: -1000.0 to 1000.0 (Safe range for position/velocity)
    
    print("[SEND] PROCESS_TRANSLATION (0x32) - Initializing Inputs...")
    pkt = PacketWriter()
    
    # 28 Definitions
    for i in range(28):
        pkt.write_int32(16)        # 1. Bit Count (v3). Set to 16 for high precision on all axes.
        pkt.write_int32(0)         # 2. Unknown/Flags (v5). Keep as 0.
        pkt.write_int32(i)         # 3. ID / Config Type (v4). Send the index here.

        pkt.write_string("-1024.0") # Min
        pkt.write_string("1024.0")  # Max
        
    payload = b'\x32' + pkt.get_bytes()
    send_packet(sock, payload)

def send_game_clock(sock):
    print(f"[SEND] GAME_CLOCK 0x2F")
    pkt = PacketWriter()

    pkt.write_int32(get_ticks())

    pkt.write_byte(0x01) # Is active or enabled? not sure

    pkt.write_int32(1) # Maybe Phase flag (0 = Push, 1 = Glimpse), 0 or 1
    pkt.write_int32(30000) # Length of next Push/Glimpse (in Ms)

    payload = b'\x2F' + pkt.get_bytes()
    send_packet(sock, payload)

def send_ping(sock):
    #print(f"[SEND] PING 0x0C")
    pkt = PacketWriter()

    pkt.write_int32(get_ticks())

    payload = b'\x0C' + pkt.get_bytes()
    send_packet(sock, payload)

def send_ping_request(sock):
    #print(f"[SEND] PING_REQUEST 0x0B")
    pkt = PacketWriter()

    pkt.write_int32(get_ticks())

    payload = b'\x0B' + pkt.get_bytes()
    send_packet(sock, payload, False, False)

def send_routing_ping(sock):
    print(f"[SEND] ROUTING_PING 0x4C")
    pkt = PacketWriter()

    pkt.write_byte(0x01)
    pkt.write_byte(0x01)

    payload = b'\x4C' + pkt.get_bytes()
    send_packet(sock, payload)

def send_hud_message(sock):
    print(f"[SEND] HUD_MESSAGE 0x11")
    pkt = PacketWriter()

    pkt.write_string("This is a test HUD message. Hi.")

    payload = b'\x11' + pkt.get_bytes()
    send_packet(sock, payload)

def send_ping_response(sock, echo_timestamp):
    """
    Packet 0x0C: PING
    Echoes the timestamp back to the client.
    """
    print(f"[SEND] PING (0x0C) - Echoing {echo_timestamp}")
    pkt = PacketWriter()
    pkt.write_int32(echo_timestamp)
    payload = b'\x0C' + pkt.get_bytes()
    send_packet(sock, payload)

def start_ping_loop(sock, stop_event):
    """
    Sends a PING_REQUEST every 2 seconds
    Stops immediately if stop_event is set.
    """
    def ping_thread():
        print("[INFO] Starting Ping Loop (Every 2.0s)...")
        while not stop_event.is_set():
            try:
                # Send 0x0B - Ask client to ping us back
                # TCP Ping (Even if you send it on TCP, it will reply back on UDP)
                send_ping_request(sock)
                
                # UDP Ping
                #udp_handler.send_ping_request(client_addr)
                
                # Wait 2 seconds, checking for the stop signal frequently
                stop_event.wait(2.0)
            except OSError:
                print("[INFO] Ping loop stopping (socket closed).")
                break
            except Exception as e:
                print(f"[ERROR] Ping loop failed: {e}")
                break

    # Daemon ensures it dies when the server stops
    t = threading.Thread(target=ping_thread, daemon=True)
    t.start()

# --- Receiver Utility ---
def recv_exact(sock: socket.socket, n: int) -> bytes | None:
    buf = b""
    while len(buf) < n:
        try:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                return None
            buf += chunk
        except socket.timeout:
            continue # Keep trying if timed out inside a packet read
        except Exception:
            return None
    return buf
    
def unpack_udp_payload(data: bytes) -> bytes:
    """
    Some of your packets appear to be raw UDP (no length),
    but this safely supports the case where UDP also includes the 2-byte BE length header.
    Returns the payload starting at the type byte.
    """
    if len(data) >= 3:
        try:
            declared = struct.unpack(">H", data[:2])[0]
            if declared == len(data):
                return data[2:]
        except Exception:
            pass
    return data
    
def udp_server_loop():
    """Listens for UDP traffic and delegates to UDPHandler."""
    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        udp_sock.bind(("0.0.0.0", 2627))
        print(f"[UDP] Listening on port 2627")
    except Exception as e:
        print(f"[UDP] Error binding: {e}")
        return

    # Initialize the Handler
    # We pass the socket (to send replies) and the Event (to notify TCP)
    handler = UDPHandler(udp_sock, udp_root_received)

    while True:
        try:
            data, addr = udp_sock.recvfrom(2048)
            
            # ONE LINE TO RULE THEM ALL:
            handler.process_packet(data, addr)
            
        except Exception as e:
            print(f"[UDP] Loop Error: {e}")
            
def start_heartbeat(sock):
    """
    Starts a background thread that sends the UPDATE_ARRAY packet 
    every 0.1 seconds (10Hz).
    """
    def heartbeat_loop():
        print("[INFO] Starting Heartbeat Thread (10Hz)...")
        while True:
            try:
                # Send the repair/update packet
                #send_repair_packet(sock)
                
                # Sleep for 100ms
                time.sleep(0.5)
            except Exception as e:
                print(f"[ERROR] Heartbeat died: {e}")
                break

    # Daemon=True ensures this thread dies when the main program closes
    hb_thread = threading.Thread(target=heartbeat_loop, daemon=True)
    hb_thread.start()

def debug_listener():
    debug_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    debug_sock.bind(("0.0.0.0", 2660)) # Port 2627 + 33
    debug_sock.listen(1)
    print("[DEBUG] Listening on Side-Channel Port 2660")
    
    while True:
        client, addr = debug_sock.accept()
        print(f"[DEBUG] Client connected to side channel! {addr}")
        while True:
            data = client.recv(1024)
            if not data: break
            print(f"[DEBUG-DUMP] {data}")

# --- Main Server Loop ---
def main():
    # Start UDP Listener in background
    udp_thread = threading.Thread(target=udp_server_loop, daemon=True)
    udp_thread.start()
    
    # Start Debug Listener in background
    debug_thread = threading.Thread(target=debug_listener, daemon=True)
    debug_thread.start()
    
    # Start TCP Server
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((HOST, PORT))
    s.listen(1)
    s.settimeout(1.0) # Allow waking up for CTRL+C
    
    print(f"Server listening on {HOST}:{PORT}...")
    print("Press CTRL+C to stop the server.")

    try:
        while True:
        # Wait for a client
            try:
                # This will block for 1 second, then raise socket.timeout
                client, addr = s.accept()
                stop_ping_event = threading.Event()
            except socket.timeout:
                # Timeout reached, loop back to check for KeyboardInterrupt
                continue
            except OSError:
                break
        
            print(f"\n[+] Client connected from {addr}")
            udp_root_received.clear() # Reset flag
            
            # Small delay before sending hello
            print("[INFO] Pausing for client initialization...")
            time.sleep(1.0)

            # 1. SERVER SPEAKS FIRST: HELLO
            #send_hello(client)
            send_hello_udp(client, PORT)
            
            # The client needs time to bind sockets and send the ROOT packet.
            # If we send AccountRequest too fast, it crashes the parser.
            print("[INFO] Waiting for Client UDP init...")
            
            # This pauses the TCP flow until the UDP thread hears "ROOT"
            if udp_root_received.wait(timeout=5.0):
                print(">>> UDP ROOT Verified! Sending TCP Confirmation.")
                send_identified_udp(client) # <--- SEND ON TCP -- This Triggers State 0xB -> Login Screen
            else:
                print("[WARN] UDP Timeout. Sending Confirmation blindly.")
                send_identified_udp(client)
                
            # sending IDENTIFIED_UDP will set is_udp_hello_key_received = 0;
            # sending the hello key will set is_udp_hello_key_received = 1;
            #send_hello_key(client)

            # LOGIN SEQUENCE
            #send_account_request(client) # This is making a Request Account Handle window popup, not really used for login

            send_hello_final(client)
        
            # 4. WAIT FOR USERNAME
            print(">>> Waiting for USERNAME (0x21)...")
            client.settimeout(None) # Wait forever for you to type
            
            username_received = False
            
            while not username_received:
                try:
                    # Read Header
                    hdr = recv_exact(client, 2)
                    if not hdr:
                        print("[-] Client disconnected while waiting for login.")
                        break
                        
                    (length,) = struct.unpack(">H", hdr)
                    # Read Body
                    body = recv_exact(client, length - 2)
                    if not body: break
                    
                    pkt_type = body[0]
                    log_packet("RECV", body)
                    
                    if handle_hello_packet(client, body):
                        continue
                    
                    # CHECK: Is this the Login Packet?
                    if pkt_type == 0x21:
                        print(">>> Username Received!")
                        username_received = True
                    elif pkt_type == 0x36:
                        print("---")
                        print("    (Ignored 'want_voice_data' packet)")
                        print("---")
                    else:
                        print("---")
                        print(f"    (Ignored non-login packet 0x{pkt_type:02X})")
                        print("---")
                        
                except Exception as e:
                    print(f"[ERROR] error waiting for username: {e}")
                    break
            
            if not username_received:
                client.close()
                continue
                
            # --- STEP 5: ASK FOR PASSWORD ---
            # Code 1 tells the client: "Okay, now show the password box"
            print(">>> Requesting Password (Status Code 1)...")
            send_login_status(client, code=1, is_donor=True)

            # --- STEP 6: WAIT FOR PASSWORD ---
            print(">>> Waiting for PASSWORD (0x21)...")
            password_received = False
            while not password_received:
                try:
                    hdr = recv_exact(client, 2)
                    if not hdr: break
                    (length,) = struct.unpack(">H", hdr)
                    body = recv_exact(client, length - 2)
                    if not body: break
                    
                    pkt_type = body[0]
                    log_packet("RECV", body)
                    
                    if handle_hello_packet(client, body):
                        continue
                    
                    if pkt_type == 0x21:
                        print(">>> Password Received!")
                        password_received = True
                    elif pkt_type == 0x36:
                        print("    (Ignored 'want_voice_data')")
                except Exception as e:
                    print(f"[ERROR] {e}")
                    break

            if not password_received:
                client.close()
                continue
                
            print(">>> Login Complete! Granting Access...")
            
            send_team_info(client)
            #  AUTHENTICATION SEQUENCE
            #send_login_info(client)   # I believe this is to show when they are banned and can't login
            send_login_status(client, code=8, is_donor=True) # <--- Login Success
            
            # GAME LOAD SEQUENCE
            
            # Order that works
            #send_motd(client, "Welcome Back") # Optional
            #send_world_stats(client)
            #send_team_info(client)
            #send_player_info(client)
            
            # Order seems not matter much from testing..
            send_player_info(client) # REQUIRED: Will get spammed [UDP] RECV Packet 19 (Session Key) from ('127.0.0.1', 52984): WulframSessionKey123
            #send_ping(client)
            send_game_clock(client)
            send_motd(client, "Party like it's 1999!")
            send_behavior_packet(client)
            send_process_translation(client)
            send_add_to_roster(client, account_id=1337, name="baff")
            send_team_info(client) # REQUIRED (crashed without): Team Info has to be somewhere around here, if it comes in much later it crashes
            send_world_stats(client) # REQUIRED (crashed without)

            start_ping_loop(client, stop_ping_event)
            
            #Server Access Denied with message (popup box on client)
            #send_reincarnate(client, 18, "Just a test.")

            # LISTEN LOOP
            while True:
                try:
                    # Read Header
                    hdr = client.recv(2)
                    if not hdr: break
                    (length,) = struct.unpack(">H", hdr)
                    
                    # Read Body
                    body = recv_exact(client, length - 2)
                    if not body: break
                    
                    pkt_type = body[0]
                    
                    # LOG THE RECEIVED PACKET
                    log_packet("RECV", body)
                    
                    # 1. BPS REQUEST (0x4E)
                    if pkt_type == 0x4E:
                        # Client sent: [4E] [Int32]
                        # We need to extract that Int32 to echo it back
                        if len(body) >= 5:
                            (requested_rate,) = struct.unpack(">I", body[1:5])
                            send_bps_reply(client, requested_rate)
                        else:
                            print("[WARN] Malformed BPS Request")

                    # 2. WANT_UPDATES (0x39)
                    elif pkt_type == 0x39:
                        # Client says "I am ready for game state."
                        # For now, we can just log it. Later, this starts the UDP stream.
                        print(">>> Client is ready for World Updates (0x39)")
                        send_chat_message(client, "System: Welcome to Wulfram!", source_id=0, target_id=0)
                        send_ping_request(client)
                        #send_repair_packet(client)
                        #send_behavior_packet(client)
                        #send_birth_notice(client)
                        # Hope this works... !
                        #send_update_array_empty(client) # doesn't work rn
                        #send_update_stats(client, account_id=1337, team_id=1)
                        #send_process_translation(client)
                        #send_add_to_roster(client, account_id=1337, name="baff")
                        
                    elif pkt_type == 0x4F:
                        print(">>> !kudos (0x4F)")
                        send_update_array_empty(client)
                        send_ping(client) 
                        send_chat_message(client, "System: Testing Complete.", source_id=0, target_id=0)
                        #send_birth_notice(client, 1337)
                        send_view_update_health(client, player_id=1337, net_id=1337, x=100.0, y=100.0, z=100.0)
                        send_tank_packet(client, net_id=1337, unit_type=0, pos=(100.0, 100.0, 100.0), vel=(100.0, 100.0, 100.0))
                        send_view_update_health(client, player_id=1337, net_id=1337, x=100.0, y=100.0, z=100.0)
                        send_view_update_health(client, player_id=1337, net_id=1337, x=100.0, y=100.0, z=100.0)
                        send_view_update_health(client, player_id=1337, net_id=1337, x=100.0, y=100.0, z=100.0)
                        send_hud_message(client)
                        #send_routing_ping(client)
                        
                        #send_birth_notice(client, 1337)
                        #send_repair_packet(client)
                        #time.sleep(0.25)
                        #send_repair_packet(client)

                    elif pkt_type == 0x0C: # PING (Client is replying to our Request)
                        # Structure: [0x0C] [Int32 Timestamp]
                        if len(body) >= 5:
                            (client_ts,) = struct.unpack(">I", body[1:5])
                            print(f">>> Client PONG received! TS={client_ts}")
                            
                            # Optional: Echo it back if the client expects a server-side confirmation
                            # send_ping_response(client, client_ts)
                        else:
                            print("[WARN] Malformed PING packet")

                except ConnectionResetError:
                    break
                except Exception:
                    break
                    
            print("[-] Client disconnected")
            stop_ping_event.set()
            client.close()

    except KeyboardInterrupt:
        print("\n[!] Stopping server...")
        s.close()
        sys.exit()
        
if __name__ == "__main__":
    main()