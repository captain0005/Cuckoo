import unittest

from PIL import Image, ImageDraw

from app.image_renderer import TextReplacement, _erase_box, _fit_text, _plan_text_layouts, _text_content_bounds
from app.ocr import TextRegion


class ImageRendererTest(unittest.TestCase):
    def assert_layouts_do_not_overlap(self, layouts):
        bounds = [_text_content_bounds(layout) for layout in layouts]
        for index, first in enumerate(bounds):
            for second in bounds[index + 1 :]:
                self.assertFalse(
                    self._rects_overlap(first, second),
                    f"Text bounds overlap: {first} and {second}",
                )

    @staticmethod
    def _rects_overlap(first, second):
        first_x, first_y, first_width, first_height = first
        second_x, second_y, second_width, second_height = second
        return (
            first_x < second_x + second_width
            and first_x + first_width > second_x
            and first_y < second_y + second_height
            and first_y + first_height > second_y
        )

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

    def test_top_title_layouts_are_shifted_apart_when_english_wraps(self):
        image = Image.new("RGB", (790, 1340), "white")
        alarm_region = TextRegion(
            text="\u8d85\u6807\u81ea\u52a8\u62a5\u8b66",
            confidence=0.99,
            x=28,
            y=18,
            width=360,
            height=42,
            polygon=[(28, 18), (388, 18), (388, 60), (28, 60)],
        )
        contact_region = TextRegion(
            text="\u53ca\u65f6\u63d0\u9192\u907f\u514d\u63a5\u89e6",
            confidence=0.99,
            x=28,
            y=44,
            width=330,
            height=42,
            polygon=[(28, 44), (358, 44), (358, 86), (28, 86)],
        )

        layouts = _plan_text_layouts(
            image,
            [
                TextReplacement(
                    region=alarm_region,
                    translated_text="Automatic alarm when standards are exceeded",
                ),
                TextReplacement(
                    region=contact_region,
                    translated_text="Timely alerts to avoid contact",
                ),
            ],
        )

        self.assertEqual(len(layouts), 2)
        first_bounds = _text_content_bounds(layouts[0])
        second_bounds = _text_content_bounds(layouts[1])
        first_bottom = first_bounds[1] + first_bounds[3]

        self.assertGreaterEqual(second_bounds[1], first_bottom)
        self.assert_layouts_do_not_overlap(layouts)

    def test_wrapped_title_keeps_display_scale(self):
        image = Image.new("RGB", (790, 1340), "white")
        region = TextRegion(
            text="\u8d85\u6807\u81ea\u52a8\u62a5\u8b66",
            confidence=0.99,
            x=28,
            y=18,
            width=360,
            height=42,
            polygon=[(28, 18), (388, 18), (388, 60), (28, 60)],
        )

        layouts = _plan_text_layouts(
            image,
            [TextReplacement(region=region, translated_text="Automatic alarm when standards are exceeded")],
        )

        self.assertEqual(len(layouts), 1)
        self.assertGreaterEqual(getattr(layouts[0].font, "size", 0), 24)
        self.assertLessEqual(len(layouts[0].lines), 3)

    def test_body_layouts_are_repositioned_to_avoid_collisions(self):
        image = Image.new("RGB", (640, 900), "white")
        screen_region = TextRegion(
            text="\u5c4f\u5e55\u62a5\u8b66",
            confidence=0.99,
            x=245,
            y=360,
            width=150,
            height=28,
            polygon=[(245, 360), (395, 360), (395, 388), (245, 388)],
        )
        audio_region = TextRegion(
            text="\u58f0\u97f3\u62a5\u8b66",
            confidence=0.99,
            x=250,
            y=374,
            width=145,
            height=28,
            polygon=[(250, 374), (395, 374), (395, 402), (250, 402)],
        )

        layouts = _plan_text_layouts(
            image,
            [
                TextReplacement(region=screen_region, translated_text="Screen alarm status indicator"),
                TextReplacement(region=audio_region, translated_text="Audio alert warning status"),
            ],
        )

        self.assertEqual(len(layouts), 2)
        self.assert_layouts_do_not_overlap(layouts)

    def test_label_layout_keeps_banner_caption_style(self):
        image = Image.new("RGB", (790, 1340), "white")
        region = TextRegion(
            text="\u706f\u5149\u62a5\u8b66",
            confidence=0.99,
            x=90,
            y=1238,
            width=120,
            height=32,
            polygon=[(90, 1238), (210, 1238), (210, 1270), (90, 1270)],
        )
        ImageDraw.Draw(image).rectangle((42, 1210, 270, 1284), fill=(0, 83, 245))

        layouts = _plan_text_layouts(
            image,
            [TextReplacement(region=region, translated_text="Light alarm")],
        )

        self.assertEqual(len(layouts), 1)
        self.assertEqual(layouts[0].lines, ["Light alarm"])
        self.assertGreaterEqual(getattr(layouts[0].font, "size", 0), 20)
        self.assertEqual(layouts[0].color, (255, 255, 255))


if __name__ == "__main__":
    unittest.main()
