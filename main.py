# main.py
from __future__ import annotations
import socket
import threading
import time
import struct
import math
import os
import random
import secrets
from typing import Dict, Tuple, Optional

from network.transport.tcp_transport import TcpTransport
from network.transport.udp_transport import UdpTransport

from network.dispatcher import PacketDispatcher
from network.streams import PacketWriter, PacketReader

from core.config import Config, PlayerSession, get_ticks
from network.packets.packet_config import PacketConfig
from network.packets import (
    Packet, MotdPacket, IdentifiedUdpPacket, LoginStatusPacket, PlayerInfoPacket,
    BpsReplyPacket, PingRequestPacket, AddToRosterPacket, WorldStatsPacket,
    DeathNoticePacket, BirthNoticePacket, CarryingInfoPacket, DockingPacket, 
    ResetGamePacket, DeleteObjectPacket,
    GameClockPacket, HelloPacket, TeamInfoPacket, ReincarnatePacket,
    TankPacket, BehaviorPacket, TranslationPacket,
    UpdateStatsPacket, CommMessagePacket,
)
from network.packets.packet_logger import PacketLogger, log_packet

from core.entity import GameEntity, UpdateMask
from core.entity_manager import EntityManager
from core.map_loader import MapLoader
from core.commands import commands
from network.packets.update_array import UpdateArrayPacket
from network.translation_config import get_config_by_index, GLOBAL_CONFIGS

# -------------------------------------------------------------------------
# CONTEXTS
# -------------------------------------------------------------------------

class ClientSession:
    """
    Encapsulates the state for a single connected player.
    Replaces the global 'player' and 'my_entity' from the server context.
    """
    def __init__(self, server: WulframServerContext, tcp_sock: socket.socket, addr: Tuple[str, int]):
        self.server = server
        self.tcp_sock = tcp_sock
        self.address = addr  # (IP, Port) from TCP connection
        
        # Identity
        self.player_id: int = 0
        self.name: str = "Unknown"
        self.team: int = 0

        # --- SESSION KEY LOGIC ---
        # Generate a random 10-char key (Wulfram seems to like strings)
        self.session_key = "Key" + secrets.token_hex(4) 
        
        # Placeholder: We don't know the real algo yet, so we will 
        # temporarily TRUST the client's TCP echo to link this.
        self.expected_udp_id = 0
        
        # Game Object associated with this client
        self.entity: Optional[GameEntity] = None
        
        # Connection State
        self.is_logged_in: bool = False
        
        # UDP Linkage
        self.udp_addr: Optional[Tuple[str, int]] = None
        self.udp_context: Optional[UdpContext] = None
        
        # Synchronization Events (Specific to this client now)
        self.stop_ping_event = threading.Event()
        # Wait for client to echo our key back
        self.key_echoed_event = threading.Event()
        self.login_received = threading.Event()

    def cleanup(self):
        """Helper to close sockets and events when client disconnects."""
        self.stop_ping_event.set()
        try:
            self.tcp_sock.close()
        except:
            pass
        if self.entity:
            # Logic to remove entity from world could go here
            pass

class WulframServerContext:
    """
    Holds configuration, the logger, shared state, and controls the sockets.
    """
    def __init__(self):
        self.cfg = Config.load()
        self.packet_cfg = PacketConfig.load("packets.toml")
        self.logger = PacketLogger()
        self.entities = EntityManager()
        self.first_map_load = False

        # Session Management
        self.sessions: list[ClientSession] = []

        # ID Counters
        self._next_player_id = 1
        
        # Shared State
        self.stop_event = threading.Event()
        self.stop_update_event = threading.Event()
        
        # Sockets
        self.tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        # Transports
        self.udp_transport: Optional[UdpTransport] = None
        
        # UDP Session Cache (Addr -> UdpContext)
        self.udp_sessions: Dict[Tuple[str, int], UdpContext] = {}

    def get_next_player_id(self) -> int:
        """Generates a unique Player/Account ID."""
        pid = self._next_player_id
        self._next_player_id += 1
        return pid

    def run(self):
        """Starts the UDP listener thread and the TCP accept loop."""
        # 1. Setup UDP
        self.udp_sock.bind((self.cfg.network.host, self.cfg.network.udp_port))
        self.udp_transport = UdpTransport(self.udp_sock)
        print(f"[UDP] Listening on port {self.cfg.network.udp_port}")
        
        # Start UDP Thread
        udp_thread = threading.Thread(target=self._udp_loop, daemon=True)
        udp_thread.start()

        # 2. Setup TCP
        self.tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.tcp_sock.bind((self.cfg.network.host, self.cfg.network.tcp_port))
        self.tcp_sock.listen(5)
        self.tcp_sock.settimeout(1.0)
        print(f"[TCP] Listening on {self.cfg.network.host}:{self.cfg.network.tcp_port}")

        # 3. Main Loop (Accepts TCP Clients)
        self._tcp_accept_loop()

    def _udp_loop(self):
        """The dedicated UDP listener loop."""
        transport = self.udp_transport
        if transport is None:
            print("[UDP-ERR] Transport not initialized, stopping UDP loop.")
            return
        
        while not self.stop_event.is_set():
            try:
                data, addr = self.udp_sock.recvfrom(2048)
                
                # Get or Create UDP Session Context
                if addr not in self.udp_sessions:
                    # KEY CHANGE: Do not try to match by IP. 
                    # Create a "Sessionless" context. The Session Key (Hello Packet) 
                    # will link this context to a player later.
                    ctx = UdpContext(transport, addr, self, session=None)
                    self.udp_sessions[addr] = ctx
                    # print(f"[UDP] New connection from {addr} (Unverified)")

                ctx = self.udp_sessions[addr]

                for packet_payload in transport.parse_datagram(data):
                    dispatcher.dispatch_payload(ctx, packet_payload)

            except Exception as e:
                print(f"[UDP-ERR] {e}") # Optional: reduce spam
                pass

    def _tcp_accept_loop(self):
        """The main blocking loop that accepts TCP connections."""
        print("Server running. Press CTRL+C to stop.")
        try:
            while not self.stop_event.is_set():
                try:
                    client_sock, addr = self.tcp_sock.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                
                print(f"\n[+] Client connected from {addr}")
                
                # --- STEP 2 LOGIC PREVIEW ---
                # Create the session
                new_session = ClientSession(self, client_sock, addr)
                self.sessions.append(new_session)

                # Handle in a thread (Non-blocking)
                t = threading.Thread(
                    target=self._handle_tcp_client, 
                    args=(new_session,), 
                    daemon=True
                )
                t.start()
                
        except KeyboardInterrupt:
            print("\n[!] Stopping server...")
            self.stop_event.set()
        finally:
            self.tcp_sock.close()
            self.udp_sock.close()

    def _handle_tcp_client(self, session: ClientSession):
        """
        Threaded handler for a single TCP client.
        """
        client_sock = session.tcp_sock
        
        # Update TcpContext to use the session
        tcp_transport = TcpTransport(client_sock)
        ctx = TcpContext(tcp_transport, self, session)
        
        try:
            do_login_and_bootstrap(client_sock, ctx, dispatcher)
            
            # Connection Loop
            while True:
                payload = tcp_transport.recv_payload()
                if not payload: break
                dispatcher.dispatch_payload(ctx, payload)
                
        except Exception as e:
            print(f"[-] Client {session.address} Disconnected: {e}")
        finally:
            session.cleanup()
            if session in self.sessions:
                self.sessions.remove(session)

class TcpContext:
    """
    Context for a specific TCP Client connection.
    Reference `server` to access global config/state.
    Reference `session` to access specific player state.
    """
    def __init__(self, transport: TcpTransport, server: WulframServerContext, session: ClientSession):
        self.transport = transport
        self.server = server # <--- Access to Config, Logger, etc.
        self.session = session # <--- Added this linkage
        
        # This is now redundant since it's in session, but we can keep it for compatibility 
        # or map it to session.stop_ping_event
        self.stop_ping_event = session.stop_ping_event

    def send(self, packet_data: bytes | Packet):
        """
        Sends data. Can accept raw bytes OR a Packet object
        """
        # Type guarding: explicitly separate bytes from Packets
        if isinstance(packet_data, Packet):
            payload = packet_data.serialize()
        else:
            payload = packet_data

        packet_len = len(payload) + 2
        header = struct.pack(">H", packet_len)
        
        try:
            self.transport.sock.sendall(header + payload)
            self.server.logger.log_packet(
                "TCP-SEND", 
                payload, 
                show_ascii=self.server.cfg.debug.show_ascii, 
                include_tcp_len_prefix=True
            )
        except OSError as e:
            print(f"[TCP-ERR] Failed to send packet: {e}")

class UdpContext:
    """Context for a UDP Endpoint (Sessionless or Session-bound)"""
    def __init__(self, transport: UdpTransport, addr: Tuple[str, int], server: WulframServerContext, session: Optional[ClientSession] = None):
        self.transport = transport
        self.addr = addr
        self.server = server # <--- Access to Config, Logger, etc.
        self.session = session # <--- The specific player this packet came from
        self.outgoing_seq = 0
        self.stream_states = {0: 0, 1: 0, 2: 0, 3: 0}

    def send(self, payload: bytes | Packet):
        # Type guarding: explicitly separate bytes from Packets
        if isinstance(payload, Packet):
            payload = payload.serialize()
        else:
            payload = payload

        self.transport.send(payload, self.addr)
        self.server.logger.log_packet("UDP-SEND", 
                                      payload, addr=self.addr, 
                                      show_ascii=self.server.cfg.debug.show_ascii, 
                                      include_tcp_len_prefix=False)

    def send_ack(self, packet_id: int, seq_num: int, subcmd: int = 1):
        """Sends a standard UDP ACK (0x02)"""
        print("send_ack")
        pkt = PacketWriter()
        
        # Wulfram ACK Payload Structure, using the one from handle_ack2 logic:
        # [0x02] [SubCmd] [AckedPacketID] [SeqNum]
        # Note: The old handler logic for send_standard_ack used:
        # [Seq(2)] [Len(2)] [SubCmd(1)] [PacketID(1)] [AckedSeq(2)]?
        
        # Matches Wulfram Reliable ACK structure
        self.outgoing_seq += 1
        pkt.write_int16(self.outgoing_seq) # Our Seq
        pkt.write_int16(9)                 # Len
        pkt.write_byte(subcmd)             # SubCmd
        pkt.write_byte(packet_id)          # Acking Packet ID
        pkt.write_int16(seq_num)           # Acking Seq Num
        
        self.send(b'\x02' + pkt.get_bytes())

# -------------------------------------------------------------------------
# DISPATCHER & HANDLERS
# -------------------------------------------------------------------------

def start_update_loop(ctx: UdpContext):
    def run():
        print(f"[UDP] Starting Global Update Loop")

        TARGET_FPS = 30
        FRAME_TIME = 1.0 / TARGET_FPS
        
        while not ctx.server.stop_update_event.is_set():
            start_time = time.time()

            try:
                # Use SESSION entity
                if ctx.session and ctx.session.entity:
                    my_ent = ctx.session.entity
                    # FIX: Use .get() to avoid KeyError: 4
                    jump_val = my_ent.actions.get(4, 0.0)
                    hover_val = my_ent.actions.get(5, 0.0) # Default to 0!
                    
                    if jump_val >= 1.0:
                        # Apply Jump Velocity (Z axis)
                        # We keep X and Y momentum
                        vx, vy, vz = my_ent.vel
                    
                        # Wake up physics if stopped (Epsilon check)
                        final_x = vx if abs(vx) > 0.01 else 0.001
                        final_y = vy if abs(vy) > 0.01 else 0.001
                        # Apply Jump
                        my_ent.vel = (final_x, final_y, 100.0)
                        my_ent.mark_dirty(UpdateMask.VEL)
                        my_ent.actions[4] = 0.0
                        print(f"Apply Jump Jets! {ent.vel}")
                    """elif abs(hover_val) > 0.01:
                        vx, vy, vz = my_ent.vel
                        final_x = vx if abs(vx) > 0.01 else 0.001
                        final_y = vy if abs(vy) > 0.01 else 0.001
                        
                        my_ent.vel = (final_x, final_y, hover_val * 10.0)
                        my_ent.mark_dirty(UpdateMask.VEL)"""
                    
                    # Todo: just update the local player's tank, no need to get dirty for all entities here
                    update_view_payload = ctx.server.entities.get_dirty_packet_view(sequence_num=get_ticks(), health=0.9, energy=1.0)
                
                    # 3. BROADCAST (Send to this client)
                    if update_view_payload:
                        ctx.send(update_view_payload)

                for ent in ctx.server.entities.get_all():
                    #ent.vel = (ent.vel[0] + 0.5, ent.vel[1] + 0.5, ent.vel[2] + 0.5)
                    #ent.mark_dirty(UpdateMask.VEL | UpdateMask.HEALTH | UpdateMask.ENERGY)
                    #ent.spin = (ent.spin[0] + 0.5, ent.spin[1] + 0.5, ent.spin[2] + 0.5)
                    #ent.mark_dirty(UpdateMask.SPIN)
                    #ent.pos = (ent.pos[0], ent.pos[1], ent.pos[2] + 0.5)
                    #ent.mark_dirty(UpdateMask.POS)
                    # Example: Spin everyone just to test
                    # We preserve X (Roll) and Y (Roll), only modifying Z (Yaw)
                    """current_roll = ent.rot[0]    # Roll
                    current_pitch = ent.rot[1]   # Pitch
                    current_yaw  = ent.rot[2]    # Yaw

                    # Increment Yaw
                    new_yaw = current_yaw + 0.1

                    # Wrap the angle to stay within -PI to +PI
                    # (This prevents it from hitting the 6.3 clamp limit in the config)
                    if new_yaw > math.pi:
                        new_yaw -= 2 * math.pi
                    elif new_yaw < -math.pi:
                        new_yaw += 2 * math.pi

                    # Apply and Mark Dirty
                    ent.rot = (current_roll, current_pitch, new_yaw)
                    ent.mark_dirty(UpdateMask.ROT)"""

                # 2. GATHER DELTAS
                # Pass health and energy/fuel for our local tank
                #ctx.outgoing_seq += 1
                update_payload = ctx.server.entities.get_dirty_packet(sequence_num=get_ticks(), health=0.9, energy=1.0)
                
                # 3. BROADCAST (Send to this client)
                if update_payload:
                    ctx.send(update_payload)
                
            except Exception as e:
                print(f"[ERR] Update Loop: {e}")
                break

            # 3. PRECISE SLEEP
            # Calculates exactly how long to sleep to maintain 10Hz
            elapsed = time.time() - start_time
            sleep_time = max(0.0, FRAME_TIME - elapsed)
            time.sleep(sleep_time)
                
    t = threading.Thread(target=run, daemon=True)
    print("    > Starting Update Loop...")
    t.start()

def start_ping_loop(ctx: TcpContext):
    def run():
        while not ctx.stop_ping_event.is_set():
            try:
                ctx.send(PingRequestPacket())
                ctx.stop_ping_event.wait(10.0)
            except OSError:
                break
            except Exception:
                break
    threading.Thread(target=run, daemon=True).start()

def unknown_packet(ctx, payload: bytes):
    opcode = payload[0]
    
    if opcode in [0x09, 0x0A, 0x0B, 0x0C, 0x10, 0x40, 0x49]:
            return
    
    print(f"[?] Unknown opcode 0x{opcode:02X} (len={len(payload)})")

# Create dispatcher early here
dispatcher = PacketDispatcher(on_unknown=unknown_packet)

# --- TCP Routes ---

@dispatcher.route(0x13)
def on_hello(ctx: TcpContext | UdpContext, payload: bytes):
    if isinstance(ctx, TcpContext):
        log_packet("TCP-RECV", payload)
    elif isinstance(ctx, UdpContext):
        log_packet("UDP-RECV", payload)
    else:
        print("[ERROR] on_hello: Unknown context type")
    
    if len(payload) < 2: return
    reader = PacketReader(payload)
    reader.read_byte() # Op
    subcmd = reader.read_byte()

    if subcmd == 0x00:
        # Client sent Version (Sub 0) - This comes from start_udp_send_hello_root
        # payload usually contains the version int (20105)
        version = reader.read_int32()
        print(f">>> Client HELLO(version) = {version} ~ 0x{version:08X}")
        #ctx.send(HelloPacket.create_version())

    # HELLO subcmd 1: UDP config request/ack
    elif subcmd == 0x01:
        # Client Echoed Key (Sub 1) - This comes from send_hello2

        try:
            client_key = reader.read_string()
        except:
            print(f"[ERROR] on_hello: Failed to read client key")
            return
        
        print(f">>> Client Echoed Key: {client_key}")

        # CASE A: We already have a session (TCP or already linked UDP)
        if ctx.session:
            if client_key == ctx.session.session_key:
                print(f">>> [{type(ctx).__name__}] Key Verified: {client_key}")
                ctx.session.key_echoed_event.set()
                ctx.send(IdentifiedUdpPacket())

        # CASE B: Sessionless UDP Context (This is the new logic)
        elif isinstance(ctx, UdpContext) and ctx.session is None:
            print(f">>> [UDP] Received Key '{client_key}' from unknown {ctx.addr}. Searching...")
            
            # Find the TCP session that generated this key
            found_session = None
            for s in ctx.server.sessions:
                if s.session_key == client_key:
                    found_session = s
                    break
            
            if found_session:
                print(f">>> [UDP] LINKED! {ctx.addr} belongs to {found_session.address}")
                
                # Link everything up
                ctx.session = found_session
                found_session.udp_addr = ctx.addr
                found_session.udp_context = ctx
                
                # Signal Main Thread
                found_session.key_echoed_event.set()
                
                # 3. Reply immediately on UDP
                ctx.send(IdentifiedUdpPacket())
            else:
                print(f"[WARN] UDP Key '{client_key}' matched no active sessions.")

    # HELLO subcmd 2: Not quite sure what this means
    # possibly just confirming the UDP link was verified?
    elif subcmd == 0x02:
        # This comes from send_hello3
        print(">>> Client HELLO(SUBCMD: 2)")

    else:
        print(f">>> Client HELLO unknown subcmd=0x{subcmd:02X}")


@dispatcher.route(0x21)
def on_login_request(ctx: TcpContext, payload: bytes):
    reader = PacketReader(payload)
    reader.read_byte() # Op
    reader.read_byte() # SubCmd
    ctx.session.name = reader.read_string()
    
    print(f">>> Username received via Dispatcher: {ctx.session.name}")
    # Signal the main thread that we have the data
    ctx.session.login_received.set()

@dispatcher.route(0x4E)
def on_bps_request(ctx: TcpContext, payload: bytes):
    log_packet("TCP-RECV", payload)
    if len(payload) >= 5:
        (requested_rate,) = struct.unpack(">I", payload[1:5])
        ctx.send(BpsReplyPacket(requested_rate))
    else:
        print("[WARN] Malformed BPS Request")

@dispatcher.route(0x39)
def on_want_updates(ctx: TcpContext, payload: bytes):
    log_packet("TCP-RECV", payload)
    print(">>> Client is ready for updates (0x39)")
    ctx.send(CommMessagePacket(
                message_type=0,
                source_player_id=ctx.session.player_id, 
                chat_scope_id=0, 
                recepient_id=0, 
                message="Server: Welcome to Wulfram on Wulf-Forge!"
            ))
    ctx.send(CommMessagePacket(
                message_type=0,
                source_player_id=ctx.session.player_id, 
                chat_scope_id=0, 
                recepient_id=0, 
                message="To spawn in type /s spawn"
            ))
    # SEND FULL WORLD SNAPSHOT
    snapshot = ctx.server.entities.get_snapshot_packet(sequence_num=get_ticks(), health=1.0, energy=1.0)
    # We send this over TCP to ensure they get the initial world state reliably
    ctx.send(snapshot)

@dispatcher.route(0x4F)
def on_kudos(ctx: TcpContext, payload: bytes):
    log_packet("TCP-RECV", payload)
    print(">>> !kudos (0x4F)")


# --- UDP Routes ---

@dispatcher.route(0x00)
def on_debug_string(ctx: UdpContext, payload: bytes):
    try:
        msg = payload[2:].decode('ascii', errors='ignore').strip('\x00')
        print(f"    > UDP DEBUG MSG: '{msg}'")
    except: pass

@dispatcher.route(0x02)
def on_ack(ctx: UdpContext, payload: bytes):
    # Just log it
    pass

@dispatcher.route(0x03)
def on_d_handshake(ctx: UdpContext, payload: bytes):
    """
    Handles the UDP Handshake.
    Payload: [0x03] [Time] [ConnID] [StreamCount] ...
    """
    log_packet("RECV-UDP", payload)

    if not ctx.session:
        print("[WARN] Ignored packet from unknown UDP source")
        return

    reader = PacketReader(payload)
    reader.read_byte() # Op
    timestamp = reader.read_int32()
    conn_id = reader.read_int32()
    stream_count = reader.read_int32()
    print(f"    > D_HANDSHAKE: Time={timestamp}, ID={conn_id}, Streams={stream_count}")
    
    # 1. Send Handshake ACK (SubCmd 0)
    pkt = PacketWriter()
    pkt.write_byte(0) # SubCmd
    pkt.write_int32(get_ticks())
    ctx.send(b'\x02' + pkt.get_bytes())

    # 2. Send Our Handshake Definitions
    # (Simplified for brevity, full impl in original udp_handler)
    pkt_hs = PacketWriter()
    pkt_hs.write_int32(get_ticks()) # Server timestamp
    pkt_hs.write_int32(ctx.session.player_id) # Player ID?
    # --- STREAM DEFINITIONS ---
    # We define 4 streams to match the client's expectations
    pkt_hs.write_int32(4) # Def Count

    # Stream 0: Unreliable
    pkt_hs.write_string("Unreliable")
    pkt_hs.write_int32(1) # ID Count
    pkt_hs.write_int32(0) # ID

    # Stream 1: Reliable (Chat/Events)
    pkt_hs.write_string("Reliable")
    pkt_hs.write_int32(1)
    pkt_hs.write_int32(1)

    # Stream 2: Meta/Receipts
    pkt_hs.write_string("Stream 2")
    pkt_hs.write_int32(1)
    pkt_hs.write_int32(2)

    # Stream 3: Game Data (Movement)
    pkt_hs.write_string("Game Data")
    pkt_hs.write_int32(1)
    pkt_hs.write_int32(3)

    # --- STREAM CONFIGURATION ---
    # Set Priorities / Window Sizes
    pkt_hs.write_int32(4) # Config Count
    
    # [StreamID] [Priority]
    pkt_hs.write_int32(0); pkt_hs.write_int32(1)
    pkt_hs.write_int32(1); pkt_hs.write_int32(1)
    pkt_hs.write_int32(2); pkt_hs.write_int32(1)
    pkt_hs.write_int32(3); pkt_hs.write_int32(1)

    ctx.send(b'\x03' + pkt_hs.get_bytes())
    # end handshake

    print("[UDP] Synchronizing Streams...")
    # 3. Unpause Streams (Critical for client to accept data)
    
    # Stream 1
    p1 = PacketWriter()
    p1.write_byte(1) # Stream Id
    p1.write_int16(1) # Sequence
    ctx.send(b'\x04' + p1.get_bytes())

    # Stream 3
    p3 = PacketWriter()
    p3.write_byte(3) # Stream Id
    p3.write_int16(1) # Sequence
    ctx.send(b'\x04' + p3.get_bytes())

@dispatcher.route(0x08)
def on_root_hello(ctx: UdpContext, payload: bytes):
    # Client confirms they heard our TCP "UDP Config" packet
    # This is just a UDP connectivity probe ("Hello There").
    # It contains no ID, so we cannot link it to a session yet.
    ctx.server.logger.log_packet("UDP-RECV (ROOT-HELLO)", payload=payload, show_ascii=True)

@dispatcher.route(0x0B)
def on_client_ping_request(ctx: UdpContext, payload: bytes):
    """
    UDP Packet 0x0B: Client Pinging Server.
    The Client sends this to measure RTT. We must reply with 0x0C.
    """
    if len(payload) < 5: return
    
    reader = PacketReader(payload)
    reader.read_byte() # Op
    
    # 1. Read the timestamp the Client sent us
    client_ts = reader.read_int32()
    
    # 2. Reply with 0x0C (Pong), echoing that timestamp exactly
    w = PacketWriter()
    w.write_int32(client_ts) # Doesn't seem to change the ping in the client no matter what this is set to?
    ctx.send(b'\x0C' + w.get_bytes())
    #print(f"    > Replying to Client Ping (Time: {client_ts})")

@dispatcher.route(0x0C)
def on_udp_ping(ctx: UdpContext, payload: bytes):
    """
    UDP Packet 0x0C: Client Replying to Server.
    This is the response to OUR 0x0B packet (sent via TCP/UDP).
    """
    if len(payload) >= 5:
        reader = PacketReader(payload)
        reader.read_byte() # Op
        # This is the timestamp WE sent originally (Server Time)
        server_ts = reader.read_int32()

        # Calculate RTT for server logs
        rtt = get_ticks() - server_ts

        #print(f"    > Server Ping Confirmed. RTT: {rtt}ms")
        
        # Shouldn't have to echo it back here, since it's a PONG
        #w = PacketWriter()
        #w.write_int32(client_ts)
        #ctx.send(b'\x0C' + w.get_bytes())

@dispatcher.route(0x33)
def on_ack2(ctx: UdpContext, payload: bytes):
    """ Packet 0x33: ACK2 (Response to Process Translation)
        Bytes: [StreamID:2] [SeqID:2] [Status:4]
        payload: [00 01] [00 09] [00 00 00 01]
        The client calls this "ACK2" in process_translation.
        It sends Int32(1) inside.
    """
    print("on_ack2")
    if len(payload) < 5: return
    # Payload: [33] [Seq:2] [Len:2] [Status:4]
    reader = PacketReader(payload)
    reader.read_byte() # Op (33)
    seq = reader.read_int16() # Sequence Num
    length = reader.read_int16() # Packet Len

    status = reader.read_int32() # Seems to always be 1

    print(f"    > RECV ACK2 (Seq {seq} | Len {length}) - Status: {status}")
    
    # Send ACK back to confirm receipt
    ctx.send_ack(packet_id=0x33, seq_num=seq)

@dispatcher.route(0x35)
def on_viewpoint(ctx: UdpContext, payload: bytes):
    """Viewpoint Info"""
    print("on_viewpoint")
    if len(payload) < 5: return
    reader = PacketReader(payload)
    reader.read_byte()
    seq = reader.read_int16()
    # Send ACK
    ctx.send_ack(packet_id=0x35, seq_num=seq)

@dispatcher.route(0x25)
def on_reincarnate(ctx: UdpContext, payload: bytes):
    """Spawn/Team Request"""
    reader = PacketReader(payload)
    reader.read_byte()
    seq = reader.read_int16()
    length = reader.read_int16()
    is_team_switch = reader.read_byte() == 0x01
    # This is team_id if is_team_switch is 1 (true)
    # If is_team_switch is 0 (false) then it's the repair pad's net id
    team_id_or_repaid_pad = reader.read_int32()
    unit_id = reader.read_int32() # Tank or Scout
    
    # [Op] [Seq] [Len] [Data...]
    # Logic to spawn would go here
    
    # Acknowledge
    ctx.send_ack(packet_id=0x25, seq_num=seq)

    # Validate Session
    if not ctx.session:
        print("[WARN] Reincarnate request from sessionless UDP")
        return

    # Check if this is a team switch or spawn request
    if (not is_team_switch):
        unk_int3 = float(reader.read_int32()) # double/float, maybe x cord
        unk_int4 = float(reader.read_int32()) # double/float, maybe y cord

        net_id = team_id_or_repaid_pad
        print(f"    > RECV REINCARNATE (SPAWN REQ): Unit ID: {unit_id} | net_id #{net_id}")
        print(f"    > Unknown values: {unk_int3} | {unk_int4}")
        
        # Find the selected entity (the repair pad they clicked on to spawn in)
        repair_pad = ctx.server.entities.get_entity(net_id)
        if not repair_pad:
            send_system_message(ctx, "Can't find selected spawn point.")
            ctx.send(ReincarnatePacket(code=4)) # Can't enter yet. Game not ready.
            return

        # 1. Create the Entity (Dynamic ID)
        # We DO NOT pass override_net_id, so EntityManager assigns a new unique ID.
        new_entity = ctx.server.entities.create_entity(
            unit_type=unit_id, 
            team_id=ctx.session.team,
            pos=repair_pad.pos,
        )

        # 2. Assign to Session
        # Remove old entity if exists
        if ctx.session.entity:
            ctx.server.entities.remove_entity(ctx, ctx.session.entity.net_id)

        ctx.session.entity = new_entity
        ctx.session.entity.is_manned = True

        # 3. Notify the Client
        send_system_message(ctx, f"Spawning Player #{new_entity.net_id}...")

        # 4. Send TankPacket with the NEW Dynamic ID
        # The client will receive this and now know "I am NetID X"
        pkt = TankPacket(
            net_id=new_entity.net_id, # <--- IMPORTANT: Use the new ID
            sequence_id=get_ticks(),
            tank_cfg=ctx.server.packet_cfg.tank,
            team_id=ctx.session.team,
            unit_type=unit_id,
            pos=repair_pad.pos,
            rot=repair_pad.rot
        )
        ctx.send(pkt)
        
        
        
        # Don't update with anything for now, sending the TankPacket to the player
        # Will create the entity on their end
        #ctx.server.my_entity.pending_mask = 0
        #ctx.server.my_entity.is_manned = True

        #start_update_loop(ctx)
        return

    team_id = team_id_or_repaid_pad
    print(f"    > RECV REINCARNATE (TEAM SWITCH): Team : {team_id}")
    # Switch their teams
    if (team_id == 1):
        ctx.session.team = 1 # Update Session
        broadcast(ctx.server, UpdateStatsPacket(player_id=ctx.session.player_id, team_id=1))
    elif (team_id == 2):
        ctx.session.team = 2 # Update Session
        broadcast(ctx.server, UpdateStatsPacket(player_id=ctx.session.player_id, team_id=2))
    
    # Sends message code about team switched successfully
    ctx.send(ReincarnatePacket(code=17))

@dispatcher.route(0x20)
def on_chat_comm_req(ctx: UdpContext, payload: bytes):
    """
    Packet 0x20: CHAT / COMM REQUEST
    """
    if len(payload) < 10: return
    if not ctx.session:
        print("[WARN] Ignored packet from unknown UDP source")
        return

    reader = PacketReader(payload)
    reader.read_byte() # Op (20)
    sequence_num = reader.read_int16()
    payload_len = reader.read_int16()

    source_scope = reader.read_int16()
    unk_id = reader.read_int16()
    inc_message = reader.read_string()

    print(f"CHAT: id: {unk_id} | source: {source_scope} | message: {inc_message}")
    
    # 1. Update Sequence State (Simplistic)
    #self.stream_states[stream_id] = sequence_num

    print(f"    > RECV RELIABLE (Sequence {sequence_num} | Len {payload_len})")
    
    # 2. SEND ACK
    ctx.send_ack(packet_id=0x20, seq_num=sequence_num)

    if (source_scope == 1): # /s system message
        # Try to process as a command
        found = commands.process(ctx, inc_message)
        
        if not found:
            send_system_message(ctx, "Unknown command.")
    else:
        broadcast_chat(
            server=ctx.server,
            message=inc_message,
            source_player_id=ctx.session.player_id,
            scope_id=source_scope
        )
        """ctx.send(CommMessagePacket(
            message_type=5,
            source_player_id=ctx.session.player_id, 
            chat_scope_id=source, 
            recepient_id=0, 
            message=inc_message
            ))"""
        
        #source = 5 # admin message
        #self.send_chat_message(addr, 5, ctx.server.cfg.player.player_id, source, 0, message)
        #testing spawn and such
        #self.send_update_tick(addr, health_val=1.0, energy_val=1.0)
        #self.send_tank_packet(addr, net_id=ctx.server.cfg.player.player_id, unit_type=0, pos=(100.0, 100.0, 100.0), vel=(0,0,0))
        #self.send_update_tick(addr, health_val=1.0, energy_val=1.0)
        #self.start_update_loop(addr)

@dispatcher.route(0x3A)
def on_beacon_request(ctx: UdpContext, payload: bytes):
    """
    Packet 0x3A: BEACON REQUEST
    """
    if len(payload) < 5: return
    reader = PacketReader(payload)
    reader.read_byte() # Op (3A)
    sequence_num = reader.read_int16()
    payload_len = reader.read_int16()

    some_id = reader.read_int32()

# --- ACTION PARSING ---

def parse_action_packet(ctx: UdpContext, payload: bytes, is_dump: bool):
    """
    Parses ACTION_UPDATE (0x0A) or ACTION_DUMP (0x09).
    Both share the same structure: Count + List of Actions.
    """
    reader = PacketReader(payload)
    reader.read_byte() # Opcode
    
    # 1. Read Header
    count = reader.read_byte() # Number of actions
    
    # These ints are likely timestamps/sequences
    time1 = reader.read_int32()
    time2 = reader.read_int32() 
    
    #print(f"    > ACTION {'DUMP' if is_dump else 'UPDATE'} | Count: {count} | T1: {time1}")

    # 2. Get Configs needed for decoding
    # Config 15: Bits used for the Action ID itself
    cfg_id_bits = get_config_by_index(15) 
    
    # Config 10: Analog Actions (ID 5)
    cfg_analog_5 = get_config_by_index(10)
    
    # Config 11: Analog Actions (Other IDs)
    cfg_analog_std = get_config_by_index(11)

    # Find the entity associated with this connection
    # For now, we assume the session player_id is the entity we control
    #my_entity = ctx.server.entities.get_entity(ctx.server.cfg.player.player_id)

    for _ in range(count):
        # A. Read Action ID
        action_id = reader.read_bits(cfg_id_bits.precision_header_bits)
        
        value = 0.0

        # B. Parse Value based on Action ID logic
        # Digital Action (1 Bit)
        if action_id >= 8 or action_id == 4:
            bit_val = reader.read_bits(1)
            value = 1.0 if bit_val else 0.0
            
        # Upward Thrust (Hover) - SPECIAL CASE
        # Analog Action ID 5 (always uses Config index 10)
        elif action_id == 5:
            value = reader.read_quantized_float(cfg_analog_5)
            
        # Analog Action 0-3, 6-7 (Config 11)
        else:
            value = reader.read_quantized_float(cfg_analog_std)

        # --- UPDATE THE ENTITY ---
        if ctx.session and ctx.session.entity:
            my_ent = ctx.session.entity

            if value != 0.0:
                my_ent.actions[action_id] = value
                #print(f"       Updated Action {action_id} -> {value:.2f}")

            action_names = {
                1: "Turn",
                2: "Forward",
                3: "Stafe",
                4: "JumpJet",
                5: "Hover (Up/Down)", 
            }
            name = action_names.get(action_id, f"Unknown_{action_id}")

        # Log it to verify inputs
        #if value != 0.0:
            #print(f"       Action: {name} [{action_id}]: {value}")

#@dispatcher.route(0x09)
#def on_action_dump(ctx: UdpContext, payload: bytes):
#    parse_action_packet(ctx, payload, is_dump=True)

@dispatcher.route(0x0A)
def on_action_update(ctx: UdpContext, payload: bytes):
    parse_action_packet(ctx, payload, is_dump=False)

# --------------------
# COMMANDS
# --------------------

from core.entity import UpdateMask

@commands.command("jump")
def cmd_jump(ctx, force="80"):
    """
    Applies a vertical velocity impulse to the player.
    Usage: /s jump [force]
    """
    player_id = ctx.server.cfg.player.player_id
    player = ctx.server.entities.get_entity(player_id)
    
    if not player:
        send_system_message(ctx, "Player entity not found.")
        return

    try:
        force_val = float(force)
    except ValueError:
        force_val = 80.0

    # 1. Keep existing X/Y velocity (momentum), but set Z to jump speed
    current_x, current_y, _ = player.vel
    player.vel = (0.001, 0.001, float(force_val))

    # 2. Mark ONLY the VEL flag. 
    # CRITICAL: Do NOT use UpdateMask.HARD_SYNC!
    # If you define UpdateMask.POS, it's fine, but unnecessary for a jump.
    player.mark_dirty(UpdateMask.VEL)
    #player.mark_dirty(UpdateMask.HARD_SYNC)
    
    # 3. (Optional) Force the packet to send immediately
    #ctx.outgoing_seq += 1
    update_payload = ctx.server.entities.get_dirty_packet_view(sequence_num=get_ticks(), health=0.75, energy=0.25)
    if update_payload:
        ctx.send(update_payload)
        
    send_system_message(ctx, "Jump Jets Activated!")

@commands.command("spawn")
def cmd_spawn(ctx, unit_type_str=None):
    """
    Usage:
      /s spawn       -> Spawns the player (self)
      /s spawn 5     -> Spawns an enemy of unit_type 5
    """
    # CASE 1: No arguments -> Spawn Player
    if unit_type_str is None:
        #ctx.outgoing_seq += 1

        pkt = TankPacket(
            net_id=ctx.server.cfg.player.player_id,
            sequence_id=get_ticks(),
            tank_cfg=ctx.server.packet_cfg.tank,
            team_id=ctx.server.player.team,
            pos=(100.0, 100.0, 100.0),
            rot=(0.0, 0.0, 0.0)
        )
        ctx.send(pkt)
        send_system_message(ctx, "Spawning Local Player...")

        #ctx.send(BirthNoticePacket(ctx.server.cfg.player.player_id))

        ctx.server.my_entity = ctx.server.entities.create_entity(
            unit_type=ctx.server.packet_cfg.tank.unit_type, 
            override_net_id=ctx.server.cfg.player.player_id, 
            team_id=ctx.server.player.team,
            pos=(100.0, 100.0, 100.0),
        )
        ctx.server.my_entity.pending_mask = 0
        ctx.server.my_entity.is_manned = True
        #start_update_loop(ctx)
        return

    # CASE 2: Argument provided -> Spawn Enemy/Entity
    try:
        u_type = int(unit_type_str)
    except ValueError:
        send_system_message(ctx, "Invalid Number.")
        return
    
    # Randomize Pos
    v_big = random.uniform(45.0, 85.0)
    v_small = random.uniform(0.0, 10.0)

    # Create via Manager
    # This automatically handles ID generation and marks it as created (Dirty)
    new_ent = ctx.server.entities.create_entity(
        unit_type=u_type, 
        team_id=ctx.server.player.team,
        pos=(80.0 + v_big, 80.0 + v_big, 25.0 + v_small),
    )

    update_payload = ctx.server.entities.get_dirty_packet(health=0.9, energy=0.5)
    if update_payload:
        ctx.send(update_payload)
    
    send_system_message(ctx, f"Spawned Entity #{new_ent.net_id} (Type {u_type})")

@commands.command("list")
def cmd_list(ctx):
    """Lists all active entities."""
    entities = ctx.server.entities.get_all()
    count = len(entities)
    
    send_system_message(ctx, f"--- Entity List ({count}) ---")
    
    if count == 0:
        send_system_message(ctx, "No entities found.")
        return

    for e in entities:
        # Format: [ID: 1] Type: 5 | Pos: 100.0, 100.0, 50.0
        msg = (f"[ID:{e.net_id}] Type:{e.unit_type} | "
               f"Pos: {e.pos[0]:.1f}, {e.pos[1]:.1f}, {e.pos[2]:.1f}")
        send_system_message(ctx, msg)

@commands.command("map")
def cmd_map(ctx, map_name="tron"):
    if not verify_map_land_exists(map_name):
        file_path = _get_map_land_path(map_name)
        send_system_message(ctx, f"Could not find map file at: {file_path}")
        print(f"[MapLoader] File not found: {file_path}")
        return

    destroy_all_entities(ctx)
    time.sleep(0.1)
    
    if (ctx.server.my_entity):
        kill_local_player(ctx)
        time.sleep(0.1) # Wait before we send map change

    ctx.send(WorldStatsPacket(map_name=map_name))
    send_system_message(ctx, f"Changing map to {map_name}...")
    time.sleep(0.1)
    cmd_loadmap(ctx, map_name)

@commands.command("loadmap")
def cmd_loadmap(ctx, map_name="bpass"):
    """
    Loads map entities from: ./shared/data/maps/<map_name>/state
    Usage: /s loadmap bpass
    """
    # 1. Verify the map exists
    if not verify_map_state_exists(map_name):
        # We reconstruct the path here just for the error message
        file_path = _get_map_state_path(map_name)
        send_system_message(ctx, f"Could not find map file at: {file_path}")
        print(f"[MapLoader] File not found: {file_path}")
        return

    # 2. Proceed to load
    file_path = _get_map_state_path(map_name)

    try:
        with open(file_path, "r") as f:
            data = f.read()
        
        # Initialize the loader with the current entity manager
        loader = MapLoader(ctx.server.entities)
        loader.load_from_string(data)
        
        send_system_message(ctx, f"Loaded map state: {map_name}")
        
        # Just send the full snapshot
        #ctx.outgoing_seq += 1
        snapshot = ctx.server.entities.get_snapshot_packet(sequence_num=get_ticks(), health=1.0, energy=1.0)
        ctx.send(snapshot)
        
    except Exception as e:
        print(f"Failed to load map: {e}")
        send_system_message(ctx, "Error loading map.")

@commands.command("reset")
def cmd_reset(ctx):
    ctx.send(ResetGamePacket())
    send_system_message(ctx, "Resetting game...")

@commands.command("die")
def cmd_die(ctx):
    if (ctx.server.my_entity):
        kill_local_player(ctx)
    else:
        send_system_message(ctx, "You may already be dead.")

@commands.command("dock")
def cmd_dock(ctx, state="1"):
    # "dock" -> dock
    # "dock 0" -> undock
    should_dock = (state != "0")
    ctx.send(DockingPacket(entity_id=0, is_docked=should_dock))
    msg = "Docking..." if should_dock else "Undocking..."
    send_system_message(ctx, msg)

@commands.command("carry")
def cmd_carry(ctx, item_id="13"):
    ctx.send(CarryingInfoPacket(
        player_id=ctx.server.cfg.player.player_id,
        has_cargo=True,
        unk_v2=1,
        item_id=int(item_id)
    ))

@commands.command("drop")
def cmd_drop(ctx):
    ctx.send(CarryingInfoPacket(
        player_id=ctx.server.cfg.player.player_id,
        has_cargo=False,
        unk_v2=1,
        item_id=0
    ))

# -------------------------------------------------------------------------
# HELPERS
# -------------------------------------------------------------------------
def send_system_message(ctx: UdpContext | TcpContext, message: str, receipient_id: int = 0):
    ctx.send(CommMessagePacket(
                message_type=0,
                source_player_id=0, #ctx.server.cfg.player.player_id, 
                chat_scope_id=0, 
                recepient_id=receipient_id, 
                message=message
            ))
    
def destroy_all_entities(ctx: UdpContext | TcpContext):
    for e in ctx.server.entities.get_all():
        ctx.server.entities.remove_entity(ctx, e.net_id)

def kill_local_player(ctx: UdpContext | TcpContext):
    if not ctx.session:
        return
    
    if not ctx.session.entity:
        send_system_message(ctx, "You may already be dead.")
        return
    
    player_id = ctx.session.entity.net_id

    # 3. Perform Logic
    # Notify client of death
    ctx.send(DeathNoticePacket(player_id))
    
    # Remove from World
    ctx.server.entities.remove_entity(ctx, player_id)
    send_system_message(ctx, "You died.")

    # 4. Clear Session State
    ctx.session.entity = None

def broadcast(server: WulframServerContext, packet_data: bytes | Packet, exclude_session: ClientSession | None = None):
    """
    Generic broadcaster. Serializes a packet once and sends it to all logged-in players.
    """

    if isinstance(packet_data, Packet):
        payload = packet_data.serialize()
    else:
        payload = packet_data
    
    # We need to frame it for TCP if we fall back, so calculate header once
    tcp_header = struct.pack(">H", len(payload) + 2)

    for session in server.sessions:
        # Skip not logged in or excluded sessions
        if not session.is_logged_in or session == exclude_session:
            continue
            
        try:
            # Prefer UDP (Reliable Stream 1 is typical for game events)
            if session.udp_context:
                session.udp_context.send(payload)
            elif session.tcp_sock:
                session.tcp_sock.sendall(tcp_header + payload)
        except Exception as e:
            print(f"[Broadcast] Error sending to {session.name}: {e}")

def broadcast_chat(server: WulframServerContext, message: str, source_player_id: int, scope_id: int):
    """
    Sends a CommMessagePacket to all connected players (including the sender).
    """
    packet = CommMessagePacket(
        message_type=5, # 5 = User Chat? (0=System, 1=?, 5=Chat)
        source_player_id=source_player_id, 
        chat_scope_id=scope_id, 
        recepient_id=0, 
        message=message
    )
    
    encoded = packet.serialize()
    
    count = 0
    for session in server.sessions:
        # Only send to players who are fully logged in
        if not session.is_logged_in:
            continue
            
        # Prefer UDP for chat (Reliable Stream 1), fallback to TCP if necessary
        try:
            if session.udp_context:
                # We reuse the raw byte payload to avoid re-serializing 50 times
                # Note: UdpContext.send handles framing
                session.udp_context.send(encoded)
                count += 1
            elif session.tcp_sock:
                # If for some reason they have no UDP yet (rare for chat), use TCP
                # We need to manually frame it for TCP if we don't use the wrapper
                # ideally we'd reconstruct a TcpContext, but raw send is easier here:
                # length + payload
                header = struct.pack(">H", len(encoded) + 2)
                session.tcp_sock.sendall(header + encoded)
                count += 1
        except Exception as e:
            print(f"[Broadcast] Failed to send to {session.name}: {e}")
            
    print(f"[Chat] Broadcasted to {count} players.")

def _get_map_state_path(map_name):
    """
    Helper to construct the map file path. 
    Keeps the path definition in one place to avoid bugs.
    """
    return os.path.join("shared", "data", "maps", map_name, "state")

def _get_map_land_path(map_name):
    """
    Helper to construct the map file path. 
    Keeps the path definition in one place to avoid bugs.
    """
    return os.path.join("shared", "data", "maps", map_name, "land")

def verify_map_state_exists(map_name):
    """
    Verifies if the map state file exists.
    Returns: True if exists, False otherwise.
    """
    file_path = _get_map_state_path(map_name)
    return os.path.exists(file_path)

def verify_map_land_exists(map_name):
    """
    Verifies if the map land file exists.
    Returns: True if exists, False otherwise.
    """
    file_path = _get_map_land_path(map_name)
    return os.path.exists(file_path)

# -------------------------------------------------------------------------
# BOOTSTRAP LOGIC
# -------------------------------------------------------------------------

def do_login_and_bootstrap(client_sock: socket.socket, ctx: TcpContext, dispatcher: PacketDispatcher):
    """
    Handles the initial sequence: Hello -> UDP Link -> Login -> World Entry.
    """
    # 1. Send UDP Config (Hello Sub 1)
    print(f"[INFO] Setting session {ctx.session.address} to WAIT for UDP...")
    
    # This let's the client know which ip and port to connect to with UDP
    ctx.send(HelloPacket.create_udp_config(
        port=ctx.server.cfg.network.udp_port, 
        host=ctx.server.cfg.network.server_ip
    ))

    # 2. Send session key to the client
    # The client will then send the session key to the UDP connection
    ctx.send(HelloPacket.create_key(ctx.session.session_key))

    # 3. The Key Exchange Loop
    # We're waiting for the client to send the session key via UDP
    print(">>> Waiting for Client Key Exchange...")
    ctx.session.key_echoed_event.clear()
    
    if (ctx.session.key_echoed_event.wait(timeout=15.0)):
        print(">>> Session key was successfully sent via UDP!")
        # And we have now sent IdentifiedUdpPacket
    else:
        print(">>> [ERROR] Timeout: Session key was NOT sent via UDP.")
        # TODO: probably should just close the connection, or maybe we wait forever?

    # --- Login Flow ---
    print(">>> Waiting for username (LOGIN 0x21)...")
    
    start_wait = time.time()
    
    # Wait for the login_received event (triggered by on_login_request)
    while not ctx.session.login_received.is_set():
        if time.time() - start_wait > 30.0:
            raise ConnectionError("Login Timed Out")

        try:
            payload = ctx.transport.recv_payload()
            if payload:
                dispatcher.dispatch_payload(ctx, payload)
        except socket.timeout:
            pass
            
    print(f">>> Username Found: {ctx.session.name}")

    print(">>> Requesting Password (Status Code 1)...")
    ctx.send(LoginStatusPacket(code=1, is_donor=True))

    print(">>> Waiting for password (LOGIN 0x21)...")
    while True:
        payload = ctx.transport.recv_payload()
        if payload is None:
            raise ConnectionError("Client disconnected during password stage.")
        dispatcher.dispatch_payload(ctx, payload)

        ctx.server.logger.log_packet(
                "TCP-LOGIN", 
                payload, 
                show_ascii=True, 
                include_tcp_len_prefix=True
            )
        
        if payload and payload[0] == 0x21:
            break

    # Assign Unique Player ID
    ctx.session.player_id = ctx.server.get_next_player_id()
    ctx.session.team = 0
    ctx.session.is_logged_in = True
    print(f">>> Login Complete! Assigned Player ID: {ctx.session.player_id}")

    # NOW we send Verified (Hello Sub 3)
    # This tells the client: "UDP is good, Key is good, we're now logged in."
    print(">>> Key Verified. Sending 'Hello Verified' (Sub 3).")

    # Send via UDP if linked, otherwise fallback to TCP
    if ctx.session.udp_context:
        print("    > Sending via UDP (Preferred)")
        ctx.session.udp_context.send(HelloPacket.create_verified())
    else:
        print("    > Sending via TCP (Fallback)")
        ctx.send(HelloPacket.create_verified())

    ctx.send(TeamInfoPacket())
    ctx.send(LoginStatusPacket(code=8, is_donor=True))
    ctx.send(PlayerInfoPacket(ctx.session.player_id, False))
    ctx.send(GameClockPacket())
    ctx.send(MotdPacket(ctx.server.cfg.game.motd))
    ctx.send(BehaviorPacket(ctx.server.packet_cfg.behavior))

    print("[SEND] TRANSLATION (0x32) - Configuration Compression Table...")
    ctx.send(TranslationPacket())
    
    # --- ROSTER SYNC ---
    
    # 1. Create the Roster Packet for THIS new player
    my_roster_pkt = AddToRosterPacket(
        account_id=ctx.session.player_id,
        name=ctx.session.name,
        nametag=ctx.server.cfg.player.nametag,
        team=ctx.session.team
    )

    # 2. Tell ME about MYSELF (so I see myself in the list)
    ctx.send(my_roster_pkt)

    # 3. Tell EVERYONE ELSE about ME
    broadcast(ctx.server, my_roster_pkt, exclude_session=ctx.session)

    # 4. Tell ME about EVERYONE ELSE (Catch up on existing players)
    for other_session in ctx.server.sessions:
        if other_session.is_logged_in and other_session != ctx.session:
            # Create a packet for the existing player
            other_pkt = AddToRosterPacket(
                account_id=other_session.player_id,
                name=other_session.name,
                nametag=ctx.server.cfg.player.nametag,
                team=other_session.team
            )
            print(f"Me: {ctx.session.player_id} | Team: {ctx.session.team} | Other player: {other_session.player_id} | Team: {other_session.team}")
            # Send it to the NEW player (ctx)
            ctx.send(other_pkt)

    ctx.send(WorldStatsPacket(map_name=ctx.server.cfg.game.map_name))

    if (not ctx.server.first_map_load):
        cmd_loadmap(ctx, ctx.server.cfg.game.map_name)
        ctx.server.first_map_load = True

    start_ping_loop(ctx)

def main():
    server = WulframServerContext()
    server.run()

if __name__ == "__main__":
    main()
