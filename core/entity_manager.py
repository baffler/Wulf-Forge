# core/entity_manager.py
from typing import Dict, List, Optional
from core.entity import GameEntity, UpdateMask
from network.packets.update_array import (
    UpdateArrayPacket,
    get_entity_update_bit_length,
    get_update_array_header_bit_length,
)
from network.packets.gameplay import DeleteObjectPacket

STATIC_ANCHOR_MASK = (
    UpdateMask.POS
    | UpdateMask.VEL
    | UpdateMask.ROT
    | UpdateMask.SPIN
    | UpdateMask.HARD_SYNC
)

# Keep update datagrams below a conservative UDP payload ceiling. This avoids
# IP fragmentation while leaving room for VPN/tunnel overhead.
MAX_UPDATE_PACKET_BYTES = 1200
MAX_UPDATE_ENTITIES = 255

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

        print(f"[DEBUG] create_entity: net_id={net_id} unit_type={unit_type} team_id={team_id} pos={pos}")

        entity = GameEntity(net_id=net_id, unit_type=unit_type, team_id=team_id)
        entity.pos = pos
        entity.health = 1.0
        # Marking DEFINITION as dirty will make sure it gets spawned
        # And HEALTH and POS will make sure those stats are updated at the same time
        entity.mark_dirty(UpdateMask.DEFINITION | UpdateMask.HEALTH | UpdateMask.POS)
        
        self._entities[net_id] = entity
        return entity

    def remove_entity(self, net_id: int) -> Optional[DeleteObjectPacket]:
        """
        Removes the entity from the registry and returns the DeleteObjectPacket.
        The caller is responsible for broadcasting this packet.
        """
        if net_id in self._entities:
            del self._entities[net_id]
            return DeleteObjectPacket(net_id=net_id)
        
        return None

    def get_entity(self, net_id: int) -> Optional[GameEntity]:
        return self._entities.get(net_id)

    def get_all(self) -> List[GameEntity]:
        return list(self._entities.values())
    
    def get_dirty_entities(self) -> List[GameEntity]:
        """Returns a list of all entities that have changed this tick."""
        return [e for e in self._entities.values() if e.pending_mask > 0]

    def clear_all_dirty_flags(self):
        """Clears dirty flags for all entities. Call this AT THE END of a tick."""
        for e in self._entities.values():
            e.clear_dirty()

    # --- PACKET GENERATION ---

    def _serialize_update_entries(
        self,
        entries: list[tuple[GameEntity, bool, int | None]],
        sequence_num: int,
        is_view_update: bool,
        local_stats: tuple[float, float] | None,
    ) -> bytes:
        packet = UpdateArrayPacket(sequence_id=sequence_num, is_view_update=is_view_update)
        if local_stats is not None:
            packet.set_local_stats(health=local_stats[0], energy=local_stats[1])

        for entity, force_spawn, forced_mask in entries:
            packet.add_entity(
                entity,
                force_spawn=force_spawn,
                forced_mask=forced_mask,
            )

        opcode = b'\x0F' if is_view_update else b'\x0E'
        return opcode + packet.get_bytes()

    def _build_batched_update_packets(
        self,
        entries: list[tuple[GameEntity, bool, int | None]],
        sequence_num: int,
        is_view_update: bool,
        local_stats: tuple[float, float] | None,
        max_packet_bytes: int = MAX_UPDATE_PACKET_BYTES,
    ) -> List[bytes]:
        """Greedily pack complete entity records into MTU-safe update arrays."""
        if max_packet_bytes < 1:
            raise ValueError("max_packet_bytes must be at least 1")

        if not entries:
            if local_stats is None:
                return []
            payload = self._serialize_update_entries(
                [], sequence_num, is_view_update, local_stats
            )
            if len(payload) > max_packet_bytes:
                raise ValueError("update-array header exceeds max_packet_bytes")
            return [payload]

        payloads: List[bytes] = []
        current_entries: list[tuple[GameEntity, bool, int | None]] = []
        header_bits = get_update_array_header_bit_length(
            is_view_update,
            local_stats,
        )
        current_bits = header_bits

        def serialize_checked(
            batch: list[tuple[GameEntity, bool, int | None]],
        ) -> bytes:
            payload = self._serialize_update_entries(
                batch,
                sequence_num,
                is_view_update,
                local_stats,
            )
            if len(payload) > max_packet_bytes:
                raise AssertionError(
                    "measured update batch exceeded max_packet_bytes after encoding"
                )
            return payload

        for entry in entries:
            entry_bits = get_entity_update_bit_length(
                entry[0],
                force_spawn=entry[1],
                forced_mask=entry[2],
            )
            candidate_count = len(current_entries) + 1
            candidate_bytes = 1 + ((current_bits + entry_bits + 7) // 8)
            exceeds_count = candidate_count > MAX_UPDATE_ENTITIES
            exceeds_bytes = candidate_bytes > max_packet_bytes

            if not current_entries and exceeds_bytes:
                raise ValueError(
                    f"entity {entry[0].net_id} update exceeds max_packet_bytes"
                )

            if current_entries and (exceeds_count or exceeds_bytes):
                payloads.append(serialize_checked(current_entries))
                current_entries = [entry]
                current_bits = header_bits + entry_bits
                single_entry_bytes = 1 + ((current_bits + 7) // 8)
                if single_entry_bytes > max_packet_bytes:
                    raise ValueError(
                        f"entity {entry[0].net_id} update exceeds max_packet_bytes"
                    )
            else:
                current_entries.append(entry)
                current_bits += entry_bits

        if current_entries:
            payloads.append(serialize_checked(current_entries))

        return payloads

    def build_update_packets(
        self,
        entities: List[GameEntity],
        sequence_num: int,
        is_view_update: bool,
        local_stats: tuple[float, float] | None = None,
        max_packet_bytes: int = MAX_UPDATE_PACKET_BYTES,
    ) -> List[bytes]:
        """
        Constructs one or more complete UpdateArray packets without clearing
        dirty flags, allowing the same state to be reused for every client.
        """
        entries = [
            (entity, bool(entity.pending_mask & UpdateMask.DEFINITION), None)
            for entity in entities
        ]
        return self._build_batched_update_packets(
            entries,
            sequence_num,
            is_view_update,
            local_stats,
            max_packet_bytes,
        )

    def build_static_anchor_packets(
        self,
        sequence_num: int,
        local_stats: tuple[float, float] | None = None,
        max_packet_bytes: int = MAX_UPDATE_PACKET_BYTES,
    ) -> List[bytes]:
        """
        Reasserts unmanned map objects so client-side collision impulses do not
        make static base props drift away locally.  The updates are split into
        MTU-safe datagrams so the correction is not lost to IP fragmentation.
        """
        static_entities = [e for e in self._entities.values() if not e.is_manned]
        if not static_entities:
            return []

        for entity in static_entities:
            entity.vel = (0.0, 0.0, 0.0)
            entity.spin = (0.0, 0.0, 0.0)

        entries = [
            (entity, False, int(STATIC_ANCHOR_MASK))
            for entity in static_entities
        ]
        return self._build_batched_update_packets(
            entries,
            sequence_num,
            False,
            local_stats,
            max_packet_bytes,
        )

    def build_forced_update_packets(
        self,
        entities: List[GameEntity],
        sequence_num: int,
        is_view_update: bool,
        forced_mask: int,
        local_stats: tuple[float, float] | None = None,
        force_spawn: bool = True,
        max_packet_bytes: int = MAX_UPDATE_PACKET_BYTES,
    ) -> List[bytes]:
        """
        Constructs an UpdateArray payload with an explicit mask instead of each
        entity's pending dirty state. This is useful for join-in-progress catch-up
        snapshots where the target client missed an earlier DEFINITION update.
        """
        entries = [(entity, force_spawn, forced_mask) for entity in entities]
        return self._build_batched_update_packets(
            entries,
            sequence_num,
            is_view_update,
            local_stats,
            max_packet_bytes,
        )

    def get_snapshot_packets(
        self,
        sequence_num: int,
        health: float = 1.0,
        energy: float = 1.0,
        max_packet_bytes: int = MAX_UPDATE_PACKET_BYTES,
    ) -> List[bytes]:
        """
        Returns packets containing the FULL state of the world + Local Stats.
        THREAD-SAFE: Does not modify entity state.
        """
        # Define the mask we want for a full snapshot (Pos + Health + Def)
        snapshot_mask = UpdateMask.POS | UpdateMask.HEALTH | UpdateMask.DEFINITION
        entries = [
            (entity, True, int(snapshot_mask))
            for entity in self._entities.values()
        ]
        return self._build_batched_update_packets(
            entries,
            sequence_num,
            True,
            (health, energy),
            max_packet_bytes,
        )

    def get_dirty_packets(
        self,
        sequence_num: int,
        health: float = 1.0,
        energy: float = 1.0,
        max_packet_bytes: int = MAX_UPDATE_PACKET_BYTES,
    ) -> List[bytes]:
        """
        Returns packets containing ONLY changed entities.
        Used in the main 10Hz update loop.
        Automatically clears the dirty flags of processed entities.
        """
        dirty_entities = [e for e in self._entities.values() if e.pending_mask > 0]
        
        # OPTIMIZATION: If nothing changed, we MIGHT still want to send stats 
        # to keep the health bar synced, but usually we only send if entities move.
        # For now, let's only send if there are entity updates OR if we want to force a heartbeat.
        if not dirty_entities:
            return []

        payloads = self.build_update_packets(
            dirty_entities,
            sequence_num,
            False,
            (health, energy),
            max_packet_bytes,
        )

        # Need to clear_dirty AFTER we call packet.get_bytes()!
        for entity in dirty_entities:
            # Reset flags so we don't send it again until it changes
            entity.clear_dirty()

        return payloads
    
    def get_dirty_packets_view(
        self,
        sequence_num: int,
        health: float = 1.0,
        energy: float = 1.0,
        max_packet_bytes: int = MAX_UPDATE_PACKET_BYTES,
    ) -> List[bytes]:
        """
        Returns packets containing ONLY changed entities.
        Used in the main update loop.
        Automatically clears the dirty flags of processed entities.
        """
        dirty_entities = [e for e in self._entities.values() if e.pending_mask > 0]
        
        # OPTIMIZATION: If nothing changed, we MIGHT still want to send stats 
        # to keep the health bar synced, but usually we only send if entities move.
        # For now, let's only send if there are entity updates OR if we want to force a heartbeat.
        if not dirty_entities:
            return []

        payloads = self.build_update_packets(
            dirty_entities,
            sequence_num,
            True,
            (health, energy),
            max_packet_bytes,
        )

        # Need to clear_dirty AFTER we call packet.get_bytes()!
        for entity in dirty_entities:
            # Reset flags so we don't send it again until it changes
            entity.clear_dirty()

        return payloads
