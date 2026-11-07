# Order filtering specification / 订单筛选规格

Version: 1
Keywords: orders amount range inclusive boundaries

## ORD-001: 金额必须为闭区间

`select_orders` 使用整数分 `amount_cents`，金额范围必须满足
`min_amount_cents <= amount_cents <= max_amount_cents`。
省略某一边界表示该侧不受限制。相等的上下界不是空区间。
金额为 0 的订单也遵守同一规则。

## ORD-002: 组合筛选与兼容性

`status` 精确匹配，与金额条件取交集。省略所有筛选条件时返回全部订单。
结果按整数订单 ID 升序排列。输入记录及其原有顺序不能被修改。

## ORD-003: 无效输入

边界不能为负数、布尔值或非整数。最小金额大于最大金额时抛出 `ValueError`。
无匹配结果时返回空列表，不制造占位订单。

## Sources

- 业务入口：`src/order_service.py::select_orders`
- 新功能验证：`tests/test_target.py`
- 兼容性验证：`tests/test_regression.py`

