import os
import csv
import re
import glob
import argparse
from collections import OrderedDict, defaultdict

NAME_PATTERN = re.compile(r'<name\s(.+?)>')
TEXT_PATTERN = re.compile(r'<text\s(.+?)>')
SELECT_PATTERN = re.compile(r'<select\s(.+?)>')
SELECT_PREFIX_PATTERN = re.compile(r'^(\s*(?:\d+\s*:\s*)?)')

class ScriptTool:
    def get_files(self, directory):
        return sorted(glob.glob(os.path.join(directory, '*.txt')))

    def extract(self, input_dir, output_csv):
        files = self.get_files(input_dir)
        if not files:
            print(f"Error: No .txt files found in '{input_dir}'.")
            return

        print(f"Extracting from '{input_dir}'...")
        
        unique_names = set()
        data_rows = []

        for file_path in files:
            file_name = os.path.basename(file_path)
            try:
                with open(file_path, 'r', encoding='shift_jis', errors='ignore') as f:
                    lines = f.readlines()
            except Exception as e:
                print(f"Failed to read {file_name}: {e}")
                continue

            for i, line in enumerate(lines):
                line_num = i + 1
                
                text_match = TEXT_PATTERN.search(line)
                if text_match:
                    raw_content = text_match.group(1).strip()
                    if raw_content.endswith('>'): 
                        raw_content = raw_content[:-1]
                    
                    speaker_name = ""
                    if i > 0:
                        prev_line = lines[i-1]
                        name_match = NAME_PATTERN.search(prev_line)
                        if name_match:
                            raw_name = name_match.group(1).split('>')[0].strip()
                            speaker_name = raw_name
                            unique_names.add(raw_name)

                    if raw_content:
                        data_rows.append(OrderedDict([
                            ('type', 'TEXT'),
                            ('source', file_name),
                            ('line', line_num),
                            ('context', speaker_name),
                            ('original', raw_content),
                            ('translation', ''),
                        ]))

                select_match = SELECT_PATTERN.search(line)
                if select_match:
                    raw_content = select_match.group(1).strip()
                    if raw_content.endswith('>'): 
                        raw_content = raw_content[:-1]
                    
                    parts = raw_content.split(',')
                    select_idx = 0

                    for part in parts:
                        clean_part = part.strip()
                        
                        if clean_part.isdigit():
                            continue

                        original_text = clean_part
                        
                        if ':' in clean_part:
                            try:
                                pre, txt = clean_part.split(':', 1)
                                if pre.strip().isdigit():
                                    original_text = txt.strip()
                            except:
                                pass
                        
                        if original_text:
                            data_rows.append(OrderedDict([
                                ('type', 'SELECT'),
                                ('source', file_name),
                                ('line', line_num),
                                ('context', str(select_idx)),
                                ('original', original_text),
                                ('translation', ''),
                            ]))
                            select_idx += 1

        final_data = []
        
        print(f"Extracted {len(unique_names)} unique names.")
        for name in sorted(list(unique_names)):
            final_data.append(OrderedDict([
                ('type', 'NAME'),
                ('source', ''),
                ('line', ''),
                ('context', ''),
                ('original', name),
                ('translation', ''),
            ]))

        print(f"Extracted {len(data_rows)} lines of text/options.")
        final_data.extend(data_rows)

        try:
            with open(output_csv, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = ['type', 'source', 'line', 'context', 'original', 'translation']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(final_data)
            print(f"Extraction complete. Saved to: {output_csv}")
        except IOError as e:
            print(f"Failed to write CSV: {e}")

    def write(self, input_dir, output_dir, csv_path):
        if not os.path.exists(csv_path):
            print(f"Error: Translation file '{csv_path}' not found.")
            return

        print(f"Loading translations from '{csv_path}'...")
        name_map = {}
        text_map = defaultdict(dict)
        select_map = defaultdict(lambda: defaultdict(dict))

        try:
            with open(csv_path, 'r', newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    original = row.get('original', '')
                    translation = row.get('translation', '').strip()
                    
                    if not translation: 
                        continue

                    r_type = row.get('type')
                    if r_type == 'NAME':
                        name_map[original] = translation
                    elif r_type == 'TEXT':
                        src = row.get('source')
                        line = int(row.get('line', 0))
                        text_map[src][line] = translation
                    elif r_type == 'SELECT':
                        src = row.get('source')
                        line = int(row.get('line', 0))
                        idx_str = row.get('context')
                        select_map[src][line][idx_str] = translation
        except Exception as e:
            print(f"Failed to load CSV: {e}")
            return

        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        files = self.get_files(input_dir)
        print(f"Processing {len(files)} files...")

        for file_path in files:
            file_name = os.path.basename(file_path)
            dest_path = os.path.join(output_dir, file_name)
            
            try:
                with open(file_path, 'r', encoding='shift_jis', errors='ignore') as f:
                    lines = f.readlines()
            except Exception as e:
                print(f"Failed to read {file_name}: {e}")
                continue

            new_lines = list(lines)
            
            file_texts = text_map.get(file_name, {})
            file_selects = select_map.get(file_name, {})

            for i, line in enumerate(lines):
                line_num = i + 1

                if line_num in file_texts:
                    trans = file_texts[line_num]
                    new_lines[i] = TEXT_PATTERN.sub(f'<text {trans}>', new_lines[i])
                    
                    if i > 0:
                        prev = new_lines[i-1]
                        nm = NAME_PATTERN.search(prev)
                        if nm:
                            raw_nm = nm.group(1).split('>')[0].strip()
                            if raw_nm in name_map:
                                t_nm = name_map[raw_nm]
                                new_lines[i-1] = NAME_PATTERN.sub(f'<name {t_nm}>', prev)

                if line_num in file_selects:
                    sm = SELECT_PATTERN.search(line)
                    if sm:
                        raw_content = sm.group(1).strip()
                        if raw_content.endswith('>'): 
                            raw_content = raw_content[:-1]
                        
                        parts = raw_content.split(',')
                        new_parts = []
                        select_idx = 0
                        
                        for part in parts:
                            clean_part = part.strip()
                            current_part = part 

                            if clean_part.isdigit():
                                new_parts.append(current_part)
                                continue
                            
                            idx_str = str(select_idx)
                            
                            if idx_str in file_selects[line_num]:
                                trans_text = file_selects[line_num][idx_str]
                                
                                prefix_match = SELECT_PREFIX_PATTERN.match(part)
                                if prefix_match:
                                    prefix = prefix_match.group(1)
                                    current_part = prefix + trans_text
                                else:
                                    current_part = trans_text
                            
                            new_parts.append(current_part)
                            select_idx += 1

                        joined_content = ",".join(new_parts)
                        new_lines[i] = SELECT_PATTERN.sub(f'<select {joined_content}>', new_lines[i])

            try:
                with open(dest_path, 'w', encoding='shift_jis', errors='replace') as f:
                    f.writelines(new_lines)
            except Exception as e:
                print(f"Failed to write {file_name}: {e}")

        print("All files processed.")

def main():
    parser = argparse.ArgumentParser(description="Script Tool")
    subparsers = parser.add_subparsers(dest='mode', required=True, help='Operation mode')

    p_extract = subparsers.add_parser('extract', help='Extract text to CSV')
    p_extract.add_argument('-i', '--input', required=True, help='Input script directory')
    p_extract.add_argument('-o', '--output', required=True, help='Output CSV file path')

    p_write = subparsers.add_parser('write', help='Write translations to scripts')
    p_write.add_argument('-i', '--input', required=True, help='Original script directory')
    p_write.add_argument('-o', '--output', required=True, help='Output script directory')
    p_write.add_argument('-c', '--csv', required=True, help='Translation CSV file path')

    args = parser.parse_args()
    tool = ScriptTool()

    if args.mode == 'extract':
        tool.extract(args.input, args.output)
    elif args.mode == 'write':
        tool.write(args.input, args.output, args.csv)

if __name__ == '__main__':
    main()