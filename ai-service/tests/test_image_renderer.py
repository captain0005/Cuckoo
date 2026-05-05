import unittest

from PIL import Image, ImageDraw

from app.image_renderer import (
    TextReplacement,
    _erase_box,
    _estimate_text_color,
    _fit_text,
    _plan_text_layouts,
    _text_content_bounds,
)
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

    def test_short_table_key_is_not_treated_as_micro_text(self):
        image = Image.new("RGB", (790, 1393), "white")
        region = TextRegion(
            text="\u8bed\u8a00",
            confidence=0.99,
            x=115,
            y=493,
            width=51,
            height=33,
            polygon=[(115, 493), (166, 493), (166, 526), (115, 526)],
        )

        layouts = _plan_text_layouts(
            image,
            [TextReplacement(region=region, translated_text="Language")],
        )

        self.assertEqual(len(layouts), 1)
        self.assertEqual(layouts[0].role, "table_key")

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

    def test_large_lower_heading_keeps_section_title_scale(self):
        image = Image.new("RGB", (790, 1393), "white")
        region = TextRegion(
            text="\u914d\u4ef6\u6e05\u5355",
            confidence=0.99,
            x=41,
            y=684,
            width=267,
            height=77,
            polygon=[(41, 684), (308, 684), (308, 761), (41, 761)],
        )

        layouts = _plan_text_layouts(
            image,
            [TextReplacement(region=region, translated_text="Accessories List")],
        )

        self.assertEqual(len(layouts), 1)
        self.assertEqual(layouts[0].role, "section_title")
        self.assertEqual(layouts[0].align, "left")
        self.assertGreaterEqual(getattr(layouts[0].font, "size", 0), 24)

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

    def test_bottom_item_captions_stay_in_columns(self):
        image = Image.new("RGB", (790, 1393), "white")
        regions = [
            TextRegion("\u4e3b\u673a", 0.99, 128, 1254, 58, 35, [(128, 1254), (186, 1254), (186, 1289), (128, 1289)]),
            TextRegion(
                "Type-C\u5145\u7535\u7ebf",
                0.99,
                267,
                1253,
                160,
                36,
                [(267, 1253), (427, 1253), (427, 1289), (267, 1289)],
            ),
            TextRegion("\u5305\u88c5\u76d2", 0.99, 481, 1254, 78, 32, [(481, 1254), (559, 1254), (559, 1286), (481, 1286)]),
            TextRegion("\u8bf4\u660e\u4e66", 0.99, 640, 1257, 77, 29, [(640, 1257), (717, 1257), (717, 1286), (640, 1286)]),
        ]
        translations = ["Main Unit", "Type-C Charging Cable", "Packaging Box", "Manual"]

        layouts = _plan_text_layouts(
            image,
            [TextReplacement(region=region, translated_text=translation) for region, translation in zip(regions, translations)],
        )

        self.assertEqual(len(layouts), 4)
        self.assertTrue(all(layout.role == "label" for layout in layouts))
        self.assertTrue(all(layout.box[1] >= 1230 for layout in layouts))
        self.assert_layouts_do_not_overlap(layouts)

    def test_tiny_bottom_product_marking_is_skipped(self):
        image = Image.new("RGB", (790, 1393), "white")
        region = TextRegion(
            text="\u7535",
            confidence=0.99,
            x=557,
            y=1202,
            width=25,
            height=16,
            polygon=[(557, 1202), (582, 1202), (582, 1218), (557, 1218)],
        )

        layouts = _plan_text_layouts(
            image,
            [TextReplacement(region=region, translated_text="Electric")],
        )

        self.assertEqual(layouts, [])

    def test_vertical_packaging_text_is_skipped(self):
        image = Image.new("RGB", (790, 1393), "white")
        region = TextRegion(
            text="\u7535\u78c1\u8f90\u5c04\u68c0\u6d4b\u4eea",
            confidence=0.99,
            x=467,
            y=975,
            width=20,
            height=109,
            polygon=[(467, 975), (487, 975), (487, 1084), (467, 1084)],
        )

        layouts = _plan_text_layouts(
            image,
            [TextReplacement(region=region, translated_text="Electromagnetic radiation detector")],
        )

        self.assertEqual(layouts, [])

    def test_light_table_text_uses_foreground_color(self):
        image = Image.new("RGB", (420, 220), (245, 247, 250))
        draw = ImageDraw.Draw(image)
        region = TextRegion(
            text="\u5c4f\u5e55\u6750\u8d28",
            confidence=0.99,
            x=70,
            y=80,
            width=90,
            height=24,
            polygon=[(70, 80), (160, 80), (160, 104), (70, 104)],
        )
        draw.text((region.x, region.y), region.text, fill=(38, 38, 38))

        color = _estimate_text_color(image, region)

        self.assertLess(sum(color), 180)


if __name__ == "__main__":
    unittest.main()
