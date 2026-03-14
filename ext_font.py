import argparse
import struct
import os
import sys
from PIL import Image

def decode(src_path, dst_path):
    if not os.path.exists(src_path):
        print(f"Error: File {src_path} not found.")
        return

    with open(src_path, 'rb') as f:
        data = f.read()

    if data[0:4] != b'EXT0':
        print("Error: Invalid header (expected EXT0)")
        return

    img_width = struct.unpack('<I', data[0x0C:0x10])[0]
    img_height = struct.unpack('<I', data[0x10:0x14])[0]
    bpp = struct.unpack('<I', data[0x1C:0x20])[0]

    palette_offset = 0x40
    palette_count = 1 << bpp
    
    palette = []
    for i in range(palette_count):
        idx = palette_offset + i * 4
        if idx + 3 < len(data):
            r = data[idx]
            g = data[idx+1]
            b = data[idx+2]
            a = data[idx+3]
            palette.append((r, g, b, a))
        else:
            palette.append((0, 0, 0, 0))

    pixel_data_start = palette_offset + (palette_count * 4)
    pixel_data = data[pixel_data_start:]
    
    img = Image.new('RGBA', (img_width, img_height))
    pix = img.load()

    for y in range(img_height):
        for x in range(img_width):
            address = y * img_width + x
            if address < len(pixel_data):
                val = pixel_data[address]
                if val < len(palette):
                    pix[x, y] = palette[val]

    img.save(dst_path)
    print(f"Success: Saved to {dst_path}")

def main():
    parser = argparse.ArgumentParser(description="EXT Font Tool")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    decode_parser = subparsers.add_parser('decode', aliases=['d'], help="Decode EXT Font to PNG")
    decode_parser.add_argument('-i', '--input', required=True, help="Input path")
    decode_parser.add_argument('-o', '--output', required=True, help="Output path")

    encode_parser = subparsers.add_parser('encode', aliases=['e'], help="Encode PNG to EXT Font")
    encode_parser.add_argument('-i', '--input', required=True, help="Input path")
    encode_parser.add_argument('-o', '--output', required=True, help="Output path")

    args = parser.parse_args()

    if args.command in ['decode', 'd']:
        decode(args.input, args.output)
    elif args.command in ['encode', 'e']:
        # encode(args.input, args.output)
        print("Error: Not implemented")
        return
    else:
        parser.print_help()

if __name__ == "__main__":
    main()