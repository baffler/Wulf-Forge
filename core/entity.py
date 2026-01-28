from dataclasses import dataclass, field
from enum import IntFlag

class UpdateMask(IntFlag):
    """
    Maps directly to the r_update_bitmask in the C++ client.
    """
    # Bit 0: Definition (0 = Delta/Move, 1 = Full Create/Def)
    DEFINITION = 1 << 0  
    # Bit 1-4: Physics Vectors
    POS        = 1 << 1  
    VEL        = 1 << 2  
    ROT        = 1 << 3  
    SPIN       = 1 << 4  
    # Bit 5-8: State/Stats
    HEALTH     = 1 << 5  
    WEAPON     = 1 << 6  
    ENERGY     = 1 << 7  
    OWNER      = 1 << 8  
    # Bit 9: Hard Sync (Forces position snap, no interpolation)
    HARD_SYNC  = 1 << 9 

@dataclass
class GameEntity:
    net_id: int
    unit_type: int = 0
    team_id: int = 0
    
    # State Data
    pos: tuple = (0.0, 0.0, 0.0)
    vel: tuple = (0.0, 0.0, 0.0)
    rot: tuple = (0.0, 0.0, 0.0)
    health: float = 1.0
    energy: float = 1.0
    
    # Flags
    is_manned: bool = True
    
    # Dirty flags: These determine what gets sent in the next packet
    pending_mask: int = 0 

    def mark_dirty(self, mask: UpdateMask):
        """Flag specific fields to be sent in the next update."""
        self.pending_mask |= mask

    def clear_dirty(self):
        """Reset flags after packet is sent."""
        self.pending_mask = 0

    def set_pos(self, x, y, z):
        self.pos = (x, y, z)
        # Usually when pos changes, we want a hard sync or standard pos update
        self.mark_dirty(UpdateMask.POS)

    def set_stats(self, health=None, energy=None):
        if health is not None:
            self.health = health
            self.mark_dirty(UpdateMask.HEALTH)
        if energy is not None:
            self.energy = energy
            self.mark_dirty(UpdateMask.ENERGY)