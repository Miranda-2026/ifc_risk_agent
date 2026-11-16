"""Guard financial settings and dashboard URLs without a Databricks connection."""

import math
import unittest

from agent_server.ui_contract import dashboard_url, normalize_weights


class UIContractTest(unittest.TestCase):
    def test_normalize_custom_weights_without_replacing_them(self):
        self.assertEqual(normalize_weights(dict(disbursed=1, risk=2, environmental=3, product=4)),
                         dict(disbursed=10, risk=20, environmental=30, product=40))

    def test_reject_invalid_weights(self):
        for value in [dict.fromkeys(("disbursed", "risk", "environmental", "product"), 0),
                      dict(disbursed=-1, risk=1, environmental=1, product=1),
                      dict(disbursed=math.nan, risk=1, environmental=1, product=1),
                      dict(disbursed=math.inf, risk=1, environmental=1, product=1),
                      dict(disbursed=True, risk=1, environmental=1, product=1),
                      dict(disbursed="25", risk=25, environmental=25, product=25),
                      dict(disbursed=1)]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_weights(value)

    def test_very_large_finite_weights_do_not_overflow(self):
        result = normalize_weights(dict(disbursed=1e308, risk=1e308, environmental=1e308, product=1e308))
        self.assertEqual(list(result.values()), [25, 25, 25, 25])

    def test_dashboard_is_optional_and_only_allows_https(self):
        self.assertEqual(dashboard_url("https://example.com/dashboard?id=1"), "https://example.com/dashboard?id=1")
        for url in [None, "", "javascript:alert(1)", "data:text/html,test", "http://example.com", "//example.com", "https://user:pass@example.com", "https://["]:
            with self.subTest(url=url):
                self.assertIsNone(dashboard_url(url))


if __name__ == "__main__":
    unittest.main()
