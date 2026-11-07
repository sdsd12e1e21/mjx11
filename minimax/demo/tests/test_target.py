"""Target behavior: orders amount range inclusive boundaries."""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from order_service import select_orders  # noqa: E402 - standalone unittest project

ORDERS = json.loads((ROOT / "data/orders.json").read_text(encoding="utf-8"))


class InclusiveAmountRangeTests(unittest.TestCase):
    def test_both_amount_boundaries_are_inclusive(self):
        result = select_orders(ORDERS, min_amount_cents=1000, max_amount_cents=3000)
        self.assertEqual([order["id"] for order in result], [2, 3, 4, 5])

    def test_equal_amount_bounds_with_status_filter(self):
        result = select_orders(ORDERS, status="paid", min_amount_cents=2000, max_amount_cents=2000)
        self.assertEqual([order["id"] for order in result], [3])

    def test_zero_amount_equal_bounds(self):
        result = select_orders(ORDERS, min_amount_cents=0, max_amount_cents=0)
        self.assertEqual([order["id"] for order in result], [1])


if __name__ == "__main__":
    unittest.main()
