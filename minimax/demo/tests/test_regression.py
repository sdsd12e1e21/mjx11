"""Existing orders amount range behavior that the fix must preserve."""

import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from order_service import select_orders  # noqa: E402 - standalone unittest project

ORDERS = json.loads((ROOT / "data/orders.json").read_text(encoding="utf-8"))


class ExistingOrderBehaviorTests(unittest.TestCase):
    def test_no_filters_returns_all_in_id_order(self):
        self.assertEqual([order["id"] for order in select_orders(ORDERS)], [1, 2, 3, 4, 5])

    def test_status_filter_is_exact(self):
        self.assertEqual([order["id"] for order in select_orders(ORDERS, status="paid")], [2, 3, 5])

    def test_input_records_are_not_mutated(self):
        before = deepcopy(ORDERS)
        result = select_orders(ORDERS)
        result[0]["status"] = "changed"
        self.assertEqual(ORDERS, before)

    def test_empty_result(self):
        self.assertEqual(select_orders(ORDERS, status="unknown"), [])

    def test_reversed_amount_range_is_rejected(self):
        with self.assertRaises(ValueError):
            select_orders(ORDERS, min_amount_cents=3000, max_amount_cents=1000)

    def test_invalid_amount_bounds_are_rejected(self):
        for value in (-1, True, 1.5, "1000"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                select_orders(ORDERS, min_amount_cents=value)


if __name__ == "__main__":
    unittest.main()
