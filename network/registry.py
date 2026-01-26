# network/core/registry.py
from __future__ import annotations
from typing import Callable, Dict, Optional, Any

Handler = Callable[[Any, bytes], None]  # (ctx, payload) -> None

class PacketRegistry:
    def __init__(self):
        self._handlers: Dict[int, Handler] = {}

    def register(self, opcode: int, handler: Handler) -> None:
        if not isinstance(opcode, int):
            raise TypeError("opcode must be int")
        if opcode in self._handlers:
            raise ValueError(f"Handler already registered for opcode 0x{opcode:02X}")
        self._handlers[opcode] = handler

    def get(self, opcode: int) -> Optional[Handler]:
        return self._handlers.get(opcode)
