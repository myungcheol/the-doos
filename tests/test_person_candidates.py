import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from person_candidates import extract


def region(text, x, y, band):
    return {'text': text, 'score': .9, 'polygon': [[x, y], [x+10, y], [x+10, y+20], [x, y+20]], 'band': band}


class PersonCandidatesTest(unittest.TestCase):
    def test_overlapping_prefix_is_preserved(self):
        prefix = region('子', 524, 770, 1)
        prefix['polygon'] = [[524,770],[550,770],[550,803],[524,803]]
        name = region('景吉', 519, 793, 1)
        name['polygon'] = [[519,793],[552,793],[552,862],[519,862]]
        candidates = extract({'image': {}, 'regions': [prefix, name]},
                             {'bands': [{'bbox': [500,750,570,900]}]})['candidates']
        self.assertEqual([c['name_text'] for c in candidates], ['子景吉'])
        self.assertEqual(candidates[0]['marker'], '子')

    def test_child_lineage_label_is_not_person_name(self):
        label = region('子系', 594, 766, 1)
        label['polygon'] = [[594,766],[627,766],[627,787],[594,787]]
        name = region('體孫', 592, 797, 1)
        name['polygon'] = [[592,797],[626,797],[626,864],[592,864]]
        candidates = extract({'image': {}, 'regions': [label, name]},
                             {'bands': [{'bbox': [580,750,640,900]}]})['candidates']
        self.assertEqual([c['name_text'] for c in candidates], ['體孫'])
        self.assertEqual(candidates[0]['lineage_marker'], '子系')

    def test_adjacent_name_endings_keep_estimated_geometry(self):
        regions = []
        for text, x0,y0,x1,y1 in [('子',147,777,173,807),('汝',146,804,173,835),
                                   ('子',186,777,211,809),('汝',185,803,213,835),
                                   ('賢慶',142,836,216,875)]:
            regions.append({'text':text,'score':.9,'band':1,'polygon':[[x0,y0],[x1,y0],[x1,y1],[x0,y1]]})
        candidates = extract({'image': {}, 'regions': regions},
                             {'bands': [{'bbox':[100,750,225,900]}]})['candidates']
        self.assertEqual([c['name_text'] for c in candidates], ['子汝慶','子汝賢'])
        self.assertTrue(all(c['geometry_estimated'] for c in candidates))

    def test_small_rotated_body_glyph_does_not_become_name(self):
        glyph = {'text':'面','score':.8,'band':1,'polygon':[[215,719],[236,731],[226,748],[205,736]]}
        body = region('説明正文長文', 30,700,1)
        body['polygon'] = [[30,700],[51,700],[51,800],[30,800]]
        candidates = extract({'image':{},'regions':[glyph,body]},
                             {'bands':[{'bbox':[0,650,300,800]}]})['candidates']
        self.assertEqual(candidates, [])

    def test_split_large_name_without_marker(self):
        first = region('景', 50, 10, 1)
        first['polygon'] = [[50, 10], [81, 10], [81, 46], [50, 46]]
        second = region('吉', 54, 51, 1)
        second['polygon'] = [[54, 51], [77, 51], [77, 76], [54, 76]]
        layout = {'bands': [{'bbox': [0, 0, 200, 150]}]}
        candidates = extract({'image': {}, 'regions': [first, second]}, layout)['candidates']
        self.assertEqual([r['name_text'] for r in candidates], ['景吉'])
        self.assertIsNone(candidates[0]['marker'])

    def test_large_name_without_marker_and_small_body(self):
        ocr = {'image': {}, 'regions': [region('杜慶寧', 70, 10, 1), region('小字説明長文', 20, 10, 1)]}
        ocr['regions'][0]['polygon'] = [[70, 10], [110, 10], [110, 120], [70, 120]]
        layout = {'bands': [{'bbox': [0, 0, 200, 150]}]}
        candidates = extract(ocr, layout)['candidates']
        self.assertEqual([r['name_text'] for r in candidates], ['杜慶寧'])
        self.assertIsNone(candidates[0]['marker'])

    def test_split_single_character_name_stops_information_ownership(self):
        son = region('子', 50, 10, 1)
        son['polygon'] = [[50, 10], [80, 10], [80, 40], [50, 40]]
        given = region('憲', 50, 55, 1)
        given['polygon'] = [[50, 55], [80, 55], [80, 85], [50, 85]]
        ocr = {'image': {}, 'regions': [region('女金世英', 150, 10, 1), son, given]}
        layout = {'bands': [{'bbox': [0, 0, 200, 150]}]}
        candidates = extract(ocr, layout)['candidates']
        self.assertEqual([r['name_text'] for r in candidates], ['女金世英', '子憲'])
        self.assertEqual(candidates[0]['information_candidates'], [])

    def test_information_is_right_to_left_and_excludes_other_band(self):
        ocr = {'image': {}, 'regions': [region('左左', 30, 10, 1), region('子之建', 80, 10, 1),
                                       region('右右', 60, 10, 1), region('他他', 50, 10, 2)]}
        layout = {'bands': [{'bbox': [0, 0, 100, 100]}]}
        candidate = extract(ocr, layout)['candidates'][0]
        self.assertEqual([r['text'] for r in candidate['information_candidates']], ['右右', '左左'])


if __name__ == '__main__':
    unittest.main()
