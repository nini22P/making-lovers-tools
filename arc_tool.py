import re
import sys
import os
import argparse
import io
from PIL import Image

"""
inspired by https://github.com/Paddel06/kinkoi-stuff/
"""

try:
    import ext_tool
except ImportError:
    print("Error: 'ext_tool.py' not found in the same directory.")
    sys.exit(1)

ENC = 'cp932'
ENDIAN = 'little'
DEFAULT_STR_PAD = 64 # may be 32 in some cases
ARC_PAD_EXT = 64  # visuals/images
ARC_PAD_SCR = 8   # scripts
DEFAULT_TILE_SIZE = 128

def parse_info_bin(data):
    if len(data) < 16: return None
    
    total_w = int.from_bytes(data[0:4], ENDIAN)
    total_h = int.from_bytes(data[4:8], ENDIAN)
    count = int.from_bytes(data[8:12], ENDIAN)
    
    entries = []
    offset = 16
    for _ in range(count):
        if offset + 16 > len(data): break
        x = int.from_bytes(data[offset:offset+4], ENDIAN)
        y = int.from_bytes(data[offset+4:offset+8], ENDIAN)
        w = int.from_bytes(data[offset+8:offset+12], ENDIAN)
        h = int.from_bytes(data[offset+12:offset+16], ENDIAN)
        entries.append({'x': x, 'y': y, 'w': w, 'h': h})
        offset += 16
        
    return total_w, total_h, entries

def make_bin_ext(total_w, total_h, entries):
    buffer = io.BytesIO()
    buffer.write(total_w.to_bytes(4, ENDIAN))
    buffer.write(total_h.to_bytes(4, ENDIAN))
    buffer.write(len(entries).to_bytes(4, ENDIAN))
    buffer.write(b'\xcc\xcc\xcc\xcc')
    
    for e in entries:
        buffer.write(int(e['x']).to_bytes(4, ENDIAN))
        buffer.write(int(e['y']).to_bytes(4, ENDIAN))
        buffer.write(int(e['w']).to_bytes(4, ENDIAN))
        buffer.write(int(e['h']).to_bytes(4, ENDIAN))
        
    return buffer.getvalue()

def make_bin_scr(in_path):
    bin_name = '00_info.bin'
    print(f"Generating {bin_name} for script...")
    
    files = sorted([f for f in os.listdir(in_path) if f.endswith('.txt')])
    label_count = 0
    buffer = io.BytesIO()
    buffer.write(bytes(8)) 
    
    label_pattern = re.compile(r'<label\s+([^>]+)>', re.IGNORECASE)

    for file in files:
        with open(os.path.join(in_path, file), 'r', encoding=ENC, errors='ignore') as script:
            file_name_bytes = (file + '\x00').encode(ENC)
            label_ofs = 0
            for line in script:
                match = label_pattern.search(line)
                if match:
                    label_count += 1
                    extracted_label = match.group(1)
                    label_bytes = (extracted_label + '\x00').encode(ENC)
                    buffer.write(label_bytes)
                    buffer.write(b'\xfe' * (DEFAULT_STR_PAD - len(label_bytes)))
                    buffer.write(file_name_bytes)
                    buffer.write(b'\xfe' * (DEFAULT_STR_PAD - len(file_name_bytes)))
                    buffer.write(label_ofs.to_bytes(8, ENDIAN))
                label_ofs += len(line.encode(ENC)) + 1
    final_data = bytearray(buffer.getvalue())
    final_data[0:8] = label_count.to_bytes(8, ENDIAN)
    with open(os.path.join(in_path, bin_name), 'wb') as f:
        f.write(final_data)

def unpack_arc(arc_path, out_path_input, str_pad):
    print(f"Unpacking: {arc_path}")
    files_in_arc = [] 
    
    with open(arc_path, 'rb') as f:
        try:
            index_len = int.from_bytes(f.read(4), ENDIAN)
            file_count = int.from_bytes(f.read(4), ENDIAN)
        except:
            print("Error: Invalid ARC header.")
            return

        file_indices = []
        for _ in range(file_count):
            name_bytes = f.read(str_pad)
            name = name_bytes.split(b'\x00')[0].decode(ENC, errors='ignore')
            size = int.from_bytes(f.read(4), ENDIAN)
            offset = int.from_bytes(f.read(4), ENDIAN)
            file_indices.append({'name': name, 'size': size, 'offset': offset})
            
        for info in file_indices:
            f.seek(info['offset'])
            data = f.read(info['size'])
            files_in_arc.append({'name': info['name'], 'data': data})

    info_bin_file = next((f for f in files_in_arc if f['name'].lower() == 'info.bin'), None)
    
    if info_bin_file:
        print("Found info.bin -> Merging tiles...")
        parse_result = parse_info_bin(info_bin_file['data'])
        
        if parse_result is None:
            print("Error: Failed to parse info.bin")
            return
        
        total_w, total_h, tile_entries = parse_result
        print(f"Canvas: {total_w}x{total_h}, Tiles: {len(tile_entries)}")
        
        ext_files = [f for f in files_in_arc if f['name'].lower().endswith('.ext')]
        
        canvas = Image.new('RGBA', (total_w, total_h))
        
        for i, entry in enumerate(tile_entries):
            if i >= len(ext_files): break
            print(f"  Tile {i:02d}: {entry['w']}x{entry['h']} at ({entry['x']}, {entry['y']})")
            
            tile_img, _ = ext_tool.bytes_to_image(ext_files[i]['data'])
            
            if tile_img:
                canvas.paste(tile_img, (entry['x'], entry['y']))
            else:
                print(f"  [Err] Failed to decode tile {i}")

        if not out_path_input:
            out_file = os.path.splitext(arc_path)[0] + ".png"
        elif os.path.isdir(out_path_input):
            out_file = os.path.join(out_path_input, os.path.basename(arc_path).replace('.arc', '.png'))
        else:
            out_file = out_path_input
            
        canvas.save(out_file)
        print(f"Merged image saved to: {out_file}")

    else:
        print("No info.bin found. Extracting raw files...")
        out_dir = out_path_input if out_path_input else os.path.splitext(arc_path)[0]
        os.makedirs(out_dir, exist_ok=True)
        
        for f in files_in_arc:
            out_p = os.path.join(out_dir, f['name'])
            with open(out_p, 'wb') as wf:
                wf.write(f['data'])
            print(f"  Extracted: {f['name']}")

def pack_arc(input_path, output_path, pack_type, str_pad, tile_size):
    entries = []
    align_pad = ARC_PAD_EXT
    
    if os.path.isfile(input_path) and input_path.lower().endswith('.png'):
        print(f"Slicing Image: {input_path} (Tile Size: {tile_size})")
        
        img = Image.open(input_path)
        total_w, total_h = img.size
        
        info_entries = []
        tile_idx = 0
        
        for y in range(0, total_h, tile_size):
            for x in range(0, total_w, tile_size):
                w = min(tile_size, total_w - x)
                h = min(tile_size, total_h - y)
                
                tile_img = img.crop((x, y, x + w, y + h))
                info_entries.append({'x': x, 'y': y, 'w': w, 'h': h})
                
                header = ext_tool.ExtHeader()
                header.set_canvas_info(total_w, total_h, float(x), float(y))

                ext_data = ext_tool.image_to_bytes(tile_img, header_template=header)
                
                tile_name = f"{tile_idx:03d}.ext"
                entries.append({'name': tile_name, 'data': ext_data})
                
                print(f"  Generated {tile_name}: {w}x{h} at ({x},{y})")
                tile_idx += 1
                
        info_bin_data = make_bin_ext(total_w, total_h, info_entries)
        entries.insert(0, {'name': 'info.bin', 'data': info_bin_data})

    elif os.path.isdir(input_path):
        print(f"Packing Folder: {input_path}")
        if pack_type == 'scr':
            make_bin_scr(input_path)
            align_pad = ARC_PAD_SCR
            
        file_list = sorted(os.listdir(input_path))
        file_list = [f for f in file_list if not f.startswith('.')]
        
        for fname in file_list:
            fpath = os.path.join(input_path, fname)
            if os.path.isdir(fpath): continue

            if pack_type == 'scr' and fname == '00_info.bin': continue 

            with open(fpath, 'rb') as f:
                raw_data = f.read()

            if pack_type == 'ext' and fname.lower().endswith('.png'):
                print(f"  [Conv] {fname} -> .ext")
                img = Image.open(io.BytesIO(raw_data))
                ext_data = ext_tool.image_to_bytes(img)
                entries.append({'name': os.path.splitext(fname)[0] + ".ext", 'data': ext_data})
            else:
                entries.append({'name': fname, 'data': raw_data})
                
        if pack_type == 'scr':
            with open(os.path.join(input_path, '00_info.bin'), 'rb') as f:
                entries.insert(0, {'name': '00_info.bin', 'data': f.read()})
                
    else:
        print("Error: Input must be a PNG file or a directory.")
        return

    file_count = len(entries)
    entries_size = (str_pad + 8) * file_count
    
    with open(output_path, 'wb') as f:
        f.write((entries_size + 8).to_bytes(4, ENDIAN))
        f.write(file_count.to_bytes(4, ENDIAN))
        
        current_offset = f.tell() + entries_size
        file_offsets = []
        simulated_offset = current_offset
        
        for entry in entries:
            pad_len = 0
            if simulated_offset % align_pad != 0:
                pad_len = align_pad - (simulated_offset % align_pad)
            simulated_offset += pad_len
            file_offsets.append((simulated_offset, pad_len))
            simulated_offset += len(entry['data'])

        for i, entry in enumerate(entries):
            name_bytes = entry['name'].encode(ENC)
            if len(name_bytes) > str_pad: name_bytes = name_bytes[:str_pad-1]
            f.write(name_bytes + b'\x00')
            f.write(b'\xfe' * (str_pad - len(name_bytes) - 1))
            f.write(len(entry['data']).to_bytes(4, ENDIAN))
            f.write(file_offsets[i][0].to_bytes(4, ENDIAN))

        for i, entry in enumerate(entries):
            offset, pad_len = file_offsets[i]
            if pad_len > 0: f.write(b'\x00' * pad_len)
            f.write(entry['data'])
            
    print(f"Pack done -> {output_path}")

def main():
    parser = argparse.ArgumentParser(description="ARC Tool")
    subparsers = parser.add_subparsers(dest='command', help='Commands')

    unpack_parser = subparsers.add_parser('unpack', help='Unpack .arc to .png (merge) or folder')
    unpack_parser.add_argument('-i', '--input', required=True, help='Input .arc file')
    unpack_parser.add_argument('-o', '---output', required=True, help='Output .png or directory')
    unpack_parser.add_argument('--str-pad', type=int, default=DEFAULT_STR_PAD, help='STR PAD value (default: 64)')

    pack_parser = subparsers.add_parser('pack', help='Pack .png (slice) or folder to .arc')
    pack_parser.add_argument('-i', '--input', required=True, help='Input .png file (for slicing) or folder')
    pack_parser.add_argument('-o', '---output', required=True, help='Output .arc file')
    pack_parser.add_argument('-t', '--type', choices=['ext', 'scr'], required=True, help='Pack type (only for folder mode)')
    pack_parser.add_argument('--str-pad', type=int, default=DEFAULT_STR_PAD, help='STR PAD value (default: 64)')
    pack_parser.add_argument('--tile-size', type=int, default=DEFAULT_TILE_SIZE, help='Tile size for slicing PNG (default: 128)')

    args = parser.parse_args()

    if args.command in ['unpack']:
        if not args.input:
            unpack_parser.print_help()
            return
        unpack_arc(args.input, args.output, args.str_pad)

    elif args.command in ['pack']:
        if not args.input:
            pack_parser.print_help()
            return
            
        out_file = args.output
        if not out_file:
            if os.path.isfile(args.input):
                out_file = os.path.splitext(args.input)[0] + ".arc"
            else:
                out_file = os.path.basename(os.path.normpath(args.input)) + ".arc"
                
        pack_arc(args.input, out_file, args.type, args.str_pad, args.tile_size)
        
    else:
        parser.print_help()

if __name__ == "__main__":
    main()