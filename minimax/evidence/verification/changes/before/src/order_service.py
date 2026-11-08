"""Order amount range filtering; the delivered baseline excludes equal boundaries."""


def select_orders(orders, *, status=None, min_amount_cents=None, max_amount_cents=None):
    for bound in (min_amount_cents, max_amount_cents):
        if bound is not None and (type(bound) is not int or bound < 0):
            raise ValueError("amount boundaries must be nonnegative integers")
    if min_amount_cents is not None and max_amount_cents is not None and min_amount_cents > max_amount_cents:
        raise ValueError("minimum amount cannot exceed maximum amount")
    selected = []
    for order in orders:
        if status is not None and order["status"] != status:
            continue
        if min_amount_cents is not None and order["amount_cents"] <= min_amount_cents:
            continue
        if max_amount_cents is not None and order["amount_cents"] >= max_amount_cents:
            continue
        selected.append(dict(order))
    return sorted(selected, key=lambda order: order["id"])
