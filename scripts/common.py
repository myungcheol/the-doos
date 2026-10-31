#!/usr/bin/env python3
"""Shared helpers for the page pipeline and the admin server."""

from __future__ import annotations

import csv
import json
import os
import tempfile
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "data" / "manifests" / "pages.csv"
PARSED_DIR = ROOT / "data" / "parsed"
OCR_DIR = ROOT / "data" / "ocr"
PROMPT_DIR = ROOT / "data" / "prompts"
REVIEW_STATUS = ROOT / "data" / "review" / "status.json"

INT_FIELDS = {"printed_page_no", "scan_seq", "width", "height", "dpi"}


def load_manifest(section: str | None = None) -> list[dict]:
    if not MANIFEST.exists():
        raise FileNotFoundError(f"{MANIFEST}가 없습니다. 먼저 scripts/build_manifest.py를 실행하세요.")
    rows: list[dict] = []
    with MANIFEST.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            for field in INT_FIELDS:
                value = row.get(field)
                row[field] = int(value) if value not in (None, "") else None
            if section and row["section"] != section:
                continue
            rows.append(row)
    return rows


def find_row(section: str, page_no: int) -> dict | None:
    for row in load_manifest(section):
        if row["printed_page_no"] == page_no:
            return row
    return None


def page_key(section: str, page_no: int) -> str:
    return f"{section}:{page_no}"


def parsed_path(section: str, page_no: int) -> Path:
    return PARSED_DIR / section / f"{page_no:04d}.json"


def meta_path(section: str, page_no: int) -> Path:
    return PARSED_DIR / section / f"{page_no:04d}.meta.json"


def ocr_path(section: str, page_no: int) -> Path:
    return OCR_DIR / section / f"{page_no:04d}.txt"


def prompt_path(section: str, page_no: int) -> Path:
    return PROMPT_DIR / section / f"{page_no:04d}.txt"


def resolve_image(row: dict) -> Path | None:
    for key in ("normalized_path", "source_path"):
        value = row.get(key)
        if not value:
            continue
        path = ROOT / value
        if path.exists():
            return path
    return None


def load_json(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def atomic_write_json(path: Path, data: object) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def load_review_status() -> dict:
    data = load_json(REVIEW_STATUS)
    return data if isinstance(data, dict) else {}


def save_review_status(data: dict) -> None:
    atomic_write_json(REVIEW_STATUS, data)


def iter_parsed(section: str | None = None) -> Iterable[tuple[str, int, dict]]:
    base = PARSED_DIR if section is None else PARSED_DIR / section
    for path in sorted(base.glob("*/*.json") if section is None else base.glob("*.json")):
        if path.name.endswith(".meta.json"):
            continue
        if not path.stem.isdigit():
            continue
        data = load_json(path)
        if isinstance(data, dict):
            yield path.parent.name, int(path.stem), data
