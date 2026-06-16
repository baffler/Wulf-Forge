"""Attach to a running wulfram2.exe and read its live physics state.

Uses pymem (ReadProcessMemory under the hood). All offsets below are the entity-physics
record offsets confirmed from the Ghidra decompilation (EntityPhysics_IntegrateStep
@ 0x004f2890); the gravity global is _DAT_005738b8.

Locating the local-player entity:
  The physics block lives at `entity_base + OFFSETS[...]`. `entity_base` is resolved from a
  pointer chain you provide in AttachConfig (a static address that holds a pointer to the
  active player entity, optionally followed by further offsets). Static module base is added
  automatically when `rebase=True` and the recorded image base differs from the live one.
  Find the pointer with Cheat Engine / Ghidra (a global holding the local ship object) and
  drop it into AttachConfig.entity_ptr_chain. Until then, attach is inert and the sim runs
  standalone.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Optional

# Entity-physics record offsets (bytes from the entity base). See sim/body.py.
OFFSETS = {
    "pos":       0x0c,
    "vel":       0x18,
    "accel":     0x24,
    "euler":     0x30,
    "ang_vel":   0x3c,
    "ang_accel": 0x48,
}

GRAVITY_ADDR = 0x005738b8          # _DAT_005738b8 (float)
DEFAULT_IMAGE_BASE = 0x00400000    # wulfram2.exe recorded preferred base


@dataclass
class AttachConfig:
    process_name: str = "wulfram2.exe"
    # Static address (in recorded image-base terms) that holds a POINTER to the player entity,
    # followed by zero or more dereference offsets to reach the physics record base.
    # Example: entity_ptr_chain = (0x006XXXXX, 0x0) -> read ptr at 0x6XXXXX, that IS the base.
    entity_ptr_chain: tuple[int, ...] = field(default_factory=tuple)
    gravity_addr: int = GRAVITY_ADDR
    image_base: int = DEFAULT_IMAGE_BASE
    rebase: bool = True


class GameAttach:
    def __init__(self, cfg: AttachConfig | None = None) -> None:
        self.cfg = cfg or AttachConfig()
        self._pm = None
        self._module_base = self.cfg.image_base

    # -- lifecycle --
    def open(self) -> None:
        try:
            import pymem  # type: ignore
        except ImportError as e:
            raise RuntimeError("pymem not installed; `pip install pymem` to use live attach") from e
        self._pm = pymem.Pymem(self.cfg.process_name)
        if self.cfg.rebase:
            mod = pymem.process.module_from_name(self._pm.process_handle, self.cfg.process_name)
            if mod is not None:
                self._module_base = mod.lpBaseOfDll

    @property
    def attached(self) -> bool:
        return self._pm is not None

    def _rebase(self, static_addr: int) -> int:
        if not self.cfg.rebase:
            return static_addr
        return static_addr - self.cfg.image_base + self._module_base

    # -- raw reads --
    def _read(self, addr: int, n: int) -> bytes:
        return self._pm.read_bytes(addr, n)

    def read_float(self, addr: int, rebase: bool = True) -> float:
        a = self._rebase(addr) if rebase else addr
        return struct.unpack("<f", self._read(a, 4))[0]

    def read_vec3(self, addr: int, rebase: bool = False) -> list[float]:
        a = self._rebase(addr) if rebase else addr
        return list(struct.unpack("<3f", self._read(a, 12)))

    def read_ptr(self, addr: int, rebase: bool = True) -> int:
        a = self._rebase(addr) if rebase else addr
        return struct.unpack("<I", self._read(a, 4))[0]

    # -- resolved reads --
    def resolve_entity_base(self) -> Optional[int]:
        chain = self.cfg.entity_ptr_chain
        if not chain:
            return None
        addr = self._rebase(chain[0])
        base = self.read_ptr(addr, rebase=False)
        for off in chain[1:]:
            if base == 0:
                return None
            base = self.read_ptr(base + off, rebase=False)
        return base or None

    def read_gravity(self) -> float:
        return self.read_float(self.cfg.gravity_addr, rebase=True)

    def read_physics(self) -> Optional[dict]:
        """Read the live entity physics block, or None if the entity can't be resolved."""
        base = self.resolve_entity_base()
        if not base:
            return None
        snap = {name: self.read_vec3(base + off, rebase=False) for name, off in OFFSETS.items()}
        snap["gravity"] = self.read_gravity()
        snap["entity_base"] = base
        return snap
