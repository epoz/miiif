"""Command line script to populate the IIIF image lookup database.

Scans the image directories given on the command line for image files --
recursively, including subdirectories -- and (Re)builds the SQLite lookup
database that maps image identifiers to file paths.
"""

import argparse
import os
import sqlite3
from pathlib import Path

from .image_service import IMAGE_SUFFIXES

LOOKUP_SCHEMA = """
CREATE TABLE IF NOT EXISTS image_map (
    identifier TEXT NOT NULL,
    path TEXT NOT NULL,
    UNIQUE (identifier, path)
)
"""


def populate(directories, db_path) -> int:
    """(Re)build the lookup database from the given image directories.

    Walks each directory recursively and indexes every supported image file,
    using its filename (without directories) as the image identifier and its
    full path as the file location.

    Returns:
        The number of indexed images.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(LOOKUP_SCHEMA)
        entries = []
        for directory in directories:
            for root, _dirs, files in os.walk(directory):
                for name in sorted(files):
                    path = Path(root) / name
                    if path.suffix.lower().lstrip(".") not in IMAGE_SUFFIXES:
                        continue
                    entries.append((path.name, str(path)))
        conn.execute("DELETE FROM image_map")
        conn.executemany(
            "INSERT OR IGNORE INTO image_map (identifier, path) VALUES (?, ?)",
            entries,
        )
        conn.commit()
        return len(entries)
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="iiif-populate",
        description=(
            "Populate the IIIF image lookup database from the given image directories."
        ),
    )
    parser.add_argument(
        "--dirs",
        nargs="+",
        required=True,
        help="Image directories to scan for images.",
    )
    parser.add_argument(
        "--db",
        required=True,
        help="Path to the SQLite lookup database.",
    )
    args = parser.parse_args(argv)
    directories = args.dirs
    db_path = Path(args.db)
    count = populate(directories, db_path)
    print(f"Indexed {count} image(s) into {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
