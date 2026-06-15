"""Map decoded client action axes -> wulfsim Inputs.

GameEntity.actions is {action_id: value} populated by the action-packet handlers
(0x09/0x0A). Action ids 1..21; the binary's control slot order is 1=turn, 2=move,
3=strafe (VehicleTuning_ComputeControlScalars). These ids are CONFIRMED in a later
task; change only this constant map if RE corrects them.
"""
from __future__ import annotations

from wulfsim.vehicle import Inputs

ACTION_TURN = 1
ACTION_THROTTLE = 2
ACTION_STRAFE = 3
ACTION_VERTICAL = 4  # provisional (flyers); unused for Tank


def _clamp_unit(v: float) -> float:
    return -1.0 if v < -1.0 else 1.0 if v > 1.0 else v


def controls_from_actions(actions: dict) -> Inputs:
    g = lambda aid: _clamp_unit(float(actions.get(aid, 0.0)))
    return Inputs(
        throttle=g(ACTION_THROTTLE),
        strafe=g(ACTION_STRAFE),
        turn=g(ACTION_TURN),
        vertical=g(ACTION_VERTICAL),
    )
