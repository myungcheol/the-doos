import unittest

from historical_dates import (REIGNS, date_draft, lunar_interval, parse_date_text,
                              resolve_regnal_year)


class HistoricalDateTests(unittest.TestCase):
    def test_korean_source_date_before_year_1000(self):
        value = parse_date_text("開寶八年乙亥十月 / 十五日生 / 淳化五年官至", "birth")
        self.assertEqual((value["start"], value["end"]), ("0975-11-20", "0975-11-20"))
        self.assertEqual(value["reference"]["regnal_year"], 8)
        self.assertEqual(value["review_status"], "needs_review")
        # Dates printed alongside the source entries in the NIKH Goryeosa DB.
        self.assertEqual(lunar_interval(975, 10, 26)["start"], "0975-12-01")
        self.assertEqual(lunar_interval(1048, 1, 1)["start"], "1048-01-18")

    def test_partial_lunar_dates_are_intervals(self):
        year = parse_date_text("高麗文宗二年戊子卒", "death")
        self.assertEqual((year["start"], year["end"], year["precision"]),
                         ("1048-01-18", "1049-02-04", "year"))
        month = lunar_interval(1048, 2)
        self.assertEqual((month["start"], month["end"], month["precision"]),
                         ("1048-03-17", "1048-04-15", "month"))
        leap_month = lunar_interval(1048, 1, leap=True)
        self.assertNotEqual(leap_month["start"], lunar_interval(1048, 1)["start"])
        self.assertEqual(parse_date_text("高麗文宗二年閏正月初一日生", "birth")["start"],
                         leap_month["start"])

    def test_invalid_or_ambiguous_dates_do_not_get_a_solar_draft(self):
        for text in ("開寶八年乙亥二月三十一日生", "開寶八年甲子十月十五日生",
                     "開寶八年淳化五年十月生", "乙亥年十月生"):
            with self.subTest(text=text):
                self.assertIsNone(date_draft(text, "birth"))
        with self.assertRaises(ValueError):
            lunar_interval(1048, 13, 1)
        with self.assertRaises(ValueError):
            lunar_interval(1048, 2, 31)
        with self.assertRaises(ValueError):
            lunar_interval(1048, None, 2)
        with self.assertRaises(ValueError):
            lunar_interval(1048, 2, 1, leap=True)

    def test_human_choice_survives_only_matching_source(self):
        source = "판독한 날짜"
        saved = {"source_text": source, "start": "1048-01-18", "end": "1048-01-18"}
        self.assertIs(date_draft(source, "birth", saved), saved)
        self.assertIsNone(date_draft("수정된 날짜", "birth", saved))
        self.assertEqual(resolve_regnal_year(next(r for r in REIGNS if r.name == "문종 文宗"), 2), 1048)

    def test_identical_king_names_require_a_country_in_automatic_parse(self):
        self.assertEqual(parse_date_text("高麗太祖元年生", "birth")["lunar"]["year"], 918)
        self.assertEqual(parse_date_text("朝鮮太祖元年生", "birth")["lunar"]["year"], 1392)
        self.assertIsNone(date_draft("太祖元年生", "birth"))


if __name__ == "__main__":
    unittest.main()
