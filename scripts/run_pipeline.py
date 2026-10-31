#!/usr/bin/env python3
"""Batch driver for the page pipeline.

Stages:
    1. manifest  -> data/manifests/pages.csv   (scripts/build_manifest.py)
    2. ocr       -> data/ocr/...                (scripts/ocr.py, optional)
    3. parse     -> data/parsed/...             (scripts/parse_page.py)

Examples:
    python3 scripts/run_pipeline.py --section genealogy --from 1 --to 25 --dry-run
    python3 scripts/run_pipeline.py --section genealogy --from 1 --to 25 --ocr
    python3 scripts/run_pipeline.py --section genealogy --limit 10 --force
    python3 scripts/run_pipeline.py --report
"""

from __future__ import annotations

import argparse
import sys
import traceback

from common import load_json, load_manifest, parsed_path
from parse_page import parse_page


def selected_rows(section: str, start: int | None, end: int | None, page_type: str | None) -> list[dict]:
    rows = []
    for row in load_manifest(section):
        if row["page_type"] == "missing":
            continue
        if page_type and row["page_type"] != page_type:
            continue
        if start is not None and row["printed_page_no"] < start:
            continue
        if end is not None and row["printed_page_no"] > end:
            continue
        rows.append(row)
    return rows


def report(section: str | None) -> int:
    sections = [section] if section else ["frontmatter", "genealogy"]
    total_present = total_parsed = 0
    for name in sections:
        rows = [row for row in load_manifest(name) if row["page_type"] != "missing"]
        parsed = sum(1 for row in rows if parsed_path(name, row["printed_page_no"]).exists())
        pending = [row["printed_page_no"] for row in rows if not parsed_path(name, row["printed_page_no"]).exists()]
        print(f"{name}: {parsed}/{len(rows)} parsed")
        if pending:
            head = ", ".join(str(number) for number in pending[:30])
            print(f"  pending: {head}{' ...' if len(pending) > 30 else ''}")
        total_present += len(rows)
        total_parsed += parsed
    print(f"total: {total_parsed}/{total_present}")
    return 0 if total_parsed == total_present else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--section", choices=["frontmatter", "genealogy"])
    parser.add_argument("--from", dest="start", type=int)
    parser.add_argument("--to", dest="end", type=int)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--type", dest="page_type")
    parser.add_argument("--force", action="store_true", help="이미 파싱된 페이지도 다시 호출")
    parser.add_argument("--dry-run", action="store_true", help="프롬프트만 생성")
    parser.add_argument("--ocr", action="store_true", help="OCR sidecar를 프롬프트에 포함")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--report", action="store_true", help="진행률만 출력")
    args = parser.parse_args()

    if args.report:
        return report(args.section)
    if not args.section:
        parser.error("--section이 필요합니다. (--report는 예외)")

    rows = selected_rows(args.section, args.start, args.end, args.page_type)
    if not args.force:
        rows = [row for row in rows if not parsed_path(args.section, row["printed_page_no"]).exists()]
    if args.limit:
        rows = rows[: args.limit]

    print(f"대상: {len(rows)}면 ({args.section})")
    done = skipped = failed = 0
    for index, row in enumerate(rows, 1):
        page_no = row["printed_page_no"]
        print(f"[{index}/{len(rows)}] {args.section} {page_no} ({row['page_type']})", flush=True)
        try:
            result = parse_page(
                args.section,
                page_no,
                force=args.force,
                dry_run=args.dry_run,
                use_ocr=args.ocr,
            )
            if result is None and not args.dry_run:
                skipped += 1
            else:
                done += 1
        except SystemExit as exc:
            failed += 1
            print(f"  FAIL: {exc}", file=sys.stderr)
            if args.fail_fast:
                return 1
        except Exception:  # noqa: BLE001 - batch should continue
            failed += 1
            print(f"  FAIL: {args.section} {page_no}", file=sys.stderr)
            traceback.print_exc()
            if args.fail_fast:
                return 1

    print(f"완료: {done} / 건너뜀 {skipped} / 실패 {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
