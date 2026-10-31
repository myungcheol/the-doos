#!/usr/bin/env python3
"""Export approved pages to data/exports/approved.jsonl.

Only pages whose review status is `approved` are exported. The output is the
durable, tracked dataset; raw AI output in data/parsed/ and review notes in
data/review/status.json stay local.

Usage:
    python3 scripts/export_approved.py
    python3 scripts/export_approved.py --check
    python3 scripts/export_approved.py --out data/exports/approved.jsonl

Important: this script does NOT mask personal data. Approve pages only after
the masking policy is settled, or treat the export as internal until then.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from common import (
    ROOT,
    atomic_write_text,
    load_json,
    load_manifest,
    load_review_status,
    page_key,
    parsed_path,
)
from validate_page import validate

DEFAULT_OUT = ROOT / "data" / "exports" / "approved.jsonl"


def display_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def needs_human_count(parsed: dict) -> int:
    count = 0
    for person in parsed.get("subjects") or []:
        if isinstance(person, dict) and person.get("needs_human"):
            count += 1
    for entry in parsed.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("needs_human"):
            count += 1
        person = entry.get("person")
        if isinstance(person, dict) and person.get("needs_human"):
            count += 1
    return count


def build_records(status: str, section: str | None) -> tuple[list[dict], list[str], list[str]]:
    statuses = load_review_status()
    records: list[dict] = []
    errors: list[str] = []
    warnings: list[str] = []

    for row in load_manifest(section):
        section_name = row["section"]
        page_no = row["printed_page_no"]
        if row["page_type"] == "missing":
            continue
        review = statuses.get(page_key(section_name, page_no))
        if not review or review.get("status") != status:
            continue

        path = parsed_path(section_name, page_no)
        parsed = load_json(path)
        if not isinstance(parsed, dict):
            errors.append(f"{section_name} {page_no}: approved인데 {display_path(path)}가 없습니다.")
            continue

        validation_errors, validation_warnings = validate(parsed, section_name, page_no)
        if validation_errors:
            errors.append(f"{section_name} {page_no}: 검증 오류 {len(validation_errors)}건")
            continue
        for message in validation_warnings:
            warnings.append(f"{section_name} {page_no}: {message}")

        human = needs_human_count(parsed)
        if human:
            warnings.append(f"{section_name} {page_no}: needs_human {human}건 (승인 상태지만 미확정 항목이 있음)")

        records.append(
            {
                "section": section_name,
                "printed_page_no": page_no,
                "review": {
                    "status": review.get("status"),
                    "note": review.get("note", ""),
                    "updated_at": review.get("updated_at"),
                },
                "needs_human": human,
                "parsed": parsed,
            }
        )

    return records, errors, warnings


def render(records: list[dict]) -> str:
    return "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", default="approved", help="내보낼 검수 상태 (기본 approved)")
    parser.add_argument("--section", choices=["frontmatter", "genealogy"])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--check", action="store_true", help="export 파일이 최신인지만 검사")
    parser.add_argument("--allow-empty", action="store_true", help="승인 페이지가 0개여도 빈 파일을 쓴다")
    args = parser.parse_args()

    records, errors, warnings = build_records(args.status, args.section)
    if errors:
        print("export 중단: 승인 데이터가 일관되지 않습니다.", file=sys.stderr)
        for message in errors:
            print(f"  - {message}", file=sys.stderr)
        return 1
    for message in warnings:
        print(f"  ! {message}", file=sys.stderr)

    if not records and not args.allow_empty:
        print(
            f"{args.status} 상태의 페이지가 없습니다. 검수 도구에서 승인한 뒤 다시 실행하세요. "
            "(빈 파일을 만들려면 --allow-empty)",
            file=sys.stderr,
        )
        return 1

    content = render(records)
    out = args.out if args.out.is_absolute() else ROOT / args.out
    existing = out.read_text(encoding="utf-8") if out.exists() else None

    if args.check:
        if existing == content:
            print(f"{display_path(out)}: up to date ({len(records)} pages)")
            return 0
        print(
            f"{display_path(out)}가 최신이 아닙니다. `python3 scripts/export_approved.py`를 실행하세요.",
            file=sys.stderr,
        )
        return 1

    if existing != content:
        atomic_write_text(out, content)
        print(f"wrote {display_path(out)}: {len(records)} pages")
    else:
        print(f"{display_path(out)}: unchanged ({len(records)} pages)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
