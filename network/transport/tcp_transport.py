# network/transport/tcp_transport.py
from __future__ import annotations
import socket
from typing import Optional
from .envelope import TcpEnvelope

def recv_exact(sock: socket.socket, n: int) -> Optional[bytes]:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf

class TcpTransport:
    def __init__(self, sock: socket.socket):
        self.sock = sock

    def send_payload(self, payload: bytes) -> None:
        framed = TcpEnvelope.encode(payload)
        self.sock.sendall(framed)

    def recv_payload(self) -> Optional[bytes]:
        hdr = recv_exact(self.sock, 2)
        if not hdr:
            return None
        total_len = TcpEnvelope.decode_header(hdr)
        body = recv_exact(self.sock, total_len - 2)
        return body
