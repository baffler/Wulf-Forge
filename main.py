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
import ipaddress
import queue
from typing import Dict, Tuple, Optional

from network.transport.tcp_transport import TcpTransport
from network.transport.udp_transport import UdpTransport

from network.dispatcher import PacketDispatcher
from network.streams import PacketWriter, PacketReader

from core.config import Config, PlayerSession, get_ticks
from core.logging_config import setup_logging
from network.packets.packet_config import PacketConfig
from network.packets import (
    Packet, MotdPacket, IdentifiedUdpPacket, LoginStatusPacket, PlayerInfoPacket,
    BpsReplyPacket, PingRequestPacket, AddToRosterPacket, RemoveFromRosterPacket,
    WorldStatsPacket, ResetGamePacket, DeleteObjectPacket,
    DeathNoticePacket, BirthNoticePacket, CarryingInfoPacket, DockingPacket, 
    GameClockPacket, HelloPacket, TeamInfoPacket, ReincarnatePacket,
    TankPacket, BehaviorPacket, TranslationPacket,
    UpdateStatsPacket, CommMessagePacket, parse_reincarnate_request,
)
from network.packets.packet_logger import PacketLogger, log_packet

from core.entity import GameEntity, UpdateMask
from core.entity_manager import EntityManager
from core.cargo import CargoSystem, CARGO_BOX_UNIT_TYPE
from core.sim.tank import TankSim
from core.sim.inputs import controls_from_actions
from core.sim.terrain import load_map_heightmap
from core.map_loader import MapLoader, ensure_team_repair_pads, resolve_spawn_entry
from core.commands import commands
from network.packets.update_array import UpdateArrayPacket
from network.translation_config import get_config_by_index, GLOBAL_CONFIGS
from mod_relay.listener import ModStateRelayListener
from mod_relay.packets import ClientStateV1
from mod_relay.state_apply import apply_mod_client_state

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

        # Gate flag for the global loop
        self.is_ready_for_updates: bool = False
        
        # UDP Linkage
        self.udp_addr: Optional[Tuple[str, int]] = None
        self.udp_context: Optional[UdpContext] = None

        # W2Mod relay debug identity. These best-effort bindings are for
        # local/LAN owner-authoritative testing, not authentication.
        self.mod_relay_addr: Optional[Tuple[str, int]] = None
        self.mod_relay_local_entity: int = 0
        self.mod_relay_packet_player_id: int = 0
        self.mod_relay_bound_at: float = 0.0
        self.mod_relay_last_seen_at: float = 0.0
        self.mod_relay_last_spawned_at: float = 0.0
        self.mod_relay_binding_reason: str = ""
        
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
        
        if (self.is_logged_in):
            broadcast(self.server, RemoveFromRosterPacket(self.player_id))

        if self.entity:
            del_pkt = self.server.entities.remove_entity(net_id=self.entity.net_id)
            if (del_pkt is not None): broadcast(self.server, del_pkt)

class WulframServerContext:
    """
    Holds configuration, the logger, shared state, and controls the sockets.
    """
    def __init__(self):
        self.cfg = Config.load()
        self.packet_cfg = PacketConfig.load("packets.toml")
        self.logger = PacketLogger()
        if self.cfg.debug.log_all_opcodes:
            # Log every opcode (including per-tick traffic). Lines are teed to
            # the logs/ file by setup_logging, so this captures all to disk.
            self.logger.spam_opcodes = set()
        self.entities = EntityManager()
        self.cargo = CargoSystem(
            self.entities,
            pickup_radius=self.packet_cfg.cargo.pickup_radius,
            ground_z=self.packet_cfg.cargo.ground_z,
        )
        self.tank_sim = TankSim(self.packet_cfg)
        self.first_map_load = False
        self.current_map_name = self.cfg.game.map_name
        self.refresh_sim_terrain()

        # Session Management
        self.sessions: list[ClientSession] = []
        self.mod_state_queue: queue.SimpleQueue[tuple[ClientSession, ClientStateV1]] = queue.SimpleQueue()
        self.mod_relay_listener: Optional[ModStateRelayListener] = None
        self.mod_relay_dirty_entity_ids: set[int] = set()
        self.mod_relay_entity_updates: dict[int, dict] = {}
        self._last_mod_broadcast_log = 0.0
        self._last_mod_coalesce_log = 0.0

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

        # Global Game Thread
        game_thread = threading.Thread(target=global_game_loop, args=(self,), daemon=True)
        game_thread.start()

    def get_next_player_id(self) -> int:
        """Generates a unique Player/Account ID."""
        pid = self._next_player_id
        self._next_player_id += 1
        return pid

    def refresh_sim_terrain(self, map_name: str | None = None) -> None:
        """Load the current map's heightmap into the tank sim (flat if absent)."""
        name = map_name or self.current_map_name
        hm = load_map_heightmap(name)
        if hm is not None:
            self.tank_sim.set_terrain(hm)
            print(f"[Sim] terrain heightmap loaded for '{name}' "
                  f"({hm.gw}x{hm.gh} over {hm.world_w:.0f}x{hm.world_h:.0f}).")
        else:
            print(f"[Sim] no land heightmap for '{name}'; tank sim uses flat terrain.")

    def enqueue_mod_client_state(self, session: ClientSession, state: ClientStateV1) -> None:
        self.mod_state_queue.put((session, state))

    def run(self):
        """Starts the UDP listener thread and the TCP accept loop."""
        # 1. Setup UDP
        self.udp_sock.bind((self.cfg.network.host, self.cfg.network.udp_port))
        self.udp_transport = UdpTransport(self.udp_sock)
        print(f"[UDP] Listening on port {self.cfg.network.udp_port}")
        
        # Start UDP Thread
        udp_thread = threading.Thread(target=self._udp_loop, daemon=True)
        udp_thread.start()

        if should_accept_client_state_relay(self):
            self.mod_relay_listener = ModStateRelayListener(
                host=self.cfg.network.host,
                port=self.cfg.mod_relay.port,
                server=self,
            )
            self.mod_relay_listener.start()
        else:
            print("[mod-relay] disabled by sync mode")

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
            self.stop_event.set()
            self.stop_update_event.set()
            if self.mod_relay_listener:
                self.mod_relay_listener.stop()
            try:
                self.tcp_sock.close()
            except OSError:
                pass
            try:
                self.udp_sock.close()
            except OSError:
                pass

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

SYNC_MODE_SERVER_SIMULATION = "server_simulation"
SYNC_MODE_CLIENT_STATE_RELAY = "client_state_relay"
VALID_SYNC_MODES = {SYNC_MODE_SERVER_SIMULATION, SYNC_MODE_CLIENT_STATE_RELAY}


def get_sync_mode(server: WulframServerContext) -> str:
    sync_cfg = getattr(getattr(server, "cfg", None), "sync", None)
    mode = str(getattr(sync_cfg, "mode", SYNC_MODE_SERVER_SIMULATION) or "").strip().lower()
    if mode not in VALID_SYNC_MODES:
        return SYNC_MODE_SERVER_SIMULATION
    return mode


def should_run_server_simulation(server: WulframServerContext) -> bool:
    return get_sync_mode(server) == SYNC_MODE_SERVER_SIMULATION


def should_accept_client_state_relay(server: WulframServerContext) -> bool:
    return get_sync_mode(server) == SYNC_MODE_CLIENT_STATE_RELAY


def _drain_mod_state_queue(server: WulframServerContext, max_updates: int = 256) -> None:
    relay_cfg = getattr(server.cfg, "mod_relay", None)
    coalesce_updates = True if relay_cfg is None else getattr(relay_cfg, "coalesce_updates", True)

    if coalesce_updates:
        latest_by_session: dict[ClientSession, ClientStateV1] = {}
        drained = 0
        for _ in range(max_updates):
            try:
                session, state = server.mod_state_queue.get_nowait()
            except queue.Empty:
                break

            drained += 1
            latest_by_session[session] = state

        if drained > len(latest_by_session) and latest_by_session:
            now = time.monotonic()
            if now - server._last_mod_coalesce_log >= 5.0:
                server._last_mod_coalesce_log = now
                print(
                    "[mod-relay] coalesced queued states "
                    f"drained={drained} applied_latest={len(latest_by_session)}"
                )

        for session, state in latest_by_session.items():
            _apply_queued_mod_state(server, session, state)
        return

    for _ in range(max_updates):
        try:
            session, state = server.mod_state_queue.get_nowait()
        except queue.Empty:
            return

        _apply_queued_mod_state(server, session, state)


def _apply_queued_mod_state(server: WulframServerContext, session: ClientSession, state: ClientStateV1) -> None:
    if session not in server.sessions or not session.is_logged_in:
        return

    if apply_mod_client_state(server, session, state):
        if session.entity is not None:
            previous_update = server.mod_relay_entity_updates.get(session.entity.net_id, {})
            apply_count = int(previous_update.get("apply_count", 0) or 0) + 1
            server.mod_relay_dirty_entity_ids.add(session.entity.net_id)
            server.mod_relay_entity_updates[session.entity.net_id] = {
                "monotonic": time.monotonic(),
                "sequence": state.sequence,
                "client_tick_ms": state.client_tick_ms,
                "local_entity": state.local_entity,
                "player_id": state.player_id,
                "mapping_reason": getattr(session, "mod_relay_binding_reason", ""),
                "apply_count": apply_count,
                "hard_sync": bool(session.entity.pending_mask & UpdateMask.HARD_SYNC),
                "hard_sync_reason": getattr(session, "mod_relay_last_hard_sync_reason", ""),
            }
        if server.mod_relay_listener:
            server.mod_relay_listener.note_applied(session, state)
    elif server.mod_relay_listener:
        server.mod_relay_listener.note_rejected_apply(session, state)


def reset_mod_relay_binding(session: ClientSession, reason: str) -> None:
    previous_addr = getattr(session, "mod_relay_addr", None)
    previous_local_entity = getattr(session, "mod_relay_local_entity", 0)
    previous_packet_player_id = getattr(session, "mod_relay_packet_player_id", 0)

    session.mod_relay_addr = None
    session.mod_relay_local_entity = 0
    session.mod_relay_packet_player_id = 0
    session.mod_relay_bound_at = 0.0
    session.mod_relay_last_seen_at = 0.0
    session.mod_relay_binding_reason = ""

    relay_cfg = getattr(getattr(session, "server", None), "cfg", None)
    relay_cfg = getattr(relay_cfg, "mod_relay", None)
    identity_trace = True if relay_cfg is None else getattr(relay_cfg, "identity_trace", True)
    if identity_trace and (previous_addr is not None or previous_local_entity or previous_packet_player_id):
        print(
            "[mod-relay] identity reset "
            f"reason={reason} session_player_id={session.player_id} "
            f"old_addr={previous_addr} old_packet_player_id={previous_packet_player_id} "
            f"old_local_entity=0x{previous_local_entity:08X}"
        )


def note_mod_relay_entity_spawn(session: ClientSession, entity: GameEntity, source: str) -> None:
    session.mod_relay_last_spawned_at = time.monotonic()
    reset_mod_relay_binding(session, f"{source}_spawn")

    relay_cfg = getattr(getattr(session, "server", None), "cfg", None)
    relay_cfg = getattr(relay_cfg, "mod_relay", None)
    identity_trace = True if relay_cfg is None else getattr(relay_cfg, "identity_trace", True)
    if identity_trace:
        tcp_addr = getattr(session, "address", None)
        udp_addr = getattr(session, "udp_addr", None)
        print(
            "[mod-relay] identity spawn "
            f"source={source} session_player_id={session.player_id} "
            f"session_entity_net_id={entity.net_id} tcp_addr={tcp_addr} "
            f"udp_addr={udp_addr}"
        )


def send_existing_player_entity_definitions(ctx: TcpContext | UdpContext, reason: str) -> bool:
    """Replay existing player entity definitions to a newly spawned client.

    This is a join-in-progress catch-up path. It does not depend on dirty flags,
    because already-spawned player entities may have cleared their DEFINITION bit
    before this client entered the world.
    """
    session = getattr(ctx, "session", None)
    if session is None or session.entity is None:
        return False

    players_by_entity_id: dict[int, tuple[int, GameEntity]] = {}
    for other_session in ctx.server.sessions:
        if other_session is session or not other_session.is_logged_in:
            continue

        entity = getattr(other_session, "entity", None)
        if entity is None or not getattr(entity, "is_manned", False):
            continue

        players_by_entity_id[entity.net_id] = (other_session.player_id, entity)

    if not players_by_entity_id:
        return False

    target_ctx = session.udp_context or ctx
    players = sorted(players_by_entity_id.values(), key=lambda item: item[1].net_id)
    entities = [entity for _player_id, entity in players]

    # Replay birth notices because late joiners missed the original spawn-time
    # broadcast. The current spawn path uses player_id here.
    for player_id, _entity in players:
        target_ctx.send(BirthNoticePacket(player_id))

    forced_mask = (
        UpdateMask.DEFINITION
        | UpdateMask.POS
        | UpdateMask.VEL
        | UpdateMask.ROT
        | UpdateMask.HEALTH
    )
    local_stats = (session.entity.health, session.entity.energy)
    payload = ctx.server.entities.build_forced_update_packet(
        entities,
        sequence_num=get_ticks(),
        is_view_update=False,
        forced_mask=forced_mask,
        local_stats=local_stats,
        force_spawn=True,
    )
    if not payload:
        return False

    target_ctx.send(b"\x0E" + payload)
    ids = ",".join(str(entity.net_id) for entity in entities)
    print(
        "[sync] sent late-join entity definitions "
        f"reason={reason} to_player={session.player_id} entities={ids}"
    )
    return True


def cargo_pickup_tick(server: WulframServerContext) -> list:
    """Collect automatic cargo pickups for all in-world players this tick.

    Server-authoritative and independent of the sync mode: it runs in both
    server_simulation and client_state_relay (the relay updates entity.pos,
    so proximity is evaluated against the player's live position). Returns the
    packets to broadcast (CARRYING_INFO + DeleteObject per pickup).
    """
    packets = []
    for session in server.sessions:
        if session.entity and session.is_logged_in:
            packets.extend(
                server.cargo.try_pickup(session.entity, session.player_id)
            )
    return packets

def player_sim_tick(server: WulframServerContext, dt: float) -> None:
    """Integrate every in-world player's tank from its inputs (server-authoritative).

    Single writer of simulated state; runs only in server_simulation mode.
    """
    phys_debug = getattr(server.cfg.debug, "debug_physics_sim", False)
    for session in server.sessions:
        if session.entity and session.is_logged_in:
            ent = session.entity
            server.tank_sim.step(ent, dt)
            if phys_debug:
                # Dump EVERY non-zero action id (not just the mapped 4) so we can
                # see which channel actually carries turn/aim when driving.
                active = {k: round(v, 2) for k, v in ent.actions.items() if abs(v) > 0.001}
                if active:
                    inp = controls_from_actions(ent.actions)
                    print(
                        f"[PHYS-SIM] pid={session.player_id} net_id={ent.net_id} "
                        f"actions={active} "
                        f"-> in(thr={inp.throttle:+.2f} turn={inp.turn:+.2f} "
                        f"str={inp.strafe:+.2f} vert={inp.vertical:+.2f}) "
                        f"pos=({ent.pos[0]:.1f},{ent.pos[1]:.1f},{ent.pos[2]:.1f}) "
                        f"vel=({ent.vel[0]:.1f},{ent.vel[1]:.1f},{ent.vel[2]:.1f}) "
                        f"yaw={ent.rot[2]:+.3f}"
                    )

def global_game_loop(server: WulframServerContext):
    """
    Main Server Tick (Targeting ~10Hz).
    Updates physics, processes inputs, and broadcasts distinct views to clients.
    """
    print("[Server] Starting Global Game Loop...")
    TARGET_FPS = 10
    FRAME_TIME = 1.0 / TARGET_FPS
    STATIC_ANCHOR_INTERVAL = 0.5
    last_static_anchor_time = 0.0

    while not server.stop_update_event.is_set():
        start_time = time.time()

        if should_accept_client_state_relay(server):
            _drain_mod_state_queue(server)
        
        if should_run_server_simulation(server):
            # --- 1. Server-authoritative tank simulation ---
            player_sim_tick(server, dt=FRAME_TIME)
            # --- 1. Process Inputs (Physics/Actions) ---
            # Apply actions (jump/hover) for every active player
            for session in server.sessions:
                if session.entity and session.is_logged_in:
                    my_ent = session.entity
                    
                    # Example: Jump Logic (from your previous code)
                    jump_val = my_ent.actions.get(4, 0.0)
                    if jump_val >= 1.0:
                        vx, vy, _ = my_ent.vel
                        # Apply Jump Velocity (Z axis)
                        final_x = vx if abs(vx) > 0.01 else 0.001
                        final_y = vy if abs(vy) > 0.01 else 0.001

                        my_ent.vel = (final_x, final_y, 100.0)
                        my_ent.mark_dirty(UpdateMask.VEL)
                        my_ent.actions[4] = 0.0 # Reset trigger

        # --- 1b. Cargo pickup scan ---
        # Server-authoritative and mode-independent: runs in BOTH server
        # simulation and client_state_relay. A slow/low uncarried vehicle near
        # a cargo box grabs it -> CARRYING_INFO (0x29) + DeleteObject.
        for pkt in cargo_pickup_tick(server):
            broadcast(server, pkt)

        # --- 2. Gather Dirty State ---
        # We get the list ONCE. The state remains valid for all clients.
        dirty_entities = server.entities.get_dirty_entities()
        current_tick = get_ticks()
        static_anchor_due = False

        if start_time - last_static_anchor_time >= STATIC_ANCHOR_INTERVAL:
            static_anchor_due = True
            last_static_anchor_time = start_time

        # --- 3. Broadcast Loop ---
        sim_mode = should_run_server_simulation(server)
        phys_debug = getattr(server.cfg.debug, "debug_physics_sim", False)
        correct_owner = getattr(server.cfg.debug, "correct_owner_in_sim", False)
        if dirty_entities or static_anchor_due:
            for session in server.sessions:
                # CHECK: Must be logged in AND ready for updates
                if not session.is_logged_in or not session.is_ready_for_updates:
                    continue

                # Skip players who aren't fully in the world yet
                if not session.is_logged_in or not session.udp_context or not session.entity:
                    continue
                
                my_entity = session.entity

                # Always gather local stats for THIS session
                # If we send a packet without this, the client HUD might zero out.
                my_stats = (my_entity.health, my_entity.energy)
                
                # --- A. PACKET FOR "OTHERS" (0x0E - Update Array) ---
                # Filter: Send updates for everyone who is NOT me
                others = [e for e in dirty_entities if e.net_id != my_entity.net_id]
                
                if others:
                    # We MUST pass local_stats here, even though it's an update for "others"
                    payload = server.entities.build_update_packet(
                        others, 
                        sequence_num=current_tick, 
                        is_view_update=False,
                        local_stats=my_stats
                    )
                    if payload:
                        # Prepend OpCode 0x0E
                        session.udp_context.send(b'\x0E' + payload)

                # --- B. PACKET FOR "SELF" (0x0F - View Update) ---
                if my_entity in dirty_entities:
                    if sim_mode and not correct_owner:
                        # Server-authoritative tank sim is APPROXIMATE; echoing the
                        # owner's own simulated pos/vel/rot back every tick fights the
                        # client's local prediction (wobble / can't-turn). The client
                        # owns its own tank view; send only a stats-only view update so
                        # the HUD stays synced. Other players still receive this tank
                        # via the 0x0E "others" packet above.
                        stats_payload = server.entities.build_update_packet(
                            [],
                            sequence_num=current_tick,
                            is_view_update=True,
                            local_stats=(my_entity.health, my_entity.energy),
                        )
                        if stats_payload:
                            session.udp_context.send(b'\x0F' + stats_payload)
                        if phys_debug:
                            print(
                                f"[PHYS-SIM] owner-correction SUPPRESSED pid={session.player_id} "
                                f"net_id={my_entity.net_id} "
                                f"sim_pos=({my_entity.pos[0]:.1f},{my_entity.pos[1]:.1f},{my_entity.pos[2]:.1f}) "
                                f"yaw={my_entity.rot[2]:+.3f} (client predicts locally; stats-only sent)"
                            )
                    else:
                        skip_owner_echo = (
                            my_entity.net_id in server.mod_relay_dirty_entity_ids
                            and not server.cfg.mod_relay.echo_owner_state
                        )
                        if not skip_owner_echo:
                            # Build payload (Includes Timestamp, Includes Local Stats)
                            stats = (my_entity.health, my_entity.energy)

                            payload = server.entities.build_update_packet(
                                [my_entity],
                                sequence_num=current_tick,
                                is_view_update=True,
                                local_stats=stats
                            )
                            if payload:
                                # Prepend OpCode 0x0F
                                session.udp_context.send(b'\x0F' + payload)
                            if phys_debug:
                                print(
                                    f"[PHYS-SIM] owner-correction SENT pid={session.player_id} "
                                    f"net_id={my_entity.net_id} "
                                    f"pos=({my_entity.pos[0]:.1f},{my_entity.pos[1]:.1f},{my_entity.pos[2]:.1f})"
                                )

                if static_anchor_due:
                    static_anchor_payload = server.entities.build_static_anchor_packet(
                        sequence_num=current_tick,
                        local_stats=my_stats,
                    )
                    if static_anchor_payload:
                        session.udp_context.send(static_anchor_payload)

        # --- 4. Cleanup ---
        # Now that everyone has been told about the updates, we can clear the flags.
        server.entities.clear_all_dirty_flags()
        server.mod_relay_dirty_entity_ids.clear()

        # --- 5. Sleep to maintain tick rate ---
        elapsed = time.time() - start_time
        sleep_time = max(0.0, FRAME_TIME - elapsed)
        time.sleep(sleep_time)

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
                    if should_run_server_simulation(ctx.server):
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
                            print(f"Apply Jump Jets! {my_ent.vel}")
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

    ctx.session.is_ready_for_updates = True
    print(f">>> Snapshot sent. Client {ctx.session.name} is now SYNCED.")

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
    request = parse_reincarnate_request(payload)

    # Acknowledge
    ctx.send_ack(packet_id=0x25, seq_num=request.sequence)

    # Validate Session
    if not ctx.session:
        print("[WARN] Reincarnate request from sessionless UDP")
        return

    # Check if this is a team switch or spawn request
    if not request.is_team_switch:
        selected_entry_id = request.selected_entry_id
        base_id = request.base_id
        unit_id = ctx.server.packet_cfg.tank.unit_type
        print(
            "    > RECV REINCARNATE (SPAWN REQ): "
            f"Entry ID: {selected_entry_id} | base_id #{base_id} | unit_type {unit_id}"
        )
        print(f"    > Unknown values: {request.extra_x} | {request.extra_y}")

        if ctx.session.team not in (1, 2):
            send_system_message(ctx, "Choose a team before entering the map.")
            ctx.send(ReincarnatePacket(code=4, message="Choose a team first."))
            return
        
        repair_pad = resolve_spawn_entry(
            ctx.server.entities,
            selected_entry_id,
            base_id,
            ctx.session.team,
        )
        if not repair_pad:
            send_system_message(ctx, "Can't find selected spawn point.")
            ctx.send(ReincarnatePacket(code=4, message="Invalid Entry Point."))
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
            del_pkt = ctx.server.entities.remove_entity(ctx.session.entity.net_id)
            if del_pkt is not None: broadcast(ctx.server, del_pkt)

        ctx.session.entity = new_entity
        ctx.session.entity.is_manned = True
        note_mod_relay_entity_spawn(ctx.session, new_entity, "reincarnate")

        # 3. Notify the Client
        spawn_x, spawn_y, spawn_z = repair_pad.pos
        send_system_message(
            ctx,
            f"Spawning Player #{new_entity.net_id} at x={spawn_x:.2f}, y={spawn_y:.2f}, z={spawn_z:.2f}...",
        )

        # 4. Send TankPacket with the NEW Dynamic ID
        # The client will receive this and now know "I am NetID X"
        pkt = TankPacket(
            net_id=new_entity.net_id,
            sequence_id=get_ticks(),
            tank_cfg=ctx.server.packet_cfg.tank,
            team_id=ctx.session.team,
            unit_type=unit_id,
            pos=repair_pad.pos,
            rot=repair_pad.rot
        )
        ctx.send(pkt)
        ctx.send(ReincarnatePacket(code=0))
        
        send_existing_player_entity_definitions(ctx, "reincarnate")

        broadcast(ctx.server, BirthNoticePacket(ctx.session.player_id))
        #broadcast(ctx.server, BirthNoticePacket(ctx.session.entity.net_id))

        return

    team_id = request.team_id
    print(f"    > RECV REINCARNATE (TEAM SWITCH): Team : {team_id}")
    # Switch their teams
    if team_id not in (1, 2):
        ctx.send(ReincarnatePacket(code=18, message="Invalid team."))
        return

    ctx.session.team = team_id
    broadcast(ctx.server, UpdateStatsPacket(player_id=ctx.session.player_id, team_id=team_id))

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

ACTION_DUMP_IDS = range(1, 22)

ACTION_NAMES = {
    1: "Turn",
    2: "Forward",
    3: "Strafe",
    4: "JumpJet",
    5: "Hover (Up/Down)",
    6: "Tilting",
}

def _read_action_value(reader: PacketReader, action_id: int) -> float:
    """
    Reads one action value. Evidence:
    ida_exports/curated_functions/004DDC60_Packet_Write_Quantized_Action.c
    at 0x4DDC60.
    """
    if action_id >= 8 or action_id == 4:
        return 1.0 if reader.read_bits(1) else 0.0
    if action_id == 5:
        return reader.read_quantized_float(get_config_by_index(10))
    return reader.read_quantized_float(get_config_by_index(11))

def _client_id_for_action_log(ctx: UdpContext) -> int | str:
    if ctx.session:
        return ctx.session.player_id or "pending"
    return "unlinked"

def _debug_config_bool(ctx: UdpContext, name: str, default: bool = False) -> bool:
    server = getattr(ctx, "server", None)
    cfg = getattr(server, "cfg", None)
    debug = getattr(cfg, "debug", None)
    return bool(getattr(debug, name, default))

def _store_action_value(
    ctx: UdpContext,
    packet_type: str,
    action_id: int,
    value: float,
) -> tuple[float | None, float]:
    old_value = None
    if ctx.session and ctx.session.entity:
        old_value = ctx.session.entity.actions.get(action_id)
        # Zero is a real released/neutral state, not "ignore this action."
        ctx.session.entity.actions[action_id] = value

    if _debug_config_bool(ctx, "debug_actions"):
        print(
            "[ACTION] "
            f"client_id={_client_id_for_action_log(ctx)} "
            f"packet={packet_type} "
            f"action_id={action_id} "
            f"action_name=\"{ACTION_NAMES.get(action_id, f'Unknown_{action_id}')}\" "
            f"old_value={old_value} "
            f"new_value={value}"
        )
    return old_value, value

def parse_action_packet(ctx: UdpContext, payload: bytes, is_dump: bool):
    """
    Parses ACTION_DUMP (0x09) or ACTION_UPDATE (0x0A).

    ACTION_DUMP carries an implicit full table for action ids 1..21.
    ACTION_UPDATE carries a counted list of explicit action id/value pairs.

    Evidence:
    - ida_exports/curated_functions/0046C790_send_action_dump_UDP.c at 0x46C790
    - ida_exports/curated_functions/0046C860_send_action_update_UDP.c at 0x46C860
    """
    reader = PacketReader(payload)
    opcode = reader.read_byte()
    packet_type = "ACTION_DUMP" if is_dump else "ACTION_UPDATE"
    decoded_actions = []

    if is_dump:
        dump_time_or_sequence = reader.read_int32()
        packet_time_or_flags = reader.read_int32()
        if _debug_config_bool(ctx, "debug_action_packets"):
            print(
                "[ACTION_PACKET] "
                f"client_id={_client_id_for_action_log(ctx)} "
                f"packet={packet_type} "
                f"opcode=0x{opcode:02X} "
                f"dump_time_or_sequence={dump_time_or_sequence} "
                f"packet_time_or_flags={packet_time_or_flags}"
            )
        action_ids = ACTION_DUMP_IDS
    else:
        count = reader.read_byte()
        first_action_time_or_sequence = reader.read_int32()
        packet_time_or_flags = reader.read_int32()
        if _debug_config_bool(ctx, "debug_action_packets"):
            print(
                "[ACTION_PACKET] "
                f"client_id={_client_id_for_action_log(ctx)} "
                f"packet={packet_type} "
                f"opcode=0x{opcode:02X} "
                f"count={count} "
                f"first_action_time_or_sequence={first_action_time_or_sequence} "
                f"packet_time_or_flags={packet_time_or_flags}"
            )
        cfg_id_bits = get_config_by_index(15)
        action_ids = (
            reader.read_bits(cfg_id_bits.precision_header_bits)
            for _ in range(count)
        )

    for action_id in action_ids:
        value = _read_action_value(reader, action_id)
        old_value, new_value = _store_action_value(
            ctx,
            packet_type,
            action_id,
            value,
        )
        decoded_actions.append((action_id, old_value, new_value))

    return decoded_actions

@dispatcher.route(0x09)
def on_action_dump(ctx: UdpContext, payload: bytes):
    parse_action_packet(ctx, payload, is_dump=True)

@dispatcher.route(0x0A)
def on_action_update(ctx: UdpContext, payload: bytes):
    parse_action_packet(ctx, payload, is_dump=False)

@dispatcher.route(0x2B)
def on_drop_request(ctx: UdpContext, payload: bytes):
    """DROP_REQUEST: deploy (flag=1) or drop (flag=0) the carried cargo.

    Body after the opcode is a single int32 written by deploy_cargo /
    drop_cargo in the client (wulfram2.exe @ 0x0045de40 / 0x0045de00).
    """
    if not ctx.session or not ctx.session.entity:
        return
    reader = PacketReader(payload)
    reader.read_byte()  # opcode 0x2B
    deploy = reader.read_int32() != 0

    packets = ctx.server.cargo.handle_drop_request(
        ctx.session.entity, ctx.session.player_id, deploy=deploy
    )
    for pkt in packets:
        broadcast(ctx.server, pkt)

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
    player_id = ctx.session.player_id
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
        ctx.session.entity = ctx.server.entities.create_entity(
            unit_type=ctx.server.packet_cfg.tank.unit_type, 
            team_id=ctx.session.team,
            pos=(100.0, 100.0, 100.0),
        )
        ctx.session.entity.pending_mask = 0
        ctx.session.entity.is_manned = True
        note_mod_relay_entity_spawn(ctx.session, ctx.session.entity, "command_spawn")

        pkt = TankPacket(
            net_id=ctx.session.entity.net_id,
            sequence_id=get_ticks(),
            tank_cfg=ctx.server.packet_cfg.tank,
            team_id=ctx.session.team,
            pos=(100.0, 100.0, 100.0),
            rot=(0.0, 0.0, 0.0)
        )
        ctx.send(pkt)
        send_existing_player_entity_definitions(ctx, "command_spawn")
        send_system_message(ctx, "Spawning Local Player...")

        ctx.send(ReincarnatePacket(code=0))
        broadcast(ctx.server, BirthNoticePacket(ctx.session.player_id))

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
        team_id=ctx.session.team,
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

    ctx.server.current_map_name = map_name
    broadcast(ctx.server, WorldStatsPacket(map_name=map_name))
    send_system_message(ctx, f"Changing map to {map_name}...")
    time.sleep(0.1)
    cmd_loadmap(ctx, map_name)

@commands.command("loadmap")
def cmd_loadmap(ctx, map_name="bpass"):
    """
    Loads map entities from: ./shared/data/maps/<map_name>/state when present.
    Land-only maps are still bootstrapped with team repair pads.
    Usage: /s loadmap bpass
    """
    # 1. Verify the map exists
    if not verify_map_land_exists(map_name):
        file_path = _get_map_land_path(map_name)
        send_system_message(ctx, f"Could not find map file at: {file_path}")
        print(f"[MapLoader] File not found: {file_path}")
        return

    # 2. Proceed to load
    map_dir = _get_map_dir_path(map_name)
    state_path = _get_map_state_path(map_name)

    try:
        # Initialize the loader with the current entity manager
        loader = MapLoader(ctx.server.entities)

        loaded_count = 0
        if os.path.exists(state_path):
            with open(state_path, "r", encoding="ascii", errors="replace") as f:
                data = f.read()
            loaded_count = loader.load_from_string(data)
            send_system_message(ctx, f"Loaded map state: {map_name}")
        else:
            print(f"[MapLoader] No state file for {map_name}; bootstrapping empty map.")
            send_system_message(ctx, f"Loaded empty map: {map_name}")

        created_pads = ensure_team_repair_pads(ctx.server.entities, map_dir)
        if created_pads:
            send_system_message(ctx, f"Created {created_pads} fallback repair pads.")
            print(f"[MapLoader] Created {created_pads} fallback repair pads for {map_name}.")
        print(f"[MapLoader] Map {map_name}: loaded {loaded_count} state entities.")

        # Load this map's terrain heightmap into the tank sim so it tracks the
        # real ground/slopes instead of a flat plane.
        ctx.server.refresh_sim_terrain(map_name)

        # Just send the full snapshot
        #ctx.outgoing_seq += 1
        snapshot = ctx.server.entities.get_snapshot_packet(sequence_num=get_ticks(), health=1.0, energy=1.0)
        broadcast(ctx.server, snapshot)
        
    except Exception as e:
        print(f"Failed to load map: {e}")
        send_system_message(ctx, "Error loading map.")

@commands.command("reset")
def cmd_reset(ctx):
    ctx.send(ResetGamePacket())
    send_system_message(ctx, "Resetting game...")

@commands.command("die")
def cmd_die(ctx):
    if (ctx.session.entity):
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
        player_id=ctx.session.player_id,
        has_cargo=True,
        cargo_type=int(item_id),
        variant=ctx.session.team,
    ))

@commands.command("drop")
def cmd_drop(ctx):
    ctx.send(CarryingInfoPacket(
        player_id=ctx.session.player_id,
        has_cargo=False,
        cargo_type=0,
        variant=ctx.session.team,
    ))

@commands.command("spawncargo")
def cmd_spawncargo(ctx, contained_type="25"):
    """Spawn a cargo box (unit_type 19) near the player for pickup testing.

    Usage: /s spawncargo [contained_unit_type]   (default 25 = power cell)
    """
    try:
        contained = int(contained_type)
    except ValueError:
        contained = 25

    pos = (100.0, 100.0, 0.0)
    if ctx.session.entity:
        px, py, _ = ctx.session.entity.pos
        pos = (px + 5.0, py, 0.0)

    box = ctx.server.entities.create_entity(
        unit_type=CARGO_BOX_UNIT_TYPE, team_id=ctx.session.team, pos=pos
    )
    box.is_manned = False
    box.cargo_contained_type = contained
    send_system_message(ctx, f"Spawned cargo box (contains unit {contained}) at {pos}.")

@commands.command("cargostatus")
def cmd_cargostatus(ctx):
    """Report this player's cargo pickup state — why a pickup does/doesn't fire."""
    ent = ctx.session.entity
    if not ent:
        send_system_message(ctx, "No entity yet (spawn first).")
        return

    d = ctx.server.cargo.describe_pickup(ent)
    nd = d["nearest_dist"]
    nearest = f"{nd:.1f}" if nd is not None else "none"
    send_system_message(
        ctx,
        f"carrying={d['carrying']} eligible={d['eligible']} | "
        f"pos=({ent.pos[0]:.0f},{ent.pos[1]:.0f},{ent.pos[2]:.0f}) "
        f"nearestBox={nearest}/{d['pickup_radius']:.1f}",
    )
    print(f"[CARGO-STATUS] pid={ctx.session.player_id} pos={ent.pos} {d}")

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
        del_packet = ctx.server.entities.remove_entity(e.net_id)
        if del_packet is not None: broadcast(ctx.server, del_packet)

def kill_local_player(ctx: UdpContext | TcpContext):
    if not ctx.session:
        return
    
    if not ctx.session.entity:
        send_system_message(ctx, "You may already be dead.")
        return
    
    net_id = ctx.session.entity.net_id

    # 3. Perform Logic
    # Notify client of death
    broadcast(ctx.server, DeathNoticePacket(net_id))
    
    # Remove from World
    del_packet = ctx.server.entities.remove_entity(net_id)
    if del_packet is not None: broadcast(ctx.server, del_packet)

    # 4. Clear Session State
    ctx.session.entity = None

    send_system_message(ctx, "You died.")

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
    return os.path.join(_get_map_dir_path(map_name), "state")

def _get_map_land_path(map_name):
    """
    Helper to construct the map file path. 
    Keeps the path definition in one place to avoid bugs.
    """
    return os.path.join(_get_map_dir_path(map_name), "land")

def _get_map_dir_path(map_name):
    return os.path.join("shared", "data", "maps", map_name)

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

def resolve_advertised_udp_host(client_sock: socket.socket, ctx: TcpContext) -> str:
    configured_host = (ctx.server.cfg.network.server_ip or "").strip()
    if configured_host.lower() not in ("", "auto", "0.0.0.0", "::"):
        _warn_if_loopback_advertised_to_remote(configured_host, ctx)
        return configured_host

    try:
        local_host = client_sock.getsockname()[0]
    except OSError:
        local_host = ""

    if not local_host or local_host in ("0.0.0.0", "::"):
        local_host = ctx.server.cfg.network.host

    if not local_host or local_host in ("0.0.0.0", "::"):
        local_host = "127.0.0.1"

    print(
        "[INFO] Auto UDP advertise host "
        f"client={ctx.session.address[0]} local_socket={local_host} configured={configured_host or 'auto'}"
    )
    return local_host


def _warn_if_loopback_advertised_to_remote(configured_host: str, ctx: TcpContext) -> None:
    try:
        advertised = ipaddress.ip_address(configured_host)
        client_ip = ipaddress.ip_address(ctx.session.address[0])
    except ValueError:
        return

    if advertised.is_loopback and not client_ip.is_loopback:
        print(
            "[WARN] network.server_ip is loopback but client is remote; "
            f"client={client_ip} advertised_udp_host={advertised}. "
            "Use server_ip=\"auto\" or your LAN/Tailscale address."
        )


def do_login_and_bootstrap(client_sock: socket.socket, ctx: TcpContext, dispatcher: PacketDispatcher):
    """
    Handles the initial sequence: Hello -> UDP Link -> Login -> World Entry.
    """
    # 1. Send UDP Config (Hello Sub 1)
    print(f"[INFO] Setting session {ctx.session.address} to WAIT for UDP...")
    advertised_udp_host = resolve_advertised_udp_host(client_sock, ctx)
    print(
        "[INFO] Advertising UDP endpoint "
        f"{advertised_udp_host}:{ctx.server.cfg.network.udp_port} to {ctx.session.address}"
    )
    
    # This let's the client know which ip and port to connect to with UDP
    ctx.send(HelloPacket.create_udp_config(
        port=ctx.server.cfg.network.udp_port, 
        host=advertised_udp_host
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

    ctx.send(WorldStatsPacket(map_name=ctx.server.current_map_name))

    if (not ctx.server.first_map_load):
        cmd_loadmap(ctx, ctx.server.current_map_name)
        ctx.server.first_map_load = True

    start_ping_loop(ctx)

def main():
    logging_runtime = setup_logging()
    try:
        print(f"[LOG] Writing server log to {logging_runtime.log_file}")
        server = WulframServerContext()
        server.run()
    finally:
        logging_runtime.restore()

if __name__ == "__main__":
    main()
