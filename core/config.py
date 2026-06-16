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
    # Address advertised to clients for the UDP key exchange. Use "auto" when
    # accepting both local and LAN/VPN clients from a wildcard bind.
    server_ip: str = "auto"
    tcp_port: int = 2627
    udp_port: int = 2627

@dataclass(frozen=True, slots=True)
class GameConfig:
    motd: str = "Welcome to Wulf-Forge! Wulfram 2 server emulator brought to you by baffler."
    map_name: str = "bpass"

@dataclass(frozen=True, slots=True)
class PlayerConfig:
    name: str = "default"
    nametag: str = "DEV"
    team:int = 0
    unit_type: int = 0

@dataclass(frozen=True, slots=True)
class DebugConfig:
    debug_packets: bool = True
    show_ascii: bool = True
    debug_actions: bool = False
    debug_action_packets: bool = False
    # Log every packet opcode (including high-frequency per-tick ones like
    # UPDATE_ARRAY/VIEW_UPDATE/PING). All packet log lines are teed to the
    # timestamped file in logs/, so enabling this captures everything to disk.
    log_all_opcodes: bool = False
    # Verbose per-tick logging of the server-side tank simulation: each active
    # player's inputs + resulting pos/vel/yaw, and whether the owner correction
    # was suppressed (server_simulation) or sent. Off by default (noisy).
    debug_physics_sim: bool = False
    # When True, send the owner its own simulated transform every tick even in
    # server_simulation (i.e. DISABLE the owner-correction suppression). Lets you
    # SEE how far the server sim has drifted from the client (rubber-banding).
    # Off by default = suppress = smooth client-side prediction.
    correct_owner_in_sim: bool = False

@dataclass(frozen=True, slots=True)
class SyncConfig:
    # server_simulation: action packets drive server-side movement.
    # client_state_relay: a modified client supplies authoritative transform state.
    mode: str = "server_simulation"

@dataclass(frozen=True, slots=True)
class ModRelayConfig:
    port: int = 28010
    owner_auth: bool = True
    debug_mapping: bool = True
    auto_bind: bool = True
    identity_trace: bool = True
    coalesce_updates: bool = True
    echo_owner_state: bool = False
    hard_sync: bool = False
    adaptive_hard_sync: bool = True
    hard_sync_teleport_distance: float = 250.0
    hard_sync_stale_ms: int = 500
    hard_sync_initial_packets: int = 3
    apply_velocity: bool = True
    apply_rotation: bool = True
    apply_spin: bool = False

# ----------------------------------------------------------------------
# ---- Not part of the static config, these will change at runtime
# ----------------------------------------------------------------------
@dataclass(slots=True)
class PlayerSession:
    player_id: int = 0
    name: str = ""
    team: int = 0
    # These get initialized later by defaults

# ---- Main Config ----

@dataclass(slots=True) # Not frozen, so we can replace the sub-objects
class Config:
    network: NetworkConfig = NetworkConfig()
    game: GameConfig = GameConfig()
    player: PlayerConfig = PlayerConfig()
    debug: DebugConfig = DebugConfig()
    sync: SyncConfig = SyncConfig()
    mod_relay: ModRelayConfig = ModRelayConfig()

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
            sync=unpack(SyncConfig, data.get("sync", {})) if "sync" in data else SyncConfig(),
            mod_relay=unpack(ModRelayConfig, data.get("mod_relay", {})) if "mod_relay" in data else ModRelayConfig(),
        )
