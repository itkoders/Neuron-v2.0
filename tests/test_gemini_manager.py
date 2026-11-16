import os
import unittest
from unittest.mock import patch

import gemini_manager
from gemini_manager import _configured_keys, gemini_generate


class GeminiKeyConfigTests(unittest.TestCase):
    def test_reads_comma_and_newline_separated_keys(self):
        with patch.dict(os.environ, {
            "GEMINI_API_KEYS": "key-one, key-two\nkey-three",
            "GEMINI_API_KEY": "key-four",
        }, clear=True):
            self.assertEqual(_configured_keys(), ["key-one", "key-two", "key-three", "key-four"])

    def test_deduplicates_and_caps_at_ten(self):
        values = ",".join("key-" + str(i) for i in range(12))
        with patch.dict(os.environ, {"GEMINI_API_KEYS": values}, clear=True):
            self.assertEqual(len(_configured_keys()), 10)

    def test_single_legacy_variable_still_works(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "legacy-key"}, clear=True):
            self.assertEqual(_configured_keys(), ["legacy-key"])

    def test_rotates_to_next_key_after_rate_limit(self):
        class FakeResponse:
            def __init__(self, status):
                self.status = status
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def json(self, content_type=None):
                return {"candidates": []}

        class FakeSession:
            def __init__(self, *args, **kwargs):
                self.calls = 0
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            def post(self, *args, **kwargs):
                self.calls += 1
                return FakeResponse(429 if self.calls == 1 else 200)

        async def run_test():
            gemini_manager._STATE.clear()
            gemini_manager._CURSOR = 0
            with patch.dict(os.environ, {"GEMINI_API_KEYS": "first-key,second-key"}, clear=True):
                with patch("gemini_manager.aiohttp.ClientSession", FakeSession):
                    data, status = await gemini_generate("test-model", {"contents": []})
            self.assertEqual(status, "ok")
            self.assertEqual(data, {"candidates": []})
            self.assertTrue(gemini_manager._STATE["first-key"]["cooldown_until"] > 0)

        import asyncio
        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
