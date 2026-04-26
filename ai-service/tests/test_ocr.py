import unittest

import numpy as np

from app.ocr import PaddleOcrImageRecognizer


class PaddleOcrImageRecognizerTest(unittest.TestCase):
    def test_regions_from_payload_accepts_numpy_rec_boxes(self):
        recognizer = PaddleOcrImageRecognizer(min_confidence=0.1)
        payload = {
            "rec_texts": ["\u4e09\u5408\u4e00"],
            "rec_scores": [0.99],
            "rec_boxes": np.array([[10, 20, 110, 60]]),
        }

        regions = recognizer._regions_from_payload(payload)

        self.assertEqual(len(regions), 1)
        self.assertEqual(regions[0].text, "\u4e09\u5408\u4e00")
        self.assertEqual(regions[0].box, (10, 20, 100, 40))


if __name__ == "__main__":
    unittest.main()
