import unittest

from app.copywriting import (
    LayoutTranslationRequest,
    adapt_translation_for_layout,
    translate_for_layout,
)


class RecordingTranslator:
    def __init__(self):
        self.calls = []

    def translate(self, text, source_language, target_language):
        self.calls.append(text)
        return "\n".join(f"literal {line} translated with extra words" for line in text.splitlines())


class CopywritingTest(unittest.TestCase):
    def test_known_ecommerce_title_uses_short_layout_copy(self):
        result = adapt_translation_for_layout(
            source_text="\u8d85\u6807\u81ea\u52a8\u62a5\u8b66",
            translated_text="Automatic alarm when standards are exceeded",
            role="title",
            target_language="en",
        )

        self.assertEqual(result, "Auto Alarm")

    def test_feature_label_is_kept_short_and_title_cased(self):
        result = adapt_translation_for_layout(
            source_text="\u706f\u5149\u62a5\u8b66",
            translated_text="light alarm warning status",
            role="label",
            target_language="en",
        )

        self.assertEqual(result, "Light Alarm")

    def test_grouped_manual_title_keeps_primary_product_message(self):
        result = adapt_translation_for_layout(
            source_text="TYPE-C\u9502\u7535\u76f4\u5145 \u65e0\u9700\u66f4\u63db\u7535\u6c60 \u5185\u7f6e\u8fbe1000\u6beb\u5b89\u6027\u80fd\u9502\u7535\u6c60",
            translated_text="No need to replace the battery",
            role="title",
            target_language="en",
        )

        self.assertEqual(result, "Type-C Direct Charge No Battery Swap")

    def test_generic_title_drops_filler_words_when_too_long(self):
        result = adapt_translation_for_layout(
            source_text="\u672a\u77e5\u6807\u9898",
            translated_text="Automatic Detection With Smart Alerts For Product Safety",
            role="title",
            target_language="en",
        )

        self.assertEqual(result, "Automatic Detection Smart Alerts Product Safety")

    def test_batch_translation_is_adapted_per_role(self):
        translator = RecordingTranslator()
        requests = [
            LayoutTranslationRequest("\u4ea7\u54c1\u53c2\u6570", "title", (0, 0, 100, 40), (790, 1393)),
            LayoutTranslationRequest("\u5c4f\u5e55\u6750\u8d28", "table_key", (0, 80, 100, 24), (790, 1393)),
        ]

        result = translate_for_layout(translator, requests, "zh", "en")

        self.assertEqual(result, ["Product Parameters", "Screen Material"])
        self.assertEqual(len(translator.calls), 1)


if __name__ == "__main__":
    unittest.main()
