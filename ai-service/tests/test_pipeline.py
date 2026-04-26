import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from app.ocr import TextRegion
from app.pipeline import ImageTranslationPipeline, StaticOcrRecognizer


class StubTranslator:
    def translate(self, text, source_language, target_language):
        return "3-in-1 EMF Detector"


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


if __name__ == "__main__":
    unittest.main()
