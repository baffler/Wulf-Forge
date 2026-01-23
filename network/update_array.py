from .streams import PacketWriter
from .compressor import COMPRESSOR_POS, COMPRESSOR_VEL, COMPRESSOR_ROT, COMPRESSOR_STAT

class UpdateArrayPacket:
    def __init__(self, sequence_id):
        self.sequence_id = sequence_id
        self.writer = PacketWriter()
        self.entity_count = 0
        
        # --- 1. WRITE GLOBAL HEADER ---
        # Packet ID 0x49 (UPDATE_ARRAY - verified from context)
        # Note: In your UDP handler, you might send the ID separately. 
        # If so, just remove this line.
        #self.writer.write_byte(0x0E) 
        
        # Sequence (Monotonic time/frame ID)
        self.writer.write_int32(sequence_id)
        
        # Weapon State (The "Reader within a Reader")
        # The client calls 'Read_Weapon_State'. 
        # Writing a single '0' bit tells it "No Weapon Changes".
        self.writer.write_bits(0, 1) 
        
        # Entity Count Placeholder (We will overwrite this later or assume 1)
        # For now, let's just write 1 because we know we are testing 1 tank.
        self.writer.write_bits(1, 8) 

        #Write all 1s (11111111)
        #self.writer.write_bits(0xFF, 8)

    def update_state(self, seq, energy=None, health=None):
        """
        Updates Health/Energy for an existing entity.
        """

        # We just wrote 1 bit (Weapon) + 8 bits (Count) = 9 bits total offset.
        # We are at Bit 41. The client likely aligns to Bit 48 before reading Int32.
        #self.writer.align()

        # 1. Net ID
        self.writer.write_int32(seq)
        
        # 2. Is Manned? (True)
        self.writer.write_bool(True)
        
        # 3. Build Mask
        # Bit 5 = Energy
        # Bit 7 = Health
        mask = 0
        if energy is not None: mask |= (1 << 5)
        if health is not None: mask |= (1 << 7)
        
        # Write Mask (10 bits)
        """
        Bit Index: [9] [8] [7] [6] [5] [4] [3] [2] [1] [0]
        Value:      0   0   1   0   1   0   0   0   0   0
        Function:  [H] [?] [HP] [?] [EN] [S] [R] [V] [P] [D]

        Bit 0 (D)  = Delta Update (0 for Delta, 1 for Definition)
        Bit 5 (EN) = Energy (You set this)
        Bit 6 (?)  = Unknown/Driver State (You skip this, which is correct)
        Bit 7 (HP) = Health (You set this)
        Bit 9 (H)  = Hard Update (For positions)
        """
        self.writer.write_bits(mask, 10)
        
        # 4. Write Data (Order matters! Low bit to High bit)

        # This is the Precision Selector.
        # Why 0 works: By sending 0 (Binary 00), you are telling the client to use "Precision Profile 0" (Index 16 in the table). As long as you aren't doing complex vector compression requiring different profiles, sending 0 is perfectly safe.
        self.writer.write_bits(0, 2)
        
        # ... Bits 0-4 skipped ...
        
        # Bit 5: Energy
        if energy is not None:
            val = COMPRESSOR_STAT.compress(energy)
            # Write 8 bits (Matches config)
            self.writer.write_bits(val, 8) 
            
        # ... Bit 6 skipped ...
        
        # Bit 7: Health
        if health is not None:
            val = COMPRESSOR_STAT.compress(health)
            self.writer.write_bits(val, 8)

    def add_creation(self, net_id, unit_type, team_id, pos, rot):
        """
        SCENARIO A: The "Spawn" Update.
        Sets Bit 0 of the mask to 1.
        """
        # 1. Net ID
        self.writer.write_int32(net_id)
        
        # 2. Is Manned? (1 bit)
        self.writer.write_bool(True)
        
        # 3. Update Mask (10 bits)
        # Bit 0 = 1 (Creation Mode)
        # Bit 1 = 1 (Has Position - Immediately follows creation)
        # Bit 3 = 1 (Has Rotation)
        mask = 0b0000001011 # Dec: 11
        self.writer.write_bits(mask, 10)
        
        # --- CREATION BLOCK (Bit 0) ---
        # Unit Type ID (Config 2 defines bits, usually 8)
        self.writer.write_bits(unit_type, 8) 
        
        # Team/State (Config 3 defines bits, usually 8)
        self.writer.write_bits(team_id, 8) # Team
        self.writer.write_bits(0, 8)       # State/Flags
        
        # Teleport/Snap Flag (1 bit)
        # 1 = Force Teleport (Don't interpolate from origin)
        self.writer.write_bool(True) 
        
        # --- UPDATE BLOCK ---
        # Since we set Bit 1 and Bit 3, we must write vectors now.
        self._write_vectors(pos, None, rot)

    def add_movement(self, net_id, pos, vel, rot):
        """
        SCENARIO B: The "Move" Update.
        Sets Bit 0 to 0 (Delta Update).
        Sets Bit 9 to 1 (Hard Sync/Keyframe).
        """
        # 1. Net ID
        self.writer.write_int32(net_id)
        
        # 2. Is Manned?
        self.writer.write_bool(True)
        
        # 3. Update Mask (10 bits)
        # Bit 0 = 0 (Delta)
        # Bit 1 = 1 (Position)
        # Bit 2 = 1 (Velocity)
        # Bit 3 = 1 (Rotation)
        # Bit 9 = 1 (Hard Update / Keyframe) -> 0x200
        mask = 0b1000001110 # Hex: 0x20E
        self.writer.write_bits(mask, 10)
        
        # --- UPDATE BLOCK ---
        self._write_vectors(pos, vel, rot)

    def _write_vectors(self, pos, vel, rot):
        """
        Compresses and writes the vectors based on the mask.
        """
        # --- POSITION (Bit 1) ---
        if pos:
            # X
            head, val, bits = COMPRESSOR_POS.compress(pos[0])
            self.writer.write_bits(head, 2) # Header
            self.writer.write_bits(val, bits) # Data
            # Y
            head, val, bits = COMPRESSOR_POS.compress(pos[1])
            self.writer.write_bits(head, 2)
            self.writer.write_bits(val, bits)
            # Z
            head, val, bits = COMPRESSOR_POS.compress(pos[2])
            self.writer.write_bits(head, 2)
            self.writer.write_bits(val, bits)

        # --- VELOCITY (Bit 2) ---
        if vel:
            # X
            head, val, bits = COMPRESSOR_VEL.compress(vel[0])
            self.writer.write_bits(head, 2)
            self.writer.write_bits(val, bits)
            # Y
            head, val, bits = COMPRESSOR_VEL.compress(vel[1])
            self.writer.write_bits(head, 2)
            self.writer.write_bits(val, bits)
            # Z
            head, val, bits = COMPRESSOR_VEL.compress(vel[2])
            self.writer.write_bits(head, 2)
            self.writer.write_bits(val, bits)

        # --- ROTATION (Bit 3) ---
        if rot:
            # X
            head, val, bits = COMPRESSOR_ROT.compress(rot[0])
            self.writer.write_bits(head, 2)
            self.writer.write_bits(val, bits)
            # Y
            head, val, bits = COMPRESSOR_ROT.compress(rot[1])
            self.writer.write_bits(head, 2)
            self.writer.write_bits(val, bits)
            # Z
            head, val, bits = COMPRESSOR_ROT.compress(rot[2])
            self.writer.write_bits(head, 2)
            self.writer.write_bits(val, bits)

    def get_bytes(self):
        return self.writer.get_bytes()