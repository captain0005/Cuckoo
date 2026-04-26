import unittest

from app.text_utils import contains_cjk, is_translatable_ocr_text, normalize_ocr_text


class TextUtilsTest(unittest.TestCase):
    def test_normalize_removes_spaces_between_cjk(self):
        self.assertEqual(normalize_ocr_text("\u4e09 \u5408 \u4e00"), "\u4e09\u5408\u4e00")

    def test_contains_cjk(self):
        self.assertTrue(contains_cjk("\u7535\u78c1\u8f90\u5c04"))
        self.assertFalse(contains_cjk("EMF Detector"))

    def test_translatable_text_requires_cjk(self):
        self.assertTrue(is_translatable_ocr_text("\u4e09\u5408\u4e00 2026"))
        self.assertFalse(is_translatable_ocr_text("2026 EMF"))


if __name__ == "__main__":
    unittest.main()
