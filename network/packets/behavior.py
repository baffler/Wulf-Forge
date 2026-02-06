# network/packets/behavior.py
from __future__ import annotations

from dataclasses import dataclass, field
from network.packets.base import Packet
from network.streams import PacketWriter
from .packet_config import BehaviorConfig

@dataclass
class BehaviorPacket(Packet):
    """
    0x24 payload
    """
    cfg: BehaviorConfig = field(repr=False)

    def serialize(self) -> bytes:
        pkt = PacketWriter()
        cfg = self.cfg

        # --------------------------
        # SECTION 1: HEADER
        # --------------------------
        h = cfg.header

        pkt.write_byte(int(h.spawn_related) & 0xFF)
        pkt.write_fixed1616(h.timeout)
        pkt.write_fixed1616(h.dbl_6792F8)
        pkt.write_fixed1616(h.velocity_q)
        pkt.write_fixed1616(h.dbl_679308)
        pkt.write_fixed1616(h.dbl_679310)

        pkt.write_int32(h.total_team_size)
        pkt.write_int32(h.glimpse_ms)
        pkt.write_int32(h.push_ms)

        pkt.write_fixed1616(h.gravity_force)
        pkt.write_int32(h.dword_6791B8)
        pkt.write_int32(h.dword_6791BC)
        pkt.write_fixed1616(h.max_pulse_charge)

        if len(h.unk11) != 11:
            raise ValueError(f"BehaviorHeader.unk11 must be exactly 11 floats, got {len(h.unk11)}")

        for v in h.unk11:
            pkt.write_fixed1616(v)

        pkt.write_byte(int(h.flag1) & 0xFF)
        pkt.write_byte(int(h.flag2) & 0xFF)

        # --------------------------
        # SECTION 2: WEAPONS (unchanged, hard-coded)
        # --------------------------
        for _u in range(cfg.weapons_units_count):
            for _i in range(cfg.weapon_slots_count):
                # 5 bool bytes
                pkt.write_byte(0)
                pkt.write_byte(0)
                pkt.write_byte(0)
                pkt.write_byte(0)
                pkt.write_byte(0)

                # targeting cone
                pkt.write_fixed1616(1.0)

                # 5 ints
                pkt.write_int32(0)
                pkt.write_int32(0)
                pkt.write_int32(0)
                pkt.write_int32(0)
                pkt.write_int32(0)

                # 4 fixeds
                pkt.write_fixed1616(100.0)
                pkt.write_fixed1616(1000.0)
                pkt.write_fixed1616(500.0)
                pkt.write_fixed1616(1.0)

        # --------------------------
        # SECTION 3: UNITS (configurable defaults)
        # --------------------------
        ud = cfg.unit_defaults
        for _ in range(cfg.unit_count):
            pkt.write_fixed1616(ud.scale)
            pkt.write_fixed1616(ud.regen_or_health_related)
            pkt.write_int32(ud.max_health)

        # --------------------------
        # SECTION 4: VEHICLE PHYSICS (configurable)
        # --------------------------
        vp = cfg.vehicle_physics
        for _ in range(cfg.vehicle_physics_count):
            pkt.write_fixed1616(vp.speed)
            pkt.write_fixed1616(vp.accel)

            pkt.write_int32(vp.engine_torque)
            pkt.write_int32(vp.suspension_stiffness)

            pkt.write_fixed1616(vp.ground_friction)
            pkt.write_fixed1616(vp.turn_rate)
            pkt.write_fixed1616(vp.suspension_dampening)

            pkt.write_int32(vp.unknown_int_30)
            pkt.write_int32(vp.mass)

        # --------------------------
        # SECTION 5: HARDPOINTS (unchanged for now)
        # --------------------------
        #pkt.align()
        _write_hardpoint_block(pkt, count=0, is_thruster=False) # Tank Weapons
        #pkt.align()
        _write_hardpoint_block(pkt, count=2, is_thruster=True)  # Tank Thrusters
        #pkt.align()
        _write_hardpoint_block(pkt, count=0, is_thruster=False) # Scout Weapons
        #pkt.align()
        _write_hardpoint_block(pkt, count=2, is_thruster=True)  # Scout Thrusters

        # --------------------------
        # SECTION 6: ACTIVE VEHICLE PHYSICS (Configurable)
        # --------------------------
        # The client iterates: Tank -> Scout -> Bomber
        # We must write the exact amount of data each class expects.
        
        av = cfg.active_vehicle_physics

        for i in range(cfg.active_vehicles_count):

            # --- VEHICLE SPECIFIC ---
            
            if i == 0: 
                # TANK (Reads 7 values)
                pkt.write_fixed1616(av.turn_adjust)
                pkt.write_fixed1616(av.move_adjust)
                pkt.write_fixed1616(av.strafe_adjust)
                pkt.write_fixed1616(av.max_velocity)
                pkt.write_fixed1616(av.low_fuel_level)
                pkt.write_fixed1616(av.max_altitude)
                pkt.write_fixed1616(av.gravity_pct)
                pass
                
            elif i == 1:
                # SCOUT (Reads 9 values)
                pkt.write_fixed1616(av.turn_adjust)
                pkt.write_fixed1616(av.move_adjust) # Move Forward Adjust
                pkt.write_fixed1616(38.0) # Move Backward Adjust
                pkt.write_fixed1616(72.0) # Strafe Adjust
                pkt.write_fixed1616(85.0) # Max Velocity
                pkt.write_fixed1616(av.low_fuel_level)
                pkt.write_fixed1616(4.9) # Max Altitude
                pkt.write_fixed1616(3.5) # Max Speed Height Pickup
                pkt.write_fixed1616(av.gravity_pct)
                
            elif i == 2:
                # BOMBER (Reads 11 values)
                pkt.write_fixed1616(-2.5132741233144) # ax_mag
                pkt.write_fixed1616(2.35619449060725) # ay_mag
                pkt.write_fixed1616(80.0) # forward_mag
                pkt.write_fixed1616(45.0)  # low_airspeed
                pkt.write_fixed1616(0.5) # angfac
                pkt.write_fixed1616(70.0)  # turn_low
                pkt.write_fixed1616(110.0)  # turn_high
                # We need 4 extra values to satisfy sub_5012D0
                pkt.write_fixed1616(340.0) # turn_zero
                pkt.write_fixed1616(1000.0) # very_high
                pkt.write_fixed1616(1800.0) # ceiling
                pkt.write_fixed1616(av.low_fuel_level) # low_fuel_level

        # --------------------------
        # FINAL: PAYLOAD
        # --------------------------
        body = pkt.get_bytes()
        payload = b"\x24" + body

        return payload


def _write_hardpoint_block(pkt: PacketWriter, count: int, is_thruster: bool) -> None:
    pkt.write_int32(count)

    if count > 0:
        for i in range(count):
            # ---------------------------------------------------------
            # COORDINATE SYSTEM: Z-UP
            # ---------------------------------------------------------
            
            if is_thruster:
                # --- TUNING VALUES ---
                
                # 1. WIDTH (How far out are the wings?)
                wing_width = 2.0
                
                # 2. LATERAL BIAS (Fixes Side Tipping)
                # Tilts Right -> Try 0.2, 0.5, 1.0
                # Tilts Left  -> Try -0.2, -0.5, -1.0
                lateral_bias = 0.0 

                # 3. LONGITUDINAL BIAS (Fixes Nose Dive)
                # Tips Forward -> Increase (0.5, 1.0)
                # Tips Backward -> Decrease (-0.5, -1.0)
                forward_bias = 0.0

                # --- CALCULATE POSITIONS ---

                # X: Left (-width) vs Right (+width), plus the bias shift
                if i % 2 == 1:
                    x_pos = wing_width + lateral_bias  # Right Thruster
                else:
                    x_pos = -wing_width + lateral_bias # Left Thruster

                # --- Y: BALANCE (Forward/Back) ---
                # Start at 0.0. 
                # If NOSE DIVES -> Change to +1.0 or +2.0
                # If LOOKING AT SKY -> Change to -1.0 or -2.0
                y_pos = forward_bias 

                # --- Z: HEIGHT (Up/Down) ---
                # Since Z is up, 0.0 is the center of the tank vertically.
                # -1.0 puts the thruster slightly below the hull.
                z_pos = -0.5 

                # --- NORMAL (Thrust Direction) ---
                # Pointing DOWN (-Z)
                # Setting this too high (-1.0) can cause a weird bug
                # where you will start flipping upside down
                nx, ny, nz = 0.0, 0.0, -0.75
                
            else:
                # Weapons (Keep valid defaults just in case)
                x_pos = 1.5 if (i % 2 == 1) else -1.5
                y_pos = 2.0 # Forward mounted guns?
                z_pos = 0.5 # Slightly raised
                nx, ny, nz = 0.0, 1.0, 0.0 # Point Forward (+Y)

            # Write Position (Fixed 16.16)
            pkt.write_fixed1616(float(x_pos))
            pkt.write_fixed1616(float(y_pos))
            pkt.write_fixed1616(float(z_pos))

            # Write Normal
            pkt.write_fixed1616(float(nx))
            pkt.write_fixed1616(float(ny))
            pkt.write_fixed1616(float(nz))

            pkt.write_int32(0) # Flag

    # FIX: Send a non-zero value for thrusters
    if is_thruster:
        # -5.0 is a safe guess for "Thrusters are 5 units below the tank center"
        # This value will populate VehicleContext offset 0x18
        pkt.write_fixed1616(-5.0) 
    else:
        # For weapons, this might be range or cooldown, 0.0 might be fine for now
        pkt.write_fixed1616(0.0)
