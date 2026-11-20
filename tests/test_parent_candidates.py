import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from parent_candidates import extract_parent_candidates


def person(name, band, x, marker='子'):
    return {'name_text':name, 'band':band, 'name_bbox':[x,band*100,x+30,band*100+80], 'marker':marker}


class ParentCandidatesTest(unittest.TestCase):
    def test_children_groups_and_female_parent(self):
        people = [person('A',1,300), person('X',1,100), person('C',2,300),
                  person('D',2,250), person('B',2,200,'女'), person('Y',2,100), person('E',3,200)]
        result = extract_parent_candidates({'candidates':people})['parent_candidates']
        self.assertEqual([(r['parent'],r['child']) for r in result['relations']], [(0,2),(0,3),(0,4),(1,5),(4,6)])
        self.assertIn('female_marker_requires_review',result['relations'][-1]['warnings'])
        self.assertTrue(all(r['needs_review'] for r in result['relations']))

    def test_missing_upper_candidate_is_unresolved_and_never_skips_band(self):
        people = [person('A',1,300),person('C',3,300),person('D',4,350)]
        result = extract_parent_candidates({'candidates':people})['parent_candidates']
        self.assertEqual(result['relations'],[])
        self.assertEqual({u['child'] for u in result['unresolved']},{0,1,2})

    def test_confirmed_002_example(self):
        people = [person('景吉',1,234,None),person('子應龍',2,233)]
        relation = extract_parent_candidates({'candidates':people})['parent_candidates']['relations'][0]
        self.assertEqual((relation['parent'],relation['child'],relation['method']),(0,1,'same_column'))
