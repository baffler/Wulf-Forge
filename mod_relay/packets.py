from __future__ import annotations

from dataclasses import dataclass
import struct


MAGIC = 0x534D3257  # "W2MS" as little-endian bytes
VERSION_V1 = 1
TYPE_CLIENT_STATE = 1

CLIENT_STATE_V1_STRUCT = struct.Struct(
    "<IHH"  # magic, version, type
    "IIII"  # sequence, client_tick_ms, player_id, local_entity
    "fff"  # pos
    "fff"  # vel
    "fff"  # rot
    "fff"  # angvel
    "I"  # flags
)


@dataclass(slots=True)
class ClientStateV1:
    sequence: int
    client_tick_ms: int
    player_id: int
    local_entity: int
    pos: tuple[float, float, float]
    vel: tuple[float, float, float]
    rot: tuple[float, float, float]
    angvel: tuple[float, float, float]
    flags: int


def parse_client_state_v1(data: bytes) -> ClientStateV1 | None:
    if len(data) != CLIENT_STATE_V1_STRUCT.size:
        return None

    unpacked = CLIENT_STATE_V1_STRUCT.unpack(data)
    magic, version, packet_type = unpacked[0:3]
    if magic != MAGIC or version != VERSION_V1 or packet_type != TYPE_CLIENT_STATE:
        return None

    sequence, client_tick_ms, player_id, local_entity = unpacked[3:7]
    pos = unpacked[7:10]
    vel = unpacked[10:13]
    rot = unpacked[13:16]
    angvel = unpacked[16:19]
    flags = unpacked[19]

    return ClientStateV1(
        sequence=sequence,
        client_tick_ms=client_tick_ms,
        player_id=player_id,
        local_entity=local_entity,
        pos=pos,
        vel=vel,
        rot=rot,
        angvel=angvel,
        flags=flags,
    )
