# core/map_loader.py
import math
from typing import Dict, Tuple
from core.entity_manager import EntityManager
from core.entity import UpdateMask

# --- CONFIGURATION ---
UNIT_TYPE_MAP = {
    "e": 25, # Power Cell
    "s": 29, # Flak Turret
    "g": 30, # Gun Turret
    "r": 27, # Repair Pad
    "f": 26, # Refuel Pad
    "u": 20, # Uplink
    "h": 35, # Not sure, going with darklight for now
}

class MapLoader:
    def __init__(self, entity_manager: EntityManager):
        self.em = entity_manager

    def load_from_string(self, map_data: str):
        """Parses the raw map text and spawns entities."""
        count = 0
        lines = map_data.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
                
            parts = line.split()
            
            try:
                # 1. Detect Type and handling 'c' prefix
                char_code = parts[0]
                is_crate = False
                data_start_index = 1
                
                # Handle 'c' prefix (Crated unit)
                if char_code == 'c':
                    is_crate = True
                    char_code = parts[1] # The actual type is the next char
                    data_start_index = 2

                # 2. Resolve Unit Type ID
                unit_type_id = 0
                if is_crate:
                    unit_type_id = 19
                else:
                    unit_type_id = UNIT_TYPE_MAP.get(char_code, 0)

                if unit_type_id == 0:
                    print(f"[MapLoader] WARN: Unknown unit code '{char_code}'")
                    continue

                # 3. Parse Data
                # Syntax: [Type] [Team] [X] [Y] [Z] [RotX] [RotY] [RotZ] [Flag]
                team_id = int(parts[data_start_index])
                
                x = float(parts[data_start_index + 1])
                y = float(parts[data_start_index + 2])
                z = float(parts[data_start_index + 3])
                
                # Rotations
                rx = float(parts[data_start_index + 4])
                ry = float(parts[data_start_index + 5])
                rz = float(parts[data_start_index + 6])
                
                # 4. Create Entity
                # Note: Coordinate systems often differ. 
                # TODO: Check if needed to swap Y and Z or negate them.
                # Assuming direct mapping for now:
                pos = (x, y, z)
                
                entity = self.em.create_entity(unit_type=unit_type_id, team_id=team_id, pos=pos)
                
                # Apply Rotation
                entity.rot = (rx, ry, rz)
                entity.mark_dirty(UpdateMask.ROT)
                
                # Optional: Handle the last flag (Active state?)
                # state_flag = int(parts[data_start_index + 7])
                
                count += 1
                
            except (ValueError, IndexError) as e:
                print(f"[MapLoader] Error parsing line: {line} | {e}")

        print(f"[MapLoader] Successfully loaded {count} entities.")