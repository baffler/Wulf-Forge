# network/transport/envelope.py
from __future__ import annotations
import struct
from dataclasses import dataclass

@dataclass(frozen=True)
class PacketEnvelope:
    """Represents one logical packet: opcode byte + body bytes (excluding TCP length)."""
    opcode: int
    body: bytes  # body excludes opcode

    def to_payload(self) -> bytes:
        return bytes([self.opcode]) + self.body

class TcpEnvelope:
    """
    Wulfram TCP framing:
      [u16_be total_len] [payload...]
    where total_len includes the 2-byte length header.
    """
    @staticmethod
    def encode(payload: bytes) -> bytes:
        total_len = len(payload) + 2
        return struct.pack(">H", total_len) + payload

    @staticmethod
    def decode_header(hdr2: bytes) -> int:
        (total_len,) = struct.unpack(">H", hdr2)
        return total_len

class UdpEnvelope:
    """
    Some UDP packets appear raw (no length header), but sometimes include:
      [u16_be total_len == datagram_len] [payload...]
    This unpacks safely.
    """
    @staticmethod
    def try_strip_length(datagram: bytes) -> bytes:
        if len(datagram) >= 3:
            try:
                declared = struct.unpack(">H", datagram[:2])[0]
                if declared == len(datagram):
                    return datagram[2:]
            except Exception:
                pass
        return datagram
