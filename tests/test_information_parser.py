import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from information_parser import parse_candidate


class InformationParserTest(unittest.TestCase):
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
                    self.assertIsNone(actual['gregorian_year'])
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
