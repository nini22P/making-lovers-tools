import argparse
import struct
import sys
from pathlib import Path
from keystone import Ks, KsError, KS_ARCH_ARM, KS_MODE_THUMB

ARCHIVE_MOUNT = 0x81051768
GET_MOUNT_BUFFER_SIZE = 0x81051788
FH_OPEN = 0x81051758
FH_CLOSE = 0x810516A8
SPRINTF = 0x81051A48
STRCPY = 0x81051A68
ALLOC = 0x81007122

# All-zero gaps in the .text data block. No movw/movt, 32-bit pointer or PC-relative
# reference points into them, unlike the 13x16 zero tables at 0x81057DF0/0x81057F2C.
PATH_HELPER_VA = 0x8106518E
PATH_CAVE_END = 0x810652C0
MOUNT_HELPER_VA = 0x81066B92
MOUNT_CAVE_END = 0x81066CC2

# Unreferenced dword in the .data padding below 0x810732F4; set to 1 once patch.psarc is mounted.
# It is addressed as a PC-relative delta from the payload, never as an absolute address.
MOUNT_FLAG = 0x810732E4

HOOKS = (
    (0x81007990, ARCHIVE_MOUNT, MOUNT_HELPER_VA),
    (0x81007A06, SPRINTF, PATH_HELPER_VA),
    (0x81007CC4, SPRINTF, PATH_HELPER_VA),
    (0x81007EAE, SPRINTF, PATH_HELPER_VA),
)

# Import stubs are ARM (blx); the game allocator is Thumb (bl).
PATH_HELPER_ASM = """
.thumb
.equ sprintf_stub, __SPRINTF__
.equ strcpy_stub, __STRCPY__
.equ fh_open_stub, __FH_OPEN__
.equ fh_close_stub, __FH_CLOSE__
path_helper:
    push {lr}
    sub sp, #0x12c
    str r0, [sp, #0x110]
    str r1, [sp, #0x114]
    str r2, [sp, #0x118]
    str r3, [sp, #0x11c]
    bl get_flag
    ldr r0, [r0]
    cmp r0, #0
    beq path_fallback
    bl get_patch_root
    mov r2, r0
    mov r0, sp
    ldr r1, [sp, #0x114]
    ldr r3, [sp, #0x11c]
    blx sprintf_stub
    movs r0, #0
    add r1, sp, #0x120
    mov r2, sp
    movs r3, #0
    blx fh_open_stub
    cmp r0, #0
    blt path_fallback
    movs r0, #0
    ldr r1, [sp, #0x120]
    blx fh_close_stub
    ldr r0, [sp, #0x110]
    mov r1, sp
    blx strcpy_stub
    b path_done
path_fallback:
    ldr r0, [sp, #0x110]
    ldr r1, [sp, #0x114]
    ldr r2, [sp, #0x118]
    ldr r3, [sp, #0x11c]
    blx sprintf_stub
path_done:
    add sp, #0x12c
    pop {pc}
// adr helpers must stay after all bl/blx; Keystone otherwise shifts their fixups.
get_flag:
    adr r0, flag_ref
    movw r1, #__FLAGDELTA_LO__
    movt r1, #__FLAGDELTA_HI__
    add r0, r0, r1
    bx lr
get_patch_root:
    adr r0, patch_root
    bx lr
patch_root:
    .ascii "/archive/patch/"
    .byte 0
flag_ref:
    .word 0
"""

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
    // r0 still holds the mount-point pointer; attr must be NULL.
    blx archive_mount_stub
    add sp, #0x10
    cmp r0, #0
    bne mount_done
    bl get_flag
    movs r1, #1
    str r1, [r0]
mount_done:
    pop {r4-r6, pc}
// adr helpers must stay after all bl/blx; Keystone otherwise shifts their fixups.
get_flag:
    adr r0, flag_ref
    movw r1, #__FLAGDELTA_LO__
    movt r1, #__FLAGDELTA_HI__
    add r0, r0, r1
    bx lr
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
    .ascii "/archive/patch/"
    .byte 0
flag_ref:
    .word 0
"""


def expand_assembly(template, flag_delta):
    delta = flag_delta & 0xFFFFFFFF
    replacements = {
        "__ARCHIVE_MOUNT__": f"0x{ARCHIVE_MOUNT:08X}",
        "__GET_MOUNT_BUFFER_SIZE__": f"0x{GET_MOUNT_BUFFER_SIZE:08X}",
        "__FH_OPEN__": f"0x{FH_OPEN:08X}",
        "__FH_CLOSE__": f"0x{FH_CLOSE:08X}",
        "__SPRINTF__": f"0x{SPRINTF:08X}",
        "__STRCPY__": f"0x{STRCPY:08X}",
        "__ALLOC__": f"0x{ALLOC:08X}",
        "__FLAGDELTA_LO__": f"0x{delta & 0xFFFF:04X}",
        "__FLAGDELTA_HI__": f"0x{delta >> 16:04X}",
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
    code = assemble(expand_assembly(template, 0), va)
    delta = MOUNT_FLAG - (va + len(code) - 4)
    resolved = assemble(expand_assembly(template, delta), va)
    if len(resolved) != len(code):
        raise ValueError(f"payload at 0x{va:08X} changed size while resolving the flag delta")
    return resolved


def patch(data):
    segments = load_segments(data)
    patched = bytearray(data)

    for asm, va, cave_end in (
        (PATH_HELPER_ASM, PATH_HELPER_VA, PATH_CAVE_END),
        (MOUNT_HELPER_ASM, MOUNT_HELPER_VA, MOUNT_CAVE_END),
    ):
        code = build_payload(asm, va)
        if va + len(code) > cave_end:
            raise ValueError(f"payload at 0x{va:08X} does not fit")
        offset = va_to_offset(segments, va, len(code))
        if any(patched[offset:offset + len(code)]):
            raise ValueError(f"code cave at 0x{va:08X} is not empty")
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
