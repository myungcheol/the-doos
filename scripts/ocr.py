#!/usr/bin/env python3
"""Optional local OCR sidecar (Tesseract).

The primary reader is the vision model. This script only produces a text
sidecar that the parser may pass as a hint. If Tesseract is not installed the
pipeline still works in vision-only mode.

Setup (Ubuntu):
    sudo apt install tesseract-ocr tesseract-ocr-kor tesseract-ocr-chi-tra

Usage:
    python3 scripts/ocr.py --section genealogy --from 1 --to 30
    python3 scripts/ocr.py --section genealogy --page 25 --force
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from common import ROOT, find_row, load_manifest, ocr_path, resolve_image


def available_languages(binary: str) -> set[str]:
    try:
        result = subprocess.run(
            [binary, "--list-langs"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return set()
    return {
        line.strip()
        for line in (result.stdout + result.stderr).splitlines()
        if line.strip() and " " not in line.strip() and "List" not in line
    }


def pick_language(languages: set[str]) -> str:
    if {"kor", "chi_tra"} <= languages:
        return "kor+chi_tra"
    if "kor" in languages:
        return "kor"
    if "chi_tra" in languages:
        return "chi_tra"
    return "eng"


def ocr_one(binary: str, language: str, psm: int, section: str, page_no: int, force: bool) -> bool:
    destination = ocr_path(section, page_no)
    if destination.exists() and not force:
        print(f"SKIP {section} {page_no}: {destination.relative_to(ROOT)}")
        return False
    row = find_row(section, page_no)
    if row is None or row["page_type"] == "missing":
        print(f"SKIP {section} {page_no}: 미수록")
        return False
    image = resolve_image(row)
    if image is None:
        print(f"SKIP {section} {page_no}: 이미지 없음")
        return False

    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        binary,
        str(image),
        "stdout",
        "-l",
        language,
        "--psm",
        str(psm),
        "-c",
        "preserve_interword_spaces=1",
    ]
    result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        print(f"FAIL {section} {page_no}: {result.stderr.strip()[:200]}")
        return False
    destination.write_text(result.stdout, encoding="utf-8")
    print(f"OCR  {section} {page_no}: {destination.relative_to(ROOT)} ({len(result.stdout)} chars)")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--section", required=True, choices=["frontmatter", "genealogy"])
    parser.add_argument("--page", type=int)
    parser.add_argument("--from", dest="start", type=int)
    parser.add_argument("--to", dest="end", type=int)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--psm", type=int, default=6, help="Tesseract page segmentation mode (기본 6)")
    args = parser.parse_args()

    binary = shutil.which("tesseract")
    if not binary:
        print(
            "Tesseract가 설치되어 있지 않습니다.\n"
            "  sudo apt install tesseract-ocr tesseract-ocr-kor tesseract-ocr-chi-tra\n"
            "또는 OCR 없이 vision 전용으로 실행하세요 (scripts/parse_page.py).",
            file=sys.stderr,
        )
        return 2

    languages = available_languages(binary)
    language = pick_language(languages)
    print(f"tesseract: {binary}, language={language}, psm={args.psm}")

    if args.page:
        rows = [find_row(args.section, args.page)]
    else:
        rows = [
            row
            for row in load_manifest(args.section)
            if row["page_type"] != "missing"
            and (args.start is None or row["printed_page_no"] >= args.start)
            and (args.end is None or row["printed_page_no"] <= args.end)
        ]
    rows = [row for row in rows if row]
    if args.limit:
        rows = rows[: args.limit]

    done = 0
    for row in rows:
        if ocr_one(binary, language, args.psm, args.section, row["printed_page_no"], args.force):
            done += 1
    print(f"완료: {done}면 OCR")
    return 0


if __name__ == "__main__":
    sys.exit(main())
