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
    python3 scripts/ocr.py --section genealogy --page 25 --format tsv
    python3 scripts/ocr.py --section genealogy --page 25 --format tsv --direction ltr
    python3 scripts/ocr.py --section genealogy --page 25 --format tsv --language chi_tra
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from common import ROOT, find_row, load_manifest, ocr_path, ocr_tsv_path, resolve_image

TSV_HEADER = [
    "level",
    "page_num",
    "block_num",
    "par_num",
    "line_num",
    "word_num",
    "left",
    "top",
    "width",
    "height",
    "conf",
    "text",
]


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


def run_tesseract(binary: str, language: str, psm: int, image: Path, fmt: str) -> str:
    command = [binary, str(image), "stdout", "-l", language, "--psm", str(psm)]
    if fmt == "tsv":
        command.append("tsv")
    else:
        command += ["-c", "preserve_interword_spaces=1"]
    result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        print(f"FAIL {image}: {result.stderr.strip()[:200]}", file=sys.stderr)
        raise RuntimeError(f"tesseract 실패: {result.stderr.strip()[:200]}")
    return result.stdout


def tsv_records(stdout: str) -> list[dict]:
    lines = stdout.splitlines()
    if not lines or lines[0].split("\t") != TSV_HEADER:
        raise ValueError("Tesseract TSV 헤더를 찾지 못했습니다.")
    records: list[dict] = []
    for line in lines[1:]:
        fields = line.split("\t")
        if len(fields) != len(TSV_HEADER):
            continue
        record = dict(zip(TSV_HEADER, fields))
        if record.get("level") == "4" and record.get("text", "").strip():
            records.append(record)
    return records


def reading_lines(stdout: str, rtl: bool) -> list[dict]:
    """Tesseract TSV(단어 좌표 포함)를 읽기 순서(단 위→아래, 단 안은 오른쪽→왼쪽)로 묶는다."""
    grouped: dict[tuple[str, str, str], list[dict]] = {}
    order: list[tuple[str, str, str]] = []
    for record in tsv_records(stdout):
        key = (record["block_num"], record["par_num"], record["line_num"])
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(
            {
                "text": record["text"].strip(),
                "left": float(record["left"]),
                "top": float(record["top"]),
                "width": float(record["width"]),
                "height": float(record["height"]),
                "conf": float(record["conf"]) if record.get("conf") else 0.0,
            }
        )
    lines: list[dict] = []
    for key in order:
        words = sorted(grouped[key], key=lambda word: word["left"], reverse=rtl)
        top = min(word["top"] for word in words)
        lines.append(
            {
                "text": " ".join(word["text"] for word in words),
                "top": top,
                "left": min(word["left"] for word in words),
                "right": max(word["left"] + word["width"] for word in words),
                "height": max(word["top"] + word["height"] for word in words) - top,
                "words": words,
            }
        )
    lines.sort(key=lambda line: (line["top"], line["left"]))
    return lines


def lines_to_text(lines: list[dict]) -> str:
    return "\n".join(line["text"] for line in lines)


def ocr_one(
    binary: str,
    language: str,
    psm: int,
    section: str,
    page_no: int,
    force: bool,
    fmt: str,
    rtl: bool,
) -> bool:
    destination = ocr_path(section, page_no)
    tsv_destination = ocr_tsv_path(section, page_no)
    skip_target = tsv_destination if fmt == "tsv" else destination
    if skip_target.exists() and not force:
        print(f"SKIP {section} {page_no}: {skip_target.relative_to(ROOT)}")
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
    try:
        raw = run_tesseract(binary, language, psm, image, fmt)
    except RuntimeError as exc:
        print(f"FAIL {section} {page_no}: {exc}", file=sys.stderr)
        return False
    if fmt == "tsv":
        lines = reading_lines(raw, rtl=rtl)
        destination.write_text(lines_to_text(lines) + "\n", encoding="utf-8")
        tsv_destination.write_text(raw, encoding="utf-8")
        print(
            f"OCR  {section} {page_no}: txt={destination.relative_to(ROOT)} tsv={tsv_destination.relative_to(ROOT)} ({len(lines)} lines)"
        )
    else:
        destination.write_text(raw, encoding="utf-8")
        print(f"OCR  {section} {page_no}: {destination.relative_to(ROOT)} ({len(raw)} chars)")
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
    parser.add_argument("--format", choices=["txt", "tsv"], default="txt", help="출력 형식 (기본 txt, tsv는 단어 좌표 포함)")
    parser.add_argument("--direction", choices=["ltr", "rtl"], default="rtl", help="단 안 읽기 방향 (기본 rtl: 오른쪽→왼쪽)")
    parser.add_argument("--language", default=None, help="Tesseract language (기본: 자동 선택 kor+chi_tra/kor/chi_tra/en). 한자 전용 스캔이면 chi_tra 지정")
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
    language = args.language or pick_language(languages)
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
        if ocr_one(
            binary,
            language,
            args.psm,
            args.section,
            row["printed_page_no"],
            args.force,
            args.format,
            args.direction == "rtl",
        ):
            done += 1
    print(f"완료: {done}면 OCR")
    return 0


if __name__ == "__main__":
    sys.exit(main())
