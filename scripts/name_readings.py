"""Load and query deterministic Korean reading candidates for name Hanja.

The runtime source is generated JSON.  This module does not choose a correct
reading: it returns every candidate with provenance.
"""

from __future__ import annotations

import argparse
import json
import unicodedata
from pathlib import Path


DEFAULT_SOURCE = Path(__file__).parents[1] / "data/name-readings.json"


def build_index(source: Path = DEFAULT_SOURCE) -> dict[str, list[dict[str, str]]]:
    data = json.loads(source.read_text(encoding="utf-8"))
    if data.get("metadata", {}).get("format_version") != 1:
        raise ValueError("지원하지 않는 독음 사전 형식입니다")
    return {
        char: [dict(entry, source="local_name_hanja_table") for entry in entries]
        for char, entries in data["characters"].items()
    }


def _initial_sound_law(reading: str) -> str | None:
    """Return the standard word-initial 두음법칙 form, if it changes."""
    if len(reading) != 1 or not "가" <= reading <= "힣":
        return None
    offset = ord(reading) - ord("가")
    initial, medial, final = offset // 588, (offset % 588) // 28, offset % 28
    if initial == 5:  # ㄹ
        replacement = 11 if medial in {2, 3, 6, 7, 12, 17, 20} else 2
    elif initial == 2 and medial in {6, 12, 17, 20}:  # ㄴ + 여/요/유/이
        replacement = 11
    else:
        return None
    return chr(ord("가") + replacement * 588 + medial * 28 + final)


def lookup_character(
    char: str,
    index: dict[str, list[dict[str, str]]],
    *,
    at_name_start: bool = False,
) -> dict:
    if len(char) != 1:
        raise ValueError("한 글자만 조회할 수 있습니다")
    normalized = unicodedata.normalize("NFKC", char)
    lookup_char = normalized if normalized in index else char
    candidates = [dict(item) for item in index.get(lookup_char, [])]
    if at_name_start:
        for item in tuple(candidates):
            derived = _initial_sound_law(item["reading"])
            if derived and not any(candidate["reading"] == derived for candidate in candidates):
                candidates.append(
                    {
                        "reading": derived,
                        "source": "initial_sound_law",
                        "kinds": ["derived"],
                        "derived_from": item["reading"],
                    }
                )
    return {
        "original": char,
        "lookup_character": lookup_char,
        "normalized_for_lookup": lookup_char != char,
        "status": "candidates" if candidates else "unregistered",
        "candidates": candidates,
        "confirmed_reading": None,
    }


def lookup_name(text: str, index: dict[str, list[dict[str, str]]]) -> dict:
    """Return per-character candidates without changing or resolving the name."""
    return {
        "original": text,
        "characters": [
            lookup_character(char, index, at_name_start=position == 0)
            for position, char in enumerate(text)
        ],
        "confirmed_reading": None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="인명 한자의 독음 후보를 조회합니다.")
    parser.add_argument("text", help="조회할 한자 이름")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="변환된 JSON 사전")
    args = parser.parse_args()
    print(json.dumps(lookup_name(args.text, build_index(args.source)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
