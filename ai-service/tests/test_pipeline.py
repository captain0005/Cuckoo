import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from app.ocr import TextRegion
from app.pipeline import ImageTranslationPipeline, ManualRegion, StaticOcrRecognizer


class StubTranslator:
    def translate(self, text, source_language, target_language):
        return "3-in-1 EMF Detector"


class EchoTranslator:
    def translate(self, text, source_language, target_language):
        return f"EN:{text}"


class PipelineTest(unittest.TestCase):
    def test_process_image_preserves_resolution_and_writes_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "input.png"
            output_path = root / "output.png"
            image = Image.new("RGB", (420, 240), "white")
            draw = ImageDraw.Draw(image)
            draw.rectangle((40, 60, 260, 120), outline="black", width=2)
            image.save(input_path)

            region = TextRegion(
                text="\u4e09\u5408\u4e00\u7535\u78c1\u8f90\u5c04\u68c0\u6d4b\u4eea",
                confidence=0.98,
                x=50,
                y=70,
                width=190,
                height=36,
                polygon=[(50, 70), (240, 70), (240, 106), (50, 106)],
            )
            pipeline = ImageTranslationPipeline(
                recognizer=StaticOcrRecognizer([region]),
                translator=StubTranslator(),
                source_language="zh",
                target_language="en",
            )

            result = pipeline.process_image(
                input_path=input_path,
                output_path=output_path,
                source_filename="input.png",
            )

            self.assertTrue(output_path.exists())
            with Image.open(output_path) as output_image:
                self.assertEqual(output_image.size, (420, 240))
            self.assertEqual(result.regions_detected, 1)
            self.assertEqual(result.regions_replaced, 1)
            self.assertEqual(result.entries[0].translated_text, "3-in-1 EMF Detector")

    def test_non_cjk_regions_are_not_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "input.png"
            output_path = root / "output.png"
            Image.new("RGB", (200, 120), "white").save(input_path)

            region = TextRegion(
                text="EMF Detector",
                confidence=0.99,
                x=10,
                y=10,
                width=90,
                height=20,
                polygon=[(10, 10), (100, 10), (100, 30), (10, 30)],
            )
            pipeline = ImageTranslationPipeline(
                recognizer=StaticOcrRecognizer([region]),
                translator=StubTranslator(),
            )

            result = pipeline.process_image(
                input_path=input_path,
                output_path=output_path,
                source_filename="input.png",
            )

            self.assertEqual(result.regions_detected, 1)
            self.assertEqual(result.regions_replaced, 0)
            self.assertTrue(output_path.exists())

    def test_tiny_middle_regions_are_skipped_after_translation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "input.png"
            output_path = root / "output.png"
            Image.new("RGB", (790, 1340), "white").save(input_path)

            region = TextRegion(
                text="\u7535\u573a\u5f3a\u5ea6",
                confidence=0.99,
                x=303,
                y=622,
                width=46,
                height=21,
                polygon=[(303, 622), (349, 622), (349, 643), (303, 643)],
            )
            pipeline = ImageTranslationPipeline(
                recognizer=StaticOcrRecognizer([region]),
                translator=StubTranslator(),
            )

            result = pipeline.process_image(
                input_path=input_path,
                output_path=output_path,
                source_filename="input.png",
            )

            self.assertEqual(result.regions_detected, 1)
            self.assertEqual(result.regions_replaced, 0)
            self.assertEqual(result.entries, [])
            self.assertTrue(any("small OCR text" in warning for warning in result.warnings))
            self.assertTrue(output_path.exists())

    def test_manual_regions_translate_only_selected_area_and_group_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "input.png"
            output_path = root / "output.png"
            Image.new("RGB", (400, 240), "white").save(input_path)

            regions = [
                TextRegion("\u5b9e\u529b", 0.99, 80, 80, 70, 30, [(80, 80), (150, 80), (150, 110), (80, 110)]),
                TextRegion("\u6e90\u5934", 0.98, 82, 118, 70, 30, [(82, 118), (152, 118), (152, 148), (82, 148)]),
                TextRegion("\u4e0d\u7ffb\u8bd1", 0.99, 280, 80, 80, 30, [(280, 80), (360, 80), (360, 110), (280, 110)]),
            ]
            pipeline = ImageTranslationPipeline(
                recognizer=StaticOcrRecognizer(regions),
                translator=EchoTranslator(),
            )

            result = pipeline.process_image(
                input_path=input_path,
                output_path=output_path,
                source_filename="input.png",
                manual_regions=[ManualRegion(x=0.15, y=0.25, width=0.32, height=0.45)],
                inpaint_engine="opencv",
            )

            self.assertEqual(result.regions_detected, 3)
            self.assertEqual(result.regions_replaced, 1)
            self.assertEqual(result.entries[0].source_text, "\u5b9e\u529b \u6e90\u5934")
            self.assertEqual(result.entries[0].translated_text, "EN:\u5b9e\u529b \u6e90\u5934")
            self.assertTrue(output_path.exists())

    def test_manual_table_column_keeps_each_row_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "input.png"
            output_path = root / "output.png"
            Image.new("RGB", (500, 700), "white").save(input_path)

            regions = [
                TextRegion("\u4ea7\u54c1\u578b\u53f7", 0.99, 75, 110, 90, 24, [(75, 110), (165, 110), (165, 134), (75, 134)]),
                TextRegion("\u5c4f\u5e55\u6750\u8d28", 0.99, 75, 170, 90, 24, [(75, 170), (165, 170), (165, 194), (75, 194)]),
                TextRegion("\u4f9b\u7535\u7535\u6e90", 0.99, 75, 230, 90, 24, [(75, 230), (165, 230), (165, 254), (75, 254)]),
                TextRegion("\u7535\u6c60", 0.99, 95, 290, 50, 24, [(95, 290), (145, 290), (145, 314), (95, 314)]),
            ]
            pipeline = ImageTranslationPipeline(
                recognizer=StaticOcrRecognizer(regions),
                translator=EchoTranslator(),
            )

            result = pipeline.process_image(
                input_path=input_path,
                output_path=output_path,
                source_filename="input.png",
                manual_regions=[ManualRegion(x=0.10, y=0.12, width=0.30, height=0.38)],
                inpaint_engine="opencv",
            )

            self.assertEqual(result.regions_detected, 4)
            self.assertEqual(result.regions_replaced, 4)
            self.assertEqual([entry.source_text for entry in result.entries], [region.text for region in regions])
            self.assertTrue(output_path.exists())


if __name__ == "__main__":
    unittest.main()
