import unittest
from unittest.mock import patch

from scripts import vibe_tracker


class CodexAccountUsageTests(unittest.TestCase):
    def test_retries_transient_failures(self):
        usage = {"summary": {"lifetimeTokens": 123}}
        side_effects = [RuntimeError("temporary"), TimeoutError(), usage]

        with patch.object(
            vibe_tracker,
            "_get_codex_account_usage_once",
            side_effect=side_effects,
        ) as request_usage:
            with patch.object(vibe_tracker.time, "sleep"):
                result = vibe_tracker.get_codex_account_usage()

        self.assertEqual(result, usage)
        self.assertEqual(request_usage.call_count, 3)


if __name__ == "__main__":
    unittest.main()
