import unittest

from app.translation import OpenAICompatibleTranslator


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": "3-in-1 EMF Detector"}}]}


class FakeClient:
    is_closed = False

    def __init__(self):
        self.request = None

    def post(self, endpoint, *, headers, json):
        self.request = {
            "endpoint": endpoint,
            "headers": headers,
            "json": json,
        }
        return FakeResponse()


class OpenAICompatibleTranslatorTest(unittest.TestCase):
    def test_qwen_mt_payload_uses_single_user_message_and_translation_options(self):
        client = FakeClient()
        translator = OpenAICompatibleTranslator(
            endpoint="https://example.test/v1/chat/completions",
            api_key="test-key",
            model="qwen-mt-plus",
            client=client,
        )

        translated = translator.translate("\u4e09\u5408\u4e00", "zh", "en")

        self.assertEqual(translated, "3-in-1 EMF Detector")
        payload = client.request["json"]
        self.assertEqual(payload["model"], "qwen-mt-plus")
        self.assertEqual(payload["messages"], [{"role": "user", "content": "\u4e09\u5408\u4e00"}])
        self.assertEqual(
            payload["translation_options"],
            {"source_lang": "Chinese", "target_lang": "English"},
        )
        self.assertFalse(payload["stream"])


if __name__ == "__main__":
    unittest.main()
