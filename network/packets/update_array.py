from network.streams import PacketWriter
from network.translation_config import *
from core.config import get_ticks
from core.entity import GameEntity, UpdateMask

class EntitySerializer:
    """
    Helper class that handles the specific bit-writing order 
    required by the C++ client's 'WIP_read_array_from_bitstream'.
    """
    def __init__(self, writer: PacketWriter):
        self.writer = writer

    def serialize(self, entity: GameEntity, force_definition=False):
        # 1. Determine the Mask
        mask = entity.pending_mask
        
        # If forcing definition (spawning), ensure Bit 0 is set
        if force_definition:
            mask |= UpdateMask.DEFINITION
            
        # 2. Write Header (Standard for every entity)
        self.writer.write_int32(entity.net_id)
        self.writer.write_bool(entity.is_manned)
        self.writer.write_bits(mask, 10)
        
        # Bank Selector
        # C++ reads Index[0].header bits. We defined this as BANK_SELECTOR_BITS (16).
        # We write '0' to choose Bank 0 (Index 16).
        self.writer.write_bits(0, BANK_SELECTOR_BITS) 

        # 3. Handle Bit 0: Definition (The "Creation" block)
        if mask & UpdateMask.DEFINITION:
            # unit_type (8 bits usually)
            self.writer.write_bits(entity.unit_type, ID_BITS_UNIT)
            # team_id (8 bits)
            self.writer.write_bits(entity.team_id, ID_BITS_TEAM)
            # team_id_also_maybe (State/Sub-team)
            self.writer.write_bits(entity.team_id, ID_BITS_TEAM) 

            # TODO: 37 = decoration, figure out what the ints are for
            if entity.unit_type == 37:
                self.writer.write_int32(0)
                self.writer.write_int32(0)
            elif entity.unit_type == 19:
                # Need to store/get actual unit id value, hardcoding 25 for now (Power Cell)
                self.writer.write_bits(25, ID_BITS_UNIT_CARGO) 
            
            # is_teleport_or_snap (Force Snap)
            self.writer.write_bool(True) 
        
        # 4. The Dynamic Data Loop
        # The C++ client iterates bits 1 through 9. Order is strict.

        # Bit 1: Position
        if mask & UpdateMask.POS:
            self._write_vec(entity.pos, COMPRESSOR_POS)
            
        # Bit 2: Velocity
        if mask & UpdateMask.VEL:
            self._write_vec(entity.vel, COMPRESSOR_VEL)
            
        # Bit 3: Rotation
        if mask & UpdateMask.ROT:
            self._write_vec(entity.rot, COMPRESSOR_ROT)
            
        # Bit 4: Spin (Angular Velocity)
        if mask & UpdateMask.SPIN:
            self._write_vec(entity.spin, COMPRESSOR_SPIN) 

        # Bit 5: Health
        if mask & UpdateMask.HEALTH:
            _, val, bits = COMPRESSOR_STAT.compress(entity.health)
            self.writer.write_bits(val, bits) 

        # Bit 6: Weapon Inventory
        if mask & UpdateMask.WEAPON:
            # TODO: Implement Net_Read_Weapon_Inventory writer
            pass 

        # Bit 7: Energy
        if mask & UpdateMask.ENERGY:
             _, val, bits = COMPRESSOR_STAT.compress(entity.energy)
             self.writer.write_bits(val, bits)

        # Bit 8: Owner/New Player
        if mask & UpdateMask.OWNER:
            # TODO: Implement Owner ID logic if needed
            self.writer.write_int32(0) 

        # Bit 9: Hard Update
        # No payload; just a flag.
        pass

    def _write_vec(self, vec, compressor: TranslationConfig):
        """
        Writes a 3D vector dynamically matching C++ logic:
        [Header] [X_Data] [Y_Data] [Z_Data]
        """
        # 1. Determine "High Quality" Priority
        # We want the max resolution defined in the config.
        # If header_bits is 2, max value is 3 (binary 11).
        priority = (1 << compressor.precision_header_bits) - 1
        
        # 2. Write the Header ONCE
        # The client reads 'precision_header_bits' here.
        self.writer.write_bits(priority, compressor.precision_header_bits)

        # 3. Write X, Y, Z
        for val in vec:
            # We enforce the priority we just wrote
            p, compressed_val, num_bits = compressor.compress(val, priority=priority)

            #print(f"[DEBUG] pri={p} val={compressed_val} bits={num_bits}")
            
            # Write the compressed int using the calculated bit count
            self.writer.write_bits(compressed_val, num_bits)

class UpdateArrayPacket:
    def __init__(self, sequence_id:int, is_view_update=False):
        self.writer = PacketWriter()
        self.sequence_id = sequence_id
        self.entities = []
        self.local_stats = None # Tuple: (Health, Energy)

        # Timestamp
        if (is_view_update):
            self.writer.write_int32(get_ticks())
        
        # Server Sequence
        self.writer.write_int32(self.sequence_id)

    def set_local_stats(self, health: float, energy: float):
        """
        Sets the HUD stats for the player receiving this packet.
        Corresponds to 'Parse_SpawnVitalStats' in C++.
        """
        self.local_stats = (health, energy)

    def add_entity(self, entity: GameEntity, force_spawn=False):
        """Adds an entity to be serialized in this packet."""
        self.entities.append((entity, force_spawn))

    def get_bytes(self):
        # --- SECTION 1: Local Stats (The "Weapon State/Vital Stats" part) ---
        if self.local_stats:
            # The client reads one bit: If 1, it reads stats.
            self.writer.write_bool(True) 
            
            # 5 bits padding/ID (based on your trace)
            self.writer.write_bits(0, 5) 
            
            _, h_val, h_bits = COMPRESSOR_STAT.compress(self.local_stats[0])
            _, e_val, e_bits = COMPRESSOR_STAT.compress(self.local_stats[1])
            
            self.writer.write_bits(h_val, h_bits)
            self.writer.write_bits(e_val, e_bits)
        else:
            # If 0, client skips Parse_SpawnVitalStats
            self.writer.write_bool(False) 

        # --- SECTION 2: Entity Loop ---
        count = len(self.entities)
        
        # Total Entity Count (8 bits)
        self.writer.write_bits(count, 8)

        serializer = EntitySerializer(self.writer)
        
        for entity, force_spawn in self.entities:
            serializer.serialize(entity, force_definition=force_spawn)

        return self.writer.get_bytes()