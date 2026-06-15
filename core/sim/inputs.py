"""Map decoded client action axes -> wulfsim Inputs.

GameEntity.actions is {action_id: value} populated by the action-packet handlers
(0x09/0x0A). The action-table ids below are CONFIRMED from wulfram2.exe:
Input_UpdateAnalogControlSliders @ 0x00441e20 commits each named analog slider to
a channel id (passed in EDI to Sync_SetChannelTarget), and that id is exactly the
N in DAT_00678e94[N] uploaded by Net_SendActionDump:
  slider "turning"        -> id 1   (EDI=1 @ 0x00442087)
  slider "moving_forward" -> id 2   (EDI=2 @ 0x00441fe6)
  slider "moving_sideways"-> id 3   (EDI=3 @ 0x00442048)
  vertical/jump            -> id 4   (digital momentary axis; high confidence)
"""
from __future__ import annotations

from wulfsim.vehicle import Inputs

ACTION_TURN = 1       # "turning"        (yaw L/R)
ACTION_THROTTLE = 2   # "moving_forward" (fwd/back)
ACTION_STRAFE = 3     # "moving_sideways"(side L/R)
ACTION_VERTICAL = 4   # vertical/jump bit (flyers); unused for Tank


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
