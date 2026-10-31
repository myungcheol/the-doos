#!/usr/bin/env python3
"""Create data/pages/ paths used by the app and the AI pipeline.

By default this makes relative symlinks to scan/ (the originals are never
modified). Use --copy to copy bytes instead.

Usage:
    python3 scripts/link_pages.py
    python3 scripts/link_pages.py --copy --force
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from common import ROOT, load_manifest


def cover_rows() -> list[dict]:
    import csv

    path = ROOT / "data" / "manifests" / "covers.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def make_link(source: Path, target: Path, copy: bool, force: bool) -> str:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        if not force:
            return "skip"
        target.unlink()
    if copy:
        shutil.copy2(source, target)
        return "copy"
    relative = os.path.relpath(source, target.parent)
    target.symlink_to(relative)
    return "link"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--copy", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    counts = {"link": 0, "copy": 0, "skip": 0, "missing": 0}
    for row in load_manifest():
        if row["page_type"] == "missing":
            continue
        source = ROOT / row["source_path"]
        target = ROOT / row["normalized_path"]
        if not source.exists():
            counts["missing"] += 1
            continue
        counts[make_link(source, target, args.copy, args.force)] += 1

    for row in cover_rows():
        source = ROOT / row["source_path"]
        target = ROOT / row["normalized_path"]
        if source.exists():
            counts[make_link(source, target, args.copy, args.force)] += 1

    print(
        "data/pages: "
        + ", ".join(f"{key}={value}" for key, value in counts.items())
        + (" (복사)" if args.copy else " (symlink)")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
