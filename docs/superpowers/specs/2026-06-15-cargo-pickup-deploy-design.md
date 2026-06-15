# Deployable Cargo: Pickup, Carry & Deployment — Design Spec

*Design spec — 2026-06-15. For the Wulf-Forge server emulator (`main.py` + `core/` +
`network/`). Implements server-authoritative cargo container pickup, carrying, and
deployment, faithful to the behavior decompiled from `wulfram2.exe` (Ghidra `W2VULK`).*

## Goal

A player vehicle flies slow & low over a cargo box, the **server** attaches it, tells the
client it is carrying via `CARRYING_INFO (0x29)`; the player presses deploy/drop, the client
sends `DROP_REQUEST (0x2B)`, and the server either spawns the contained unit as a structure
(deploy) or releases a loose, re-pickupable box (drop). All authority is server-side, mirroring
the original.

## Reverse-engineered reference (load-bearing facts)

All addresses are in `wulfram2.exe` (image base `0x00400000`).

### Pickup — server-authoritative, automatic; the client sends NO pickup packet
- There is no `pickup_cargo` console command, no `*PICKUP*` entry in the packet-name table
  (`0x00560960`), and no cargo-pickup sender among the `Net_SendStart` callers.
- The client renders cues only: `target_closest_cargo`, `non_base_cargo_close_and_not_carrying`,
  `cargo_pickup_fail` (HUD/context-help tables), and detects the physical touch locally via the
  collision callback `Net_HandleCargoAttachHold` @ `0x00419ff0` (object attach-event `0x13`),
  which plays audio/HUD and emits a local hold-request (`Net_AddEntityHold`).
- `max_speed_height_pickup` (default **3.5**) is a vehicle-tuning float (`MedicVehicleTuning_BindConfig`
  @ `0x004f679c`, object `+0x48`) — the speed/height eligibility gate for grabbing cargo.
- Authoritative carry state is whatever the server's last `0x29` said.

### Carry — `CARRYING_INFO` (server→client opcode `0x29`)
- Handler `Net_HandleCarryingInfo` @ `0x0046e190` → `Player_SetCarriedCargo` @ `0x00476330`
  (registered at `Net_RegisterMessageHandlers` `0x0046c222`).
- **Wire layout (authoritative, per disassembly):**

  | Off  | Size       | Field      | Meaning |
  |------|------------|------------|---------|
  | 0x00 | int32      | `entityId` | entity whose carry state is set |
  | 0x04 | byte       | `hasCargo` | 0 = not carrying, nonzero = carrying |
  | 0x05 | byte       | `cargoType`| carried unit/buildable type id |
  | 0x06 | byte       | `unk_v2`   | team/colour-variant index for the cargo model |

- ⚠️ Wulf-Forge's current `CarryingInfoPacket` writes `hasCargo, unk_v2, item_id` — i.e.
  `unk_v2` and `cargoType` are **swapped** vs. the binary. Must be corrected.

### Deploy / Drop — `DROP_REQUEST` (client→server opcode `0x2B`, reliable)
- Commands `deploy_cargo` @ `0x0045de40`, `drop_cargo` @ `0x0045de00` (registered in
  `Cmd_RegisterAll` ~`0x0041c493`). Both call `Net_SendStart(type=0x2B, "DROP_REQUEST")`,
  write **one int32**, then `Proto_FinishPacket`.
- **Body:** a single int32 — `1` = deploy carried cargo as a structure, `0` = drop loose.
- **No position/target field** — the server already knows what the tank carries and where it is.
- The client never gates the send on placement validity; the good/iffy/bad icons are advisory.
  The server is fully authoritative.

### Representation — cargo box & contained type
- A cargo box in-world is `unit_type 19`. The contained unit type rides in the entity
  DEFINITION block (`ID_BITS_UNIT_CARGO`); `25` = power cell = entity type `0x19`.
- `EntityType_MapBuildableIndex` @ `0x004e4b00`: buildable index 0→`0x19`, 1→`0x1A`, … 11→`0x24`,
  default `0x27`. Selected-type `0xD` = "ENEMY CARGO (LOCKED)".
- The `MapState_CargoTokenToKind`/`KindToToken` table (@ `0x004e9f70`) is **map-file serialization
  only** — not the deploy path. Do not conflate "kind" with the buildable index/entity type.

### Deploy placement validation (deferred this iteration — recorded for the later phase)
- Client HUD cue only; server decides. Rules (from `Deploy_Evaluate*` @ `0x004528e0`–`0x00452a50`):
  power cell (`0x19`) → backup-radius probe (`deploy_backup_radius`, global `0x00679184`) hit ⇒ IFFY
  (backup only); 2× `building_wedge_radius` (global `0x00679180`) probe hit ⇒ BAD (overlap); else GOOD.
  Powered items (descriptor `+0x23` flag) need a same-team active power cell within wedge radius
  (`available_power` at entity `+0xD4` ≠ 0, team at `+0xF0`) plus a capacity check.
- Both radii are already present in `network/packets/packet_config.py` (`building_wedge_radius`,
  `deploy_backup_radius`) and shipped in the BEHAVIOR packet.

## Architecture

```
core/cargo.py            # NEW: CargoSystem — pure-ish pickup/deploy/drop logic, testable
  class CargoSystem:
    tick(server)                       # per-update-loop pickup scan
    handle_drop_request(ctx, deploy)   # 0x2B: deploy (spawn unit) or drop (loose box)
    _eligible_for_pickup(player)       # speed/height gate (max_speed_height_pickup)
    _nearest_cargo_box(player)         # proximity scan over unit_type 19 entities
core/entity.py           # extend GameEntity with carry/cargo fields
network/packets/gameplay.py   # fix CarryingInfoPacket field order; add DropRequest decode helper
network/packets/update_array.py  # write entity.cargo_contained_type (not literal 25)
main.py                  # add 0x2B route + cargo_system.tick() call in the 10Hz loop;
                         #   add /s spawncargo debug command
tests/test_cargo.py      # NEW: protocol + logic tests
```

### Decisions
1. **One module, thin `main.py` surface.** `CargoSystem` owns the logic; `main.py` only routes
   `0x2B` and calls `tick()` once per loop. Keeps the 75 KB `main.py` from growing and isolates
   a unit we can test without sockets.
2. **Pickup is server-driven proximity + gate.** Each tick, an uncarried manned player whose
   horizontal speed and altitude pass the `max_speed_height_pickup` gate, and who is within a
   pickup radius of a non-base cargo box (`unit_type 19`), grabs it: set carry state, remove the
   box (`DeleteObjectPacket`), broadcast `CARRYING_INFO(hasCargo=1, cargoType=contained, unk_v2=team)`.
3. **Deploy spawns an unmanned static-anchored unit.** `0x2B` flag=1 → `create_entity(unit_type=
   carried_cargo_type)` at the tank's position (terrain-dropped z), `is_manned=False` → settles →
   held in place by the existing `build_static_anchor_packet` ("physics then freeze once settled").
   Clear carry; broadcast `0x29 hasCargo=0`.
4. **Drop spawns a loose re-pickupable box.** `0x2B` flag=0 → `create_entity(unit_type=19,
   cargo_contained_type=carried)` at the tank's position, `is_manned=False`. Clear carry;
   broadcast `0x29 hasCargo=0`.
5. **Placement validation = always-allow this iteration.** The client never gates on it, so a
   first pass is behaviorally faithful. The radii/`available_power`/team data hooks are modeled
   (fields exist) but the power-network rule engine is a bounded follow-up phase.
6. **Carry field-order fix.** `CarryingInfoPacket` → `{int32 id, byte hasCargo, byte cargoType,
   byte unk_v2}`; update `/carry` and `/drop` debug commands to match.

### State added to `GameEntity`
- `carried_cargo_type: int | None = None` — contained unit type the entity is holding.
- `carried_variant: int = 0` — the `unk_v2` team/variant byte (server sends `team_id`).
- `cargo_contained_type: int = 25` — for box entities (`unit_type 19`); drives the DEFINITION
  `ID_BITS_UNIT_CARGO` write (replaces the `update_array.py` literal `25`).
- `available_power: float = 0.0` — modeled now, used by the deferred validation phase.

### Constants / tunables
All live in `packets.toml` so they can be tuned without code changes:
- `max_speed_height_pickup` — `behavior.active_vehicle_physics` (already `3.5`); the pickup speed gate.
- `[cargo] pickup_radius` (`15.0`) — max distance to auto-grab a box.
- `[cargo] max_pickup_altitude` (`10.0`) — max height above `ground_z` to be eligible.
- `[cargo] ground_z` (`0.0`) — ground reference for the altitude check and deploy settle; a flat
  approximation until terrain sampling is wired in.

## Build order
1. Tests-first protocol layer: `CarryingInfoPacket` byte layout, `DROP_REQUEST` decode,
   `update_array` contained-type write. (TDD; pure, no sockets.)
2. `GameEntity` carry fields + `CargoSystem` logic (eligibility, nearest-box, deploy, drop) with
   tests over a fake EntityManager.
3. Wire into `main.py`: `0x2B` route, `tick()` in the loop, `/s spawncargo` debug command.
4. Manual verification against the client (pickup cue, carry HUD, deploy spawns a structure,
   drop leaves a re-pickupable box).

## Testing
`tests/test_cargo.py`:
- `CARRYING_INFO` serializes to `{id, hasCargo, cargoType, unk_v2}` byte-for-byte (matches RE table).
- `DROP_REQUEST` decode yields the correct deploy/drop flag.
- `update_array` DEFINITION for `unit_type 19` writes `entity.cargo_contained_type`.
- Pickup eligibility: too-fast / too-high player is rejected; slow-low player within radius grabs
  the nearest box and emits `0x29 hasCargo=1`.
- Deploy: `0x2B` flag=1 spawns an unmanned entity of the contained `unit_type`, clears carry,
  emits `0x29 hasCargo=0`.
- Drop: `0x2B` flag=0 spawns an unmanned `unit_type 19` box carrying the right contained type.

## Explicitly out of scope (this iteration)
- Power-network placement validation (cells/capacity/region-overlap radius math).
- Factory/base cargo production (boxes are seeded via `/s spawncargo` for now).
- The client-local hold-request packet (`Net_AddEntityHold`) — pickup is driven server-side,
  which is the authoritative path.

## Natural next extension — pad landing detection (repair / fuel pads)

Landing on a repair pad or fuel pad is the **same kind of server-side collision/proximity
work** as cargo pickup: detect when a vehicle is slow & low enough and within range of a pad,
then drive the docking/repair/refuel state (the client already has `DockingPacket` (0x38),
`/dock`, and `Pad_DrawDockStatusBanner`). The intent is to generalize `CargoSystem`'s
eligibility + nearest-entity probe into a shared proximity helper so pad landing can reuse it
rather than duplicating the scan. Deferred to its own iteration; recorded here so the
detection layer is designed with that reuse in mind.
