#!/usr/bin/env python3
"""Build the AI prompt for one page.

The reading rules are extracted from docs/02-ai-parsing-guide.ko.md §2 at
runtime, so that document stays the single source of truth. The JSON contract
is schema/page.schema.json.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUIDE = ROOT / "docs" / "02-ai-parsing-guide.ko.md"
SCHEMA = ROOT / "schema" / "page.schema.json"


def _section(text: str, start: str, end: str) -> str:
    begin = text.find(start)
    if begin < 0:
        raise ValueError(f"가이드에서 '{start}'를 찾지 못했습니다.")
    finish = text.find(end, begin)
    if finish < 0:
        raise ValueError(f"가이드에서 '{end}'를 찾지 못했습니다.")
    return text[begin:finish].strip()


def load_rules() -> str:
    text = GUIDE.read_text(encoding="utf-8")
    return _section(text, "### 2.1 역할", "### 2.3 출력 형식")


def load_schema() -> dict:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def schema_text() -> str:
    return json.dumps(load_schema(), ensure_ascii=False, indent=2)


def build_messages(
    *,
    section: str,
    page_no: int,
    page_type_hint: str,
    width: int | None,
    height: int | None,
    image_path: str,
    ocr_text: str | None = None,
    notes: str | None = None,
) -> list[dict]:
    rules = load_rules()
    system = (
        rules
        + "\n\n추가 출력 규칙: JSON 객체 하나만 출력한다. 코드펜스·설명·인사말을 붙이지 않는다. "
        "확실하지 않은 값은 null 또는 needs_human=true로 둔다."
    )
    user = (
        "다음 페이지를 판독해 아래 JSON Schema에 맞는 JSON으로 출력하라.\n\n"
        f"section: {section}\n"
        f"printed_page_no: {page_no}\n"
        f"page_type_hint: {page_type_hint}\n"
        f"image_width: {width if width is not None else 'unknown'}\n"
        f"image_height: {height if height is not None else 'unknown'}\n"
    )
    if notes:
        user += f"manifest_notes: {notes}\n"
    user += "\nJSON Schema:\n```json\n" + schema_text() + "\n```\n"
    if ocr_text:
        user += (
            "\n아래 OCR 텍스트는 보조 자료다. 이미지와 다르면 이미지를 우선한다. "
            "OCR에 없는 글자를 추측으로 채우지 않는다.\n"
            "```text\n" + ocr_text.strip()[:20000] + "\n```\n"
        )
    user += f"\n이미지: {image_path}\n"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_prompt_text(**kwargs) -> str:
    messages = build_messages(**kwargs)
    return "\n\n".join(f"[{message['role']}]\n{message['content']}" for message in messages)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--section", default="genealogy", choices=["frontmatter", "genealogy"])
    parser.add_argument("--page", type=int, default=25)
    parser.add_argument("--type", default="genealogy")
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    parser.add_argument("--image", default="data/pages/genealogy/0025.jpg")
    args = parser.parse_args()
    print(
        build_prompt_text(
            section=args.section,
            page_no=args.page,
            page_type_hint=args.type,
            width=args.width,
            height=args.height,
            image_path=args.image,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
