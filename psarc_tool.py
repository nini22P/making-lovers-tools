import os
import subprocess
import argparse
import shutil
import sys

def run_command(command, cwd=None):
    try:
        result = subprocess.run(command, shell=True, check=True, capture_output=True, text=True, cwd=cwd)
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Command failed: {e}")
        if e.stderr: print(f"Details: {e.stderr}")
        return None

def extract_psarc(args):
    input_path = os.path.abspath(args.input)
    output_path = os.path.abspath(args.output)
    
    if not os.path.isfile(input_path):
        print(f"[ERROR] Input .psarc file not found: {input_path}")
        return

    base_name = os.path.splitext(os.path.basename(input_path))[0]
    list_file = os.path.join(output_path, f"{base_name}.txt")

    print(f"--- [EXTRACTING] ---")
    if not os.path.exists(output_path):
        os.makedirs(output_path)

    print(f"Extracting to: {output_path}")
    run_command(f'psarc extract "{input_path}" --to="{output_path}"')

    print(f"Generating list: {list_file}")
    output = run_command(f'psarc list "{input_path}"')
    
    if output:
        lines = output.splitlines()
        with open(list_file, "w", encoding="utf-8") as f:
            for line in lines:
                clean_line = line.split(' ')[0].strip()
                if clean_line.lower() != "listing" and clean_line:
                    f.write(clean_line + "\n")
    
    print(f"Extraction complete.")

def create_psarc(args):
    input_txt = os.path.abspath(args.input)
    final_output_path = os.path.abspath(args.output)
    
    if not os.path.isfile(input_txt):
        print(f"[ERROR] Input list file (.txt) not found: {input_txt}")
        return

    working_dir = os.path.dirname(input_txt)
    list_filename = os.path.basename(input_txt)
    psarc_filename = os.path.basename(final_output_path)

    print(f"--- [CREATING] ---")
    print(f"Using list: {list_filename}")
    print(f"Working directory: {working_dir}")
    
    cmd = f'psarc create -i --overwrite --inputfile="{list_filename}"'
    
    if run_command(cmd, cwd=working_dir) is not None:
        temp_output = os.path.join(working_dir, psarc_filename)
        
        if temp_output != final_output_path:
            print(f"Moving: {temp_output} -> {final_output_path}")
            if os.path.exists(final_output_path):
                os.remove(final_output_path)
            shutil.move(temp_output, final_output_path)
            
        print(f"Create finished: {final_output_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PSARC Tool")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    extract_parser = subparsers.add_parser("extract", help="Extract a .psarc file")
    extract_parser.add_argument("-i", "--input", required=True, help="Input .psarc file")
    extract_parser.add_argument("-o", "--output", required=True, help="Output directory")

    create_parser = subparsers.add_parser("create", help="Create a .psarc file from list")
    create_parser.add_argument("-i", "--input", required=True, help="Input .txt list file")
    create_parser.add_argument("-o", "--output", required=True, help="Final .psarc output path")

    args = parser.parse_args()

    if args.command == "extract":
        extract_psarc(args)
    elif args.command == "create":
        create_psarc(args)
    else:
        parser.print_help()
        sys.exit(1)
        
    sys.exit(0)