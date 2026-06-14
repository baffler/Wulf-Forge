from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

from mod_relay.packets import ClientStateV1


@dataclass(slots=True)
class MappingResult:
    session: Any | None
    reason: str = ""


def resolve_mod_packet_session(
    server: Any,
    addr: tuple[str, int],
    state: ClientStateV1,
) -> MappingResult:
    """Resolve a W2Mod packet to a current ClientSession.

    V1 is intentionally simple and not secure: prefer configured/player-sent IDs,
    otherwise fall back to a unique source-IP match for LAN/debug playtests.
    """
    sessions = [s for s in getattr(server, "sessions", []) if getattr(s, "is_logged_in", False)]

    if state.player_id:
        for session in sessions:
            if getattr(session, "player_id", 0) == state.player_id:
                _remember_mapping(session, addr, state, "matched_session_player_id")
                return MappingResult(session=session, reason="matched_session_player_id")

            entity = getattr(session, "entity", None)
            if entity is not None and getattr(entity, "net_id", 0) == state.player_id:
                _remember_mapping(session, addr, state, "matched_entity_net_id")
                return MappingResult(session=session, reason="matched_entity_net_id")

        bound = _match_existing_binding(sessions, addr, state)
        if bound is not None:
            _remember_mapping(bound, addr, state, "existing_debug_binding")
            return MappingResult(session=bound, reason="existing_debug_binding")

        if _auto_bind_enabled(server):
            auto = _auto_bind_same_ip_session(server, sessions, addr, state, f"unknown player_id={state.player_id}")
            if auto.session is not None:
                return auto

        return MappingResult(session=None, reason=f"unknown player_id={state.player_id}")

    bound = _match_existing_binding(sessions, addr, state)
    if bound is not None:
        _remember_mapping(bound, addr, state, "existing_debug_binding")
        return MappingResult(session=bound, reason="existing_debug_binding")

    source_ip = addr[0]
    matches = [
        session
        for session in sessions
        if _session_matches_ip(session, source_ip)
    ]

    if len(matches) == 1:
        _remember_mapping(matches[0], addr, state, "unique_source_ip")
        return MappingResult(session=matches[0], reason="unique_source_ip")

    if not matches:
        return MappingResult(session=None, reason=f"no session for ip={source_ip}")

    if _auto_bind_enabled(server):
        auto = _auto_bind_same_ip_session(server, sessions, addr, state, f"ambiguous ip={source_ip} matches={len(matches)}")
        if auto.session is not None:
            return auto

    return MappingResult(session=None, reason=f"ambiguous ip={source_ip} matches={len(matches)}")


def map_mod_packet_to_session(server: Any, addr: tuple[str, int], state: ClientStateV1) -> Any | None:
    return resolve_mod_packet_session(server, addr, state).session


def _auto_bind_enabled(server: Any) -> bool:
    relay_cfg = getattr(getattr(server, "cfg", None), "mod_relay", None)
    if relay_cfg is None:
        return True
    return bool(getattr(relay_cfg, "debug_mapping", True) and getattr(relay_cfg, "auto_bind", True))


def _match_existing_binding(
    sessions: list[Any],
    addr: tuple[str, int],
    state: ClientStateV1,
) -> Any | None:
    by_addr = [session for session in sessions if getattr(session, "mod_relay_addr", None) == addr]
    if len(by_addr) == 1:
        return by_addr[0]

    if state.local_entity:
        source_ip = addr[0]
        by_local_entity = [
            session
            for session in sessions
            if getattr(session, "mod_relay_local_entity", 0) == state.local_entity
            and _session_matches_ip(session, source_ip)
        ]
        if len(by_local_entity) == 1:
            return by_local_entity[0]

    return None


def _auto_bind_same_ip_session(
    server: Any,
    sessions: list[Any],
    addr: tuple[str, int],
    state: ClientStateV1,
    fallback_reason: str,
) -> MappingResult:
    source_ip = addr[0]
    same_ip = [
        session
        for session in sessions
        if _session_matches_ip(session, source_ip) and getattr(session, "entity", None) is not None
    ]

    unbound = [session for session in same_ip if getattr(session, "mod_relay_addr", None) is None]
    if len(unbound) == 1:
        _remember_mapping(unbound[0], addr, state, "auto_bound_only_unbound_same_ip")
        return MappingResult(session=unbound[0], reason="auto_bound_only_unbound_same_ip")

    recent = [
        session
        for session in unbound
        if getattr(session, "mod_relay_last_spawned_at", 0.0) > 0.0
    ]
    if recent:
        recent.sort(key=lambda session: getattr(session, "mod_relay_last_spawned_at", 0.0), reverse=True)
        newest = recent[0]
        newest_at = getattr(newest, "mod_relay_last_spawned_at", 0.0)
        second_at = getattr(recent[1], "mod_relay_last_spawned_at", 0.0) if len(recent) > 1 else 0.0
        if newest_at > second_at:
            _remember_mapping(newest, addr, state, "auto_bound_recent_spawn_same_ip")
            return MappingResult(session=newest, reason="auto_bound_recent_spawn_same_ip")

    return MappingResult(session=None, reason=fallback_reason)


def _session_matches_ip(session: Any, source_ip: str) -> bool:
    udp_addr = getattr(session, "udp_addr", None)
    return (
        getattr(session, "address", ("", 0))[0] == source_ip
        or (udp_addr is not None and udp_addr[0] == source_ip)
    )


def _remember_mapping(
    session: Any,
    addr: tuple[str, int],
    state: ClientStateV1,
    reason: str,
) -> None:
    now = time.monotonic()
    if getattr(session, "mod_relay_addr", None) is None:
        setattr(session, "mod_relay_bound_at", now)

    setattr(session, "mod_relay_binding_reason", reason)
    setattr(session, "mod_relay_addr", addr)
    setattr(session, "mod_relay_last_seen_at", now)
    setattr(session, "mod_relay_local_entity", state.local_entity)
    setattr(session, "mod_relay_packet_player_id", state.player_id)
