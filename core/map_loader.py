# core/map_loader.py
from dataclasses import dataclass
from pathlib import Path
from core.entity_manager import EntityManager
from core.entity import UpdateMask

# --- CONFIGURATION ---
REPAIR_PAD_UNIT_TYPE = 27

UNIT_TYPE_MAP = {
    "e": 25, # Power Cell
    "s": 29, # Flak Turret
    "g": 30, # Gun Turret
    "r": REPAIR_PAD_UNIT_TYPE, # Repair Pad
    "f": 26, # Refuel Pad
    "u": 20, # Uplink
    "h": 35, # Not sure, going with darklight for now
}

@dataclass(frozen=True, slots=True)
class LandSummary:
    world_w: float
    world_h: float
    max_height: float

def read_land_summary(map_dir: str | Path) -> LandSummary:
    """Read just enough of a Wulfram land file to place fallback spawns."""
    path = Path(map_dir) / "land"
    with path.open("r", encoding="ascii", errors="replace") as f:
        grid_line = f.readline().strip()
        world_line = f.readline().strip()
        grid_w_s, grid_h_s = grid_line.split("x", 1)
        world_w_s, world_h_s = world_line.split("x", 1)
        grid_w = int(grid_w_s)
        grid_h = int(grid_h_s)
        max_height = 0.0

        for _ in range(grid_w * grid_h):
            line = f.readline()
            if not line:
                break
            parts = line.split()
            if len(parts) >= 2:
                max_height = max(max_height, float(parts[1]))

    return LandSummary(float(world_w_s), float(world_h_s), max_height)

def ensure_team_repair_pads(
    entity_manager: EntityManager,
    map_dir: str | Path | None = None,
    height_offset: float = 200.0,
) -> int:
    """
    Ensure both playable teams have a selectable repair pad.

    The client enters the map by selecting a team-colored repair pad. Some
    shipped maps have no state file, so synthesize pads above the terrain
    using land dimensions and maximum height.
    """
    existing_teams = {
        entity.team_id
        for entity in entity_manager.get_all()
        if entity.unit_type == REPAIR_PAD_UNIT_TYPE and entity.team_id in (1, 2)
    }

    if map_dir is not None and (Path(map_dir) / "land").exists():
        summary = read_land_summary(map_dir)
        world_w = summary.world_w
        world_h = summary.world_h
        spawn_z = summary.max_height + height_offset
    else:
        world_w = 1000.0
        world_h = 1000.0
        spawn_z = height_offset

    positions = {
        1: (world_w * 0.42, world_h * 0.50, spawn_z),
        2: (world_w * 0.58, world_h * 0.50, spawn_z),
    }

    created = 0
    for team_id in (1, 2):
        if team_id in existing_teams:
            continue
        pad = entity_manager.create_entity(
            unit_type=REPAIR_PAD_UNIT_TYPE,
            team_id=team_id,
            pos=positions[team_id],
        )
        pad.is_manned = False
        created += 1

    return created

def resolve_repair_pad(
    entity_manager: EntityManager,
    repair_pad_id: int,
    team_id: int,
):
    """
    Resolve a client entry-point selection to a team repair pad.

    The retail client can send base id 0 even after a valid map click when its
    current-base global has not been populated. In that case choose the first
    known repair pad for the selected team.
    """
    if team_id not in (1, 2):
        return None

    if repair_pad_id:
        entity = entity_manager.get_entity(repair_pad_id)
        if (
            entity is not None
            and entity.unit_type == REPAIR_PAD_UNIT_TYPE
            and entity.team_id == team_id
        ):
            return entity
        return None

    for entity in entity_manager.get_all():
        if entity.unit_type == REPAIR_PAD_UNIT_TYPE and entity.team_id == team_id:
            return entity

    return None

def resolve_spawn_entry(
    entity_manager: EntityManager,
    selected_entry_id: int,
    base_id: int,
    team_id: int,
):
    """
    Resolve a reincarnate spawn request to a repair pad.

    The client sends the clicked entry id first and a current-base id second.
    In observed sessions the base id is often zero, so try the clicked entry
    before falling back to the base id or first known team pad.
    """
    for candidate_id in (selected_entry_id, base_id):
        if not candidate_id:
            continue
        repair_pad = resolve_repair_pad(entity_manager, candidate_id, team_id)
        if repair_pad is not None:
            return repair_pad

    return resolve_repair_pad(entity_manager, 0, team_id)

class MapLoader:
    def __init__(self, entity_manager: EntityManager):
        self.em = entity_manager

    def load_from_string(self, map_data: str) -> int:
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
                entity.is_manned = False
                
                # Apply Rotation
                entity.rot = (rx, ry, rz)
                entity.mark_dirty(UpdateMask.ROT)
                
                # Optional: Handle the last flag (Active state?)
                # state_flag = int(parts[data_start_index + 7])
                
                count += 1
                
            except (ValueError, IndexError) as e:
                print(f"[MapLoader] Error parsing line: {line} | {e}")

        print(f"[MapLoader] Successfully loaded {count} entities.")
        return count
