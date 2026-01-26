# config.py
from __future__ import annotations
from dataclasses import dataclass
import time

# ---- Tick clock ----
_SERVER_START = time.monotonic()

def get_ticks() -> int:
    return int((time.monotonic() - _SERVER_START) * 1000) & 0xFFFFFFFF


@dataclass(frozen=True, slots=True)
class NetworkConfig:
    host: str = "127.0.0.1"
    tcp_port: int = 2627
    udp_port: int = 2627


@dataclass(frozen=True, slots=True)
class GameConfig:
    session_key: str = "WulframSessionKey123"
    motd: str = "Welcome to Wulf-Forge!"


@dataclass(frozen=True, slots=True)
class PlayerConfig:
    player_id: int = 1337
    name: str = "baff"
    nametag: str = "DEV"
    team: int = 2
    unit_type: int = 0


@dataclass(frozen=True, slots=True)
class DebugConfig:
    debug_packets: bool = True
    show_ascii: bool = True


@dataclass(frozen=True, slots=True)
class Config:
    network: NetworkConfig = NetworkConfig()
    game: GameConfig = GameConfig()
    player: PlayerConfig = PlayerConfig()
    debug: DebugConfig = DebugConfig()
