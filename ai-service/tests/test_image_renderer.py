import unittest

from PIL import Image

from app.image_renderer import TextReplacement, _erase_box, _fit_text, _plan_text_layouts
from app.ocr import TextRegion


class ImageRendererTest(unittest.TestCase):
    def test_fit_text_prefers_smaller_font_over_splitting_word(self):
        _, lines = _fit_text("Three-in-one", 300, 120)

        self.assertEqual(lines, ["Three-in-one"])

    def test_title_layout_expands_and_left_aligns_top_text(self):
        image = Image.new("RGB", (790, 1340), "white")
        region = TextRegion(
            text="\u7535\u78c1\u8f90\u5c04\u68c0\u6d4b\u4eea",
            confidence=0.99,
            x=42,
            y=195,
            width=498,
            height=79,
            polygon=[(42, 195), (540, 195), (540, 274), (42, 274)],
        )

        layouts = _plan_text_layouts(
            image,
            [TextReplacement(region=region, translated_text="Electromagnetic radiation detector")],
        )

        self.assertEqual(len(layouts), 1)
        self.assertEqual(layouts[0].align, "left")
        self.assertGreater(layouts[0].box[2], 520)

    def test_middle_micro_text_is_skipped(self):
        image = Image.new("RGB", (790, 1340), "white")
        region = TextRegion(
            text="\u7535\u573a\u5f3a\u5ea6",
            confidence=0.99,
            x=303,
            y=622,
            width=46,
            height=21,
            polygon=[(303, 622), (349, 622), (349, 643), (303, 643)],
        )

        layouts = _plan_text_layouts(
            image,
            [TextReplacement(region=region, translated_text="Electric field strength")],
        )

        self.assertEqual(layouts, [])

    def test_label_layout_uses_badge_width_to_keep_words_intact(self):
        image = Image.new("RGB", (790, 1340), "white")
        region = TextRegion(
            text="\u78c1\u573a",
            confidence=0.99,
            x=381,
            y=1206,
            width=53,
            height=30,
            polygon=[(381, 1206), (434, 1206), (434, 1236), (381, 1236)],
        )

        layouts = _plan_text_layouts(
            image,
            [TextReplacement(region=region, translated_text="Magnetic field")],
        )

        self.assertEqual(len(layouts), 1)
        self.assertEqual(layouts[0].lines, ["Magnetic field"])
        self.assertGreaterEqual(layouts[0].box[2], 120)

    def test_label_erase_box_does_not_expand_down_into_numbers(self):
        region = TextRegion(
            text="\u7535\u573a",
            confidence=0.99,
            x=132,
            y=1205,
            width=54,
            height=31,
            polygon=[(132, 1205), (186, 1205), (186, 1236), (132, 1236)],
        )

        _, y, _, height = _erase_box(region, (790, 1340), "label")

        self.assertLess(y, region.y)
        self.assertEqual(y + height, region.y + region.height)


if __name__ == "__main__":
    unittest.main()
