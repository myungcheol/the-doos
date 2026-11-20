import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from ocr_image import vertical_retry_windows


class VerticalRetryTest(unittest.TestCase):
    def test_horizontal_region_retries_only_crossed_columns(self):
        band = {'bbox':[0,0,100,120], 'columns':[
            {'bbox':[10,0,25,120]}, {'bbox':[35,0,50,120]}, {'bbox':[75,0,90,120]}]}
        region = {'text':'横讀誤認','polygon':[[8,20],[55,20],[55,35],[8,35]]}
        windows = vertical_retry_windows([region],band)
        self.assertEqual(len(windows),2)
        self.assertTrue(all(w[3]-w[1] > w[2]-w[0] for w in windows))
        self.assertLessEqual(windows[0][2],windows[1][0])

    def test_vertical_region_does_not_trigger_retry(self):
        band = {'bbox':[0,0,100,120], 'columns':[{'bbox':[10,0,25,120]}]}
        region = {'text':'縱書正文','polygon':[[10,10],[25,10],[25,90],[10,90]]}
        self.assertEqual(vertical_retry_windows([region],band),[])
