# This script is intended for filtering simfiles with low-level charts, for events with casual visitors to enjoy pump.
# It scans source folder for simfiles with charts below specified level - and moves those simfiles to output folder

# WARNING: it moves all simfiles into _ONE_ output folder, not preserving their original path structure.
# So don't use it on the whole stepmania Songs folder - use it on separate pack folders instead


import os
import re
import shutil
import sys



def find_and_move_folders(source_folder, target_folder, min_level):
    # Ensure the target folder exists
    os.makedirs(target_folder, exist_ok=True)

    # Walk through the folder structure
    for root, dirs, files in os.walk(source_folder):
        for folder in dirs:
            folder_path = os.path.join(root, folder)
            ssc_files = [f for f in os.listdir(folder_path) if f.endswith('.ssc')]

            for ssc_file in ssc_files:
                ssc_file_path = os.path.join(folder_path, ssc_file)
                try:
                    content = open_file(ssc_file_path)
                    # Look for the "#METER:<number>;" pattern
                    match = re.search(r"#METER:(\d+);", content)
                    if match:
                        number = int(match.group(1))
                        if number <= min_level:
                            move_folder(folder_path, target_folder)
                            break  # Move on to the next folder once a match is found
                except Exception as e:
                    print(f"Error reading file {ssc_file_path}: {e}")


def open_file(file_path):
    """
    Tries to open a file with UTF-8 encoding, falling back to other encodings if needed.
    Returns the file content as a string.
    """
    encodings = ['utf-8', 'latin-1', 'windows-1252']
    for encoding in encodings:
        try:
            with open(file_path, 'r', encoding=encoding) as file:
                return file.read()
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError(f"Unable to decode file: {file_path}")


def move_folder(folder_path, target_folder):
    folder_name = os.path.basename(folder_path)
    target_path = os.path.join(target_folder, folder_name)

    # Check if a folder with the same name exists, and resolve name conflicts
    counter = 2
    while os.path.exists(target_path):
        target_path = os.path.join(target_folder, f"{folder_name}_{counter}")
        counter += 1

    # Move the folder
    shutil.move(folder_path, target_path)
    print(f"Moved '{folder_path}' to '{target_path}'")



if len(sys.argv) < 3:
    print(f"Usage: {sys.argv[0]} source_folder target_folder min_level")
    exit(0)


source_folder = sys.argv[1]
if not os.path.exists(source_folder):
    print(f"Source folder '{source_folder}' not exists")
    exit(1)

target_folder = sys.argv[2]
if not os.path.exists(target_folder):
    print(f"Target folder '{target_folder}' not exists")
    exit(1)

min_level = int(sys.argv[3])

find_and_move_folders(source_folder, target_folder, min_level)
