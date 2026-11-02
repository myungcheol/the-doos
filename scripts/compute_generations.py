#!/usr/bin/env python3
"""Compute absolute generation numbers from father links in parsed pages.

The book rarely prints an absolute `世` number, but every person can point to
their father through `person.father`.  This script resolves those links across
pages and walks the resulting chain once, at import time, to obtain
`generation_no`.  The result is written to `data/exports/generations.jsonl`
so that `people.generation_no` can be loaded without a recursive query at
runtime.

Usage:
    python3 scripts/compute_generations.py
    python3 scripts/compute_generations.py --out /tmp/opencode/generations.jsonl
    python3 scripts/compute_generations.py --stdout
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common import ROOT, PARSED_DIR


def load_pages() -> list[dict]:
    pages: list[dict] = []
    for path in sorted(PARSED_DIR.rglob("*.json")):
        if path.name.endswith(".meta.json"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict) or not isinstance(data.get("page"), dict):
            continue
        pages.append({"path": path, "data": data})
    return pages


def person_key(section: str, page_no: int, row: int, column: int) -> tuple:
    return (section, page_no, row, column)


def collect_people(pages: list[dict]) -> dict[tuple, dict]:
    people: dict[tuple, dict] = {}
    for item in pages:
        data = item["data"]
        page = data["page"]
        section = page["section"]
        page_no = page["printed_page_no"]
        for subject in data.get("subjects") or []:
            if not isinstance(subject, dict):
                continue
            row, column = subject.get("row"), subject.get("column")
            if not (isinstance(row, int) and isinstance(column, int)):
                continue
            key = person_key(section, page_no, row, column)
            people[key] = {
                "key": key,
                "section": section,
                "page_no": page_no,
                "row": row,
                "column": column,
                "as_printed": subject.get("as_printed"),
                "name_hanja": subject.get("name_hanja"),
                "printed_generation": subject.get("generation_no"),
                "father": subject.get("father"),
            }
        for entry in data.get("entries") or []:
            if not isinstance(entry, dict):
                continue
            person = entry.get("person")
            if not isinstance(person, dict):
                continue
            row, column = entry.get("row"), entry.get("column")
            if not (isinstance(row, int) and isinstance(column, int)):
                continue
            key = person_key(section, page_no, row, column)
            people[key] = {
                "key": key,
                "section": section,
                "page_no": page_no,
                "row": row,
                "column": column,
                "as_printed": person.get("as_printed"),
                "name_hanja": person.get("name_hanja"),
                "printed_generation": person.get("generation_no"),
                "father": person.get("father"),
            }
    return people


def resolve_father(person: dict, people: dict[tuple, dict]) -> tuple | None:
    father = person.get("father")
    if not isinstance(father, dict):
        return None
    row, column = father.get("row"), father.get("column")
    section, page_no = person["section"], person["page_no"]
    if isinstance(row, int) and isinstance(column, int):
        key = (section, page_no, row, column)
        if key in people:
            return key
    page_ref = father.get("page_ref")
    if isinstance(page_ref, dict):
        target_section = page_ref.get("target_section") or section
        target_page_no = page_ref.get("target_page_no")
        name = father.get("as_printed")
        if isinstance(target_page_no, int):
            for key, other in people.items():
                if (
                    other["section"] == target_section
                    and other["page_no"] == target_page_no
                    and other.get("as_printed") == name
                ):
                    return key
    return None


def compute(people: dict[tuple, dict]) -> dict[tuple, int | None]:
    # resolve father keys
    father_of: dict[tuple, tuple | None] = {}
    for key, person in people.items():
        father_of[key] = resolve_father(person, people)

    # detect cycles
    for start in people:
        seen: set[tuple] = set()
        cur = start
        while cur is not None:
            if cur in seen:
                print(f"cycle detected at {start}")
                break
            seen.add(cur)
            cur = father_of.get(cur)

    # roots: people with no father
    roots = [k for k, v in father_of.items() if v is None]
    generation: dict[tuple, int | None] = {}
    for root in roots:
        printed = people[root].get("printed_generation")
        generation[root] = printed if isinstance(printed, int) else 1

    # propagate (topological: keep iterating until no change)
    changed = True
    while changed:
        changed = False
        for key, father in father_of.items():
            if key in generation:
                continue
            if father is not None and father in generation and generation[father] is not None:
                generation[key] = generation[father] + 1
                changed = True

    for key in people:
        generation.setdefault(key, None)
    return generation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "exports" / "generations.jsonl")
    parser.add_argument("--stdout", action="store_true")
    args = parser.parse_args()

    pages = load_pages()
    people = collect_people(pages)
    generation = compute(people)

    records = []
    for key in sorted(people):
        person = people[key]
        father_key = None
        # recompute father key for output
        fk = resolve_father(person, people)
        if fk is not None:
            father_key = list(fk)
        records.append(
            {
                "section": person["section"],
                "printed_page_no": person["page_no"],
                "row": person["row"],
                "column": person["column"],
                "as_printed": person["as_printed"],
                "name_hanja": person["name_hanja"],
                "father": father_key,
                "printed_generation": person["printed_generation"],
                "generation_no": generation.get(key),
            }
        )

    unknown = sum(1 for r in records if r["generation_no"] is None)
    print(f"people: {len(records)}, roots: {sum(1 for r in records if r['father'] is None)}, unknown generations: {unknown}")

    if args.stdout:
        for record in records:
            print(json.dumps(record, ensure_ascii=False))
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
