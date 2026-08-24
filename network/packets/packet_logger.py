# network/packet_logger.py
from __future__ import annotations
import struct
from typing import Optional, Tuple


# Canonical application packet names come from the client's
# NetDebug_PopulatePacketHistogram table in wulfram2.exe.  The D_* entries are
# transport-control packets registered by the lower-level datagram protocol.
PACKET_NAMES: dict[int, str] = {
    0x02: "D_ACK",
    0x03: "D_HANDSHAKE",
    0x04: "D_SET_START",
    0x08: "ROOT",
    0x09: "ACTION_DUMP",
    0x0A: "ACTION_UPDATE",
    0x0B: "PING_REQUEST",
    0x0C: "PING",
    0x0D: "TRANSIENT_ARRAY",
    0x0E: "UPDATE_ARRAY",
    0x0F: "VIEW_UPDATE",
    0x10: "ACK1",
    0x11: "HUD_MESSAGE",
    0x12: "LAG_FIX",
    0x13: "HELLO",
    0x14: "HIDE_OBJECT",
    0x15: "DELETE_OBJECT",
    0x16: "WORLD_STATS",
    0x17: "PLAYER",
    0x18: "TANK",
    0x19: "TANK_RESEND_REQUEST",
    0x1A: "ADD_TO_ROSTER",
    0x1B: "REMOVE_FROM_ROSTER",
    0x1C: "UPDATE_STATS",
    0x1D: "DEATH_NOTICE",
    0x1E: "BIRTH_NOTICE",
    0x1F: "COMM_MESSAGE",
    0x20: "COMM_MESSAGE_REQUEST",
    0x21: "LOGIN",
    0x22: "LOGIN_STATUS",
    0x23: "MOTD",
    0x24: "BEHAVIOR",
    0x25: "REINCARNATE",
    0x26: "RETARGET",
    0x27: "SHIP_STATUS",
    0x28: "TEAM_INFO",
    0x29: "CARRYING_INFO",
    0x2A: "UPLINK_INFO",
    0x2B: "DROP_REQUEST",
    0x2C: "SPACE_MAP_UPDATE",
    0x2D: "SUPPLY_SHIP_INFO",
    0x2E: "WEAPON_DEMAND",
    0x2F: "GAME_CLOCK",
    0x30: "WARP_STATUS",
    0x31: "CONTINUOUS_SOUND",
    0x32: "TRANSLATION",
    0x33: "ACK2",
    0x34: "MODEM",
    0x35: "VIEWPOINT_INFO",
    0x36: "STRING_VALUE",
    0x37: "VERSION_ERROR",
    0x38: "DOCKING",
    0x39: "WANT_UPDATES",
    0x3A: "BEACON_REQUEST",
    0x3B: "BEACON_MODIFY",
    0x3C: "BEACON_STATUS",
    0x3D: "BEACON_DELETE",
    0x3E: "LOAD_STATUS",
    0x40: "KEEP_ALIVE",
    0x4C: "ROUTING_PING",
    0x4D: "ID_UDP",
    0x4E: "BPS_REQUEST",
    # Added after the older histogram table. Net_SendWantVoiceData uses this
    # generic key/value envelope for the "want_voice_data" request.
    0x54: "GENERIC",
    0x55: "DEBUG_COORDS",
}


def packet_name(opcode: int) -> Optional[str]:
    """Return the reverse-engineered name for an opcode, if known."""
    return PACKET_NAMES.get(opcode)


class PacketLogger:
    def __init__(self):
        # Keep the public attribute for compatibility with existing tooling.
        self.packet_names = PACKET_NAMES.copy()

    # ---------------------------
    # New API (matches my log_packet)
    # ---------------------------
    def log_packet(
        self,
        direction: str,
        payload: bytes,
        *,
        addr: Optional[Tuple[str, int]] = None,
        show_ascii: bool = True,
        include_tcp_len_prefix: bool = True,
        prefix_label: Optional[str] = None,
    ) -> None:
        """
        Logs a packet where payload starts with opcode:
            payload = [opcode][body...]
        This matches the convention used by the refactored server code.

        include_tcp_len_prefix:
            If True, prints the 2-byte big-endian length prefix (len(payload)+2)
            as part of the hex dump (handy for TCP debugging).
        """
        if not payload:
            return

        pkt_type = payload[0]
        name = self.packet_names.get(pkt_type, "UNKNOWN")

        # Ignore spammy packets
        if pkt_type in [0x09, 0x0B, 0x0C, 0x0E, 0x0F, 0x40, 0x49]:
            return

        # Displayed length: match your old style (just the bytes you pass in)
        # But we also optionally show the TCP framing in the hex dump.
        length = len(payload)

        addr_str = f" | Addr={addr}" if addr else ""
        label = f"{prefix_label} " if prefix_label else ""

        print(f"[{direction}] {label}{name:<14} (0x{pkt_type:02X}) | Len={length:<3}{addr_str}")

        # Hex dump: optionally include the TCP 2-byte length prefix
        if include_tcp_len_prefix:
            tcp_len = len(payload) + 2
            header = struct.pack(">H", tcp_len)
            hex_str = (header + payload).hex().upper()
        else:
            hex_str = payload.hex().upper()

        print(f"       Body={hex_str}")

        if show_ascii:
            ascii_str = "".join(chr(b) if 32 <= b <= 126 else "." for b in payload)
            print(f"       Ascii='{ascii_str}'")

        print("-" * 50)

    # ---------------------------
    # Backwards-compatible API (your current calls)
    # ---------------------------
    def log(
        self,
        direction: str,
        pkt_type: int,
        payload: bytes,
        addr: Optional[Tuple[str, int]] = None,
        show_ascii: bool = True,
    ) -> None:
        """
        Backwards compatible with your old call sites:
            log(direction, pkt_type, payload)
        Here payload can be either:
          - body only (no opcode), OR
          - full payload that already includes opcode
        We normalize to log_packet().
        """
        if not payload:
            # If caller passed body-only and it's empty, still log header line if you want.
            self.log_packet(direction, bytes([pkt_type]), addr=addr, show_ascii=show_ascii)
            return

        # If caller already included opcode, trust it.
        if payload[0] == pkt_type:
            full = payload
        else:
            full = bytes([pkt_type]) + payload

        self.log_packet(direction, full, addr=addr, show_ascii=show_ascii, include_tcp_len_prefix=False)


# Optional convenience function if you want the exact name "log_packet" as a free function.
_default_logger = PacketLogger()

def log_packet(direction: str, payload: bytes, show_ascii: bool = True) -> None:
    """
    Free-function wrapper (drop-in for my earlier example).
    payload includes opcode as first byte.
    """
    _default_logger.log_packet(direction, payload, show_ascii=show_ascii)
