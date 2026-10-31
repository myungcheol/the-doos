#!/usr/bin/env python3
"""Copy the STATUS.md summary into README.md.

STATUS.md is the source of truth for progress. README.md contains only a
generated summary between two markers, so the two cannot drift silently.

Usage:
    python3 scripts/sync_status.py          # update README.md
    python3 scripts/sync_status.py --check  # fail if README.md is stale
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATUS = ROOT / "STATUS.md"
README = ROOT / "README.md"
BEGIN = "<!-- STATUS:BEGIN -->"
END = "<!-- STATUS:END -->"


def extract_summary(status_text: str) -> str:
    start = status_text.find("## 1. 요약")
    if start < 0:
        raise ValueError("STATUS.md에서 '## 1. 요약'을 찾지 못했습니다.")
    finish = status_text.find("\n---", start)
    if finish < 0:
        raise ValueError("STATUS.md 요약 섹션의 끝을 찾지 못했습니다.")
    summary = status_text[start:finish].strip()
    summary = summary.removeprefix("## 1. 요약").strip()

    last = re.search(r"^> 마지막 갱신:.*$", status_text, re.MULTILINE)
    header = (
        "> 이 표는 `STATUS.md`에서 자동 생성됩니다. 직접 수정하지 마세요.\n>\n"
        + (last.group(0) + "\n\n" if last else "")
    )
    return header + summary


def render(readme_text: str, summary: str) -> str:
    pattern = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.DOTALL)
    if not pattern.search(readme_text):
        raise ValueError(f"README.md에 {BEGIN} / {END} 마커가 없습니다.")
    block = f"{BEGIN}\n{summary}\n{END}"
    return pattern.sub(lambda _: block, readme_text, count=1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="README.md가 최신인지만 검사")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    status_text = STATUS.read_text(encoding="utf-8")
    readme_text = README.read_text(encoding="utf-8")
    updated = render(readme_text, extract_summary(status_text))

    if updated == readme_text:
        if not args.quiet:
            print("README.md: already in sync")
        return 0

    if args.check:
        print(
            "README.md의 진행 상황 요약이 STATUS.md와 다릅니다. "
            "`python3 scripts/sync_status.py`를 실행하세요.",
            file=sys.stderr,
        )
        return 1

    README.write_text(updated, encoding="utf-8")
    if not args.quiet:
        print("README.md: status summary updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
