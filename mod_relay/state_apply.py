from __future__ import annotations

import math
import time
from typing import Any

from core.entity import UpdateMask
from mod_relay.packets import ClientStateV1

WORLD_LIMIT = 1_000_000.0
VELOCITY_LIMIT = 100_000.0
ROTATION_LIMIT = 1_000.0
SPIN_LIMIT = 10_000.0


def apply_mod_client_state(server: Any, session: Any, state: ClientStateV1) -> bool:
    """Apply experimental owner-authoritative W2Mod state to one entity.

    This is the only mutation point for the V1 mod relay. It deliberately updates
    the existing GameEntity and dirty flags so normal 0x0E/0x0F broadcasts carry
    the movement instead of creating a second movement broadcast path.
    """
    entity = getattr(session, "entity", None)
    if entity is None:
        return False

    relay_cfg = getattr(getattr(server, "cfg", None), "mod_relay", None)
    apply_velocity = True if relay_cfg is None else relay_cfg.apply_velocity
    apply_rotation = True if relay_cfg is None else relay_cfg.apply_rotation
    apply_spin = False if relay_cfg is None else relay_cfg.apply_spin
    hard_sync = False if relay_cfg is None else relay_cfg.hard_sync

    if not _valid_vec(state.pos, WORLD_LIMIT):
        return False

    mask = UpdateMask.POS
    previous_pos = entity.pos
    entity.pos = state.pos

    if apply_velocity and _valid_vec(state.vel, VELOCITY_LIMIT):
        entity.vel = state.vel
        mask |= UpdateMask.VEL

    # The client receive path expects rotation with position when it has to force
    # initialize an invisible entity, so keep this enabled unless isolating a crash.
    # Evidence:
    # - ida_exports/curated_functions/0047D760_WIP_read_array_from_bitstream.c at 0x0047D760
    # - ida_exports/curated_functions/0047D2F0_Apply_Entity_Update_Snapshot.c at 0x0047D2F0
    if apply_rotation and not _valid_vec(state.rot, ROTATION_LIMIT):
        return False

    if apply_rotation:
        entity.rot = state.rot
        mask |= UpdateMask.ROT

    if apply_spin and _valid_vec(state.angvel, SPIN_LIMIT):
        entity.spin = state.angvel
        mask |= UpdateMask.SPIN

    hard_sync_reason = ""
    if hard_sync:
        hard_sync_reason = "forced"
    else:
        hard_sync_reason = _adaptive_hard_sync_reason(server, entity, state, previous_pos, relay_cfg)

    if hard_sync_reason:
        mask |= UpdateMask.HARD_SYNC

    setattr(session, "mod_relay_last_hard_sync_reason", hard_sync_reason)
    entity.mark_dirty(mask)
    return True


def _valid_vec(vec: tuple[float, float, float], limit: float) -> bool:
    return (
        len(vec) == 3
        and all(math.isfinite(value) for value in vec)
        and all(abs(value) < limit for value in vec)
    )


def _adaptive_hard_sync_reason(
    server: Any,
    entity: Any,
    state: ClientStateV1,
    previous_pos: tuple[float, float, float],
    relay_cfg: Any,
) -> str:
    adaptive_hard_sync = True if relay_cfg is None else getattr(relay_cfg, "adaptive_hard_sync", True)
    if not adaptive_hard_sync:
        return ""

    initial_packets = _nonnegative_int(getattr(relay_cfg, "hard_sync_initial_packets", 3) if relay_cfg else 3)
    stale_ms = _nonnegative_int(getattr(relay_cfg, "hard_sync_stale_ms", 500) if relay_cfg else 500)
    teleport_distance = _nonnegative_float(
        getattr(relay_cfg, "hard_sync_teleport_distance", 250.0) if relay_cfg else 250.0
    )

    relay_updates = getattr(server, "mod_relay_entity_updates", {})
    previous_update = relay_updates.get(getattr(entity, "net_id", None), {})
    apply_count = _nonnegative_int(previous_update.get("apply_count", 0))
    if apply_count < initial_packets:
        return "initial"

    last_monotonic = previous_update.get("monotonic")
    if stale_ms > 0 and isinstance(last_monotonic, (int, float)):
        elapsed_ms = (time.monotonic() - float(last_monotonic)) * 1000.0
        if elapsed_ms >= stale_ms:
            return "stale"

    if teleport_distance > 0 and _valid_vec(previous_pos, WORLD_LIMIT):
        if _distance(previous_pos, state.pos) >= teleport_distance:
            return "teleport"

    return ""


def _distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return math.sqrt(
        (a[0] - b[0]) * (a[0] - b[0])
        + (a[1] - b[1]) * (a[1] - b[1])
        + (a[2] - b[2]) * (a[2] - b[2])
    )


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _nonnegative_float(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(parsed):
        return 0.0
    return max(0.0, parsed)
