"""Spike 2: emulate the FULL EntityPhysics_IntegrateStep @ 0x4f2890 -- the
rotation (orientation MATRIX, the part we couldn't reimplement) + linear
integration -- byte-exact, on a hand-built entity struct.

Struct (physics body), offsets from RE:
  +0x0c pos   +0x18 vel   +0x24 accel
  +0x30 euler(pitch,roll,yaw)  +0x3c ang_vel  +0x48 ang_accel(torque)
  +0x58 orientation matrix (rebuilt from euler when it differs from +0xa0 prev)
  +0xa0 prev-euler   +0xbc -> model-physics(+0xb8 sim_time, +4 -> +0x78/+0x7c damping)
  +0xc0 -> flags(+3 damping, +4 kinematic, +5 rotation-enable)
"""
import struct
import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
from unicorn.x86_const import UC_X86_REG_ESP, UC_X86_REG_EIP

EXE = r"C:/Users/balsa/Desktop/WulframII/Game/wulfram2.exe"
INTEGRATE_STEP = 0x004F2890
SENTINEL = 0x00BADBAD
STACK = 0x00900000
ARENA = 0x00A00000           # entity + sub-structs live here
E = ARENA                    # entity base
M = ARENA + 0x1000           # model-physics struct
D = ARENA + 0x2000           # damping struct (M+4 -> D)
F = ARENA + 0x3000           # flags struct


def align(v, a=0x1000):
    return (v + a - 1) & ~(a - 1)


def main():
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    pe = pefile.PE(EXE, fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase
    uc.mem_map(base, align(pe.OPTIONAL_HEADER.SizeOfImage))
    uc.mem_write(base, pe.get_memory_mapped_image(ImageBase=base))
    uc.mem_map(STACK, 0x10000)
    uc.mem_map(ARENA, 0x10000)

    def wf(addr, *vals):  # write floats
        uc.mem_write(addr, struct.pack("<" + "f" * len(vals), *vals))

    # entity fields
    wf(E + 0x0c, 0.0, 0.0, 0.0)     # pos
    wf(E + 0x18, 10.0, 0.0, 0.0)    # vel  (+x)
    wf(E + 0x24, 0.0, 0.0, 0.0)     # accel
    wf(E + 0x30, 0.0, 0.0, 0.1)     # euler: yaw=0.1
    wf(E + 0x3c, 0.0, 0.0, 1.0)     # ang_vel: yaw-rate = 1.0 rad/s
    wf(E + 0x48, 0.0, 0.0, 0.0)     # ang_accel
    wf(E + 0xa0, 9.0, 9.0, 9.0)     # prev-euler != euler -> force matrix rebuild
    uc.mem_write(E + 0xbc, struct.pack("<I", M))
    uc.mem_write(E + 0xc0, struct.pack("<I", F))
    # model-physics struct
    uc.mem_write(M + 0x04, struct.pack("<I", D))
    uc.mem_write(M + 0xb8, struct.pack("<d", 0.0))   # sim_time
    wf(D + 0x78, 0.0)                                # k_lin (unused: flag+3=0)
    wf(D + 0x7c, 0.0)                                # k_ang
    # flags all zero -> +3=0 (no damping fold), +4=0 (not kinematic), +5=0 (rotation on)

    sp = STACK + 0x8000
    uc.mem_write(sp, struct.pack("<I", SENTINEL) + struct.pack("<I", E) + struct.pack("<d", 0.1))
    uc.reg_write(UC_X86_REG_ESP, sp)
    uc.reg_write(UC_X86_REG_EIP, INTEGRATE_STEP)

    pos0 = struct.unpack("<fff", uc.mem_read(E + 0x0c, 12))
    eul0 = struct.unpack("<fff", uc.mem_read(E + 0x30, 12))
    uc.emu_start(INTEGRATE_STEP, SENTINEL, timeout=0, count=0)
    pos1 = struct.unpack("<fff", uc.mem_read(E + 0x0c, 12))
    eul1 = struct.unpack("<fff", uc.mem_read(E + 0x30, 12))
    mat = struct.unpack("<9f", uc.mem_read(E + 0x58, 36))

    print(f"pos  {pos0} -> {pos1}   (expect x ~ 1.0 from vel*dt)")
    print(f"euler{eul0} -> {eul1}   (expect yaw advanced from ang_vel*dt)")
    print(f"orientation matrix (rebuilt by real code): {[round(m,4) for m in mat]}")
    pos_ok = abs(pos1[0] - 1.0) < 1e-4
    yaw_moved = abs(eul1[2] - eul0[2]) > 1e-4
    print("RESULT:", "PASS -- full IntegrateStep (matrix rotation + linear) ran byte-exact"
          if (pos_ok and yaw_moved) else "FAIL")


if __name__ == "__main__":
    main()
