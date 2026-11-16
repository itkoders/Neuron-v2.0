import os
import unittest
from unittest.mock import patch

from gemini_manager import _configured_keys


class GeminiKeyConfigTests(unittest.TestCase):
    def test_reads_comma_and_newline_separated_keys(self):
        with patch.dict(os.environ, {
            "GEMINI_API_KEYS": "key-one, key-two\\nkey-three",
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


if __name__ == "__main__":
    unittest.main()
