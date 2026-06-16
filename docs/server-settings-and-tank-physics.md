# How Server Settings Drive Tank Physics

*Reverse-engineering report — derived from the Ghidra export of `wulfram2.exe`
(`reverseengineering/programs/.../wulfram2.exe/`), cross-checked against the
re-implemented `network/packets/behavior.py` and `packets.toml`.*

## TL;DR

The server never simulates the client's tank for it. Instead, at join/round-start it
ships a single **`BEHAVIOR` packet (type `0x24`)** containing *every physics tunable* —
gravity, mass, friction, engine torque, turn/move/strafe authority, max velocity, max
altitude, fuel thresholds, etc. The client deserializes those into **global variables and
per-vehicle tuning structs** once, then its **local physics loop** reads them every frame
to integrate the tank's motion. The server only sends authoritative *corrections*
afterward; the felt "feel" of the tank is 100% determined by the values in that one packet.

Data flow:

```
SERVER ──BEHAVIOR(0x24)──▶ Net_HandleBehavior (0046dc00)
                              │  writes globals + fills tuning records
                              ▼
        ┌─────────────────────────────────────────────┐
        │  Chassis tuning  (VehiclePhysics  ×2)         │  speed, accel, torque,
        │  Pilot tuning    (VehicleTuning   ×3)         │  friction, mass, turn_adjust,
        │  Header globals  (gravity_force, timeouts…)   │  max_velocity, gravity_pct…
        └─────────────────────────────────────────────┘
                              │  (read every frame)
                              ▼
   Player_UpdateLocalVehicleTick (0046af90)
        └─▶ VehicleTuning_ComputeControlScalars (004f9540)   ← scales tunables to controls
        └─▶ Vehicle_ApplyThrustForces (004f9b10)             ← throttle → force/torque
        └─▶ Vehicle_UpdateFlightPhysics (00501a50)           ← lift/drag/aero (flyers)
        └─▶ EntityPhysics_RunWorldTick (004f8550)            ← integrate + collide
                 └─ EntityPhysics_IntegrateStep (004f2890)   ← v += a·dt ; x += v·dt
        └─▶ Interp_ReplayLocalPlayerPrediction (004699b0)    ← reconcile vs server
```

---

## 1. The settings arrive in one packet: `BEHAVIOR` (0x24)

**`Net_HandleBehavior` @ `0x0046dc00`** is the sole consumer. Its plate comment:

> *"Parses an incoming BEHAVIOR packet, deserializing the full set of server-driven
> gameplay tuning globals (flags, float/int rates, and physics parameters) into their
> global variables."*

It sits in the main network dispatch table alongside the other server-message handlers
(`SHIP_STATUS`, `TEAM_INFO`, `GAME_CLOCK`, `WARP_STATUS`, `REINCARNATE`, …) in the
`0x0046dc00–0x0046f000` range. All multi-byte numeric fields are **16.16 fixed-point**
(`write_fixed1616` in the re-impl), decoded to floats on receipt.

The packet is laid out in six sections (confirmed by the re-implementation in
`network/packets/behavior.py` and the field defaults in `packets.toml`):

| # | Section | What it carries | Where it lands |
|---|---------|-----------------|----------------|
| 1 | **Header** | `timeout`, `gravity_force`, velocity quantum, pulse-charge cap, team size, glimpse/push timers, 11 `unk` floats, 2 flag bytes | global vars (`gravity_force`, `dword_6791B8`, `dbl_6792F8`, …) |
| 2 | **Weapons** | per-unit/per-slot weapon params (cone, ranges) | weapon tables |
| 3 | **Unit defaults** | `scale`, `max_health`, regen — ×`unit_count` (39) | unit definition records |
| 4 | **Vehicle physics (chassis)** | `speed, accel, engine_torque, suspension_stiffness, ground_friction, turn_rate, suspension_dampening, mass` — ×`vehicle_physics_count` (2: Tank, Scout) | chassis tuning records |
| 5 | **Hardpoints / thrusters** | thruster positions + thrust-direction normals per team/class | `VehicleContext` thrust geometry |
| 6 | **Active vehicle physics (pilot)** | `turn_adjust, move_adjust, strafe_adjust, max_velocity, low_fuel_level, max_altitude, gravity_pct` (Tank=7 values; Scout=9; Bomber=11) | `VehicleTuning` records |

The two physics sections matter most: **Section 4 = the chassis/rigid-body parameters**,
**Section 6 = the pilot control authority**. They feed two different structures.

---

## 2. Where the settings are stored: two tuning layers

### Layer A — Chassis tuning (Section 4)

These are the rigid-body constants of the hull: `mass`, `ground_friction`,
`engine_torque`, `suspension_stiffness/dampening`, base `speed`/`accel`. They parameterize
the generic entity integrator (below) and the suspension that keeps the tank hovering at
ride height over terrain.

### Layer B — Pilot tuning: the `VehicleTuning` record (Section 6)

This is the cluster the report is really about, at `0x004f9250–0x004f9700`:

| Function | Addr | Role |
|----------|------|------|
| `VehicleTuning_LoadDefaults` | `004f9340` | Installs vtable + **default** adjust/velocity/fuel/altitude/gravity values from global constants. |
| `VehicleTuning_RegisterConfigBindings` | `004f93b0` | Maps the keys **`turn_adjust, move_adjust, strafe_adjust, max_velocity, low_fuel_level, max_altitude, gravity_perc`** to struct fields — these are exactly the 7 Tank values in Section 6. |
| `VehicleTuning_Deserialize` / `_Serialize` | `004f94c0` / `004f9440` | Read/write the record from the packet/file stream. |
| `VehicleTuning_GetMoveAdjust` | `004f9260` | Returns `move_adjust` (offset `0x18`). |
| `VehicleTuning_GetLowFuelLevel` | `004f9250` | Returns `low_fuel_level` (offset `0x30`). |
| `VehicleTuning_ComputeControlScalars` | `004f9540` | **The bridge to physics** — see §3. |
| `VehicleTuning_RampOverTimeRange` | `004f9280` | Time-based ramp of a tunable (smooth spin-up). |

The values are held in a **tuning table** with normalizing accessors
(`0x004f6420–0x004f64e0`):

- `VehicleTuningTable_GetValue` / `SetValue` — raw slot read/write.
- `VehicleTuningSlot_GetScaledValue` (`004f6420`) — *"Divides a tuning slot scalar by a
  runtime divisor and clamps the result to the normalized control range."*
- `VehicleTuningTable_SetScaleLimit` (`004f64e0`) — stores the per-slot clamp used during
  normalization.

So each server value is stored once, then **read back through a divisor + clamp** so the
raw 16.16 number becomes a normalized control coefficient in `[min, 1.0]`.

The Tank uses the base `VehicleTuning`; the Medic/Scout has its own extended profile
(`MedicVehicleTuning_ConstructDefaults` @ `004f6690`, *"default movement, altitude,
gravity, and fuel thresholds"*) with the extra fields Section 6 sends for those classes.

---

## 3. How the settings reach the physics each frame

The local tank is driven once per tick from
**`Player_UpdateLocalVehicleTick` @ `0x0046af90`**. The chain that turns stored settings
into motion:

### 3a. Tunables → control scalars
**`VehicleTuning_ComputeControlScalars` @ `0x004f9540`**:
> *"Fetches scaled axis and control values from the vehicle tuning table, negates two of
> them, and clamps each result between a global minimum and 1.0."*

This converts `turn_adjust`, `move_adjust`, `strafe_adjust`, etc. into per-axis control
coefficients. (Flyers additionally run `Vehicle_LoadAndClampTuningFactors` @ `004f1380`
and `Vehicle_ComputeAirspeedAltitudeFactors` @ `004f1490`, which fold `max_altitude` and a
low-airspeed factor into the turn rate so the tank loses authority near its ceiling.)

### 3b. Control scalars + throttle → forces
**`Vehicle_ApplyThrustForces` @ `0x004f9b10`**:
> *"Computes the vehicle's thrust and torque vectors in world space from throttle and
> ground-proximity factors and accumulates them onto the physics body's force and torque
> accumulators."*

This is where the hover-tank "feel" is produced: the pilot's throttle/turn input is
multiplied by the (server-tuned) control scalars and the thruster geometry from Section 5,
then accumulated as **force + torque** on the entity's physics body. `engine_torque` and
the thrust-limiter terms cap how much can be applied;
`MedicVehicle_ApplyThrustAndLift` (`004f6ed0`) is the Scout/Medic analogue that also
produces the **lift** that holds it off the ground. Thrust/altitude limiters
(`MedicVehicle_UpdateThrustLimiters` @ `004f6bc0`) blend in **speed, fuel, and altitude**
— so `low_fuel_level` and `max_altitude` from the packet directly throttle available lift.

### 3c. Aerodynamics (flying classes)
**`Vehicle_ApplyAerodynamicForces` @ `0x004f15b0`** + `Vehicle_UpdateFlightPhysics`
(`00501a50`): computes pitch authority, lift, thrust, and drag from orientation and the
flight-dynamics tunables (the 11 Bomber values bound by
`Config_BindFlightDynamicsParams` @ `00501140`: `ax_mag, forward_mag, turn limits,
ceiling, low_fuel_level`, …) and accumulates them as impulses/forces. The Tank skips most
of this; it's primarily thrust + suspension + gravity.

### 3d. Integration — where gravity and mass finally act
The accumulated forces are integrated by the generic physics core
(`0x004f10c0–0x004f2890`):

- `EntityPhysics_IntegrateLinear` (`004f27a0`) — *"Integrates linear position and velocity
  with optional damping/control acceleration."* `ground_friction` enters here as the
  damping term; `mass` scales force→acceleration; the header **`gravity_force` × per-class
  `gravity_pct`** is the constant downward acceleration.
- `EntityPhysics_IntegrateRotation*` (`004f12c0`, `004f14a0`, `Euler_IntegrateFixedTick`
  `004f23d0`) — angular velocity → orientation, on the fixed-tick denominator.
- `EntityPhysics_IntegrateStep` (`004f2890`) — *"Advances entity physics position and
  rotation over one time step."*
- `Vec3_IntegratePositionVelocity` (`004f10c0`) — the underlying `v += a·dt; x += v·dt`.

`max_velocity` clamps the integrated speed; `max_altitude` is enforced via
`Collision_CheckEntityAgainstCeiling` (`004fb050`).

### 3e. The world tick wraps it up
**`EntityPhysics_RunWorldTick` @ `0x004f8550`**:
> *"Runs the world physics tick by integrating every entity over the frame timestep,
> resolving all collision contacts, and then clearing each entity's accumulated linear and
> angular velocity."*

Per frame: integrate all entities → resolve collisions
(`CollisionContact_ResolveAll` `004f8510`, suspension/ground via
`Collision_CheckObjectGroundHeight` `00500f60` + `Terrain_GetHeightAtPoint` `004fa340`) →
clear accumulators for next frame. `suspension_stiffness/dampening` shape the ground-
contact response that gives the tank its springy hover ride.

---

## 4. The settings are also re-applied during prediction/reconciliation

Because this is a networked game, the client predicts locally and reconciles against the
server. The same tuning values are used when **re-simulating** during reconciliation, so
prediction and authority stay consistent (`0x00469760–0x00469ae0`):

- `Interp_SaveEntityPhysicsState` / `Interp_RestoreEntityPhysicsState` (`004697..`) —
  snapshot/rollback position, velocity, orientation, matrices.
- `Interp_ReplayLocalPlayerPrediction` (`004699b0`) — *"When a fresh prediction is pending,
  saves the local player's physics state, applies the predicted position/orientation,
  re-simulates movement, and on success commits it (otherwise rolls the state back)."*
- `Interp_StorePredictionState` / `Interp_RecordLocalPlayerPredictedContact` — confirm a
  predicted collision still holds against the saved state.

The re-simulation runs the *exact same* tunable-driven integrators from §3, which is why
every physics constant has to be known client-side — the server can't be in the loop for
each frame at 1990s latencies.

---

## 5. Practical takeaways for the project

1. **One packet owns the feel.** Editing the Section-4/Section-6 fields in `packets.toml`
   and re-sending `BEHAVIOR(0x24)` is sufficient to retune the entire tank — no client
   patch needed. This is what `network/packets/behavior.py` already exploits.
2. **Two structs, two jobs.** Section 4 (chassis: mass/friction/torque/suspension) shapes
   the rigid body; Section 6 (`VehicleTuning`: turn/move/strafe/velocity/altitude/fuel/
   gravity_pct) shapes pilot authority. Both flow into the same integrator.
3. **Per-class field counts differ** (Tank 7 / Scout 9 / Bomber 11) — the client reads a
   fixed count per class, so the packet must write exactly that many fixed-point values or
   everything after it desyncs.
4. **Gravity is two-stage**: a global `gravity_force` (header) scaled by a per-class
   `gravity_pct` (Section 6). Set `gravity_pct = 0` for a free-floating test vehicle.
5. **`low_fuel_level` and `max_altitude` are active limiters**, not just HUD values — they
   directly cut thrust/lift in `MedicVehicle_UpdateThrustLimiters` and the ceiling check.

## Key function index

| Address | Name | Stage |
|---------|------|-------|
| `0046dc00` | `Net_HandleBehavior` | Parse server settings → globals/structs |
| `0046af90` | `Player_UpdateLocalVehicleTick` | Per-tick entry |
| `004f9340` | `VehicleTuning_LoadDefaults` | Defaults |
| `004f93b0` | `VehicleTuning_RegisterConfigBindings` | Field mapping |
| `004f9540` | `VehicleTuning_ComputeControlScalars` | Tunables → control coeffs |
| `004f6420` | `VehicleTuningSlot_GetScaledValue` | Normalize/clamp tunable |
| `004f9b10` | `Vehicle_ApplyThrustForces` | Throttle → force/torque |
| `004f6ed0` | `MedicVehicle_ApplyThrustAndLift` | Scout/Medic lift |
| `004f6bc0` | `MedicVehicle_UpdateThrustLimiters` | fuel/altitude limiting |
| `00501140` | `Config_BindFlightDynamicsParams` | Flyer aero tunables |
| `004f15b0` | `Vehicle_ApplyAerodynamicForces` | Lift/drag/pitch |
| `004f27a0` | `EntityPhysics_IntegrateLinear` | gravity/mass/friction integration |
| `004f2890` | `EntityPhysics_IntegrateStep` | One step pos+rot |
| `004f8550` | `EntityPhysics_RunWorldTick` | Integrate-all + collide |
| `004fb050` | `Collision_CheckEntityAgainstCeiling` | `max_altitude` enforcement |
| `004699b0` | `Interp_ReplayLocalPlayerPrediction` | Reconcile re-sim |

*Caveat: the Ghidra MCP bridge was disconnected during this report, so function bodies
were not re-decompiled live; the analysis is built from the exported plate comments,
symbols, and the existing `behavior.py`/`packets.toml` re-implementation. Offsets/field
names in §3d (e.g. exactly where `gravity_force` is multiplied) are inferred from the
comments and should be confirmed against the decompilation when the bridge is back.*
