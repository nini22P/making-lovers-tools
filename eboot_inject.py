import argparse
import struct
import sys
from pathlib import Path
from keystone import Ks, KsError, KS_ARCH_ARM, KS_MODE_THUMB

ARCHIVE_MOUNT = 0x81051768
GET_MOUNT_BUFFER_SIZE = 0x81051788
ALLOC = 0x81007122

# All-zero gap in the .text data block. No movw/movt, 32-bit pointer or PC-relative
# reference points into it, unlike the 13x16 zero tables at 0x81057DF0/0x81057F2C.
MOUNT_HELPER_VA = 0x81066B92
MOUNT_CAVE_END = 0x81066CC2

HOOKS = (
    (0x81007990, ARCHIVE_MOUNT, MOUNT_HELPER_VA),
)

# Import stubs are ARM (blx); the game allocator is Thumb (bl).
# patch.psarc is mounted at the same mount point as data_00.psarc: FIOS resolves
# archives sharing a mount point in mount order, so patched files win and missing
# files fall through to data_00 without a separate path probe.
MOUNT_HELPER_ASM = """
.thumb
.equ archive_mount_stub, __ARCHIVE_MOUNT__
.equ get_mount_size_stub, __GET_MOUNT_BUFFER_SIZE__
.equ alloc_fn, __ALLOC__
mount_both:
    push {r4-r6, lr}
    ldr r4, [sp, #16]
    ldr r5, [sp, #20]
    ldr r6, [sp, #24]
    sub sp, #16
    str r4, [sp]
    str r5, [sp, #4]
    str r6, [sp, #8]
    movs r0, #0
    blx archive_mount_stub
    add sp, #16
    bl mount_patch
    pop {r4-r6, pc}
mount_patch:
    push {r4-r6, lr}
    bl get_patch_path
    mov r1, r0
    movs r0, #0
    movs r2, #0
    blx get_mount_size_stub
    cmp r0, #0
    ble mount_done
    mov r4, r0
    movs r0, #1
    adds r1, r4, #16
    movs r2, #8
    bl alloc_fn
    cmp r0, #0
    beq mount_done
    mov r5, r0
    add r6, r5, #16
    sub sp, #0x10
    str r6, [sp]
    str r4, [sp, #4]
    movs r0, #0
    str r0, [sp, #8]
    str r0, [sp, #12]
    mov r1, r5
    movs r0, #0
    bl get_patch_path
    mov r2, r0
    bl get_mount_point
    mov r3, r0
    movs r0, #0
    blx archive_mount_stub
    add sp, #0x10
mount_done:
    pop {r4-r6, pc}
// adr helpers must stay after all bl/blx; Keystone otherwise shifts their fixups.
get_patch_path:
    adr r0, patch_path
    bx lr
get_mount_point:
    adr r0, mount_point
    bx lr
patch_path:
    .ascii "app0:data/patch.psarc"
    .byte 0
mount_point:
    .ascii "/archive/data_00/"
    .byte 0
"""


def expand_assembly(template):
    replacements = {
        "__ARCHIVE_MOUNT__": f"0x{ARCHIVE_MOUNT:08X}",
        "__GET_MOUNT_BUFFER_SIZE__": f"0x{GET_MOUNT_BUFFER_SIZE:08X}",
        "__ALLOC__": f"0x{ALLOC:08X}",
    }
    for name, value in replacements.items():
        template = template.replace(name, value)
    return template


def assemble(source, address):
    ks = Ks(KS_ARCH_ARM, KS_MODE_THUMB)
    try:
        encoding, _ = ks.asm(source, addr=address)
    except KsError as error:
        raise ValueError(f"assembly failed at 0x{address:08X}: {error}")
    if encoding is None:
        raise ValueError(f"assembly produced no output at 0x{address:08X}")
    return bytes(encoding)


def load_segments(data):
    if data[:6] != b"\x7fELF\x01\x01":
        raise ValueError("not a 32-bit little-endian ELF")
    phoff = struct.unpack_from("<I", data, 0x1C)[0]
    phnum = struct.unpack_from("<H", data, 0x2C)[0]
    segments = []
    for i in range(phnum):
        p_type, p_offset, p_vaddr, _, p_filesz, _, p_flags, _ = struct.unpack_from(
            "<8I", data, phoff + i * 32
        )
        segments.append((p_type, p_offset, p_vaddr, p_filesz, p_flags))
    return segments


def va_to_offset(segments, va, size):
    for p_type, p_offset, p_vaddr, p_filesz, p_flags in segments:
        if p_type == 1 and p_flags & 1 and p_vaddr <= va and va + size <= p_vaddr + p_filesz:
            return p_offset + va - p_vaddr
    raise ValueError(f"VA 0x{va:08X} is not in an executable segment")


def build_payload(template, va):
    return assemble(expand_assembly(template), va)


def patch(data):
    segments = load_segments(data)
    patched = bytearray(data)

    code = build_payload(MOUNT_HELPER_ASM, MOUNT_HELPER_VA)
    if MOUNT_HELPER_VA + len(code) > MOUNT_CAVE_END:
        raise ValueError(f"payload at 0x{MOUNT_HELPER_VA:08X} does not fit")
    offset = va_to_offset(segments, MOUNT_HELPER_VA, len(code))
    if any(patched[offset:offset + len(code)]):
        raise ValueError(f"code cave at 0x{MOUNT_HELPER_VA:08X} is not empty")
    patched[offset:offset + len(code)] = code

    for address, original_target, helper_va in HOOKS:
        original = assemble(f"blx 0x{original_target:08X}", address)
        offset = va_to_offset(segments, address, 4)
        if patched[offset:offset + 4] != original:
            raise ValueError(f"unexpected instruction at 0x{address:08X}")
        patched[offset:offset + 4] = assemble(f"bl 0x{helper_va:08X}", address)

    return patched


def main():
    parser = argparse.ArgumentParser(description="Patch eboot elf for patch.psarc support")
    parser.add_argument("-i", "--input", required=True, help="Input eboot.bin.elf")
    parser.add_argument("-o", "--output", help="Output ELF (default: overwrite input)")
    args = parser.parse_args()

    source = Path(args.input)
    destination = Path(args.output) if args.output else source
    try:
        destination.write_bytes(patch(source.read_bytes()))
    except (OSError, ValueError, struct.error) as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1

    print(f"Patched {destination}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
