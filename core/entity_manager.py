# core/entity_manager.py
from typing import Dict, List, Optional
from core.entity import GameEntity, UpdateMask
from network.packets.update_array import UpdateArrayPacket

class EntityManager:
    def __init__(self):
        self._entities: Dict[int, GameEntity] = {}
        self._next_net_id = 1  # Start at 1, 0 might be reserved or null

    def create_entity(self, unit_type: int, team_id: int, pos: tuple = (0,0,0), override_net_id: Optional[int] = None) -> GameEntity:
        """Creates, stores, and returns a new entity."""
        if override_net_id is not None:
            net_id = override_net_id
        else:
            net_id = self._next_net_id
            self._next_net_id += 1

        entity = GameEntity(net_id=net_id, unit_type=unit_type, team_id=team_id)
        entity.pos = pos
        entity.health = 1.0
        # Marking DEFINITION as dirty will make sure it gets spawned
        # And HEALTH and POS will make sure those stats are updated at the same time
        entity.mark_dirty(UpdateMask.DEFINITION | UpdateMask.HEALTH | UpdateMask.POS)
        
        self._entities[net_id] = entity
        return entity

    def remove_entity(self, net_id: int):
        if net_id in self._entities:
            del self._entities[net_id]
            # TODO: need to send a "Destroy Entity" packet here.

    def get_entity(self, net_id: int) -> Optional[GameEntity]:
        return self._entities.get(net_id)

    def get_all(self) -> List[GameEntity]:
        return list(self._entities.values())

    # --- PACKET GENERATION ---

    def get_snapshot_packet(self, health: float = 1.0, energy: float = 1.0) -> bytes:
        """
        Returns a packet containing the FULL state of the world + Local Stats.
        """
        packet = UpdateArrayPacket()

        # Tell the client it is alive
        packet.set_local_stats(health=health, energy=energy)
        
        for entity in self._entities.values():
            # TEMPORARY HACK: Force the POS bit on the entity's mask 
            # just for this serialization moment, or handle it in the serializer.
            # The cleanest way without mutating the entity state permanently:
            
            # 1. Save original mask
            original_mask = entity.pending_mask
            
            # 2. Force POS + DEFINITION locally for this packet
            # (set DEFINITION via force_spawn=True, but we need POS to ensure coords are sent)
            entity.pending_mask |= UpdateMask.POS
            entity.pending_mask |= UpdateMask.HEALTH
            
            # 3. Add to packet
            packet.add_entity(entity, force_spawn=True)

        payload = packet.get_bytes()

        # Have to restore the mask AFTER packet.get_bytes()
        for entity in self._entities.values():
            # Restore original mask
            entity.pending_mask = original_mask

        return b'\x0E' + payload

    def get_dirty_packet(self, health: float = 1.0, energy: float = 1.0) -> Optional[bytes]:
        """
        Returns a packet containing ONLY changed entities.
        Used in the main 10Hz update loop.
        Automatically clears the dirty flags of processed entities.
        """
        dirty_entities = [e for e in self._entities.values() if e.pending_mask > 0]
        
        # OPTIMIZATION: If nothing changed, we MIGHT still want to send stats 
        # to keep the health bar synced, but usually we only send if entities move.
        # For now, let's only send if there are entity updates OR if we want to force a heartbeat.
        if not dirty_entities:
            return None

        packet = UpdateArrayPacket()
        packet.set_local_stats(health=health, energy=energy)
        
        for entity in dirty_entities:
            packet.add_entity(entity, force_spawn=False)

        payload = packet.get_bytes()

        # Need to clear_dirty AFTER we call packet.get_bytes()!
        for entity in dirty_entities:
            # Reset flags so we don't send it again until it changes
            entity.clear_dirty()

        return b'\x0E' + payload