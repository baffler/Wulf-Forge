"""Control-scalar normalization -- 1:1 port.

  VehicleTuningSlot_GetScaledValue   0x004f6420
  VehicleTuning_ComputeControlScalars 0x004f9540

Each server tuning value (turn/move/strafe adjust, ...) is divided by a runtime divisor
and clamped to the normalized range [-1.0, 1.0]. ComputeControlScalars additionally
negates the turn and strafe coefficients. The result is a per-axis authority multiplier,
not the thrust magnitude itself (magnitude comes from the chassis scale factors and the
raw input in the thrust path).
"""
from __future__ import annotations

from dataclasses import dataclass

from .constants import CONTROL_CLAMP_MIN, CONTROL_CLAMP_MAX


def get_scaled_value(raw: float, divisor: float) -> float:
    """VehicleTuningSlot_GetScaledValue @ 0x004f6420: raw/divisor clamped to [-1, 1]."""
    v = raw / divisor if divisor != 0.0 else 0.0
    if v <= CONTROL_CLAMP_MAX:
        if v < CONTROL_CLAMP_MIN:
            return CONTROL_CLAMP_MIN
        return v
    return CONTROL_CLAMP_MAX


def _clamp(v: float) -> float:
    """The inline clamp used throughout ComputeControlScalars: [-1, 1]."""
    if v <= CONTROL_CLAMP_MAX:
        if v < CONTROL_CLAMP_MIN:
            return CONTROL_CLAMP_MIN
        return v
    return CONTROL_CLAMP_MAX


@dataclass(slots=True)
class ControlScalars:
    """Normalized per-axis authority coefficients (vehicle control struct):
        move  (+0x70), turn (+0x74, negated), strafe (+0x78, negated)."""
    move: float = 0.0    # +0x70
    turn: float = 0.0    # +0x74 (negated)
    strafe: float = 0.0  # +0x78 (negated)


def compute_control_scalars(turn_adjust: float, move_adjust: float, strafe_adjust: float,
                            divisor: float) -> ControlScalars:
    """VehicleTuning_ComputeControlScalars @ 0x004f9540.

    Slot order in the binary: 1=turn, 2=move, 3=strafe. Turn and strafe are negated,
    then every coefficient is clamped to [-1, 1].
    """
    turn = -get_scaled_value(turn_adjust, divisor)
    strafe = -get_scaled_value(strafe_adjust, divisor)
    move = get_scaled_value(move_adjust, divisor)
    return ControlScalars(move=_clamp(move), turn=_clamp(turn), strafe=_clamp(strafe))
