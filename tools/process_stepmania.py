#!/usr/bin/env python3
"""
StepMania chart folder processor.

Usage:
    python process_stepmania.py /path/to/songs
    python process_stepmania.py /path/to/songs --offset -0.05
"""

import argparse
import os
import re
import sys
from pathlib import Path

CHART_EXTENSIONS = {".ssc", ".sm", ".sma"}
OLD_EXTENSION = ".old"

# SSC fields whose values are filenames that must exist
ASSET_FIELDS = {"BANNER", "BACKGROUND", "PREVIEWVID", "MUSIC"}


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="Process StepMania song folders: clean up old files, "
                    "deduplicate chart files, patch metadata fields."
    )
    parser.add_argument(
        "source",
        metavar="SOURCE_FOLDER",
        help="Root folder to scan recursively for song subfolders.",
    )
    parser.add_argument(
        "--offset",
        metavar="SECONDS",
        type=float,
        default=None,
        help="If given, add this value to every #OFFSET field in .ssc files "
             "and store the original value in #SOURCEOFFSET.",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Folder scanning
# ---------------------------------------------------------------------------

def find_song_folders(root: Path) -> list[Path]:
    """
    Return every directory under *root* (including root itself) that
    contains at least one file with a chart extension.
    """
    song_folders = []
    for dirpath, _dirnames, filenames in os.walk(root):
        folder = Path(dirpath)
        if any(Path(f).suffix.lower() in CHART_EXTENSIONS for f in filenames):
            song_folders.append(folder)
    return song_folders


# ---------------------------------------------------------------------------
# File cleanup helpers
# ---------------------------------------------------------------------------

def delete_old_files(folder: Path) -> None:
    """Delete every *.old file in *folder*."""
    for f in folder.iterdir():
        if f.is_file() and f.suffix.lower() == OLD_EXTENSION:
            print(f"  [delete] {f.name}")
            f.unlink()


def deduplicate_chart_files(folder: Path) -> None:
    """
    Priority rules:
      - .ssc present -> delete .sm and .sma, keep .ssc.
      - .ssc absent, .sma present -> delete .sm, keep .sma.
      - .sm only -> keep it.

    All chart files in the folder must share the same stem (case-insensitive).
    If stems differ across any chart files, raise an error.
    """
    chart_files = [
        f for f in folder.iterdir()
        if f.is_file() and f.suffix.lower() in CHART_EXTENSIONS
    ]

    if not chart_files:
        return

    # Enforce that all chart files share the same stem
    stems = {f.stem.lower() for f in chart_files}
    if len(stems) > 1:
        names = ", ".join(f.name for f in sorted(chart_files))
        raise RuntimeError(
            f"Chart files with mismatched names in '{folder}': {names} -- "
            "all chart files (.ssc, .sma, .sm) must share the same base name."
        )

    by_ext: dict[str, Path] = {f.suffix.lower(): f for f in chart_files}

    if ".ssc" in by_ext:
        for ext in (".sm", ".sma"):
            if ext in by_ext:
                print(f"  [delete duplicate] {by_ext[ext].name}")
                by_ext[ext].unlink()
    elif ".sma" in by_ext:
        if ".sm" in by_ext:
            print(f"  [delete duplicate] {by_ext['.sm'].name}")
            by_ext[".sm"].unlink()


# ---------------------------------------------------------------------------
# SSC patching helpers
# ---------------------------------------------------------------------------

def read_text_file(path: Path) -> str:
    """Read a text file, trying UTF-8 then latin-1 as fallback."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1")


def field_pattern(field_name: str) -> re.Pattern:
    """Return a compiled regex that matches  #FIELDNAME:<value>;  lines."""
    return re.compile(
        rf"(#\s*{re.escape(field_name)}\s*:)([^;]*)(;)",
        re.IGNORECASE,
    )


def verify_asset_fields(ssc_path: Path, content: str) -> None:
    """
    For each of BANNER, BACKGROUND, PREVIEWVID, MUSIC: if the field is
    present and non-empty, check that the referenced file exists next to the
    .ssc file.  Raise RuntimeError if any are missing.
    """
    folder = ssc_path.parent
    errors = []
    for field in ASSET_FIELDS:
        pat = field_pattern(field)
        for m in pat.finditer(content):
            value = m.group(2).strip()
            if not value:
                continue
            asset_path = folder / value
            if not asset_path.exists():
                errors.append(f"#{field}: '{value}' not found in '{folder}'")
    if errors:
        raise RuntimeError(
            f"Missing asset files referenced in '{ssc_path}':\n"
            + "\n".join(f"  {e}" for e in errors)
        )


def patch_ssc_file(ssc_path: Path, offset_delta: float | None) -> None:
    """
    Modify *ssc_path* in-place:

      1. #SOURCEPATH: rewrite value if already present, insert after the first
         tag line if absent.

      2. If offset_delta is given, process every #OFFSET occurrence:
           - Each #OFFSET may or may not be immediately preceded by a
             #SOURCEOFFSET line (on the line directly before it).
           - If #SOURCEOFFSET IS present before this #OFFSET:
               * Use #SOURCEOFFSET's value as the base.
               * Rewrite #OFFSET = base + delta.
               * Leave #SOURCEOFFSET unchanged.
           - If #SOURCEOFFSET is NOT present before this #OFFSET:
               * Insert  #SOURCEOFFSET:<current #OFFSET value>;  on the line
                 immediately before #OFFSET.
               * Rewrite #OFFSET = original + delta.

      3. Verify that asset files referenced by the file actually exist.
    """
    content = read_text_file(ssc_path)
    folder = ssc_path.parent.resolve()
    changed = False

    # --- 1. #SOURCEPATH -------------------------------------------------------
    sourcepath_pat = re.compile(
        r"(#\s*SOURCEPATH\s*:)([^;]*)(;)", re.IGNORECASE
    )

    if sourcepath_pat.search(content):
        # Rewrite existing value
        new_content = sourcepath_pat.sub(
            lambda m: f"{m.group(1)}{folder}{m.group(3)}", content
        )
        if new_content != content:
            content = new_content
            changed = True
            print(f"  [patch] updated #SOURCEPATH")
        else:
            print(f"  [patch] #SOURCEPATH already correct, skipped")
    else:
        # Insert after the very first tag line for readability
        insert_line = f"#SOURCEPATH:{folder};\n"
        first_tag = re.search(r"^#[^\n]+\n", content, re.MULTILINE)
        if first_tag:
            pos = first_tag.end()
            content = content[:pos] + insert_line + content[pos:]
        else:
            content = insert_line + content
        changed = True
        print(f"  [patch] added #SOURCEPATH")

    # --- 2. #OFFSET / #SOURCEOFFSET -------------------------------------------
    if offset_delta is not None:
        # Match an optional #SOURCEOFFSET line on the line immediately before
        # a #OFFSET field.  Both are allowed to have arbitrary spacing /
        # capitalisation.
        #
        # Named groups:
        #   so_line  -- the whole "#SOURCEOFFSET:...;\n" line (may be absent)
        #   so_val   -- the numeric string inside #SOURCEOFFSET
        #   off_tag  -- "#OFFSET:" prefix (with any internal spaces)
        #   off_val  -- the numeric string inside #OFFSET
        #   off_end  -- the closing ";"
        combined_pat = re.compile(
            r"(?P<so_line>#\s*SOURCEOFFSET\s*:[ \t]*(?P<so_val>[^;]*);[ \t]*\n)?"
            r"(?P<off_tag>#\s*OFFSET\s*:)(?P<off_val>[^;]*)(?P<off_end>;)",
            re.IGNORECASE,
        )

        new_parts: list[str] = []
        last_end = 0

        for m in combined_pat.finditer(content):
            new_parts.append(content[last_end: m.start()])

            off_val_str = m.group("off_val").strip()
            try:
                off_val = float(off_val_str)
            except ValueError:
                raise RuntimeError(
                    f"Cannot parse #OFFSET value '{off_val_str}' in '{ssc_path}'"
                )

            if m.group("so_line") is not None:
                # #SOURCEOFFSET already present -- use it as the immutable base
                so_val_str = m.group("so_val").strip()
                try:
                    base_val = float(so_val_str)
                except ValueError:
                    raise RuntimeError(
                        f"Cannot parse #SOURCEOFFSET value '{so_val_str}' "
                        f"in '{ssc_path}'"
                    )
                new_val = base_val + offset_delta
                # Keep #SOURCEOFFSET line verbatim, rewrite #OFFSET
                new_parts.append(m.group("so_line"))
                new_parts.append(
                    f"{m.group('off_tag')}{new_val:.6f}{m.group('off_end')}"
                )
                print(
                    f"  [patch] #OFFSET {base_val:.6f} + {offset_delta:+.6f} "
                    f"= {new_val:.6f} (base from existing #SOURCEOFFSET)"
                )
            else:
                # No #SOURCEOFFSET yet -- copy current #OFFSET value as the base
                new_val = off_val + offset_delta
                new_parts.append(f"#SOURCEOFFSET:{off_val_str};\n")
                new_parts.append(
                    f"{m.group('off_tag')}{new_val:.6f}{m.group('off_end')}"
                )
                print(
                    f"  [patch] added #SOURCEOFFSET ({off_val_str}), "
                    f"#OFFSET -> {new_val:.6f} (delta {offset_delta:+.6f})"
                )

            changed = True
            last_end = m.end()

        new_parts.append(content[last_end:])
        content = "".join(new_parts)

    # --- 3. Write back --------------------------------------------------------
    if changed:
        ssc_path.write_text(content, encoding="utf-8")
        print(f"  [saved] {ssc_path.name}")

    # --- 4. Verify asset files ------------------------------------------------
    # Done after writing so a missing asset never blocks metadata patches.
    verify_asset_fields(ssc_path, content)


# ---------------------------------------------------------------------------
# Main processing loop
# ---------------------------------------------------------------------------

def process_folder(folder: Path, offset_delta: float | None) -> None:
    print(f"\n[folder] {folder}")

    # Step 1: delete *.old files
    delete_old_files(folder)

    # Step 2: resolve duplicate chart files
    deduplicate_chart_files(folder)

    # Step 3: patch every remaining .ssc file
    for ssc_file in sorted(folder.glob("*.ssc")):
        print(f"  [processing] {ssc_file.name}")
        patch_ssc_file(ssc_file, offset_delta)


def main():
    args = parse_args()
    root = Path(args.source).resolve()

    if not root.is_dir():
        print(f"ERROR: '{root}' is not a directory.", file=sys.stderr)
        sys.exit(1)

    song_folders = find_song_folders(root)
    if not song_folders:
        print("No song folders found.")
        return

    print(f"Found {len(song_folders)} song folder(s) under '{root}'.")

    errors = []
    for folder in song_folders:
        try:
            process_folder(folder, args.offset)
        except RuntimeError as exc:
            errors.append(str(exc))
            print(f"  [ERROR] {exc}", file=sys.stderr)

    if errors:
        print(
            f"\n{len(errors)} error(s) encountered during processing.",
            file=sys.stderr,
        )
        sys.exit(1)
    else:
        print("\nDone.")


if __name__ == "__main__":
    main()
