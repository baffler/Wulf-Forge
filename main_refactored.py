# main_refactored.py
from __future__ import annotations
import socket
import threading
import time
import struct

from network.transport.tcp_transport import TcpTransport
from network.dispatcher import PacketDispatcher

#from network.streams import PacketWriter
from network.udp_handler import UDPHandler

from core.config import Config
from network.packets.packet_config import PacketConfig
from network.packets import (
    Packet, TankPacket, BehaviorPacket, MotdPacket, 
    GameClockPacket, HelloPacket
)

udp_root_received = threading.Event()

from network.packets.packet_logger import PacketLogger, log_packet

# ---- outgoing packets  ----
from main import (
    send_identified_udp,
    send_login_status, send_team_info, send_player_info,
    send_process_translation, send_add_to_roster, send_world_stats,
    send_bps_reply, send_chat_message, send_ping_request,
    send_ping, handle_hello_packet,
)

class ServerContext:
    """
    Passed to handlers. Keeps sockets/transports and any shared state.
    """
    def __init__(self, tcp: TcpTransport, cfg: Config, packet_cfg: PacketConfig):
        self.tcp = tcp
        self.cfg = cfg
        self.packet_cfg = packet_cfg
        self.stop_ping_event = threading.Event()
        self.logger = PacketLogger()

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
            self.tcp.sock.sendall(header + payload)
            self.logger.log_packet(
                "SEND", 
                payload, 
                show_ascii=self.cfg.debug.show_ascii, 
                include_tcp_len_prefix=True
            )
        except OSError as e:
            print(f"[ERR] Failed to send packet: {e}")

def start_ping_loop(ctx: ServerContext):
    def run():
        while not ctx.stop_ping_event.is_set():
            try:
                send_ping_request(ctx.tcp.sock)   # uses your existing function
                ctx.stop_ping_event.wait(2.0)
            except OSError:
                break
            except Exception:
                break
    threading.Thread(target=run, daemon=True).start()

def unknown_packet(ctx: ServerContext, payload: bytes):
    opcode = payload[0]
    print(f"[TCP] Unknown opcode 0x{opcode:02X} (len={len(payload)})")

# Create dispatcher early here
dispatcher = PacketDispatcher(on_unknown=unknown_packet)

# ------------------ TCP HANDLERS ------------------

@dispatcher.route(0x13)
def on_hello(ctx: ServerContext, payload: bytes):
    log_packet("RECV", payload)
    handle_hello_packet(ctx.tcp.sock, payload)

@dispatcher.route(0x21)
def on_login_request(ctx: ServerContext, payload: bytes):
    # 0x21
    log_packet("RECV", payload)
    # Minimal: do nothing here; your main flow can wait on flags if you want.
    # Or parse it here later (move parsing responsibility into this handler).

@dispatcher.route(0x4E)
def on_bps_request(ctx: ServerContext, payload: bytes):
    log_packet("RECV", payload)
    if len(payload) >= 5:
        (requested_rate,) = struct.unpack(">I", payload[1:5])
        send_bps_reply(ctx.tcp.sock, requested_rate)
    else:
        print("[WARN] Malformed BPS Request")

@dispatcher.route(0x39)
def on_want_updates(ctx: ServerContext, payload: bytes):
    log_packet("RECV", payload)
    print(">>> Client is ready for updates (0x39)")
    send_chat_message(ctx.tcp.sock, "System: Welcome to Wulfram!", source_id=0, target_id=0)
    send_ping_request(ctx.tcp.sock)

@dispatcher.route(0x4F)
def on_kudos(ctx: ServerContext, payload: bytes):
    log_packet("RECV", payload)
    print(">>> !kudos (0x4F)")
    #send_update_array_empty(ctx.tcp.sock)
    send_ping(ctx.tcp.sock)
    send_chat_message(ctx.tcp.sock, "System: Testing Complete.", source_id=0, target_id=0)
    # Spawn the player!
    pkt = TankPacket(
        net_id=1337,
        tank_cfg=ctx.packet_cfg.tank,
        pos=(100.0, 100.0, 100.0),
        vel=(50.0, 0.0, 50.0)
    )
    ctx.send(pkt)

@dispatcher.route(0x0C)
def on_ping(ctx: ServerContext, payload: bytes):
    log_packet("RECV", payload)
    if len(payload) >= 5:
        (client_ts,) = struct.unpack(">I", payload[1:5])
        print(f">>> Client PONG received! TS={client_ts}")
    else:
        print("[WARN] Malformed PING packet")

# ------------------ UDP THREAD ------------------

def udp_server_loop():
    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_sock.bind(("0.0.0.0", 2627))
    print("[UDP] Listening on port 2627")

    handler = UDPHandler(udp_sock, udp_root_received)

    while True:
        data, addr = udp_sock.recvfrom(2048)
        handler.process_packet(data, addr)

# ------------------ MAIN ------------------

def do_login_and_bootstrap(client_sock: socket.socket, ctx: ServerContext, dispatcher: PacketDispatcher):
    udp_root_received.clear()

    time.sleep(1.0)
    
    # This let's the client know which ip and port to connect to with UDP
    ctx.send(HelloPacket.create_udp_config(port=ctx.cfg.network.udp_port, host=ctx.cfg.network.server_ip))

    print("[INFO] Waiting for Client UDP init...")
    if udp_root_received.wait(timeout=5.0):
        print(">>> UDP ROOT Verified! Sending TCP Confirmation.")
        send_identified_udp(client_sock)
    else:
        print("[WARN] UDP Timeout. Sending Confirmation blindly.")
        send_identified_udp(client_sock)

    # Let's the client know they are now verified
    ctx.send(HelloPacket.create_verified())

    # --- Username stage ---
    print(">>> Waiting for USERNAME (0x21)...")
    client_sock.settimeout(None)

    # keep waiting until we see opcode 0x21.
    while True:
        payload = ctx.tcp.recv_payload()
        if payload is None:
            raise ConnectionError("Client disconnected during username stage.")
        dispatcher.dispatch_payload(ctx, payload)
        if payload and payload[0] == 0x21:
            break

    print(">>> Requesting Password (Status Code 1)...")
    send_login_status(client_sock, code=1, is_donor=True)

    print(">>> Waiting for PASSWORD (0x21)...")
    while True:
        payload = ctx.tcp.recv_payload()
        if payload is None:
            raise ConnectionError("Client disconnected during password stage.")
        dispatcher.dispatch_payload(ctx, payload)
        if payload and payload[0] == 0x21:
            break

    print(">>> Login Complete! Granting Access...")
    send_team_info(client_sock)
    send_login_status(client_sock, code=8, is_donor=True)

    send_player_info(client_sock)
    ctx.send(GameClockPacket())
    ctx.send(MotdPacket("Party like it's 1999!"))
    ctx.send(BehaviorPacket(ctx.packet_cfg.behavior))

    send_process_translation(client_sock)
    send_add_to_roster(client_sock, account_id=1337, name="baff")
    send_team_info(client_sock)
    send_world_stats(client_sock)

    start_ping_loop(ctx)

def main():
    cfg = Config.load()
    packet_cfg = PacketConfig.load("packets.toml")

    threading.Thread(target=udp_server_loop, daemon=True).start()

    host = cfg.network.host
    port = cfg.network.tcp_port

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((host, port))
    s.listen(1)
    s.settimeout(1.0)

    print(f"Server listening on {host}:{port}...")

    try:
        while True:
            try:
                client_sock, addr = s.accept()
            except socket.timeout:
                continue

            print(f"\n[+] Client connected from {addr}")

            tcp = TcpTransport(client_sock)
            ctx = ServerContext(tcp, cfg, packet_cfg)

            try:
                do_login_and_bootstrap(client_sock, ctx, dispatcher)

                # Main listen loop
                while True:
                    payload = tcp.recv_payload()
                    if payload is None:
                        break
                    dispatcher.dispatch_payload(ctx, payload)

            except Exception as e:
                print(f"[ERR] Client session ended: {e}")
            finally:
                ctx.stop_ping_event.set()
                try:
                    client_sock.close()
                except Exception:
                    pass

    except KeyboardInterrupt:
        print("\n[!] Stopping server...")
    finally:
        try:
            s.close()
        except Exception:
            pass

if __name__ == "__main__":
    main()
