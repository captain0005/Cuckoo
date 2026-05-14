import unittest

import numpy as np
from PIL import Image

from app.config import settings
from app.inpainting import InpaintUnavailableError, inpaint_with_lama, lama_runtime_status


class InpaintingTest(unittest.TestCase):
    def test_lama_pixel_limit_blocks_unsafe_request_before_loading_model(self):
        old_max_pixels = settings.lama_max_pixels
        old_min_available_mb = settings.lama_min_available_mb
        settings.lama_max_pixels = 1
        settings.lama_min_available_mb = 0
        try:
            image = Image.new("RGB", (10, 10), "white")
            mask = np.ones((10, 10), dtype=np.uint8) * 255

            with self.assertRaises(InpaintUnavailableError):
                inpaint_with_lama(image, mask)
        finally:
            settings.lama_max_pixels = old_max_pixels
            settings.lama_min_available_mb = old_min_available_mb

    def test_lama_runtime_status_does_not_load_model(self):
        status = lama_runtime_status()

        self.assertIn("model_available", status)
        self.assertIn("available_mb", status)
        self.assertIn("cached", status)


if __name__ == "__main__":
    unittest.main()
