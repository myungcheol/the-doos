import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from information_parser import parse_candidate


class InformationParserTest(unittest.TestCase):
    def test_positional_years_and_ocr_zero_keep_original_provenance(self):
        for fragments, year, month, day, kind in [
            (['一九。四年甲辰', '十二月二十八日', '生'],1904,12,28,'birth'),
            (['一九三', '八年二月', '五日'],1938,2,5,'date_unspecified'),
            (['一九〇四年生'],1904,None,None,'birth'),
        ]:
            with self.subTest(fragments=fragments):
                regions = [{'text':t,'bbox':None} for t in fragments]
                parsed = parse_candidate({'information_candidates':regions},'owner')
                item = next(i for i in parsed['items'] if i.get('date'))
                self.assertEqual(item['kind'],kind)
                self.assertEqual(item['date']['year_number'],year)
                self.assertEqual(item['date']['month'],month)
                self.assertEqual(item['date']['day'],day)
                self.assertEqual(''.join(i['raw'] for i in parsed['items']), ''.join(fragments))
                self.assertEqual(''.join(regions[r['region_index']]['text'][r['start']:r['end']] for r in item['source_refs']), item['raw'])
                self.assertEqual(bool(item['date']['ocr_corrections']), '。' in ''.join(fragments))

    def test_punctuation_outside_four_digit_year_is_not_normalized(self):
        parsed = parse_candidate({'information_candidates':[{'text':'甲辰。二月生','bbox':None}]},'owner')
        self.assertEqual(parsed['source_text'],'甲辰。二月生')
        self.assertTrue(all(not i.get('date',{}).get('ocr_corrections') for i in parsed['items']))

    def test_spouse_designation_without氏_uses_marker_region(self):
        regions = [{'text':'配金海金','bbox':[0,0,10,80]},
                   {'text':'丙戌生','bbox':[0,0,10,80]}]
        parsed = parse_candidate({'information_candidates':regions}, 'owner')
        spouse = next(i for i in parsed['items'] if i['kind'] == 'spouse_information')
        self.assertEqual(spouse['subject']['label'], '金海金')

    def test_辛_before_burial_is_flagged_as_likely_misread_death_marker(self):
        regions = [{'text':'甲戌十一月辛','bbox':[0,0,10,80]},
                   {'text':'葬于先塋','bbox':[0,0,10,80]}]
        parsed = parse_candidate({'information_candidates':regions}, 'owner')
        death = next(i for i in parsed['items'] if i['kind'] == 'death')
        self.assertEqual(death['raw'], '甲戌十一月辛')
        self.assertEqual(death['date']['year_text'], '甲戌')
        self.assertEqual(death['date']['month'], 11)
        self.assertEqual(death['ocr_marker_interpretation'], {'raw':'辛', 'interpreted_as':'卒'})
        self.assertTrue(death['warnings'])

    def test_fixtures_and_complete_source_coverage(self):
        fixture = Path(__file__).parent / 'fixtures' / 'information-samples.json'
        for case in json.loads(fixture.read_text(encoding='utf-8'))['cases']:
            with self.subTest(case=case['id']):
                regions = [{'text': t, 'bbox': [100-i*20,0,110-i*20,100]}
                           for i,t in enumerate(case['fragments'])]
                parsed = parse_candidate({'information_candidates': regions}, 'test-owner')
                items = parsed['items']
                self.assertEqual([item['kind'] for item in items], case['kinds'])
                # No text, provenance, or ownership may disappear or overlap.
                self.assertEqual(''.join(i['raw'] for i in items), parsed['source_text'])
                cursor = 0
                for item in items:
                    self.assertEqual(item['start'], cursor)
                    cursor = item['end']
                    self.assertEqual(item['owner_id'], 'test-owner')
                    source = ''.join(regions[r['region_index']]['text'][r['start']:r['end']]
                                     for r in item['source_refs'])
                    self.assertEqual(source, item['raw'])
                dates = [i['date'] for i in items if 'date' in i]
                for actual, expected in zip(dates, case.get('dates', [])):
                    for key,value in expected.items():
                        self.assertEqual(actual[key], value)
                    self.assertEqual(actual['gregorian_year'], expected.get('gregorian_year'))
                if 'dates' in case:
                    self.assertEqual(len(dates), len(case['dates']))
                if case.get('warning'):
                    self.assertTrue(any(i.get('warnings') for i in items))
                spouses = [i for i in items if i['kind']=='spouse_information']
                for scope, expected in zip(spouses, case.get('spouses', [])):
                    self.assertEqual(scope['subject']['label'], expected['label'])
                    self.assertEqual(scope['subject']['relation_type'], expected['relation_type'])
                    event = next(i for i in scope['items'] if i['kind']==expected['event'])
                    self.assertEqual(event['date']['year_text'], expected['year'])
                    self.assertNotEqual(event['owner_id'], 'test-owner')
                    self.assertEqual(event['owner_id'], scope['subject']['id'])
                    self.assertEqual(''.join(i['raw'] for i in scope['items']), scope['raw'])
                    for child in scope['items']:
                        self.assertEqual(parsed['source_text'][child['start']:child['end']], child['raw'])
                        self.assertEqual(''.join(regions[r['region_index']]['text'][r['start']:r['end']]
                                                 for r in child['source_refs']), child['raw'])
                if 'spouses' in case:
                    self.assertEqual(len(spouses), len(case['spouses']))


if __name__ == '__main__':
    unittest.main()
