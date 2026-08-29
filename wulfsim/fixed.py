"""16.16 fixed-point helpers, matching the client wire format.

All multi-byte numeric BEHAVIOR(0x24) fields are 16.16 fixed-point on the wire
(`write_fixed1616` in the repo's network/streams) and decoded to float on receipt by
Net_HandleBehavior. The sandbox loads tunables as floats directly, but these helpers
let us round-trip a value through the same quantization the client sees, so a tunable
shown in the UI matches what the client would actually integrate.
"""
from __future__ import annotations

_SCALE = 1 << 16  # 65536


def to_fixed(value: float) -> int:
    """Float -> signed 32-bit 16.16, matching write_fixed1616."""
    return int(round(value * _SCALE)) & 0xFFFFFFFF


def from_fixed(raw: int) -> float:
    """Signed 32-bit 16.16 -> float."""
    raw &= 0xFFFFFFFF
    if raw & 0x80000000:
        raw -= 0x100000000
    return raw / _SCALE


def quantize(value: float) -> float:
    """Round-trip a value through 16.16 to reflect on-wire precision loss."""
    return from_fixed(to_fixed(value))
