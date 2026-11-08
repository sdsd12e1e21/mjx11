"""Unit tests for the review scheduling logic."""

from __future__ import annotations

from datetime import date, timedelta

from app.models import SelfAssessment
from app.scheduler import MASTERED_DEFER_DAYS, compute_next_review_date, compute_schedule


def test_empty_records_returns_all_cards_by_difficulty():
    plan = compute_schedule(records=[], today=date(2026, 11, 8))
    assert len(plan.items) > 0
    priorities = [item.priority for item in plan.items]
    assert all(p == "new" for p in priorities)

    difficulties = [item.card.difficulty for item in plan.items]
    for i in range(len(difficulties) - 1):
        assert difficulties[i] >= difficulties[i + 1]


def test_needs_work_cards_prioritized_over_new():
    records = [
        {
            "card_id": "db-btree",
            "assessment": SelfAssessment.NEEDS_WORK.value,
            "date": str(date(2026, 11, 7)),
        },
    ]
    plan = compute_schedule(records=records, today=date(2026, 11, 8))
    assert plan.items[0].card.id == "db-btree"
    assert plan.items[0].priority == "needs_work"


def test_mastered_cards_deferred_for_three_days():
    today = date(2026, 11, 8)
    records = [
        {
            "card_id": "db-btree",
            "assessment": SelfAssessment.MASTERED.value,
            "date": str(today - timedelta(days=1)),
        },
    ]
    plan = compute_schedule(records=records, today=today)
    card_ids = [item.card.id for item in plan.items]
    assert "db-btree" not in card_ids


def test_mastered_cards_return_after_deferral():
    today = date(2026, 11, 8)
    records = [
        {
            "card_id": "db-btree",
            "assessment": SelfAssessment.MASTERED.value,
            "date": str(today - timedelta(days=MASTERED_DEFER_DAYS)),
        },
    ]
    plan = compute_schedule(records=records, today=today)
    card_ids = [item.card.id for item in plan.items]
    assert "db-btree" in card_ids
    btree_item = next(item for item in plan.items if item.card.id == "db-btree")
    assert btree_item.priority == "mastered_due"


def test_needs_work_sorted_by_oldest_first():
    today = date(2026, 11, 8)
    records = [
        {
            "card_id": "db-btree",
            "assessment": SelfAssessment.NEEDS_WORK.value,
            "date": str(today - timedelta(days=1)),
        },
        {
            "card_id": "db-transaction-acid",
            "assessment": SelfAssessment.NEEDS_WORK.value,
            "date": str(today - timedelta(days=5)),
        },
    ]
    plan = compute_schedule(records=records, today=today)
    needs_work_items = [item for item in plan.items if item.priority == "needs_work"]
    assert len(needs_work_items) == 2
    assert needs_work_items[0].card.id == "db-transaction-acid"


def test_latest_record_wins_for_same_card():
    today = date(2026, 11, 8)
    records = [
        {
            "card_id": "db-btree",
            "assessment": SelfAssessment.NEEDS_WORK.value,
            "date": str(today - timedelta(days=5)),
        },
        {
            "card_id": "db-btree",
            "assessment": SelfAssessment.MASTERED.value,
            "date": str(today - timedelta(days=1)),
        },
    ]
    plan = compute_schedule(records=records, today=today)
    card_ids = [item.card.id for item in plan.items]
    assert "db-btree" not in card_ids


def test_max_items_limits_plan_size():
    plan = compute_schedule(records=[], today=date(2026, 11, 8), max_items=3)
    assert len(plan.items) == 3


def test_total_estimated_minutes_scales_with_difficulty():
    plan = compute_schedule(records=[], today=date(2026, 11, 8), max_items=5)
    expected = sum(max(1, item.card.difficulty) * 2 for item in plan.items)
    assert plan.total_estimated_minutes == expected


def test_next_review_date_needs_work_is_one_day():
    today = date(2026, 11, 8)
    result = compute_next_review_date(today, SelfAssessment.NEEDS_WORK.value)
    assert result == str(today + timedelta(days=1))


def test_next_review_date_mastered_is_three_days():
    today = date(2026, 11, 8)
    result = compute_next_review_date(today, SelfAssessment.MASTERED.value)
    assert result == str(today + timedelta(days=MASTERED_DEFER_DAYS))


def test_corrupt_date_in_record_does_not_crash():
    records = [
        {
            "card_id": "db-btree",
            "assessment": SelfAssessment.NEEDS_WORK.value,
            "date": "not-a-date",
        },
    ]
    plan = compute_schedule(records=records, today=date(2026, 11, 8))
    assert len(plan.items) > 0


def test_record_without_card_id_is_ignored():
    records = [
        {
            "assessment": SelfAssessment.NEEDS_WORK.value,
            "date": "2026-11-07",
        },
    ]
    plan = compute_schedule(records=records, today=date(2026, 11, 8))
    all_ids = [item.card.id for item in plan.items]
    assert len(all_ids) == len(set(all_ids))


def test_needs_work_before_mastered_due():
    """Regression: needs_work cards must appear before mastered_due cards."""
    today = date(2026, 11, 8)
    records = [
        {
            "card_id": "db-btree",
            "assessment": SelfAssessment.MASTERED.value,
            "date": str(today - timedelta(days=MASTERED_DEFER_DAYS)),
        },
        {
            "card_id": "db-transaction-acid",
            "assessment": SelfAssessment.NEEDS_WORK.value,
            "date": str(today - timedelta(days=1)),
        },
    ]
    plan = compute_schedule(records=records, today=today)
    priorities = [item.priority for item in plan.items]
    first_needs_work = priorities.index("needs_work")
    first_mastered_due = priorities.index("mastered_due")
    assert first_needs_work < first_mastered_due


def test_mastered_due_before_new_cards():
    """Regression: mastered_due cards must appear before never-reviewed cards."""
    today = date(2026, 11, 8)
    records = [
        {
            "card_id": "db-btree",
            "assessment": SelfAssessment.MASTERED.value,
            "date": str(today - timedelta(days=MASTERED_DEFER_DAYS)),
        },
    ]
    plan = compute_schedule(records=records, today=today, max_items=12)
    priorities = [item.priority for item in plan.items]
    first_mastered_due = priorities.index("mastered_due")
    first_new = priorities.index("new")
    assert first_mastered_due < first_new


def test_daily_minutes_budget_limits_plan():
    """Regression: daily_minutes should cap the plan size."""
    plan_unlimited = compute_schedule(records=[], today=date(2026, 11, 8), max_items=12)
    plan_budget = compute_schedule(records=[], today=date(2026, 11, 8), max_items=12, daily_minutes=10)
    assert plan_budget.total_estimated_minutes <= plan_unlimited.total_estimated_minutes
    assert len(plan_budget.items) < len(plan_unlimited.items)


def test_daily_minutes_includes_one_overshoot_card():
    """A single card that exceeds remaining budget is still included (first card exception)."""
    today = date(2026, 11, 8)
    records = [
        {
            "card_id": "db-distributed-cap",
            "assessment": SelfAssessment.NEEDS_WORK.value,
            "date": str(today - timedelta(days=1)),
        },
    ]
    plan = compute_schedule(records=records, today=today, max_items=12, daily_minutes=2)
    assert len(plan.items) >= 1
    assert plan.items[0].card.id == "db-distributed-cap"
    assert plan.items[0].priority == "needs_work"


def test_daily_minutes_no_overshoot_for_subsequent_cards():
    """Subsequent cards must not exceed the remaining budget."""
    today = date(2026, 11, 8)
    # db-distributed-cap has difficulty 5, so 10 minutes estimated
    # db-btree has difficulty 3, so 6 minutes estimated
    records = [
        {
            "card_id": "db-distributed-cap",
            "assessment": SelfAssessment.NEEDS_WORK.value,
            "date": str(today - timedelta(days=2)),
        },
        {
            "card_id": "db-btree",
            "assessment": SelfAssessment.NEEDS_WORK.value,
            "date": str(today - timedelta(days=1)),
        },
    ]
    # Budget is 12 minutes: first card (10 min) fits, second card (6 min) would exceed remaining 2 min
    plan = compute_schedule(records=records, today=today, max_items=12, daily_minutes=12)
    assert len(plan.items) == 1
    assert plan.items[0].card.id == "db-distributed-cap"
    assert plan.total_estimated_minutes == 10


def test_daily_minutes_allows_multiple_cards_within_budget():
    """Multiple cards can be included if they all fit within budget."""
    today = date(2026, 11, 8)
    # db-sql-join has difficulty 2, so 4 minutes estimated
    # db-transaction-acid has difficulty 2, so 4 minutes estimated
    records = [
        {
            "card_id": "db-sql-join",
            "assessment": SelfAssessment.NEEDS_WORK.value,
            "date": str(today - timedelta(days=2)),
        },
        {
            "card_id": "db-transaction-acid",
            "assessment": SelfAssessment.NEEDS_WORK.value,
            "date": str(today - timedelta(days=1)),
        },
    ]
    # Budget is 10 minutes: both cards (4+4=8 min) fit
    plan = compute_schedule(records=records, today=today, max_items=12, daily_minutes=10)
    assert len(plan.items) == 2
    assert plan.total_estimated_minutes == 8


def test_same_day_records_use_created_at():
    """Regression: when two records share the same date, created_at breaks the tie."""
    today = date(2026, 11, 8)
    records = [
        {
            "card_id": "db-btree",
            "assessment": SelfAssessment.NEEDS_WORK.value,
            "date": str(today - timedelta(days=1)),
            "created_at": "2026-11-07T10:00:00Z",
        },
        {
            "card_id": "db-btree",
            "assessment": SelfAssessment.MASTERED.value,
            "date": str(today - timedelta(days=1)),
            "created_at": "2026-11-07T18:00:00Z",
        },
    ]
    plan = compute_schedule(records=records, today=today)
    card_ids = [item.card.id for item in plan.items]
    assert "db-btree" not in card_ids


def test_same_day_records_created_at_tiebreaker_needs_work():
    """If the latest same-day record is needs_work, the card should appear."""
    today = date(2026, 11, 8)
    records = [
        {
            "card_id": "db-btree",
            "assessment": SelfAssessment.MASTERED.value,
            "date": str(today - timedelta(days=1)),
            "created_at": "2026-11-07T10:00:00Z",
        },
        {
            "card_id": "db-btree",
            "assessment": SelfAssessment.NEEDS_WORK.value,
            "date": str(today - timedelta(days=1)),
            "created_at": "2026-11-07T18:00:00Z",
        },
    ]
    plan = compute_schedule(records=records, today=today)
    needs_work_items = [item for item in plan.items if item.priority == "needs_work"]
    assert len(needs_work_items) == 1
    assert needs_work_items[0].card.id == "db-btree"
