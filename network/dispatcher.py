# network/dispatcher.py
from __future__ import annotations
from typing import Callable, Any

class PacketDispatcher:
    def __init__(self, on_unknown: Callable[[Any, bytes], None] | None = None):
        # Maps Opcode (int) -> Handler Function
        self._handlers: dict[int, Callable] = {}
        self.on_unknown = on_unknown

    def route(self, opcode: int):
        """
        Decorator to register a handler for a specific opcode.
        Usage: @dispatcher.route(0x13)
        """
        def decorator(func):
            if opcode in self._handlers:
                print(f"[WARN] Overwriting handler for opcode 0x{opcode:02X}")
            self._handlers[opcode] = func
            return func
        return decorator

    def dispatch_payload(self, ctx: Any, payload: bytes):
        if not payload:
            return

        opcode = payload[0]
        handler = self._handlers.get(opcode)

        if handler:
            # Call the handler found via the decorator
            handler(ctx, payload)
        elif self.on_unknown:
            self.on_unknown(ctx, payload)
        else:
            print(f"[TCP] Unhandled opcode 0x{opcode:02X}")