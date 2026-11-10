"""Conservative drafts of historical lunar birth/death dates.

The conversion uses sxtwl's Chinese astronomical calendar model.  The result
is a review draft, not a claim that a local historical calendar was identical.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import re

try:
    import sxtwl
except ImportError:  # The OCR CLI does not require review dependencies.
    sxtwl = None


@dataclass(frozen=True)
class Reign:
    country: str
    name: str
    aliases: tuple[str, ...]
    first_ce_year: int
    last_ce_year: int


# First regnal years, rather than accession years. Sources are listed in the
# README; restrict automatic lookup to entries whose year numbering was checked.
REIGNS = (
    Reign("고려", "태조 太祖", ("太祖", "태조"), 918, 943),
    Reign("고려", "혜종 惠宗", ("惠宗", "혜종"), 944, 945),
    Reign("고려", "정종 定宗", ("定宗",), 946, 949),
    Reign("고려", "광종 光宗", ("光宗", "광종"), 950, 975),
    Reign("고려", "경종 景宗", ("景宗", "경종"), 976, 981),
    Reign("고려", "성종 成宗", ("成宗", "성종"), 982, 997),
    Reign("고려", "목종 穆宗", ("穆宗", "목종"), 998, 1009),
    Reign("고려", "현종 顯宗", ("顯宗", "현종"), 1010, 1031),
    Reign("고려", "덕종 德宗", ("德宗", "덕종"), 1032, 1034),
    Reign("고려", "정종 靖宗", ("靖宗",), 1035, 1046),
    Reign("고려", "문종 文宗", ("文宗", "문종"), 1047, 1083),
    Reign("고려", "선종 宣宗", ("宣宗", "선종"), 1084, 1094),
    Reign("고려", "헌종 獻宗", ("獻宗", "헌종"), 1095, 1095),
    Reign("고려", "숙종 肅宗", ("肅宗", "숙종"), 1096, 1105),
    Reign("고려", "예종 睿宗", ("睿宗", "예종"), 1106, 1122),
    Reign("고려", "인종 仁宗", ("仁宗", "인종"), 1123, 1146),
    Reign("고려", "의종 毅宗", ("毅宗", "의종"), 1147, 1170),
    Reign("고려", "명종 明宗", ("明宗", "명종"), 1171, 1197),
    Reign("고려", "신종 神宗", ("神宗", "신종"), 1198, 1204),
    Reign("고려", "희종 熙宗", ("熙宗", "희종"), 1205, 1211),
    Reign("고려", "강종 康宗", ("康宗", "강종"), 1212, 1213),
    Reign("고려", "고종 高宗", ("高宗", "고종"), 1214, 1259),
    Reign("고려", "원종 元宗", ("元宗", "원종"), 1260, 1274),
    Reign("고려", "충렬왕 忠烈王", ("忠烈王", "충렬왕"), 1275, 1308),
    Reign("고려", "충선왕 忠宣王", ("忠宣王", "충선왕"), 1309, 1313),
    Reign("고려", "충숙왕 忠肅王", ("忠肅王", "충숙왕"), 1314, 1330),
    Reign("고려", "충혜왕 忠惠王", ("忠惠王", "충혜왕"), 1331, 1331),
    Reign("고려", "충목왕 忠穆王", ("忠穆王", "충목왕"), 1345, 1348),
    Reign("고려", "충정왕 忠定王", ("忠定王", "충정왕"), 1349, 1351),
    Reign("고려", "공민왕 恭愍王", ("恭愍王", "공민왕"), 1352, 1374),
    Reign("고려", "우왕 禑王", ("禑王", "우왕"), 1375, 1388),
    Reign("고려", "공양왕 恭讓王", ("恭讓王", "공양왕"), 1389, 1392),
    Reign("조선", "태조 太祖", ("太祖", "태조"), 1392, 1398),
    Reign("조선", "세종 世宗", ("世宗", "세종"), 1419, 1450),
    Reign("조선", "세조 世祖", ("世祖", "세조"), 1455, 1468),
    Reign("조선", "예종 睿宗", ("睿宗", "예종"), 1469, 1469),
    Reign("조선", "성종 成宗", ("成宗", "성종"), 1470, 1494),
    Reign("조선", "중종 中宗", ("中宗", "중종"), 1506, 1544),
    Reign("조선", "인조 仁祖", ("仁祖", "인조"), 1623, 1649),
    Reign("송", "개보 開寶", ("開寶", "开宝", "개보"), 968, 976),
    Reign("송", "순화 淳化", ("淳化", "순화"), 990, 994),
)

_DIGITS = {"零": 0, "〇": 0, "○": 0, "一": 1, "二": 2, "兩": 2, "两": 2,
           "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_NUM = r"[零〇○一二兩两三四五六七八九十廿卅正元初冬臘腊\d]+"
_GANJI = "甲乙丙丁戊己庚辛壬癸"
_ZHI = "子丑寅卯辰巳午未申酉戌亥"


def chinese_number(text: str) -> int | None:
    text = text.strip()
    if text in ("正", "元"):
        return 1
    if text == "冬":
        return 11
    if text in ("臘", "腊"):
        return 12
    if text.startswith("初"):
        return chinese_number(text[1:])
    if text.isdecimal():
        return int(text)
    if text.startswith("卅"):
        return 30 + (chinese_number(text[1:]) or 0)
    if text.startswith("廿"):
        return 20 + (chinese_number(text[1:]) or 0)
    if "十" in text:
        left, right = text.split("十", 1)
        tens = _DIGITS.get(left, 1) if left else 1
        units = chinese_number(right) if right else 0
        return tens * 10 + units if units is not None else None
    if text in _DIGITS:
        return _DIGITS[text]
    if text and all(char in _DIGITS for char in text):
        return int("".join(str(_DIGITS[char]) for char in text))
    return None


def find_reigns(text: str, country: str | None = None) -> list[Reign]:
    if country is None:
        if "高麗" in text or "고려" in text:
            country = "고려"
        elif "朝鮮" in text or "조선" in text:
            country = "조선"
    return [reign for reign in REIGNS if (country is None or reign.country == country)
            and any(alias in text for alias in reign.aliases)]


def resolve_regnal_year(reign: Reign, year: int) -> int:
    if year < 1 or reign.first_ce_year + year - 1 > reign.last_ce_year:
        raise ValueError("재위 연수 범위를 벗어납니다.")
    return reign.first_ce_year + year - 1


def _valid_lunar(year: int, month: int, day: int, leap: bool) -> date:
    if sxtwl is None:
        raise RuntimeError("양력 변환에는 sxtwl이 필요합니다. requirements-desktop.txt를 설치하세요.")
    if not (1 <= year <= 9998 and 1 <= month <= 12 and 1 <= day <= 30):
        raise ValueError("음력 연·월·일 범위를 확인하세요.")
    solar = sxtwl.fromLunar(year, month, day, leap)
    result = date(solar.getSolarYear(), solar.getSolarMonth(), solar.getSolarDay())
    reverse = sxtwl.fromSolar(result.year, result.month, result.day)
    if (reverse.getLunarYear(), reverse.getLunarMonth(), reverse.getLunarDay(),
            bool(reverse.isLunarLeap())) != (year, month, day, leap):
        raise ValueError("해당 음력 날짜가 존재하지 않습니다.")
    return result


def lunar_interval(year: int, month: int | None = None,
                   day: int | None = None, leap: bool = False) -> dict:
    """Return an inclusive proleptic Gregorian interval at source precision."""
    if day is not None and month is None:
        raise ValueError("일을 입력하려면 월이 필요합니다.")
    if leap and month is None:
        raise ValueError("윤달을 입력하려면 월이 필요합니다.")
    start = _valid_lunar(year, month or 1, day or 1, leap)
    if day is not None:
        end = start
        precision = "day"
    elif month is not None:
        last = 29 if _last_day(year, month, leap) == 29 else 30
        end = _valid_lunar(year, month, last, leap)
        precision = "month"
    else:
        end = _valid_lunar(year + 1, 1, 1, False) - timedelta(days=1)
        precision = "year"
    return {"start": start.isoformat(), "end": end.isoformat(),
            "precision": precision, "lunar": {"year": year, "month": month,
                                              "day": day, "leap_month": leap},
            "calendar_model": "sxtwl-2.0.7-chinese", "review_status": "needs_review"}


def _last_day(year: int, month: int, leap: bool) -> int:
    try:
        _valid_lunar(year, month, 30, leap)
        return 30
    except ValueError:
        _valid_lunar(year, month, 29, leap)
        return 29


def sexagenary_year(year: int) -> str:
    return _GANJI[(year - 4) % 10] + _ZHI[(year - 4) % 12]


def parse_date_parts(text: str, event: str | None = None) -> dict:
    """Preserve OCR date components, distinguishing observed and inferred ganji."""
    source = re.sub(r"\s+|/", "", text or "")
    if event == "birth":
        marker = re.search(r"生|誕", source)
    elif event == "death":
        marker = re.search(r"卒|歿|殁|薨|逝", source)
    else:
        marker = None
    if marker:
        source = source[:marker.start()]
    years = list(re.finditer(rf"({_NUM})年", source))
    year = years[0] if len(years) == 1 else None
    regnal_year = chinese_number(year.group(1)) if year else None
    reigns = find_reigns(source[:year.start()] if year else source)
    reign = reigns[0] if len(reigns) == 1 else None
    ce_year = None
    if reign and regnal_year:
        try:
            ce_year = resolve_regnal_year(reign, regnal_year)
        except ValueError:
            pass
    country = ("고려" if "高麗" in source or "고려" in source else
               "조선" if "朝鮮" in source or "조선" in source else
               reign.country if reign else None)
    rest = source[year.end():] if year else source
    ganji = re.search(rf"[{_GANJI}][{_ZHI}]?", rest)
    observed = ganji.group() if ganji else None
    expected = sexagenary_year(ce_year) if ce_year else None
    if observed and len(observed) == 2:
        sexagenary = observed
        origin = "ocr"
    elif observed and expected and expected.startswith(observed):
        sexagenary = expected
        origin = "inferred_from_regnal_year"
    else:
        sexagenary = None
        origin = "unresolved" if observed else None
    month_matches = list(re.finditer(rf"(閏|闰)?({_NUM})月", rest))
    day_matches = list(re.finditer(rf"({_NUM})日", rest))
    month_match = month_matches[0] if len(month_matches) == 1 else None
    day_match = day_matches[0] if len(day_matches) == 1 else None
    month = chinese_number(month_match.group(2)) if month_match else None
    day = chinese_number(day_match.group(1)) if day_match else None
    return {"country": country, "ruler_or_era": reign.name if reign else None,
            "regnal_year": regnal_year, "ce_year": ce_year,
            "sexagenary_year": sexagenary, "sexagenary_ocr": observed,
            "sexagenary_source": origin, "month": month, "day": day,
            "leap_month": bool(month_match and month_match.group(1)),
            "source_text": text, "review_status": "needs_review",
            "year_conflict": bool(observed and expected and not expected.startswith(observed)),
            "ambiguous": len(years) > 1 or len(month_matches) > 1 or len(day_matches) > 1}


def date_parts_draft(source_text: str | None, event: str, saved: dict | None = None) -> dict | None:
    """Use a matching reviewed value, or populate an unverified OCR draft."""
    source = source_text or ""
    if not source:
        return None
    if isinstance(saved, dict) and saved.get("source_text") == source:
        return saved
    parts = parse_date_parts(source, event)
    if not any(parts.get(key) for key in ("country", "ruler_or_era", "regnal_year",
                                             "sexagenary_ocr", "month", "day")):
        return None
    return parts


def date_parts_with_solar(source_text: str | None, event: str,
                          saved: dict | None = None, solar: dict | None = None) -> dict | None:
    """Read older solar-only review records without discarding their choices."""
    parts = date_parts_draft(source_text, event, saved)
    if not isinstance(solar, dict) or solar.get("source_text") != (source_text or ""):
        return parts
    result = dict(parts or parse_date_parts(source_text or "", event))
    reference = solar.get("reference") or {}
    lunar = solar.get("lunar") or {}
    legacy_solar_only = not (isinstance(saved, dict) and saved.get("source_text") == source_text)
    for key, value in (("country", reference.get("country")),
                       ("ruler_or_era", reference.get("name")),
                       ("regnal_year", reference.get("regnal_year")),
                       ("ce_year", lunar.get("year")),
                       ("month", lunar.get("month")), ("day", lunar.get("day"))):
        if value is not None and (legacy_solar_only or result.get(key) is None):
            result[key] = value
    result["leap_month"] = bool(lunar.get("leap_month", result.get("leap_month")))
    if legacy_solar_only:
        result["year_conflict"] = False
        result["ambiguous"] = False
        if isinstance(result.get("ce_year"), int):
            expected = sexagenary_year(result["ce_year"])
            if result.get("sexagenary_year") and result["sexagenary_year"] != expected:
                result["sexagenary_year"] = expected
                result["sexagenary_source"] = "reviewer"
    if not result.get("mapping_source"):
        result["mapping_source"] = reference.get("mapping_source")
    for key in ("first_ce_year", "last_ce_year"):
        if key not in result and key in reference:
            result[key] = reference[key]
    if legacy_solar_only:
        result["review_status"] = solar.get("review_status", result.get("review_status"))
    return result


def reviewed_date_parts(source_text: str, event: str, previous: dict | None,
                        fields: dict, confirmed: bool = False) -> dict | None:
    """Apply reviewer component edits and recompute the CE/ganji consistency."""
    source = source_text.strip()
    source_changed = bool(previous and previous.get("source_text") != source)
    base = date_parts_draft(source, event, previous) or parse_date_parts(source, event)
    editable = ("country", "ruler_or_era", "regnal_year", "sexagenary_year",
                "month", "day", "leap_month")
    if source_changed:
        unchanged_old_fields = all(
            (bool(fields.get(key)) == bool(previous.get(key)) if key == "leap_month" else
             str(fields.get(key) or "").strip() == str(previous.get(key) or ""))
            for key in editable
        )
        if unchanged_old_fields:
            fields = {key: base.get(key) for key in editable}
    result = dict(base)
    for key in ("country", "ruler_or_era", "sexagenary_year"):
        result[key] = str(fields.get(key) or "").strip() or None
    for key in ("regnal_year", "month", "day"):
        raw = str(fields.get(key) or "").strip()
        number = chinese_number(raw) if raw else None
        if raw and number is None:
            raise ValueError(f"{key}: 숫자를 읽을 수 없습니다.")
        result[key] = number
    result["leap_month"] = bool(fields.get("leap_month"))
    result["source_text"] = source
    if not any(result.get(key) for key in ("country", "ruler_or_era", "regnal_year",
                                           "sexagenary_year", "month", "day")):
        return None
    if not source:
        raise ValueError("먼저 출생 또는 사망 원문을 입력하세요.")
    matching = [r for r in REIGNS if r.country == result["country"]
                and (r.name == result["ruler_or_era"]
                     or result["ruler_or_era"] in r.aliases)]
    if len(matching) == 1 and result["regnal_year"]:
        result["ce_year"] = resolve_regnal_year(matching[0], result["regnal_year"])
        result["mapping_source"] = "catalog"
        result["first_ce_year"] = matching[0].first_ce_year
        result["last_ce_year"] = matching[0].last_ce_year
    elif (previous and previous.get("source_text") == source
          and previous.get("country") == result["country"]
          and previous.get("ruler_or_era") == result["ruler_or_era"]
          and previous.get("regnal_year") == result["regnal_year"]):
        result["ce_year"] = previous.get("ce_year")
        result["mapping_source"] = previous.get("mapping_source")
    else:
        result["ce_year"] = None
        result["mapping_source"] = None
        result.pop("first_ce_year", None)
        result.pop("last_ce_year", None)
    expected = sexagenary_year(result["ce_year"]) if result.get("ce_year") else None
    result["year_conflict"] = bool(
        (base.get("year_conflict") and result["sexagenary_year"] == base.get("sexagenary_year"))
        or (expected and result["sexagenary_year"] and expected != result["sexagenary_year"])
    )
    if result["sexagenary_year"] != base.get("sexagenary_year"):
        result["sexagenary_source"] = "reviewer"
    edited = any(result.get(key) != base.get(key) for key in editable)
    result["ambiguous"] = bool(base.get("ambiguous") and not edited)
    result["review_status"] = "confirmed" if confirmed and not source_changed else "needs_review"
    return result


def solar_from_parts(parts: dict) -> dict:
    """Convert reviewed components only when the CE year is resolved and consistent."""
    year = parts.get("ce_year")
    if not isinstance(year, int) or parts.get("ambiguous") or parts.get("year_conflict"):
        raise ValueError("서기 연도나 OCR 날짜 표기를 확인하세요.")
    ganji = parts.get("sexagenary_year")
    if ganji and ganji != sexagenary_year(year):
        raise ValueError("간지와 서기 연도가 일치하지 않습니다.")
    month, day = parts.get("month"), parts.get("day")
    if day is not None and month is None:
        raise ValueError("월 없이 일만 읽혔습니다.")
    result = lunar_interval(year, month, day, bool(parts.get("leap_month")))
    result["reference"] = {"country": parts.get("country"),
                           "name": parts.get("ruler_or_era"),
                           "regnal_year": parts.get("regnal_year"),
                           "sexagenary": parts.get("sexagenary_ocr"),
                           "mapping_source": parts.get("mapping_source"),
                           "first_ce_year": parts.get("first_ce_year"),
                           "last_ce_year": parts.get("last_ce_year")}
    result["review_status"] = parts.get("review_status", "needs_review")
    result["source_text"] = parts.get("source_text")
    return result


def solar_draft_for_parts(parts: dict | None) -> dict | None:
    if not parts:
        return None
    try:
        return solar_from_parts(parts)
    except (ValueError, RuntimeError):
        return None


def parse_date_text(text: str, event: str | None = None) -> dict:
    """Extract an unambiguous historical date and convert its lunar interval."""
    return solar_from_parts(parse_date_parts(text, event))


def format_interval(value: dict | None) -> str:
    if not value:
        return "양력 초안 없음 · 왕/연호와 음력 날짜를 확인하세요"
    start, end = value["start"], value["end"]
    suffix = {"day": "일", "month": "월", "year": "년"}.get(value.get("precision"), "")
    status = "확인" if value.get("review_status") == "confirmed" else "검토 대기"
    return f"{start}" + (f" ~ {end}" if end != start else "") + f" ({suffix} 단위 · {status})"


def date_draft(source_text: str | None, event: str, saved: dict | None = None) -> dict | None:
    """Reuse a matching human choice; otherwise derive a fresh unverified draft."""
    source = source_text or ""
    if not source:
        return None
    if isinstance(saved, dict) and saved.get("source_text") == source:
        return saved
    try:
        return parse_date_text(source, event)
    except (ValueError, RuntimeError):
        return None
