#!/usr/bin/env python3
"""Migrate legacy `raw_name` fields to `as_printed`.

This is a one-time helper for data created before the rename. It updates:
- data/parsed/**/*.json
- data/exports/approved.jsonl (if present)

Usage:
    python3 scripts/migrate_raw_name.py
    python3 scripts/migrate_raw_name.py --dry-run
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import ROOT, PARSED_DIR, atomic_write_text


def migrate_object(value: object) -> int:
    changed = 0
    if isinstance(value, dict):
        if "raw_name" in value and "as_printed" not in value:
            value["as_printed"] = value.pop("raw_name")
            changed += 1
        elif "raw_name" in value and "as_printed" in value:
            # Prefer the new field; remove the legacy duplicate.
            del value["raw_name"]
            changed += 1
        for child in value.values():
            changed += migrate_object(child)
    elif isinstance(value, list):
        for item in value:
            changed += migrate_object(item)
    return changed


def migrate_parsed() -> int:
    total = 0
    if not PARSED_DIR.exists():
        return total
    for path in sorted(PARSED_DIR.glob("**/*.json")):
        if path.name.endswith(".meta.json"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        changed = migrate_object(data)
        if changed:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            total += changed
    return total


def migrate_approved() -> int:
    path = ROOT / "data" / "exports" / "approved.jsonl"
    if not path.exists():
        return 0
    changed = 0
    lines = path.read_text(encoding="utf-8").splitlines()
    output = []
    for line in lines:
        if not line.strip():
            output.append(line)
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            output.append(line)
            continue
        changed += migrate_object(record)
        output.append(json.dumps(record, ensure_ascii=False))
    if changed:
        atomic_write_text(path, "\n".join(output) + ("\n" if output else ""))
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.dry_run:
        # Count without writing by operating on copies.
        import copy

        parsed_changed = 0
        if PARSED_DIR.exists():
            for path in sorted(PARSED_DIR.glob("**/*.json")):
                if path.name.endswith(".meta.json"):
                    continue
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                parsed_changed += migrate_object(copy.deepcopy(data))
        approved_changed = 0
        approved_path = ROOT / "data" / "exports" / "approved.jsonl"
        if approved_path.exists():
            for line in approved_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                approved_changed += migrate_object(copy.deepcopy(record))
        print(f"dry-run: parsed={parsed_changed}, approved={approved_changed}")
        return 0

    parsed_changed = migrate_parsed()
    approved_changed = migrate_approved()
    print(f"migrated: parsed={parsed_changed}, approved={approved_changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())