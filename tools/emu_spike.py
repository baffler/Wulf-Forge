"""Feasibility spike: run a REAL wulfram2.exe physics function via the Unicorn
x86 emulator against memory we set up, and read the result back.

If this works, it proves the "slice off chunks of the client and run them" approach:
byte-exact physics, no reimplementation, no whole-game launch. Here we call the
leaf integrator Vec3_IntegratePositionVelocity(dt, pos*, vel*, accel*) @ 0x4f10c0
(pos += vel*dt + 0.5*accel*dt^2) and verify pos.x.
"""
import struct
import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
from unicorn.x86_const import UC_X86_REG_ESP, UC_X86_REG_EIP

EXE = r"C:/Users/balsa/Desktop/WulframII/Game/wulfram2.exe"
FUNC = 0x004F10C0          # Vec3_IntegratePositionVelocity
SENTINEL = 0x00BADBAD      # fake return address; stop when EIP reaches it
STACK = 0x00900000
SCRATCH = 0x00A00000


def align(v, a=0x1000):
    return (v + a - 1) & ~(a - 1)


def load_image(uc):
    pe = pefile.PE(EXE, fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase
    size = align(pe.OPTIONAL_HEADER.SizeOfImage)
    uc.mem_map(base, size)
    uc.mem_write(base, pe.get_memory_mapped_image(ImageBase=base))
    return base


def main():
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    base = load_image(uc)
    print(f"mapped wulfram2.exe at 0x{base:08x}")

    uc.mem_map(STACK, 0x10000)
    uc.mem_map(SCRATCH, 0x1000)

    pos_a, vel_a, acc_a = SCRATCH, SCRATCH + 0x10, SCRATCH + 0x20
    uc.mem_write(pos_a, struct.pack("<fff", 0.0, 0.0, 0.0))
    uc.mem_write(vel_a, struct.pack("<fff", 10.0, 0.0, 0.0))
    uc.mem_write(acc_a, struct.pack("<fff", 0.0, 0.0, 0.0))

    # __cdecl frame: [ret][dt(double)][pos*][vel*][accel*]
    sp = STACK + 0x8000
    frame = (struct.pack("<I", SENTINEL)
             + struct.pack("<d", 0.1)
             + struct.pack("<III", pos_a, vel_a, acc_a))
    uc.mem_write(sp, frame)
    uc.reg_write(UC_X86_REG_ESP, sp)
    uc.reg_write(UC_X86_REG_EIP, FUNC)

    before = struct.unpack("<fff", uc.mem_read(pos_a, 12))
    uc.emu_start(FUNC, SENTINEL, timeout=0, count=0)
    after = struct.unpack("<fff", uc.mem_read(pos_a, 12))

    print(f"pos before: {before}")
    print(f"pos after : {after}")
    print(f"expected  : (1.0, 0.0, 0.0)   [pos += vel*dt = 10*0.1]")
    ok = abs(after[0] - 1.0) < 1e-5 and abs(after[1]) < 1e-5 and abs(after[2]) < 1e-5
    print("RESULT:", "PASS -- real wulfram physics ran byte-exact" if ok else "FAIL")


if __name__ == "__main__":
    main()
