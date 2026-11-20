"""Convert the saved name-Hanja HTML table into deterministic JSON data."""

from __future__ import annotations

import argparse
import hashlib
import json
import unicodedata
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).parents[1]
DEFAULT_SOURCE = ROOT / "docs/research/인명용한자.html"
DEFAULT_OUTPUT = ROOT / "data/name-readings.json"


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag == "td" and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self._cell is not None and self._row is not None:
            self._row.append("".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None


def _hanja(text: str) -> Iterable[str]:
    for char in text:
        if char in " -()":
            continue
        if "CJK" in unicodedata.name(char, "") or char in "々〆〇":
            yield char


def convert(source: Path = DEFAULT_SOURCE) -> dict:
    source_bytes = source.read_bytes()
    parser = _TableParser()
    parser.feed(source_bytes.decode("utf-8"))
    characters: dict[str, list[dict]] = defaultdict(list)
    row_count = 0
    for row in parser.rows:
        if len(row) != 4 or row[0] in {"", "한글"} or len(row[0]) > 3:
            continue
        row_count += 1
        for column, kind in ((row[1], "education"), (row[2], "name"), (row[3], "variant")):
            for char in _hanja(column):
                entry = next(
                    (candidate for candidate in characters[char] if candidate["reading"] == row[0]),
                    None,
                )
                if entry is None:
                    entry = {"reading": row[0], "kinds": []}
                    characters[char].append(entry)
                if kind not in entry["kinds"]:
                    entry["kinds"].append(kind)
    if not characters:
        raise ValueError("독음 행을 찾지 못했습니다")
    ordered_characters = {char: characters[char] for char in sorted(characters)}
    return {
        "metadata": {
            "format_version": 1,
            "source_file": "docs/research/인명용한자.html",
            "source_url": "https://namu.wiki/w/인명용%20한자",
            "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
            "source_license": "CC BY-NC-SA 2.0 KR",
            "source_license_url": "https://creativecommons.org/licenses/by-nc-sa/2.0/kr/",
            "transformation": "HTML 음별 표를 한자별 독음 후보로 역색인",
            "source_row_count": row_count,
            "character_count": len(ordered_characters),
            "candidate_count": sum(len(entries) for entries in ordered_characters.values()),
        },
        "characters": ordered_characters,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="인명용 한자 HTML 표를 JSON으로 변환합니다.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(convert(args.source), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
