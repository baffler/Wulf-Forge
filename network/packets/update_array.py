from network.streams import PacketWriter
from network.compressor import FloatCompressor, COMPRESSOR_POS, COMPRESSOR_VEL, COMPRESSOR_ROT, COMPRESSOR_STAT
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
        
        # bool_isManned
        self.writer.write_bool(entity.is_manned)
        
        # r_update_bitmask
        self.writer.write_bits(mask, 10)
        
        # Translation Config Header (start at 16, write 16 bits)
        self.writer.write_bits(16, 16) 

        # 3. Handle Bit 0: Definition (The "Creation" block)
        if mask & UpdateMask.DEFINITION:
            # unit_type (8 bits usually)
            self.writer.write_bits(entity.unit_type, 16)
            # team_id (8 bits)
            self.writer.write_bits(entity.team_id, 16)
            # team_id_also_maybe (State/Sub-team)
            self.writer.write_bits(entity.team_id, 16) 
            
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
            # Assuming 0 spin for now, using ROT compressor
            self._write_vec((0,0,0), COMPRESSOR_ROT) 

        # Bit 5: Health
        if mask & UpdateMask.HEALTH:
            val = COMPRESSOR_STAT.compress(entity.health)
            self.writer.write_bits(val, 10) 

        # Bit 6: Weapon Inventory
        if mask & UpdateMask.WEAPON:
            # TODO: Implement Net_Read_Weapon_Inventory writer
            pass 

        # Bit 7: Energy
        if mask & UpdateMask.ENERGY:
             val = COMPRESSOR_STAT.compress(entity.energy)
             self.writer.write_bits(val, 10)

        # Bit 8: Owner/New Player
        if mask & UpdateMask.OWNER:
            # TODO: Implement Owner ID logic if needed
            self.writer.write_int32(0) 

        # Bit 9: Hard Update
        # No payload; just a flag.
        pass

    def _write_vec(self, vec, compressor: FloatCompressor):
        """Writes X, Y, Z using the provided compressor."""
        self.writer.write_bits(4, 4)
        for val in vec:
            h, v, bc = compressor.compress(val)
            self.writer.write_bits(v, 20)

class UpdateArrayPacket:
    def __init__(self, sequence_id=None):
        if sequence_id is None:
            sequence_id = get_ticks()
            
        self.writer = PacketWriter()
        self.sequence_id = sequence_id
        self.entities = []
        self.local_stats = None # Tuple: (Health, Energy)
        
        # --- WRITE PACKET HEADER ---
        # Note: If your system handles Packet IDs outside this class, remove this line.
        # self.writer.write_int8(0x49) 
        
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
            
            h_val = COMPRESSOR_STAT.compress(self.local_stats[0])
            e_val = COMPRESSOR_STAT.compress(self.local_stats[1])
            
            self.writer.write_bits(h_val, 10)
            self.writer.write_bits(e_val, 10)
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