# config.py
from __future__ import annotations
from dataclasses import dataclass, fields
import time
import os
import tomllib

# ---- Tick clock (Unchanged) ----
_SERVER_START = time.monotonic()

def get_ticks() -> int:
    return int((time.monotonic() - _SERVER_START) * 1000) & 0xFFFFFFFF

# ---- Config Sections ----

@dataclass(frozen=True, slots=True)
class NetworkConfig:
    host: str = "127.0.0.1"
    server_ip: str = "127.0.0.1"
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

# ---- Main Config ----

@dataclass(slots=True) # Not frozen, so we can replace the sub-objects
class Config:
    network: NetworkConfig = NetworkConfig()
    game: GameConfig = GameConfig()
    player: PlayerConfig = PlayerConfig()
    debug: DebugConfig = DebugConfig()

    @classmethod
    def load(cls, filename: str = "config.toml") -> Config:
        """
        Loads config from a TOML file. 
        If the file doesn't exist, returns default config.
        """
        if not os.path.exists(filename):
            print(f"[WARN] {filename} not found. Using defaults.")
            return cls()

        with open(filename, "rb") as f:
            data = tomllib.load(f)

        # Helper to unpack dictionary into a specific dataclass
        def unpack(dataclass_type, section_data):
            # Filter out keys in the TOML that don't belong to the dataclass
            # (Prevents crashing if you add extra junk to the toml file)
            valid_keys = {f.name for f in fields(dataclass_type)}
            clean_data = {k: v for k, v in section_data.items() if k in valid_keys}
            return dataclass_type(**clean_data)

        # Build the config object by checking if sections exist in the TOML
        # If a section is missing in TOML, it falls back to the default class instance
        return cls(
            network=unpack(NetworkConfig, data.get("network", {})) if "network" in data else NetworkConfig(),
            game=unpack(GameConfig, data.get("game", {})) if "game" in data else GameConfig(),
            player=unpack(PlayerConfig, data.get("player", {})) if "player" in data else PlayerConfig(),
            debug=unpack(DebugConfig, data.get("debug", {})) if "debug" in data else DebugConfig(),
        )