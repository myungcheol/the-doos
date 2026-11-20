import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from page_references import extract_references, resolve_reference


class PageReferenceTest(unittest.TestCase):
    def test_explicit_reference_missing_and_ambiguous_target(self):
        people = {'candidates':[{'name_text':'子景吉','name_bbox':[10,10,40,80]}]}
        ocr = {'regions':[{'text':'下2','polygon':[[15,90],[35,90],[35,100],[15,100]]}]}
        with tempfile.TemporaryDirectory() as directory:
            missing = extract_references(ocr,people,directory)[0]
            self.assertEqual(missing['status'],'scan_missing')
            Path(directory,'002.jpg').touch()
            ref = extract_references(ocr,people,directory)[0]
            self.assertEqual((ref['person'],ref['status']),(0,'unprocessed'))
            self.assertEqual(resolve_reference(ref,people['candidates'][0],{'candidates':[{'name_text':'景吉'}]})['status'],'candidate')
            self.assertEqual(resolve_reference(ref,people['candidates'][0],{'candidates':[{'name_text':'景吉'},{'name_text':'景吉'}]})['status'],'ambiguous')

    def test_f_prefix_is_uncertain(self):
        ocr = {'regions':[{'text':'F3','polygon':[[15,90],[35,90],[35,100],[15,100]]}]}
        people = {'candidates':[{'name_text':'子景斗','name_bbox':[10,10,40,80]}]}
        with tempfile.TemporaryDirectory() as directory:
            self.assertTrue(extract_references(ocr,people,directory)[0]['ocr_direction_uncertain'])
