# main_refactored.py
from __future__ import annotations
import socket
import threading
import time
import struct
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
    GameClockPacket, HelloPacket, TeamInfoPacket,
    TankPacket, BehaviorPacket, TranslationPacket,
    UpdateStatsPacket, CommMessagePacket,
)
from network.packets.packet_logger import PacketLogger, log_packet

# -------------------------------------------------------------------------
# CONTEXTS
# -------------------------------------------------------------------------

class WulframServerContext:
    """
    Holds configuration, the logger, shared state, and controls the sockets.
    """
    def __init__(self):
        self.cfg = Config.load()
        self.packet_cfg = PacketConfig.load("packets.toml")
        self.logger = PacketLogger()

        defaults = self.cfg.player
        self.player = PlayerSession(
            player_id=defaults.player_id,
            name=defaults.name,
            team=defaults.team
        )
        
        # Shared State
        self.udp_root_received = threading.Event()
        self.stop_event = threading.Event()
        
        # Sockets
        self.tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        # Transports
        self.udp_transport: Optional[UdpTransport] = None
        
        # UDP Session Cache (Addr -> UdpContext)
        self.udp_sessions: Dict[Tuple[str, int], UdpContext] = {}

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
        self.tcp_sock.listen(1)
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
                    self.udp_sessions[addr] = UdpContext(transport, addr, self)
                ctx = self.udp_sessions[addr]

                # Parse & Dispatch
                # (UdpTransport handles unpacking batched packets and stripping headers)
                for packet_payload in transport.parse_datagram(data):
                    dispatcher.dispatch_payload(ctx, packet_payload)

            except Exception as e:
                print(f"[UDP-ERR] {e}")

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
                
                # Handle the new TCP client in its own thread or blocking (blocking for now as per original)
                self._handle_tcp_client(client_sock)
                
        except KeyboardInterrupt:
            print("\n[!] Stopping server...")
            self.stop_event.set()
        finally:
            self.tcp_sock.close()
            self.udp_sock.close()

    def _handle_tcp_client(self, client_sock: socket.socket):
        tcp_transport = TcpTransport(client_sock)
        ctx = TcpContext(tcp_transport, self)
        
        try:
            do_login_and_bootstrap(client_sock, ctx, dispatcher)
            
            # Connection Loop
            while True:
                payload = tcp_transport.recv_payload()
                if not payload: break
                dispatcher.dispatch_payload(ctx, payload)
                
        except Exception as e:
            print(f"[-] Client Disconnected: {e}")
        finally:
            ctx.stop_ping_event.set()
            client_sock.close()

class TcpContext:
    """
    Context for a specific TCP Client connection.
    Reference `server` to access global config/state.
    """
    def __init__(self, transport: TcpTransport, server: WulframServerContext):
        self.transport = transport
        self.server = server # <--- Access to Config, Logger, etc.
        self.stop_ping_event = threading.Event()

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
    def __init__(self, transport: UdpTransport, addr: Tuple[str, int], server: WulframServerContext):
        self.transport = transport
        self.addr = addr
        self.server = server # <--- Access to Config, Logger, etc.
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

def start_ping_loop(ctx: TcpContext):
    def run():
        while not ctx.stop_ping_event.is_set():
            try:
                ctx.send(PingRequestPacket())
                ctx.stop_ping_event.wait(2.0)
            except OSError:
                break
            except Exception:
                break
    threading.Thread(target=run, daemon=True).start()

def unknown_packet(ctx, payload: bytes):
    opcode = payload[0]
    print(f"[?] Unknown opcode 0x{opcode:02X} (len={len(payload)})")

# Create dispatcher early here
dispatcher = PacketDispatcher(on_unknown=unknown_packet)

# --- TCP Routes ---

@dispatcher.route(0x13)
def on_hello(ctx: TcpContext, payload: bytes):
    log_packet("TCP-RECV", payload)
    
    if len(payload) < 2: return
    reader = PacketReader(payload)
    reader.read_byte() # Op
    subcmd = reader.read_byte()

    if subcmd == 0x00:
        #version = struct.unpack(">I", body[2:6])[0]
        print(f">>> Client HELLO(version)")# = 0x{version:08X}")

    # HELLO subcmd 1: UDP config request/ack
    elif subcmd == 0x01:
        print(">>> Client HELLO(UDP) received")

    # HELLO subcmd 2: Session key request
    elif subcmd == 0x02:
        print(">>> Client HELLO(SessionKey request) -> sending hello_key now")
        ctx.send(HelloPacket.create_key(ctx.server.cfg.game.session_key))

    else:
        print(f">>> Client HELLO unknown subcmd=0x{subcmd:02X}")


@dispatcher.route(0x21)
def on_login_request(ctx: TcpContext, payload: bytes):
    # 0x21
    log_packet("TCP-RECV", payload)
    # Minimal: do nothing here; flow can wait on flags
    # Or parse it here later (move parsing responsibility into this handler).

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
                source_player_id=ctx.server.cfg.player.player_id, 
                chat_scope_id=0, 
                recepient_id=0, 
                message="Server: Welcome to Wulfram on Wulf-Forge!"
            ))
    ctx.send(CommMessagePacket(
                message_type=0,
                source_player_id=ctx.server.cfg.player.player_id, 
                chat_scope_id=0, 
                recepient_id=0, 
                message="To spawn in type /s spawn"
            ))
    #send_ping_request(ctx.transport.sock)

@dispatcher.route(0x4F)
def on_kudos(ctx: TcpContext, payload: bytes):
    log_packet("TCP-RECV", payload)
    print(">>> !kudos (0x4F)")
    #send_update_array_empty(ctx.tcp.sock)
    #send_ping(ctx.transport.sock)


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
    pkt_hs.write_int32(get_ticks())
    pkt_hs.write_int32(1001) # Player ID
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
def on_hello_ack(ctx: UdpContext, payload: bytes):
    # Client confirms they heard our TCP "UDP Config" packet
    if not ctx.server.udp_root_received.is_set():
        print("    > UDP Link Verified via 0x08.")
        ctx.server.udp_root_received.set()

@dispatcher.route(0x0C)
def on_udp_ping(ctx: UdpContext, payload: bytes):
    """Ping Reply"""
    if len(payload) >= 5:
        reader = PacketReader(payload)
        reader.read_byte() # Op
        ts = reader.read_int32()
        rtt = get_ticks() - ts
        print(f"    > UDP PONG RTT={rtt}ms")
        
        # Echo back
        w = PacketWriter()
        w.write_int32(get_ticks())
        ctx.send(b'\x0C' + w.get_bytes())

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
    team_id = reader.read_int32() # passed as an arg, this is the team id ! red = 1, blue = 2
    unk_int2 = reader.read_int32() # always 0 ?

    print(f"    > RECV REINCARNATE (Sequence {seq} | Len {length}): IsTeamSwitch?: {is_team_switch} | Team Number: {team_id} | {unk_int2}")
    
    # [Op] [Seq] [Len] [Data...]
    # Logic to spawn would go here
    
    # Acknowledge
    ctx.send_ack(packet_id=0x25, seq_num=seq)

    # Check if this is a team switch or spawn request
    if (not is_team_switch):
        unk_int3 = reader.read_int32() # 2000
        unk_int4 = reader.read_int32() # 700

        print(f"    > SPAWN IN? : {unk_int3} | {unk_int4}")
        #self.send_reincarnate(addr, 4, "") #Can't enter yet. Game not ready.
        #self.send_tank_packet(addr, net_id=ctx.server.cfg.player.player_id, unit_type=0, pos=(100.0, 100.0, 100.0), vel=(100.0, 100.0, 100.0))

    # Switch their teams
    # Team 0: is *maybe* a spawn request? Or a request to spawn when there's no repair pads?
    if (team_id == 1):
        ctx.server.player.team = 1
        ctx.send(UpdateStatsPacket(player_id=ctx.server.cfg.player.player_id, team_id=1))
    elif (team_id == 2):
        ctx.server.player.team = 2
        ctx.send(UpdateStatsPacket(player_id=ctx.server.cfg.player.player_id, team_id=2))
    
    #Sends message about team switched successfully
    #self.send_reincarnate(addr, 17, "")

@dispatcher.route(0x20)
def on_chat_comm_req(ctx: UdpContext, payload: bytes):
    """
    Packet 0x20: CHAT / COMM REQUEST
    """
    if len(payload) < 10: return

    reader = PacketReader(payload)
    reader.read_byte() # Op (20)
    sequence_num = reader.read_int16()
    payload_len = reader.read_int16()

    source = reader.read_int16()
    unk_id = reader.read_int16()
    inc_message = reader.read_string()

    print(f"CHAT: id: {unk_id} | source: {source} | message: {inc_message}")
    
    # 1. Update Sequence State (Simplistic)
    #self.stream_states[stream_id] = sequence_num

    print(f"    > RECV RELIABLE (Sequence {sequence_num} | Len {payload_len})")
    
    # 2. SEND ACK
    ctx.send_ack(packet_id=0x20, seq_num=sequence_num)

    if (source == 1): # /s system message
        if (inc_message == "spawn"):
            # Spawn the player!
            pkt = TankPacket(
                net_id=ctx.server.cfg.player.player_id,
                tank_cfg=ctx.server.packet_cfg.tank,
                pos=(100.0, 100.0, 100.0),
                vel=(0.0, 0.0, 0.0)
            )
            ctx.send(pkt)
        else:
            ctx.send(CommMessagePacket(
                message_type=0,
                source_player_id=ctx.server.cfg.player.player_id, 
                chat_scope_id=0, 
                recepient_id=0, 
                message="Unknown command."
            ))
    else:
        ctx.send(CommMessagePacket(
            message_type=5,
            source_player_id=ctx.server.cfg.player.player_id, 
            chat_scope_id=source, 
            recepient_id=0, 
            message=inc_message
            ))
        
        #source = 5 # admin message
        #self.send_chat_message(addr, 5, ctx.server.cfg.player.player_id, source, 0, message)
        #testing spawn and such
        #self.send_update_tick(addr, health_val=1.0, energy_val=1.0)
        #self.send_tank_packet(addr, net_id=ctx.server.cfg.player.player_id, unit_type=0, pos=(100.0, 100.0, 100.0), vel=(0,0,0))
        #self.send_update_tick(addr, health_val=1.0, energy_val=1.0)
        #self.start_update_loop(addr)

# -------------------------------------------------------------------------
# BOOTSTRAP LOGIC
# -------------------------------------------------------------------------

def do_login_and_bootstrap(client_sock: socket.socket, ctx: TcpContext, dispatcher: PacketDispatcher):
    """
    Handles the initial sequence: Hello -> UDP Link -> Login -> World Entry.
    """
    ctx.server.udp_root_received.clear()
    time.sleep(1.0)
    
    # This let's the client know which ip and port to connect to with UDP
    ctx.send(HelloPacket.create_udp_config(
        port=ctx.server.cfg.network.udp_port, 
        host=ctx.server.cfg.network.server_ip))

    print("[INFO] Waiting for Client UDP init...")
    if ctx.server.udp_root_received.wait(timeout=5.0):
        print(">>> UDP ROOT Verified! Sending TCP Confirmation.")
        ctx.send(IdentifiedUdpPacket())
    else:
        print("[WARN] UDP Timeout. Sending Confirmation blindly.")
        ctx.send(IdentifiedUdpPacket())

    # Let's the client know they are now verified
    ctx.send(HelloPacket.create_verified())

    # --- Login Flow ---
    print(">>> Waiting for username (LOGIN 0x21)...")
    client_sock.settimeout(None)

    # keep waiting until we see opcode 0x21.
    while True:
        payload = ctx.transport.recv_payload()
        if payload is None:
            raise ConnectionError("Client disconnected during username stage.")
        dispatcher.dispatch_payload(ctx, payload)
        if payload and payload[0] == 0x21:
            pktl = PacketReader(payload)
            pktl.read_byte() # Op
            pktl.read_byte() # SubCmd
            ctx.server.player.name = pktl.read_string()
            print(f">>> Username: {ctx.server.player.name}")
            break

    print(">>> Requesting Password (Status Code 1)...")
    ctx.send(LoginStatusPacket(code=1, is_donor=True))

    print(">>> Waiting for password (LOGIN 0x21)...")
    while True:
        payload = ctx.transport.recv_payload()
        if payload is None:
            raise ConnectionError("Client disconnected during password stage.")
        dispatcher.dispatch_payload(ctx, payload)
        if payload and payload[0] == 0x21:
            break

    print(">>> Login Complete!")
    ctx.send(TeamInfoPacket())
    ctx.send(LoginStatusPacket(code=8, is_donor=True))
    ctx.send(PlayerInfoPacket(ctx.server.cfg.player.player_id, False))
    ctx.send(GameClockPacket())
    ctx.send(MotdPacket(ctx.server.cfg.game.motd))
    ctx.send(BehaviorPacket(ctx.server.packet_cfg.behavior))

    ctx.send(TranslationPacket())

    # TODO: check if this is actually team, since this is sent before we select a team
    ctx.send(AddToRosterPacket(
        account_id=ctx.server.cfg.player.player_id, 
        name=ctx.server.player.name,
        nametag=ctx.server.cfg.player.nametag,
        team=ctx.server.player.team))

    ctx.send(WorldStatsPacket(map_name=ctx.server.cfg.game.map_name))

    start_ping_loop(ctx)

def main():
    server = WulframServerContext()
    server.run()

if __name__ == "__main__":
    main()
