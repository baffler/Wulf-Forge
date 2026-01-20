import struct
import time
import threading
from .streams import PacketReader, PacketWriter
from .packet_logger import PacketLogger

# Helper for Wulfram 32-bit timestamp
def get_ticks():
    return int(time.time() * 1000) & 0x7FFFFFFF

class UDPHandler:
    def __init__(self, sock, root_event):
        self.sock = sock
        self.root_event = root_event
        self.logger = PacketLogger()

        self.outgoingSequenceNumber = 0
        
        # Simple Stream State Tracker (Dictionary)
        # Key: StreamID (int) -> Value: CurrentSequence (int)
        self.stream_states = {
            0: 0, # Unreliable
            1: 0, # Reliable
            2: 0, # Chat
            3: 0  # Game Data
        }

        # The Dispatcher
        self.packet_map = {
            0x00: self.handle_debug_string,
            0x02: self.handle_ack,
            0x03: self.handle_d_handshake,
            0x08: self.handle_hello_ack,
            0x09: self.handle_process_root,
            0x0A: self.handle_process_voice,
            0x13: self.handle_session_key,
            0x20: self.handle_comm_req,  # Chat (If sent unreliably)
            0x25: self.handle_reincarnate,
            0x33: self.handle_ack2, 
            0x40: self.handle_keep_alive,
        }

    def process_packet(self, data, addr):
        """
        Entry point for all UDP data.
        Now supports BATCHED packets
        """
        if not data: return

        # 1. Handle Wulfram's Transport Framing (The 2-byte Length Header)
        #    If the packet starts with a short matching its length, strip it.
        payload = self._unpack_payload(data)
        if not payload: return

        # 2. BATCH PROCESSING LOOP
        #    Treat the payload as a stream of concatenated packets.
        cursor = 0
        total_len = len(payload)
        batch_index = 0

        while cursor < total_len:
            # We need at least 1 byte for the OpCode
            if (total_len - cursor) < 1: 
                break

            batch_index += 1

            pkt_type = payload[cursor]
            
            # --- PACKET SIZING LOGIC ---
            # We must determine how big this packet is to know where the next one starts.
            
            packet_body = None
            bytes_consumed = 0

            if pkt_type == 0x00:
                # [0x00] [LenByte] [String...]
                # This is the "Hello" packet. It has a specific length byte.
                if (total_len - cursor) >= 2:
                    str_len = payload[cursor + 1]
                    total_packet_size = 1 + 1 + str_len # Op + Len + Body
                    
                    if (cursor + total_packet_size) <= total_len:
                        # Extract just the string body
                        packet_body = payload[cursor + 2 : cursor + total_packet_size]
                        bytes_consumed = total_packet_size
                    else:
                        print(f"[ERR] Malformed 0x00 packet at {cursor}")
                        break
                else:
                    break
            
            else:
                # [DEFAULT]
                # For Handshakes (0x03) and others, we assume they consume
                # the REST of the buffer.
                #print("Consuming buffer...")
                packet_body = payload[cursor + 1:] # Skip OpCode
                bytes_consumed = total_len - cursor # Eat everything

            # --- DISPATCH ---
            if pkt_type in self.packet_map:
                try:
                    self.logger.log(f"UDP BATCH #{batch_index}", pkt_type, packet_body, addr)
                    self.packet_map[pkt_type](packet_body, addr)
                except Exception as e:
                    print(f"[ERROR] Handler 0x{pkt_type:02X} failed: {e}")
            else:
                self._handle_unknown(pkt_type, packet_body, addr)

            # Advance to the next packet in the batch
            cursor += bytes_consumed

    def _unpack_payload(self, data):
        """Checks for the optional 2-byte length header Wulfram adds."""
        if len(data) >= 3:
            try:
                # Big-Endian Short Length Check
                declared_len = struct.unpack(">H", data[:2])[0]
                # If the first 2 bytes match the total length, it's a frame header.
                # Strip it (return data[2:])
                if declared_len == len(data):
                    return data[2:]
            except: pass
        return data

    def _pack(self, opcode, payload):
        return bytes([opcode]) + payload

    # ==========================
    #      CORE HANDLERS
    # ==========================

    def handle_debug_string(self, data, addr):
        """Packet 0x00: The 'Hello' String"""
        try:
            # It's usually null-terminated, so strip the \0
            msg = data.decode('ascii', errors='ignore').strip('\x00')
            print(f"    > RECV MSG (0x00): '{msg}'")
        except:
            print(f"    > RECV MSG (0x00): [Binary Data]")

    def handle_ack(self, data, addr):
        """Packet 0x02: """
        try:
            # It's usually null-terminated, so strip the \0
            msg = data.decode('ascii', errors='ignore').strip('\x00')
            print(f"    > RECV ACK (0x02): '{msg}'")
        except:
            print(f"    > RECV ACK (0x02): [Binary Data]")

    def handle_ack2(self, data, addr):
        """
        Packet 0x33: ACK2 (Response to Process Translation)
        Bytes: [StreamID:2] [SeqID:2] [Status:4]
        payload: [00 01] [00 09] [00 00 00 01]
        The client calls this "ACK2" in process_translation.
        It sends Int32(1) inside.
        """
        if len(data) < 4: return

        reader = PacketReader(data)
        
        # Parse Reliability Header
        sequence_num = reader.read_int16() # 00 01
        packet_len = reader.read_int16() # 00 09

        # Read Payload
        status_code = reader.read_int32() # 00 00 00 01 (The 1 form the code)
        
        print(f"    > RECV ACK2/RELIABLE 0x33 (Seq {sequence_num} | Len {packet_len}) - Status: {status_code}")

        # 1. SEND TIMED ACK (Fixes 'Out of Hunks')
        # We must use SubCmd 2 (8 bytes) because the client crashes on SubCmd 1 (4 bytes).
        # We assume the client wants the timestamp for sync purposes.
        #self.send_timed_ack(addr, stream_id, sequence_num)
        self.send_standard_ack(addr, sequence_num, 0x33)
        #self.send_d_ack(addr)

        # 2. Update State
        #current_seq = self.stream_states.get(stream_id, 0)
        #if sequence_num > current_seq:
            #self.stream_states[stream_id] = sequence_num

    def handle_d_handshake(self, data, addr):
        """Packet 0x03"""
        reader = PacketReader(data)
        try:
            timestamp = reader.read_int32()
            conn_id = reader.read_int32()
            stream_count = reader.read_int32()
            print(f"    > D_HANDSHAKE: Time={timestamp}, ID={conn_id}, Streams={stream_count}")

            # 1. Acknowledge the Handshake (SubCmd 0)
            self.send_d_ack(addr)

            # 2. Send OUR Handshake (Definitions)
            # (This tells the client what Stream 1, 2, 3 actually DO)
            self.send_d_handshake(addr)

            # 3. CRITICAL: Initialize ALL streams you defined!
            # If you don't start them, the client won't use them.
            print("[UDP] Synchronizing Streams...")
            self.send_d_set_start(addr, 1, 1) # Unpause Stream 1 (Reliable)
            self.send_d_set_start(addr, 3, 1) # Unpause Stream 3 (Game Data)
        
        except Exception as e:
            print(f"[ERR] Bad D_HANDSHAKE: {e}")

    # ==========================
    #      SENDING HELPERS
    # ==========================

    def send_standard_ack(self, addr, sequence_num, packet_id):
        """
        Packet 0x02: SubCmd 1 (Standard ACK)
        """
        pkt = PacketWriter()

        #= works =======================
        #pkt.write_int16(stream_id)
        #pkt.write_int16(sequence_num)

        #pkt.write_byte(1)           # SubCmd 1
        
        #pkt.write_byte(packet_id)    # packet_id we are acking
        #pkt.write_int16(stream_id)   # stream_id for the packet id we are acking
        
        #self._send(0x02, pkt.get_bytes(), addr)
        #= works =====================

        #= testing ====================
        self.outgoingSequenceNumber += 1

        pkt.write_int16(self.outgoingSequenceNumber)
        pkt.write_int16(9) # This payload length will always be 9

        pkt.write_byte(1)           # SubCmd 1
        
        pkt.write_byte(packet_id)    # packet_id we are acking
        
        
        pkt.write_int16(sequence_num)   # should be OUR sequence num (not sure yet!)
        
        self._send(0x02, pkt.get_bytes(), addr)
        

    def send_timed_ack(self, addr, stream_id, sequence_num, packet_id):
        """
        Packet 0x02: SubCmd 2 (Timed ACK)
        """
        pkt = PacketWriter()

        pkt.write_int16(stream_id)
        pkt.write_int16(sequence_num)

        pkt.write_byte(2)           # SubCmd 2
        pkt.write_int32(get_ticks()) # Timestamp

        pkt.write_byte(packet_id)    # packet_id we need to ack for
        pkt.write_int16(stream_id)   # stream id
        
        self._send(0x02, pkt.get_bytes(), addr)

    def send_d_ack(self, addr):
        """Packet 0x02: SubCmd 0 (Handshake ACK)"""
        pkt = PacketWriter()
        
        #pkt.write_int16(stream_id)
        #pkt.write_int16(sequence_num)

        pkt.write_byte(0)           # SubCmd 0
        pkt.write_int32(get_ticks())
        self._send(0x02, pkt.get_bytes(), addr)

    def send_d_handshake(self, addr):
        """
        Packet 0x03: D_HANDSHAKE
        Constructs the Stream Definitions.
        """
        pkt = PacketWriter()
        pkt.write_int32(get_ticks())
        pkt.write_int32(1001) # Our Player ID

        # --- STREAM DEFINITIONS ---
        # We define 4 streams to match the client's expectations
        pkt.write_int32(4) # Def Count

        # Stream 0: Unreliable
        pkt.write_string("Unreliable")
        pkt.write_int32(1) # ID Count
        pkt.write_int32(0) # ID

        # Stream 1: Reliable (Chat/Events)
        pkt.write_string("Reliable")
        pkt.write_int32(1)
        pkt.write_int32(1)

        # Stream 2: Meta/Receipts
        pkt.write_string("Stream 2")
        pkt.write_int32(1)
        pkt.write_int32(2)

        # Stream 3: Game Data (Movement)
        pkt.write_string("Game Data")
        pkt.write_int32(1)
        pkt.write_int32(3)

        # --- STREAM CONFIGURATION ---
        # Set Priorities / Window Sizes
        pkt.write_int32(4) # Config Count
        
        # [StreamID] [Priority]
        pkt.write_int32(0); pkt.write_int32(1)
        pkt.write_int32(1); pkt.write_int32(1)
        pkt.write_int32(2); pkt.write_int32(1)
        pkt.write_int32(3); pkt.write_int32(1)

        self._send(0x03, pkt.get_bytes(), addr)

    def send_d_set_start(self, addr, stream_id, sequence):
        """Packet 0x04: Unpause Stream"""
        pkt = PacketWriter()
        pkt.write_byte(stream_id)
        pkt.write_int16(sequence)
        
        # 0x04 is a raw packet, usually no extra headers
        self.sock.sendto(self._pack(0x04, pkt.get_bytes()), addr)

    def _handle_unknown(self, pkt_type, data, addr):
        # Useful for debugging new packet types
        print(f"[?] Unknown OpCode: 0x{pkt_type:02X} Len={len(data)}")
        pass

    def _send(self, opcode, payload, addr):
        full_pkg = self._pack(opcode, payload)

        self.sock.sendto(full_pkg, addr)
        self.logger.log("SEND", opcode, payload, addr)

    def send_reliable_packet(self, addr, stream_id, sequence_num, opcode, payload):
        pkt = PacketWriter()
        
        # 1. Stream ID (2 bytes)
        pkt.write_int16(stream_id)
        
        # 2. Sequence Number (2 bytes)
        #pkt.write_int16(sequence_num)
        
        # 3. LENGTH (2 bytes) - THE MISSING FIELD!
        # Size = 2 (Seq) + 2 (Len) + 1 (Op) + Payload
        total_len = 5 + len(payload)
        pkt.write_int16(total_len)
        
        # 4. OpCode (1 byte)
        pkt.write_byte(opcode)
        
        # 5. Payload
        full_packet = pkt.get_bytes() + payload
        
        self._send(opcode, full_packet, addr) # Note: _send usually adds UDP header too

    def handle_session_key(self, data, addr):
        # 0x13: Session Key (UDP)
        # Confirming the client has switched to UDP encryption context
        reader = PacketReader(data)
        subcmd = reader.read_byte()
        key = reader.read_string()
        print(f"    > UDP SESSION KEY: {key}")
        
    def handle_hello_ack(self, data, addr):
        # 0x08: HELLO_ACK
        # Sent by the client to confirm they received our "Hello" (if using UDP handshake)
        
        # Signal the Main TCP Thread that UDP is alive
        if not self.root_event.is_set():
            print("    > UDP Link Verified. Signaling TCP Thread.")
            self.root_event.set()
    
    def handle_process_root(self, data, addr):
        # 0x09: PROCESS_ROOT
        pass

    def handle_process_voice(self, data, addr):
        # 0x0A: PROCESS_VOICE
        pass

    def handle_keep_alive(self, data, addr):
        # 0x40: KEEP_ALIVE
        # Just a heartbeat. We can ignore it or log it sparingly.
        pass

    def handle_reincarnate(self, data, addr):
        # 0x25: REINCARNATE
        if len(data) < 8: return

        reader = PacketReader(data)
        sequence_num = reader.read_int16()
        payload_len = reader.read_int16()

        # 0 = spawn request (and we read more bytes and such)
        #(0x25) | Len=43  | Addr=('127.0.0.1', 51875)
        #Body=00 12 00 16 00 00 00 00 00 00 00 00 00 00 00 07D0000002BC2500120016000000000000000000000007D0000002BC
        # 1 = team switch request (and we read just 2 more ints)
        is_team_switch = reader.read_byte() == 0x01

        team_id = reader.read_int32() # passed as an arg, this is the team id ! red = 1, blue = 2
        unk_int2 = reader.read_int32() # always 0 ?

        print(f"    > RECV REINCARNATE (Sequence {sequence_num} | Len {payload_len}): IsTeamSwitch?: {is_team_switch} | Team Number: {team_id} | {unk_int2}")

        if (not is_team_switch):
            unk_int3 = reader.read_int32() # 2000
            unk_int4 = reader.read_int32() # 700

            print(f"    > SPAWN IN? : {unk_int3} | {unk_int4}")
            self.send_reincarnate(addr, 4, "") #Can't enter yet. Game not ready.
            self.send_tank_packet(addr, net_id=1337, unit_type=0, pos=(100.0, 100.0, 100.0), vel=(100.0, 100.0, 100.0))

        self.send_standard_ack(addr, sequence_num, 0x25)

        # Switch their teams
        # Team 0: is *maybe* a spawn request? Or a request to spawn when there's no repair pads?
        if (team_id == 1):
            self.send_update_stats(addr, account_id=1337, team_id=1)
        elif (team_id == 2):
            self.send_update_stats(addr, account_id=1337, team_id=2)
        
        #Sends message about team switched successfully
        self.send_reincarnate(addr, 17, "")

    def handle_comm_req(self, data, addr):
        """
        Packet 0x20: CHAT / COMM REQUEST
        TODO: look up the correct stream id for comm_req
        """
        if len(data) < 10: return

        reader = PacketReader(data)
        sequence_num = reader.read_int16()
        payload_len = reader.read_int16()

        source = reader.read_int16()
        unk_id = reader.read_int16()
        message = reader.read_string()

        print(f"unknown id: {unk_id} | source: {source} | message: {message}")
        
        # 1. Update Sequence State (Simplistic)
        #self.stream_states[stream_id] = sequence_num

        print(f"    > RECV RELIABLE (Sequence {sequence_num} | Len {payload_len})")

        # 2. SEND ACK
        #self.send_timed_ack(addr, stream_id, sequence_num, 0x20)
        self.send_standard_ack(addr, sequence_num, 0x20)

        # 3. SEND CHAT MESSAGE
        self.send_chat_message(addr, 5, 1337, source, 0, message)
        
        #source = 5 # admin message
        #self.send_chat_message(addr, 5, 1337, source, 0, message)

    def send_chat_message(self, addr, message_type, source_player_id, chat_scope_id, recepient_id, message):
        """Packet 0x1F: COMM_MESSAGE (Server -> Client)"""
        pkt = PacketWriter()
        pkt.write_int16(message_type) # Message Class/Type
        pkt.write_int32(source_player_id) # Source Player ID
        pkt.write_int16(chat_scope_id) # Chat Channel/Scope (0 = Global, 4 = Team, 5 = Command/Console)
        pkt.write_int32(recepient_id) # Recipient ID (only used for whispers i believe)
        pkt.write_string(message)
        
        self._send(0x1F, pkt.get_bytes(), addr)

    def send_update_stats(self, addr, account_id, team_id):
        """Packet 0x1C: UPDATE_STATS
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
        pkt.write_fixed1616(1.0)
        pkt.write_fixed1616(1.0)
        
        pkt.write_int32(10)           # Extra / Flags
        
        self._send(0x1C, pkt.get_bytes(), addr)

    def send_reincarnate(self, addr, code: int, message: str):
        """
        Sends the Reincarnate response (Server -> Client).
        Structure: [OpCode 0x25] [Byte code] [String message]
        
        Recv: (Client ->) [0x25] [int (Team ID)] [int (?)]
        """
        print(f"[SEND] Sending ReIncarnate (0x25): code={code} '{message}'")
        pkt = PacketWriter()
        
        pkt.write_byte(code)
        pkt.write_string(message)
        
        self._send(0x25, pkt.get_bytes(), addr)

    def send_tank_packet(self, addr, net_id, unit_type, pos, vel, flags=1):
        print(f"[SEND] TANK (0x18) ID={net_id} Type={unit_type}")
        
        pkt = PacketWriter()
        
        # 1. Timestamp (Int32)
        tick_count = get_ticks()
        pkt.write_int32(tick_count)
        
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
        
        self._send(0x18, pkt.get_bytes(), addr)

    def handle_stream_check(self, data, addr):
        # 0x00: Often just a keep-alive/ping inside a reliable container
        pass