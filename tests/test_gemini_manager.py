import os
import unittest
from unittest.mock import patch

import gemini_manager
from gemini_manager import _configured_key, gemini_generate


class GeminiKeyConfigTests(unittest.TestCase):
    def setUp(self):
        gemini_manager._STATE.clear()
        for key in gemini_manager._TOTAL:
            gemini_manager._TOTAL[key] = 0

    def test_reads_only_single_api_key(self):
        with patch.dict(os.environ, {
            "GEMINI_API_KEY": "one-key",
            "GEMINI_API_KEYS": "ignored-one,ignored-two",
        }, clear=True):
            self.assertEqual(_configured_key(), "one-key")

    def test_missing_single_key_is_not_configured(self):
        with patch.dict(os.environ, {"GEMINI_API_KEYS": "ignored-key"}, clear=True):
            self.assertEqual(_configured_key(), "")

    def test_status_exposes_one_masked_key_only(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "secret-1234"}, clear=True):
            status = gemini_manager.gemini_status()
        self.assertEqual(status["configured"], 1)
        self.assertEqual(status["max_keys"], 1)
        self.assertEqual(len(status["keys"]), 1)
        self.assertEqual(status["keys"][0]["masked"], "…1234")
        self.assertNotIn("secret-1234", str(status))

    def test_missing_key_does_not_call_provider(self):
        async def run_test():
            with patch.dict(os.environ, {}, clear=True):
                data, status = await gemini_generate("test-model", {"contents": []})
            self.assertIsNone(data)
            self.assertEqual(status, "not_configured")
        import asyncio
        asyncio.run(run_test())

    def test_single_key_success(self):
        class FakeResponse:
            status = 200
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def json(self, content_type=None):
                return {"candidates": []}

        class FakeSession:
            def __init__(self, *args, **kwargs):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            def post(self, *args, **kwargs):
                return FakeResponse()

        async def run_test():
            with patch.dict(os.environ, {"GEMINI_API_KEY": "single-key"}, clear=True):
                with patch("gemini_manager.aiohttp.ClientSession", FakeSession):
                    data, status = await gemini_generate("test-model", {"contents": []})
            self.assertEqual(status, "ok")
            self.assertEqual(data, {"candidates": []})
            self.assertEqual(gemini_manager._STATE["single-key"]["success"], 1)
        import asyncio
        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
