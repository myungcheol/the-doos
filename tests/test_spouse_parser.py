import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from information_parser import parse_candidate
from spouse_parser import parse_spouses


def parse(text):
    person = {'information_candidates':[{'text':text,'bbox':[0,0,20,100]}]}
    person['information'] = parse_candidate(person, 'A')
    return parse_spouses(person)


class SpouseParserTest(unittest.TestCase):
    def test_distinct_spouses_and_concubine(self):
        result = parse('甲辰生配金氏丙午卒配李氏丁未生妾洪氏戊申生')
        self.assertEqual([p['designation_raw'] for p in result['people']], ['金氏','李氏','洪氏'])
        self.assertEqual([m['relation_type'] for m in result['marriages']], ['spouse','spouse','concubine'])
        self.assertEqual(len({p['id'] for p in result['people']}), 3)
        self.assertTrue(all(m['wife_rank'] is None for m in result['marriages']))
        for person in result['people']:
            self.assertTrue(all(i['owner_id']==person['id'] for i in person['information_items']))
            self.assertIsNone(person['personal_name'])

    def test_repeated_clan_is_not_merged(self):
        result = parse('配金氏甲辰生配金氏丙午生')
        self.assertEqual(len(result['people']),2)
        self.assertNotEqual(result['people'][0]['id'], result['people'][1]['id'])

    def test_relatives_dates_and_concubine_are_not_attached_to_A(self):
        result = parse('配金氏甲辰生父某丙午卒納妾李氏丁未生')
        self.assertEqual(len(result['marriages']),1)
        self.assertEqual(result['marriages'][0]['relation_type'],'spouse')
        person = result['people'][0]
        self.assertEqual([i['raw'] for i in person['information_items'] if 'date' in i],['甲辰生'])
        self.assertTrue(any('丙午' in i['raw'] for i in person['unresolved_items']))
        self.assertEqual(len(result['unresolved_scopes']),1)

    def test_explicit_new_spouse_after_relative_context(self):
        result = parse('配金氏父某配李氏甲辰生')
        self.assertEqual(len(result['people']),2)


if __name__ == '__main__':
    unittest.main()
