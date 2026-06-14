from __future__ import annotations

import socket
import threading
import time
from typing import Any

from mod_relay.packets import ClientStateV1, parse_client_state_v1
from mod_relay.session_mapper import resolve_mod_packet_session


class ModStateRelayListener:
    def __init__(self, host: str, port: int, server: Any):
        self.host = host
        self.port = port
        self.server = server
        self.sock: socket.socket | None = None
        self.thread: threading.Thread | None = None
        self.running = False
        self._stop_event = threading.Event()
        self._last_sequence_by_key: dict[Any, int] = {}
        self._last_addr_by_key: dict[Any, tuple[str, int]] = {}
        self._last_seen_by_key: dict[Any, float] = {}
        self._last_log_by_key: dict[str, float] = {}
        self._last_identity_by_key: dict[Any, tuple[Any, ...]] = {}
        self._first_valid_logged = False
        self._last_summary_time = time.monotonic()
        self.rx_count = 0
        self.accepted_count = 0
        self.applied_count = 0
        self.malformed_count = 0
        self.unmapped_count = 0
        self.dropped_order_count = 0
        self.sequence_reset_count = 0
        self.rejected_apply_count = 0

    def start(self) -> None:
        if self.running:
            return

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.host, self.port))
        self.sock.settimeout(0.25)
        self.running = True
        self._stop_event.clear()
        self.thread = threading.Thread(target=self._recv_loop, name="ModStateRelay", daemon=True)
        self.thread.start()
        print(f"[mod-relay] listening on UDP {self.host}:{self.port}")

    def stop(self) -> None:
        if not self.running:
            return

        self.running = False
        self._stop_event.set()
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

        if self.thread is not None:
            self.thread.join(timeout=1.0)
            self.thread = None

        print("[mod-relay] stopped")

    def note_applied(self, session: Any, state: ClientStateV1) -> None:
        self.applied_count += 1
        now = time.monotonic()
        if now - self._last_summary_time >= 5.0:
            self._last_summary_time = now
            entity = getattr(session, "entity", None)
            entity_id = getattr(entity, "net_id", "none")
            print(
                "[mod-relay] stats "
                f"rx={self.rx_count} accepted={self.accepted_count} "
                f"applied={self.applied_count} dropped_order={self.dropped_order_count} "
                f"rejected_apply={self.rejected_apply_count} "
                f"seq_resets={self.sequence_reset_count} "
                f"unmapped={self.unmapped_count} malformed={self.malformed_count} "
                f"last_entity={entity_id} last_seq={state.sequence}"
            )

    def note_rejected_apply(self, session: Any, state: ClientStateV1) -> None:
        self.rejected_apply_count += 1
        entity = getattr(session, "entity", None)
        entity_id = getattr(entity, "net_id", "none")
        self._rate_log(
            f"rejected_apply:{entity_id}",
            "[mod-relay] decoded packet rejected before entity apply "
            f"entity={entity_id} seq={state.sequence} "
            f"pos={_fmt_vec(state.pos)} vel={_fmt_vec(state.vel)} rot={_fmt_vec(state.rot)}",
        )

    def _recv_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                assert self.sock is not None
                data, addr = self.sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                if self.running:
                    self._rate_log("socket_error", "[mod-relay] socket closed unexpectedly")
                break

            self.rx_count += 1
            state = parse_client_state_v1(data)
            if state is None:
                self.malformed_count += 1
                self._rate_log("malformed", f"[mod-relay] dropped malformed packet size={len(data)}")
                continue

            if not self._first_valid_logged:
                self._first_valid_logged = True
                print(
                    "[mod-relay] first valid packet "
                    f"addr={addr[0]}:{addr[1]} seq={state.sequence} "
                    f"player_id={state.player_id} local_entity=0x{state.local_entity:08X} "
                    f"pos={_fmt_vec(state.pos)} "
                    f"vel={_fmt_vec(state.vel)} rot={_fmt_vec(state.rot)}"
                )

            result = resolve_mod_packet_session(self.server, addr, state)
            session = result.session
            if session is None:
                self.unmapped_count += 1
                reason = result.reason or "unmapped"
                self._rate_log(
                    f"unmapped:{reason}",
                    f"[mod-relay] unmapped packet addr={addr[0]}:{addr[1]} "
                    f"packet_player_id={state.player_id} local_entity=0x{state.local_entity:08X} {reason}",
                )
                continue

            key = getattr(session, "player_id", 0) or id(session)
            self._log_identity_mapping(key, addr, state, session, result.reason)
            now = time.monotonic()
            last_sequence = self._last_sequence_by_key.get(key)
            last_addr = self._last_addr_by_key.get(key)
            last_seen = self._last_seen_by_key.get(key, 0.0)
            if last_sequence is not None and state.sequence <= last_sequence:
                is_new_sender = last_addr is not None and addr != last_addr
                is_idle_restart = state.sequence <= 16 and (now - last_seen) >= 0.5
                if is_new_sender or is_idle_restart:
                    self.sequence_reset_count += 1
                    print(
                        "[mod-relay] accepted sequence reset "
                        f"session={getattr(session, 'player_id', 'unknown')} "
                        f"seq={state.sequence} previous={last_sequence} "
                        f"addr={addr[0]}:{addr[1]}"
                    )
                else:
                    self.dropped_order_count += 1
                    self._last_seen_by_key[key] = now
                    self._rate_log(
                        f"order:{key}",
                        "[mod-relay] dropped out-of-order packet "
                        f"session={getattr(session, 'player_id', 'unknown')} "
                        f"seq={state.sequence} last={last_sequence}",
                    )
                    continue

            self._last_sequence_by_key[key] = state.sequence
            self._last_addr_by_key[key] = addr
            self._last_seen_by_key[key] = now
            self.accepted_count += 1
            owner_auth_enabled = getattr(getattr(self.server, "cfg", None), "mod_relay", None)
            owner_auth_enabled = True if owner_auth_enabled is None else owner_auth_enabled.owner_auth
            if not owner_auth_enabled:
                self._rate_log("owner_auth_disabled", "[mod-relay] owner-auth disabled; decoded packet without applying")
                continue

            if hasattr(self.server, "enqueue_mod_client_state"):
                self.server.enqueue_mod_client_state(session, state)

    def _rate_log(self, key: str, message: str, interval_seconds: float = 5.0) -> None:
        now = time.monotonic()
        last = self._last_log_by_key.get(key, 0.0)
        if now - last >= interval_seconds:
            self._last_log_by_key[key] = now
            print(message)

    def _log_identity_mapping(
        self,
        key: Any,
        addr: tuple[str, int],
        state: ClientStateV1,
        session: Any,
        reason: str,
    ) -> None:
        relay_cfg = getattr(getattr(self.server, "cfg", None), "mod_relay", None)
        identity_trace = True if relay_cfg is None else getattr(relay_cfg, "identity_trace", True)
        if not identity_trace:
            return

        entity = getattr(session, "entity", None)
        entity_id = getattr(entity, "net_id", 0)
        identity = (
            addr,
            state.player_id,
            state.local_entity,
            getattr(session, "player_id", 0),
            entity_id,
            reason,
        )
        if self._last_identity_by_key.get(key) == identity:
            return

        self._last_identity_by_key[key] = identity
        print(
            "[mod-relay] identity map "
            f"reason={reason or 'unknown'} addr={addr[0]}:{addr[1]} "
            f"session_player_id={getattr(session, 'player_id', 0)} "
            f"session_entity_net_id={entity_id} "
            f"packet_player_id={state.player_id} "
            f"local_entity=0x{state.local_entity:08X}"
        )


def _fmt_vec(vec: tuple[float, float, float]) -> str:
    return f"({vec[0]:.2f}, {vec[1]:.2f}, {vec[2]:.2f})"
