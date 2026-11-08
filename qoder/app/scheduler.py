"""Deterministic review scheduling logic.

Priority rules (explainable, no ML):
1. Cards assessed as "needs_work" come first, sorted by earliest review date
   (longest time since last attempt first), then by card.id for stability.
2. Cards assessed as "mastered" that are due (last review >= 3 days ago) come
   next, sorted by longest time since review first, then card.id.
3. Cards never reviewed come last, sorted by difficulty descending, then card.id.
4. The plan respects a daily_minutes budget when provided; a single card that
   exceeds the remaining budget is still included so the user can review it,
   but no further cards are added after that overshoot.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from app.cards import BUILTIN_CARDS
from app.models import ReviewCard, ScheduleItem, SelfAssessment, StudyPlan


MASTERED_DEFER_DAYS = 3
_MINUTES_PER_DIFFICULTY = 2


def _parse_date(value: str) -> Optional[date]:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _parse_datetime(value: str) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _card_by_id(card_id: str) -> Optional[ReviewCard]:
    for card in BUILTIN_CARDS:
        if card.id == card_id:
            return card
    return None


def _record_sort_key(rec: dict) -> tuple:
    """Produce a comparable sort key for a record. Prefer created_at, fall back to date."""
    created_at = _parse_datetime(rec.get("created_at", ""))
    if created_at is not None:
        return (1, created_at, "")
    rec_date = _parse_date(rec.get("date", ""))
    if rec_date is not None:
        return (0, datetime.combine(rec_date, datetime.min.time()), rec.get("record_id", ""))
    return (-1, datetime.min, rec.get("record_id", ""))


def _latest_record_per_card(records: list[dict]) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for rec in records:
        card_id = rec.get("card_id")
        if not card_id:
            continue
        existing = latest.get(card_id)
        if existing is None:
            latest[card_id] = rec
        else:
            if _record_sort_key(rec) > _record_sort_key(existing):
                latest[card_id] = rec
    return latest


def _estimate_minutes(card: ReviewCard) -> int:
    return max(1, card.difficulty) * _MINUTES_PER_DIFFICULTY


def compute_schedule(
    records: list[dict],
    today: Optional[date] = None,
    max_items: int = 10,
    daily_minutes: Optional[int] = None,
) -> StudyPlan:
    if today is None:
        today = date.today()

    latest_by_card = _latest_record_per_card(records)

    never_reviewed: list[ScheduleItem] = []
    needs_work: list[ScheduleItem] = []
    mastered_due: list[ScheduleItem] = []

    for card in BUILTIN_CARDS:
        last_rec = latest_by_card.get(card.id)
        if last_rec is None:
            never_reviewed.append(ScheduleItem(
                card=card,
                priority="new",
                reason="尚未复习过，按难度从高到低排列",
            ))
            continue

        assessment = last_rec.get("assessment")
        last_date = _parse_date(last_rec.get("date", ""))

        if assessment == SelfAssessment.NEEDS_WORK.value:
            days_text = f"上次复习: {last_date}" if last_date else "上次复习: 未知"
            needs_work.append(ScheduleItem(
                card=card,
                priority="needs_work",
                reason=f"上次自评为「需加强」，{days_text}，优先复习",
                last_assessment=SelfAssessment.NEEDS_WORK,
                last_review_date=str(last_date) if last_date else None,
            ))
        elif assessment == SelfAssessment.MASTERED.value:
            if last_date and (today - last_date).days >= MASTERED_DEFER_DAYS:
                mastered_due.append(ScheduleItem(
                    card=card,
                    priority="mastered_due",
                    reason=f"上次自评为「已掌握」，距今 {(today - last_date).days} 天，可以复习巩固",
                    last_assessment=SelfAssessment.MASTERED,
                    last_review_date=str(last_date),
                ))

    never_reviewed.sort(key=lambda item: (-item.card.difficulty, item.card.id))
    needs_work.sort(key=lambda item: (
        item.last_review_date or "9999-12-31",
        item.card.id,
    ))
    mastered_due.sort(key=lambda item: (
        -(today - _parse_date(item.last_review_date or str(today))).days,
        item.card.id,
    ))

    ordered = needs_work + mastered_due + never_reviewed

    selected: list[ScheduleItem] = []
    budget_remaining = daily_minutes
    for item in ordered:
        if len(selected) >= max_items:
            break
        card_minutes = _estimate_minutes(item.card)

        if budget_remaining is not None:
            if len(selected) == 0:
                # First card: always include, even if it exceeds budget
                selected.append(item)
                budget_remaining -= card_minutes
            elif card_minutes <= budget_remaining:
                # Subsequent cards: only include if they fit within budget
                selected.append(item)
                budget_remaining -= card_minutes
            else:
                # Card doesn't fit, stop adding
                break
        else:
            # No budget constraint
            selected.append(item)

    total_minutes = sum(_estimate_minutes(item.card) for item in selected)

    memory_refs: list[dict] = []
    for rec in records:
        if rec.get("_artifact_id"):
            memory_refs.append({
                "artifact_id": rec["_artifact_id"],
                "revision": rec.get("_revision", 0),
                "state": rec.get("_state", "active"),
                "state_version": rec.get("_state_version", 0),
            })

    return StudyPlan(
        space_id="",
        date=str(today),
        items=selected,
        total_estimated_minutes=total_minutes,
        memory_references=memory_refs[:20],
    )


def compute_next_review_date(today: Optional[date] = None, assessment: Optional[str] = None) -> str:
    if today is None:
        today = date.today()
    if assessment == SelfAssessment.NEEDS_WORK.value:
        next_date = today + timedelta(days=1)
    elif assessment == SelfAssessment.MASTERED.value:
        next_date = today + timedelta(days=MASTERED_DEFER_DAYS)
    else:
        next_date = today + timedelta(days=2)
    return str(next_date)
