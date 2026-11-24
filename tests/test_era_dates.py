import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from information_parser import parse_candidate


def read(*parts):
    regions = [{'text': part, 'bbox': None} for part in parts]
    return parse_candidate({'information_candidates': regions}, 'A')['items'][0]


class EraDatesTest(unittest.TestCase):
    def test_year_anchors_and_namespaces(self):
        for raw, year in [('至正十六年丙申', 1356), ('恭愍王五年', 1356), ('宋乾德元年', 963),
                          ('燕山君卽位年', 1494), ('燕山元年', 1495), ('弘治八年', 1495),
                          ('忠惠王後二年', 1341), ('乾德元年癸亥', 963), ('光武十一年', 1907)]:
            with self.subTest(raw=raw):
                item = read(raw + '生')
                self.assertEqual(item['raw'], raw + '生')
                self.assertEqual(item['date']['gregorian_year'], year)
                self.assertEqual(item['date']['conversion_status'], 'resolved')

    def test_conflicts_repetition_and_bounds(self):
        for raw, status, years in [('至正十六年甲辰', 'conflict', []),
                                   ('忠惠王二年', 'ambiguous', [1332, 1341]),
                                   ('乾德元年', 'ambiguous', [919, 963]),
                                   ('燕山十三年', 'unresolved', []),
                                   ('至正即位年', 'unresolved', [])]:
            with self.subTest(raw=raw):
                date = read(raw + '卒')['date']
                self.assertEqual(date['conversion_status'], status)
                self.assertEqual(date['date_details']['candidate_years'], years)
                self.assertIsNone(date['gregorian_year'])
        date = read('甲辰二月生')['date']
        self.assertEqual(date['conversion_status'], 'ambiguous')
        self.assertIn(1904, date['date_details']['candidate_years'])
        self.assertIn(1964, date['date_details']['candidate_years'])

    def test_original_precision_and_unreadable_components(self):
        for suffix, month, day, ma, da in [('', 1, 1, True, True), ('五月', 5, 1, False, True),
                ('正月初一日', 1, 1, False, False), ('□月五日', None, 5, False, False),
                ('閏二月三十日', 2, 30, False, False)]:
            with self.subTest(suffix=suffix):
                item = read('至正十', '六年' + suffix + '生')
                date = item['date']
                self.assertEqual((date['normalized_month'], date['normalized_day']), (month, day))
                self.assertEqual((date['month_assumed'], date['day_assumed']), (ma, da))
                self.assertEqual(date['month_text'] is None, ma)
                self.assertEqual(date['day_text'] is None, da)
                self.assertEqual(date['calendar'], 'lunar' if '閏' in suffix else 'unknown')
                self.assertEqual([r['region_index'] for r in item['source_refs']], [0, 1])

    def test_explicit_calendar_and_spouse_source(self):
        scope = read('配金氏陰曆至正十六年二月三十日卒')
        event = next(item for item in scope['items'] if item['kind'] == 'death')
        self.assertEqual(event['owner_id'], scope['subject']['id'])
        self.assertEqual(event['date']['year_text'], '至正十六年')
        self.assertEqual(event['date']['calendar'], 'lunar')
        self.assertEqual(event['date']['normalized_day'], 30)
        self.assertEqual(event['warnings'], [])
