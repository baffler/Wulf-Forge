# main_refactored.py
from __future__ import annotations
import socket
import threading
import time
import struct

from network.transport.tcp_transport import TcpTransport
from network.registry import PacketRegistry
from network.dispatcher import PacketDispatcher

from network.streams import PacketWriter
from network.udp_handler import UDPHandler

from config import Config
from packet_config import PacketConfig
from network.packets.tank import build_tank_payload
from network.packets.behavior import build_behavior_payload

HOST = "127.0.0.1"
PORT = 2627
SESSION_KEY = "WulframSessionKey123"

udp_root_received = threading.Event()

from network.packets.packet_logger import PacketLogger, log_packet

# ---- outgoing packets (leave as free functions for now) ----
from main import (
    send_hello_udp, send_identified_udp, send_hello_final,
    send_login_status, send_team_info, send_player_info,
    send_game_clock, send_motd, send_behavior_packet,
    send_process_translation, send_add_to_roster, send_world_stats,
    send_bps_reply, send_chat_message, send_ping_request,
    send_update_array_empty, send_ping, send_tank_packet,
    handle_hello_packet,
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

def send_tcp(sock: socket.socket, logger: PacketLogger, payload: bytes, *, show_ascii: bool) -> None:
    # TCP framing: 2-byte big-endian length includes the header itself
    packet_len = len(payload) + 2
    header = struct.pack(">H", packet_len)
    sock.sendall(header + payload)

    # payload already includes opcode as first byte
    logger.log_packet("SEND", payload, show_ascii=show_ascii, include_tcp_len_prefix=True)

def unknown_packet(ctx: ServerContext, payload: bytes):
    opcode = payload[0]
    print(f"[TCP] Unknown opcode 0x{opcode:02X} (len={len(payload)})")

# ------------------ TCP HANDLERS ------------------

def on_hello(ctx: ServerContext, payload: bytes):
    # Let your existing logic consume it.
    # If it handled it, it may send hello_key, etc.
    log_packet("RECV", payload)
    handle_hello_packet(ctx.tcp.sock, payload)

def on_login_request(ctx: ServerContext, payload: bytes):
    # This is 0x21 in your code; you currently treat both username and password as 0x21.
    log_packet("RECV", payload)
    # Minimal: do nothing here; your main flow can wait on flags if you want.
    # Or parse it here later (move parsing responsibility into this handler).

def on_bps_request(ctx: ServerContext, payload: bytes):
    log_packet("RECV", payload)
    if len(payload) >= 5:
        (requested_rate,) = struct.unpack(">I", payload[1:5])
        send_bps_reply(ctx.tcp.sock, requested_rate)
    else:
        print("[WARN] Malformed BPS Request")

def on_want_updates(ctx: ServerContext, payload: bytes):
    log_packet("RECV", payload)
    print(">>> Client is ready for World Updates (0x39)")
    send_chat_message(ctx.tcp.sock, "System: Welcome to Wulfram!", source_id=0, target_id=0)
    send_ping_request(ctx.tcp.sock)

def on_kudos(ctx: ServerContext, payload: bytes):
    log_packet("RECV", payload)
    print(">>> !kudos (0x4F)")
    send_update_array_empty(ctx.tcp.sock)
    send_ping(ctx.tcp.sock)
    send_chat_message(ctx.tcp.sock, "System: Testing Complete.", source_id=0, target_id=0)
    #send_tank_packet(ctx.tcp.sock, net_id=1337, unit_type=0, pos=(100.0, 100.0, 100.0), vel=(100.0, 100.0, 100.0))
    payload = build_tank_payload(
        net_id=1337,
        tank_cfg=ctx.packet_cfg.tank,
        pos=(100.0, 100.0, 100.0),
        vel=(100.0, 100.0, 100.0),
    )
    send_tcp(ctx.tcp.sock, ctx.logger, payload, show_ascii=ctx.cfg.debug.show_ascii)


def on_ping(ctx: ServerContext, payload: bytes):
    log_packet("RECV", payload)
    if len(payload) >= 5:
        (client_ts,) = struct.unpack(">I", payload[1:5])
        print(f">>> Client PONG received! TS={client_ts}")
    else:
        print("[WARN] Malformed PING packet")

def build_registry() -> PacketRegistry:
    reg = PacketRegistry()
    reg.register(0x13, on_hello)
    reg.register(0x21, on_login_request)
    reg.register(0x4E, on_bps_request)
    reg.register(0x39, on_want_updates)
    reg.register(0x4F, on_kudos)
    reg.register(0x0C, on_ping)
    return reg

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
    # Keep your existing “server speaks first” sequence
    udp_root_received.clear()

    time.sleep(1.0)
    send_hello_udp(client_sock, PORT)

    print("[INFO] Waiting for Client UDP init...")
    if udp_root_received.wait(timeout=5.0):
        print(">>> UDP ROOT Verified! Sending TCP Confirmation.")
        send_identified_udp(client_sock)
    else:
        print("[WARN] UDP Timeout. Sending Confirmation blindly.")
        send_identified_udp(client_sock)

    send_hello_final(client_sock)

    # --- Username stage ---
    print(">>> Waiting for USERNAME (0x21)...")
    client_sock.settimeout(None)

    # Minimal approach: keep waiting until we see opcode 0x21.
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
    send_game_clock(client_sock)
    send_motd(client_sock, "Party like it's 1999!")
    #send_behavior_packet(client_sock)
    behavior_payload = build_behavior_payload(ctx.packet_cfg.behavior)
    send_tcp(ctx.tcp.sock, ctx.logger, behavior_payload, show_ascii=ctx.cfg.debug.show_ascii)

    send_process_translation(client_sock)
    send_add_to_roster(client_sock, account_id=1337, name="baff")
    send_team_info(client_sock)
    send_world_stats(client_sock)

    start_ping_loop(ctx)

def main():
    cfg = Config()
    packet_cfg = PacketConfig()

    threading.Thread(target=udp_server_loop, daemon=True).start()

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((HOST, PORT))
    s.listen(1)
    s.settimeout(1.0)

    reg = build_registry()
    dispatcher = PacketDispatcher(reg, on_unknown=unknown_packet)

    print(f"Server listening on {HOST}:{PORT}...")

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
