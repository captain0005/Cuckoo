import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

from app.image_renderer import (
    TextReplacement,
    _build_inpaint_mask,
    _erase_box,
    _estimate_text_color,
    _fit_text,
    _inpaint_layouts,
    _inpaint_masked_area_with_lama,
    _plan_text_layouts,
    _text_content_bounds,
)
from app.config import settings
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

    def test_product_parameter_title_has_capped_display_size(self):
        image = Image.new("RGB", (790, 1321), "white")
        region = TextRegion(
            text="\u4ea7\u54c1\u53c2\u6570",
            confidence=0.99,
            x=41,
            y=43,
            width=269,
            height=78,
            polygon=[(41, 43), (310, 43), (310, 121), (41, 121)],
        )

        layouts = _plan_text_layouts(
            image,
            [TextReplacement(region=region, translated_text="Product Parameters")],
        )

        self.assertEqual(len(layouts), 1)
        self.assertEqual(layouts[0].role, "title")
        self.assertLessEqual(getattr(layouts[0].font, "size", 0), 56)

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

    def test_table_value_uses_cell_width_for_long_translation(self):
        image = Image.new("RGB", (790, 1321), (245, 247, 250))
        draw = ImageDraw.Draw(image)
        for y in (150, 217, 270, 324, 376):
            draw.line((45, y, 757, y), fill=(70, 74, 80), width=1)
        draw.line((45, 150, 45, 642), fill=(70, 74, 80), width=1)
        draw.line((253, 150, 253, 642), fill=(70, 74, 80), width=1)
        draw.line((757, 150, 757, 642), fill=(70, 74, 80), width=1)
        region = TextRegion(
            text="\u80cc\u5149\u4eae\u5ea6\u53ef\u8c03",
            confidence=0.99,
            x=440,
            y=339,
            width=121,
            height=24,
            polygon=[(440, 339), (561, 339), (561, 363), (440, 363)],
        )

        layouts = _plan_text_layouts(
            image,
            [TextReplacement(region=region, translated_text="Backlight brightness is adjustable.")],
        )

        self.assertEqual(len(layouts), 1)
        self.assertEqual(layouts[0].role, "table_value")
        self.assertGreater(layouts[0].box[2], 360)
        self.assertEqual(layouts[0].lines, ["Backlight brightness is adjustable."])
        self.assertGreaterEqual(getattr(layouts[0].font, "size", 0), 18)
        _, erase_y, _, erase_height = _erase_box(region, image.size, layouts[0].role)
        self.assertGreater(erase_y, 324)
        self.assertLess(erase_y + erase_height, 376)

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

    def test_centered_top_heading_keeps_center_alignment_and_scale(self):
        image = Image.new("RGB", (800, 800), "white")
        region = TextRegion(
            text="USB\u8f93\u51fa",
            confidence=0.99,
            x=252,
            y=51,
            width=292,
            height=56,
            polygon=[(252, 51), (544, 51), (544, 107), (252, 107)],
        )

        layouts = _plan_text_layouts(
            image,
            [TextReplacement(region=region, translated_text="USB output")],
        )

        self.assertEqual(len(layouts), 1)
        self.assertEqual(layouts[0].role, "center_title")
        self.assertEqual(layouts[0].align, "center")
        self.assertGreaterEqual(getattr(layouts[0].font, "size", 0), 34)

    def test_blue_feature_bar_keeps_icon_area_and_uses_white_text(self):
        image = Image.new("RGB", (800, 800), "white")
        ImageDraw.Draw(image).polygon([(25, 528), (270, 528), (260, 575), (15, 575)], fill=(0, 66, 245))
        region = TextRegion(
            text="\u53ef\u710a\u954d\u3001\u94c1\u3001\u94a2",
            confidence=0.99,
            x=90,
            y=538,
            width=160,
            height=28,
            polygon=[(90, 538), (250, 538), (250, 566), (90, 566)],
        )

        layouts = _plan_text_layouts(
            image,
            [TextReplacement(region=region, translated_text="Weldable nickel, iron, and steel")],
        )

        self.assertEqual(len(layouts), 1)
        self.assertEqual(layouts[0].role, "feature_bar")
        self.assertGreaterEqual(layouts[0].box[0], region.x)
        self.assertEqual(layouts[0].color, (255, 255, 255))
        self.assertLessEqual(len(layouts[0].lines), 2)

    def test_colored_tag_stays_on_tag_background(self):
        image = Image.new("RGB", (800, 800), "white")
        ImageDraw.Draw(image).rounded_rectangle((30, 278, 260, 316), radius=6, fill=(245, 171, 24))
        region = TextRegion(
            text="\u70b9\u710a\u673a+\u5145\u7535\u5b9d\u4e8c\u5408",
            confidence=0.99,
            x=35,
            y=282,
            width=220,
            height=27,
            polygon=[(35, 282), (255, 282), (255, 309), (35, 309)],
        )

        layouts = _plan_text_layouts(
            image,
            [TextReplacement(region=region, translated_text="Spot welder + power bank 2-in-1")],
        )

        self.assertEqual(len(layouts), 1)
        self.assertEqual(layouts[0].role, "tag")
        self.assertEqual(layouts[0].align, "center")
        self.assertLessEqual(len(layouts[0].lines), 2)

    def test_single_character_icon_badge_is_skipped(self):
        image = Image.new("RGB", (800, 800), "white")
        region = TextRegion(
            text="\u9001",
            confidence=0.99,
            x=10,
            y=340,
            width=43,
            height=41,
            polygon=[(10, 340), (53, 340), (53, 381), (10, 381)],
        )

        layouts = _plan_text_layouts(
            image,
            [TextReplacement(region=region, translated_text="Free gift")],
        )

        self.assertEqual(layouts, [])

    def test_large_bottom_decorative_badge_text_is_skipped(self):
        image = Image.new("RGB", (800, 800), "white")
        region = TextRegion(
            text="\u5de5\u5382",
            confidence=0.99,
            x=680,
            y=659,
            width=101,
            height=59,
            polygon=[(680, 659), (781, 659), (781, 718), (680, 718)],
        )

        layouts = _plan_text_layouts(
            image,
            [TextReplacement(region=region, translated_text="Factory")],
        )

        self.assertEqual(layouts, [])

    def test_forced_manual_badge_text_is_rendered(self):
        image = Image.new("RGB", (800, 800), "white")
        region = TextRegion(
            text="\u5de5\u5382\u76f4\u9500",
            confidence=0.99,
            x=620,
            y=650,
            width=150,
            height=96,
            polygon=[(620, 650), (770, 650), (770, 746), (620, 746)],
        )

        layouts = _plan_text_layouts(
            image,
            [TextReplacement(region=region, translated_text="Factory Direct", force=True)],
        )

        self.assertEqual(len(layouts), 1)
        self.assertEqual(layouts[0].role, "manual")
        self.assertEqual(layouts[0].align, "center")

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

    def test_long_bottom_caption_prefers_readable_wrapping(self):
        image = Image.new("RGB", (790, 1393), "white")
        region = TextRegion(
            "Type-C\u5145\u7535\u7ebf",
            0.99,
            267,
            1253,
            160,
            36,
            [(267, 1253), (427, 1253), (427, 1289), (267, 1289)],
        )

        layouts = _plan_text_layouts(
            image,
            [TextReplacement(region=region, translated_text="Type-C charging cable")],
        )

        self.assertEqual(len(layouts), 1)
        self.assertEqual(layouts[0].role, "label")
        self.assertGreaterEqual(getattr(layouts[0].font, "size", 0), 18)
        self.assertLessEqual(len(layouts[0].lines), 2)

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

    def test_lama_inpainting_crops_to_mask_bounds(self):
        image = Image.new("RGB", (1000, 1000), "gray")
        mask = np.zeros((1000, 1000), dtype=np.uint8)
        mask[480:520, 100:150] = 255
        seen = {}

        def fake_inpaint(crop, crop_mask):
            seen["crop_size"] = crop.size
            seen["mask_shape"] = crop_mask.shape
            return Image.new("RGB", crop.size, "white")

        with patch("app.image_renderer.inpaint_with_lama", side_effect=fake_inpaint):
            result = _inpaint_masked_area_with_lama(image, mask)

        self.assertEqual(result.size, image.size)
        self.assertLess(seen["crop_size"][0] * seen["crop_size"][1], image.width * image.height)
        self.assertEqual(seen["mask_shape"], (104, 114))

    def test_manual_group_erases_ocr_boxes_not_entire_manual_selection(self):
        image = Image.new("RGB", (400, 240), "white")
        source_regions = [
            TextRegion("实力", 0.99, 80, 80, 70, 30, [(80, 80), (150, 80), (150, 110), (80, 110)]),
            TextRegion("源头", 0.98, 82, 118, 70, 30, [(82, 118), (152, 118), (152, 148), (82, 148)]),
        ]
        manual_region = TextRegion("实力 源头", 0.98, 60, 60, 180, 130, [(60, 60), (240, 60), (240, 190), (60, 190)])
        layouts = _plan_text_layouts(
            image,
            [
                TextReplacement(
                    region=manual_region,
                    translated_text="Factory Direct",
                    force=True,
                    erase_regions=source_regions,
                )
            ],
        )

        mask = _build_inpaint_mask(image, layouts)

        self.assertEqual(mask[70, 220], 0)
        self.assertEqual(mask[90, 100], 255)
        self.assertEqual(mask[130, 100], 255)

    def test_lama_runtime_limit_falls_back_without_failing_render(self):
        old_max_pixels = settings.lama_max_pixels
        old_min_available_mb = settings.lama_min_available_mb
        settings.lama_max_pixels = 1
        settings.lama_min_available_mb = 0
        try:
            image = Image.new("RGB", (220, 120), "white")
            region = TextRegion(
                text="\u4ea7\u54c1\u53c2\u6570",
                confidence=0.99,
                x=20,
                y=20,
                width=100,
                height=28,
                polygon=[(20, 20), (120, 20), (120, 48), (20, 48)],
            )
            layouts = _plan_text_layouts(image, [TextReplacement(region=region, translated_text="Product Parameters")])
            warnings: list[str] = []

            result = _inpaint_layouts(image, layouts, engine="lama", warnings=warnings)

            self.assertEqual(result.size, image.size)
            self.assertTrue(any("LAMA inpainting unavailable" in warning for warning in warnings))
        finally:
            settings.lama_max_pixels = old_max_pixels
            settings.lama_min_available_mb = old_min_available_mb


if __name__ == "__main__":
    unittest.main()
