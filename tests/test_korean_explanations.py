import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from information_parser import parse_candidate
from korean_explanations import enrich_explanations, explain_item
from spouse_parser import enrich_spouses


FIXTURE = Path(__file__).parent / 'fixtures/explanation-samples.json'


class ExplanationTest(unittest.TestCase):
    def test_rule_samples_keep_ownership_precision_and_raw(self):
        for case in json.loads(FIXTURE.read_text(encoding='utf-8'))['cases']:
            with self.subTest(case=case['id']):
                person = {'information_candidates': [{'text': part, 'bbox': None} for part in case['fragments']]}
                person['information'] = parse_candidate(person, 'owner')
                document = enrich_spouses({'candidates': [person]})
                enrich_explanations(document)
                results = []
                for item in person['information']['items']:
                    results.append(item['explanation']['automatic'])
                    results.extend(child['explanation']['automatic'] for child in item.get('items', []))
                self.assertEqual(results, case['expected'])
                self.assertEqual(''.join(item['raw'] for item in person['information']['items']), ''.join(case['fragments']))
                if case['id'] == 'concubine':
                    self.assertEqual(person['spouses']['marriages'][0]['relation_type'], 'concubine')
                    self.assertEqual(person['spouses']['people'][0]['information_items'][1]['explanation']['automatic'], '甲辰 (월·일 미상) 태어남.')

    def test_manual_explanation_survives_repeated_enrichment(self):
        item = {'kind': 'unclassified', 'raw': '不詳', 'explanation': {'automatic': None, 'manual': '검수자가 입력한 풀이'}}
        document = {'candidates': [{'information': {'items': [item]}}]}
        once = deepcopy(enrich_explanations(document))
        self.assertEqual(enrich_explanations(document), once)
        self.assertEqual(item['explanation'], {'automatic': None, 'manual': '검수자가 입력한 풀이'})

    def test_assumed_components_are_never_stated_as_actual_dates(self):
        item = {'kind': 'birth', 'date': {'year_text': '甲辰', 'month_text': None, 'day_text': None,
                                         'month': 1, 'day': 1, 'month_assumed': True, 'day_assumed': True}}
        self.assertEqual(explain_item(item)['automatic'], '甲辰 (월·일 미상) 태어남.')

    def test_unverified_date_and_manual_override_stay_distinct(self):
        item = {'kind': 'birth', 'date': {'year_text': '甲辰', 'month_text': '十三月', 'month': 13},
                'warnings': ['date components out of range'], 'manual_explanation': '원문 재검토 필요'}
        self.assertEqual(explain_item(item), {'automatic': None, 'manual': '원문 재검토 필요'})


if __name__ == '__main__':
    unittest.main()
