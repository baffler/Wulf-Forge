# network/packet_logger.py
from __future__ import annotations
import struct
from typing import Optional, Tuple

class PacketLogger:
    def __init__(self):
        # Map IDs to Readable Names
        self.packet_names = {
            0x02: "D_ACK",
            0x03: "D_HANDSHAKE",
            0x08: "HELLO_ACK",
            0x09: "ACTION_DUMP",
            0x0A: "ACTION_UPDATE",
            0x0B: "PING_REQUEST",
            0x13: "HELLO",
            0x1F: "COMM_MESSAGE",
            0x20: "COMM_REQ",
            0x21: "LOGIN_REQ",
            0x24: "BEHAVIOR",
            0x33: "ACK2",
            0x40: "KEEP_ALIVE",
            0x4C: "ROUTING_PING",
            0x4D: "ID_UDP",
            0x4E: "BPS_REQUEST",
        }

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
