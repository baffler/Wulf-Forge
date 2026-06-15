"""Server-authoritative cargo pickup, carry, and deployment.

Reverse-engineered from wulfram2.exe (Ghidra W2VULK). See
docs/superpowers/specs/2026-06-15-cargo-pickup-deploy-design.md.

Authority model (faithful to the client):
- Pickup is server-driven and automatic. The client sends NO pickup packet; it
  only renders cues. When an uncarried vehicle is slow & low enough (the
  `max_speed_height_pickup` gate) and within range of a non-base cargo box
  (unit_type 19), the server attaches it and pushes CARRYING_INFO (0x29).
- Deploy/drop arrive as DROP_REQUEST (0x2B), a single int32: 1 = deploy carried
  cargo as a structure, 0 = drop it loose. The server is fully authoritative;
  the client's good/iffy/bad placement icons are advisory only.

This module is renderer/socket agnostic: methods mutate the EntityManager and
return a list of packets for the caller to broadcast. New entities created here
are marked dirty by the EntityManager and ride out on the normal update loop.
"""
from __future__ import annotations

import math
from typing import List, Optional

from core.entity import GameEntity
from core.entity_manager import EntityManager
from network.packets.base import Packet
from network.packets.gameplay import CarryingInfoPacket

# A cargo box in-world is this unit type; the contained unit type rides in the
# entity DEFINITION block (ID_BITS_UNIT_CARGO).
CARGO_BOX_UNIT_TYPE = 19


class CargoSystem:
    def __init__(
        self,
        entities: EntityManager,
        *,
        pickup_radius: float = 15.0,
        ground_z: float = 0.0,
    ):
        self.entities = entities
        # Collision distance: pick up a box when within this 3D range of it.
        self.pickup_radius = pickup_radius
        # Flat ground reference until terrain sampling is wired in; the deployed
        # unit settles here and is then held by the static-anchor mechanism.
        self.ground_z = ground_z

    # -- pickup -----------------------------------------------------------

    def is_eligible(self, carrier: GameEntity) -> bool:
        """Collision-based pickup: the only gate is not already carrying.

        Speed/altitude no longer gate pickup — touching a box grabs it.
        """
        return carrier.carried_cargo_type is None

    def describe_pickup(self, carrier: GameEntity) -> dict:
        """Diagnostic snapshot of a carrier's pickup state (for /s cargostatus)."""
        box = self.find_nearest_box(carrier)
        nearest = None
        if box is not None:
            bx, by, bz = box.pos
            cx, cy, cz = carrier.pos
            nearest = math.sqrt((bx - cx) ** 2 + (by - cy) ** 2 + (bz - cz) ** 2)
        return {
            "carrying": carrier.carried_cargo_type is not None,
            "eligible": self.is_eligible(carrier),
            "nearest_dist": nearest,
            "pickup_radius": self.pickup_radius,
        }

    def find_nearest_box(self, carrier: GameEntity) -> Optional[GameEntity]:
        """Nearest cargo box within the collision radius, else None."""
        best: Optional[GameEntity] = None
        best_dist = self.pickup_radius
        cx, cy, cz = carrier.pos
        for ent in self.entities.get_all():
            if ent is carrier or ent.unit_type != CARGO_BOX_UNIT_TYPE:
                continue
            ex, ey, ez = ent.pos
            dist = math.sqrt((ex - cx) ** 2 + (ey - cy) ** 2 + (ez - cz) ** 2)
            if dist <= best_dist:
                best = ent
                best_dist = dist
        return best

    def try_pickup(self, carrier: GameEntity, carrier_id: int) -> List[Packet]:
        """Attempt an automatic pickup for one carrier; returns packets to broadcast."""
        if not self.is_eligible(carrier):
            return []
        box = self.find_nearest_box(carrier)
        if box is None:
            return []
        return self._attach(carrier, carrier_id, box)

    def _attach(self, carrier: GameEntity, carrier_id: int, box: GameEntity) -> List[Packet]:
        carrier.carried_cargo_type = box.cargo_contained_type
        carrier.carried_variant = carrier.team_id
        packets: List[Packet] = [
            CarryingInfoPacket(
                player_id=carrier_id,
                has_cargo=True,
                cargo_type=box.cargo_contained_type,
                variant=carrier.team_id,
            )
        ]
        del_pkt = self.entities.remove_entity(box.net_id)
        if del_pkt is not None:
            packets.append(del_pkt)
        return packets

    # -- deploy / drop ----------------------------------------------------

    def handle_drop_request(self, carrier: GameEntity, carrier_id: int, deploy: bool) -> List[Packet]:
        """Handle a DROP_REQUEST (0x2B): deploy a structure or drop a loose box."""
        if carrier.carried_cargo_type is None:
            return []

        contained = carrier.carried_cargo_type
        cx, cy, _cz = carrier.pos
        spawn_pos = (cx, cy, self.ground_z)

        if deploy:
            # The contained unit becomes a real structure. Unmanned => the
            # static-anchor mechanism freezes it once settled.
            unit = self.entities.create_entity(
                unit_type=contained, team_id=carrier.team_id, pos=spawn_pos
            )
            unit.is_manned = False
        else:
            # Release a loose, re-pickupable cargo box carrying the same unit.
            box = self.entities.create_entity(
                unit_type=CARGO_BOX_UNIT_TYPE, team_id=carrier.team_id, pos=spawn_pos
            )
            box.is_manned = False
            box.cargo_contained_type = contained

        carrier.carried_cargo_type = None
        return [
            CarryingInfoPacket(
                player_id=carrier_id,
                has_cargo=False,
                cargo_type=0,
                variant=carrier.team_id,
            )
        ]
