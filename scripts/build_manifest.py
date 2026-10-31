#!/usr/bin/env python3
"""Build data/manifests/pages.csv from the scan folders.

The scan filenames are the printed page numbers (3-digit zero padded).
Pages that do not exist on disk are still emitted, marked page_type=missing,
so the manifest is a complete inventory of the printed book.

No third-party packages are required.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN = ROOT / "scan"
OUT = ROOT / "data" / "manifests" / "pages.csv"
COVERS_OUT = ROOT / "data" / "manifests" / "covers.csv"

FIELDS = [
    "section",
    "printed_page_no",
    "scan_seq",
    "source_path",
    "normalized_path",
    "sha256",
    "width",
    "height",
    "dpi",
    "page_type",
    "quality_flags",
    "notes",
]

FRONTMATTER_LAST = 93
GENEALOGY_LAST = 938

# page_type by printed page number. Anything not listed is "genealogy".
FRONTMATTER_TYPES = {
    **{n: "preface" for n in range(1, 47)},
    47: "index",
    **{n: "photo" for n in range(49, 63)},
    63: "generation_name_table",
    65: "index",
    66: "index",
}
GENEALOGY_TYPES = {
    932: "property",
    933: "property",
    936: "officers",
    937: "subscription",
    938: "colophon",
}

# Human notes for pages that need one.
FRONTMATTER_NOTES = {
    1: "世譜序",
    2: "서문",
    3: "서문",
    4: "杜陵序 追考",
    47: "目次(목차)",
    63: "行列名字例(항렬표)",
    65: "早見索引(조견색인)",
    66: "早見索引(조견색인)",
}
GENEALOGY_NOTES = {
    1: "1~6세 표. 단=세대 확인용",
    932: "宗中財產目錄",
    933: "宗中財產目錄",
    936: "刊行委員會 任員錄",
    937: "收單",
    938: "刊記(간기)",
}


def jpeg_info(path: Path) -> tuple[int | None, int | None, int | None]:
    """Return (width, height, dpi) from JPEG headers without Pillow."""
    width = height = None
    dpi = None
    with path.open("rb") as fh:
        if fh.read(2) != b"\xff\xd8":
            return None, None, None
        while True:
            byte = fh.read(1)
            if not byte:
                break
            if byte != b"\xff":
                continue
            marker = fh.read(1)
            while marker == b"\xff":  # fill bytes
                marker = fh.read(1)
            if not marker:
                break
            code = marker[0]
            if code in (0xD8, 0xD9) or 0xD0 <= code <= 0xD7 or code == 0x01:
                continue
            raw_len = fh.read(2)
            if len(raw_len) != 2:
                break
            seg_len = struct.unpack(">H", raw_len)[0]
            if seg_len < 2:
                break
            payload = fh.read(seg_len - 2)

            # APP0 / JFIF density
            if code == 0xE0 and payload.startswith(b"JFIF\x00") and len(payload) >= 12:
                units = payload[7]
                xden, yden = struct.unpack(">HH", payload[8:12])
                if units == 1 and xden:
                    dpi = xden
                elif units == 2 and xden:  # dots per cm
                    dpi = round(xden * 2.54)

            # SOF0..SOF15, except DHT/JPG/DAC
            if 0xC0 <= code <= 0xCF and code not in (0xC4, 0xC8, 0xCC):
                if len(payload) >= 5:
                    height, width = struct.unpack(">HH", payload[1:5])
                    break
    return width, height, dpi


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def existing_pages(section: str) -> dict[int, Path]:
    pages: dict[int, Path] = {}
    for path in sorted((SCAN / section).glob("*.jpg")):
        if not path.stem.isdigit():
            continue
        pages[int(path.stem)] = path
    return pages


def build_section(section: str, last: int, types: dict[int, str], notes: dict[int, str]) -> list[dict]:
    pages = existing_pages(section)
    rows: list[dict] = []
    scan_seq = 0
    for page_no in range(1, last + 1):
        path = pages.get(page_no)
        if path is None:
            rows.append(
                {
                    "section": section,
                    "printed_page_no": page_no,
                    "scan_seq": "",
                    "source_path": "",
                    "normalized_path": "",
                    "sha256": "",
                    "width": "",
                    "height": "",
                    "dpi": "",
                    "page_type": "missing",
                    "quality_flags": "missing",
                    "notes": f"MISSING: {section} {page_no}면 미수록",
                }
            )
            continue

        scan_seq += 1
        width, height, dpi = jpeg_info(path)
        rows.append(
            {
                "section": section,
                "printed_page_no": page_no,
                "scan_seq": scan_seq,
                "source_path": path.relative_to(ROOT).as_posix(),
                "normalized_path": f"data/pages/{section}/{page_no:04d}.jpg",
                "sha256": sha256(path),
                "width": width or "",
                "height": height or "",
                "dpi": dpi or "",
                "page_type": types.get(page_no, "genealogy" if section == "genealogy" else "preface"),
                "quality_flags": "",
                "notes": notes.get(page_no, ""),
            }
        )
    return rows


def build_covers() -> list[dict]:
    rows = []
    for key, filename in (("front", "앞표지.jpg"), ("back", "뒷표지.jpg")):
        path = SCAN / filename
        if not path.exists():
            continue
        width, height, dpi = jpeg_info(path)
        rows.append(
            {
                "cover": key,
                "source_path": path.relative_to(ROOT).as_posix(),
                "normalized_path": f"data/pages/covers/{key}.jpg",
                "sha256": sha256(path),
                "width": width or "",
                "height": height or "",
                "dpi": dpi or "",
            }
        )
    return rows


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--covers-out", type=Path, default=COVERS_OUT)
    args = parser.parse_args()

    rows = build_section("frontmatter", FRONTMATTER_LAST, FRONTMATTER_TYPES, FRONTMATTER_NOTES)
    rows += build_section("genealogy", GENEALOGY_LAST, GENEALOGY_TYPES, GENEALOGY_NOTES)
    write_csv(args.out, FIELDS, rows)
    write_csv(
        args.covers_out,
        ["cover", "source_path", "normalized_path", "sha256", "width", "height", "dpi"],
        build_covers(),
    )

    missing = sum(1 for row in rows if row["page_type"] == "missing")
    present = len(rows) - missing
    print(f"wrote {args.out}: {len(rows)} rows ({present} present, {missing} missing)")
    print(f"wrote {args.covers_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
