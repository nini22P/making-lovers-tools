import struct
import os
import argparse
from pathlib import Path
from PIL import Image

class ExtHeader:
    """
    EXT File Header Structure (64 Bytes)
    ---------------------------------------------------------
    Offset | Type    | Description
    ---------------------------------------------------------
    0x00   | char[4] | Signature "EXT0"
    0x04   | float   | X Offset (Position on canvas)
    0x08   | float   | Y Offset (Position on canvas)
    0x0C   | uint32  | Texture Width (Actual data width)
    0x10   | uint32  | Texture Height (Actual data height)
    0x14   | uint32  | Canvas Width (Original width)
    0x18   | uint32  | Canvas Height (Original height)
    0x1C   | hex     | Magic Marker 1 (F1 D8 FF FF)
    0x20   | hex     | Magic Marker 2 (F1 D8 FF FF)
    0x24   | uint32  | Bit Depth (8, 24, or 32)
    0x28   | uint32  | Unknown Flags / Layer ID (Preserve this)
    0x2C   | ...     | Reserved / Padding (Zeros)
    ---------------------------------------------------------
    """
    SIZE = 64
    
    def __init__(self):
        self.raw_data = bytearray(self.SIZE)
        self.raw_data[0:4] = b'EXT0'
        self.raw_data[0x1C:0x20] = bytes.fromhex("F1D8FFFF")
        self.raw_data[0x20:0x24] = bytes.fromhex("F1D8FFFF")
        
        self.x_offset = 0.0
        self.y_offset = 0.0
        self.tex_width = 0
        self.tex_height = 0
        self.canvas_width = 0
        self.canvas_height = 0
        self.bit_depth = 32

    @classmethod
    def parse(cls, data):
        if len(data) < cls.SIZE:
            return None

        if data[0:3] != b'EXT':
            return None 
        
        version = data[3:4]
        if version != b'0':
            print(f"[Skip] Unsupported version: EXT{version.decode(errors='ignore')}")
            return None

        h = cls()
        h.raw_data = bytearray(data[:cls.SIZE])
        
        h.x_offset = struct.unpack_from('<f', data, 0x04)[0]
        h.y_offset = struct.unpack_from('<f', data, 0x08)[0]
        h.tex_width = struct.unpack_from('<I', data, 0x0C)[0]
        h.tex_height = struct.unpack_from('<I', data, 0x10)[0]
        h.canvas_width = struct.unpack_from('<I', data, 0x14)[0]
        h.canvas_height = struct.unpack_from('<I', data, 0x18)[0]
        h.bit_depth = struct.unpack_from('<I', data, 0x24)[0]
        
        if h.bit_depth not in [8, 24, 32]:
            print(f"[Skip] Unsupported bit depth: {h.bit_depth}")
            return None
            
        return h

    def update_dims(self, width, height, bit_depth):
        self.tex_width = width
        self.tex_height = height
        self.bit_depth = bit_depth
        
        struct.pack_into('<I', self.raw_data, 0x0C, width)
        struct.pack_into('<I', self.raw_data, 0x10, height)
        struct.pack_into('<I', self.raw_data, 0x24, bit_depth)

    def set_canvas_info(self, canvas_w, canvas_h, x_off=0.0, y_off=0.0):
        self.canvas_width = canvas_w
        self.canvas_height = canvas_h
        self.x_offset = x_off
        self.y_offset = y_off
        
        struct.pack_into('<f', self.raw_data, 0x04, x_off)
        struct.pack_into('<f', self.raw_data, 0x08, y_off)
        struct.pack_into('<I', self.raw_data, 0x14, canvas_w)
        struct.pack_into('<I', self.raw_data, 0x18, canvas_h)

    def to_bytes(self):
        return bytes(self.raw_data)

def bytes_to_image(ext_bytes):
    header = ExtHeader.parse(ext_bytes[:ExtHeader.SIZE])
    if not header:
        return None, None

    pixel_data = ext_bytes[ExtHeader.SIZE:]
    img = None
    
    try:
        if header.bit_depth == 32:
            img = Image.frombytes('RGBA', (header.tex_width, header.tex_height), pixel_data, 'raw', 'BGRA')

        elif header.bit_depth == 24:
            img = Image.frombytes('RGB', (header.tex_width, header.tex_height), pixel_data, 'raw', 'BGR')

        elif header.bit_depth == 8:
            if len(pixel_data) < 1024:
                return None, None
            
            palette_data = pixel_data[:1024]
            index_data = pixel_data[1024:]
            
            pil_palette = []
            transparent_index = -1
            
            for i in range(0, 1024, 4):
                b = palette_data[i]
                g = palette_data[i+1]
                r = palette_data[i+2]
                a = palette_data[i+3]
                
                pil_palette.extend([r, g, b])
                
                if a == 0 and transparent_index == -1:
                    transparent_index = i // 4
            
            img = Image.frombytes('P', (header.tex_width, header.tex_height), index_data)
            img.putpalette(pil_palette)
            
            if transparent_index != -1:
                img.info['transparency'] = transparent_index
            
        return img, header
    except Exception as e:
        print(f"[Warn] Image create failed: {e}")
        return None, None

def image_to_bytes(img, header_template=None):
    width, height = img.size
    
    if header_template:
        header = header_template
    else:
        header = ExtHeader()
        header.set_canvas_info(width, height)

    body_data = bytearray()
    
    if img.mode == 'P':
        target_depth = 8
        palette = img.getpalette()
        if not palette: palette = []
        if len(palette) < 768: 
            palette.extend([0]*(768-len(palette)))

        transparency = img.info.get('transparency')
        
        for i in range(0, 256):
            r = palette[i*3]
            g = palette[i*3+1]
            b = palette[i*3+2]
            
            a = 255
            
            if transparency is not None:
                if isinstance(transparency, bytes):
                    if i < len(transparency): 
                        a = transparency[i]
                elif isinstance(transparency, int):
                    if i == transparency: 
                        a = 0
            
            body_data.extend([b, g, r, a])
        
        body_data.extend(img.tobytes())

    elif img.mode == 'RGB':
        target_depth = 24
        body_data.extend(img.tobytes("raw", "BGR"))

    else:
        target_depth = 32
        if img.mode != 'RGBA':
            img = img.convert('RGBA')
        body_data.extend(img.tobytes("raw", "BGRA"))

    header.update_dims(width, height, target_depth)

    return header.to_bytes() + body_data

def decode_ext_file(src_path, dst_path):
    try:
        with open(src_path, 'rb') as f:
            data = f.read()
            
        img, header = bytes_to_image(data)
        if not img or not header: return False
        
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        img.save(dst_path)
        print(f"[Decoded] {os.path.basename(src_path)} ({header.tex_width}x{header.tex_height}, {header.bit_depth}bpp)")
        return True
    except Exception as e:
        print(f"[Err] {src_path}: {e}")
        return False

def encode_ext_file(src_png, dst_ext):
    try:
        img = Image.open(src_png)
        
        header_template = None
        if os.path.exists(dst_ext):
            try:
                with open(dst_ext, 'rb') as f:
                    raw = f.read(ExtHeader.SIZE)
                    header_template = ExtHeader.parse(raw)
            except: pass
            
        ext_bytes = image_to_bytes(img, header_template)
        
        os.makedirs(os.path.dirname(dst_ext), exist_ok=True)
        with open(dst_ext, 'wb') as f:
            f.write(ext_bytes)
            
        new_header = ExtHeader.parse(ext_bytes[:ExtHeader.SIZE])

        if not new_header: return False
        
        print(f"[Encoded] {os.path.basename(dst_ext)} ({new_header.tex_width}x{new_header.tex_height}, {new_header.bit_depth}bpp)")
        return True
    except Exception as e:
        print(f"[Err] {src_png}: {e}")
        return False

def process(mode, input_path, output_path):
    in_p = Path(input_path)
    out_p = Path(output_path)

    if in_p.is_file():
        if mode == 'd':
            dst = out_p if out_p.suffix else (out_p / (in_p.stem + ".png"))
            decode_ext_file(in_p, dst)
        else:
            dst = out_p if out_p.suffix else (out_p / (in_p.stem + ".ext"))
            encode_ext_file(in_p, dst)
        return

    if in_p.is_dir():
        count = 0
        for root, dirs, files in os.walk(in_p):
            for file in files:
                src_file = Path(root) / file
                rel_path = src_file.relative_to(in_p)
                
                if mode == 'd' and file.lower().endswith('.ext'):
                    dst_file = out_p / rel_path.with_suffix('.png')
                    decode_ext_file(src_file, dst_file)
                    count += 1
                elif mode == 'e' and file.lower().endswith('.png'):
                    dst_file = out_p / rel_path.with_suffix('.ext')
                    encode_ext_file(src_file, dst_file)
                    count += 1
        print(f"Processed {count} files.")

def main():
    parser = argparse.ArgumentParser(description="EXT Tool")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    decode_parser = subparsers.add_parser('decode', aliases=['d'], help="Decode EXT to PNG")
    decode_parser.add_argument('-i', '--input', required=True, help="Input path")
    decode_parser.add_argument('-o', '--output', required=True, help="Output path")

    encode_parser = subparsers.add_parser('encode', aliases=['e'], help="Encode PNG to EXT")
    encode_parser.add_argument('-i', '--input', required=True, help="Input path")
    encode_parser.add_argument('-o', '--output', required=True, help="Output path")

    args = parser.parse_args()

    if args.command in ['decode', 'd']:
        process('d', args.input, args.output)
    elif args.command in ['encode', 'e']:
        process('e', args.input, args.output)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()