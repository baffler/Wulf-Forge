# network/core/dispatcher.py
from __future__ import annotations
from typing import Any
from .registry import PacketRegistry

class PacketDispatcher:
    def __init__(self, registry: PacketRegistry, *, on_unknown=None):
        self.registry = registry
        self.on_unknown = on_unknown

    def dispatch_payload(self, ctx: Any, payload: bytes) -> None:
        if not payload:
            return
        opcode = payload[0]
        handler = self.registry.get(opcode)
        if handler:
            handler(ctx, payload)
        else:
            if self.on_unknown:
                self.on_unknown(ctx, payload)
