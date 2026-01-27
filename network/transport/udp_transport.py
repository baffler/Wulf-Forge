# network/transport/udp_transport.py
from __future__ import annotations
import socket
from typing import Iterator
from .envelope import UdpEnvelope

class UdpTransport:
    def __init__(self, sock: socket.socket):
        self.sock = sock

    def send(self, payload: bytes, addr: tuple[str, int]) -> None:
        """
        Sends a packet payload (Opcode + Body) to the specified address.
        """
        self.sock.sendto(payload, addr)

    @staticmethod
    def parse_datagram(datagram: bytes) -> Iterator[bytes]:
        """
        Parses a raw UDP datagram into one or more packet payloads.
        Handles Wulfram's optional length header and packet batching.
        """
        # 1. Strip the optional 2-byte total length header if present
        data = UdpEnvelope.try_strip_length(datagram)
        
        cursor = 0
        total_len = len(data)
        
        while cursor < total_len:
            # Need at least 1 byte for OpCode
            if (total_len - cursor) < 1:
                break
                
            opcode = data[cursor]
            
            # --- Batching Logic ---
            # TODO: need to revisit this because it may not be needed...
            # 0x00 (Debug String) has an explicit internal length: [00][Len][Str...]
            if opcode == 0x00:
                if (total_len - cursor) >= 2:
                    str_len = data[cursor + 1]
                    pkt_size = 1 + 1 + str_len # Op + LenByte + String
                    
                    if (cursor + pkt_size) <= total_len:
                        yield data[cursor : cursor + pkt_size]
                        cursor += pkt_size
                        continue
            
            # Default: Consume the rest of the datagram as a single packet
            # (Most Wulfram packets are 1 per datagram or last in batch)
            yield data[cursor:]
            break