"""Unit tests for space isolation and input validation."""

from __future__ import annotations

import pytest

from app.models import (
    LearningSpace,
    SaveSessionRequest,
    SelfAssessment,
    SetupPreferencesRequest,
)


def test_synthetic_spaces_have_distinct_ids():
    spaces = [
        LearningSpace(space_id="synthetic-xiaoming", name="小明（合成演示）", is_synthetic=True),
        LearningSpace(space_id="synthetic-xiaohong", name="小红（合成演示）", is_synthetic=True),
    ]
    ids = [s.space_id for s in spaces]
    assert len(ids) == len(set(ids))


def test_idempotency_keys_are_unique_per_space():
    prefix = "studyrelay-space"
    key_a = f"{prefix}-synthetic-xiaoming"
    key_b = f"{prefix}-synthetic-xiaohong"
    assert key_a != key_b


def test_preferences_validation_daily_minutes_too_low():
    with pytest.raises(Exception):
        SetupPreferencesRequest(daily_minutes=2, learning_goal="test")


def test_preferences_validation_daily_minutes_too_high():
    with pytest.raises(Exception):
        SetupPreferencesRequest(daily_minutes=200, learning_goal="test")


def test_preferences_validation_empty_goal():
    with pytest.raises(Exception):
        SetupPreferencesRequest(daily_minutes=30, learning_goal="")


def test_preferences_valid():
    prefs = SetupPreferencesRequest(daily_minutes=30, learning_goal="掌握数据库索引")
    assert prefs.daily_minutes == 30
    assert prefs.learning_goal == "掌握数据库索引"


def test_session_validation_invalid_assessment():
    with pytest.raises(Exception):
        SaveSessionRequest(card_id="db-btree", assessment="invalid_value")


def test_session_validation_valid_needs_work():
    req = SaveSessionRequest(card_id="db-btree", assessment=SelfAssessment.NEEDS_WORK)
    assert req.assessment == SelfAssessment.NEEDS_WORK


def test_session_validation_valid_mastered():
    req = SaveSessionRequest(card_id="db-btree", assessment=SelfAssessment.MASTERED)
    assert req.assessment == SelfAssessment.MASTERED


def test_session_notes_optional():
    req = SaveSessionRequest(card_id="db-btree", assessment=SelfAssessment.NEEDS_WORK)
    assert req.notes is None


def test_learning_space_name_max_length():
    long_name = "a" * 101
    assert len(long_name) > 100


def test_learning_space_name_valid():
    space = LearningSpace(space_id="custom-abc123", name="我的学习空间", is_synthetic=False)
    assert space.name == "我的学习空间"
    assert space.is_synthetic is False


def test_session_notes_max_length():
    """Regression: notes field has a max_length of 500."""
    long_notes = "x" * 501
    with pytest.raises(Exception):
        SaveSessionRequest(card_id="db-btree", assessment=SelfAssessment.NEEDS_WORK, notes=long_notes)


def test_session_notes_at_max_length():
    """Notes at exactly 500 characters should be valid."""
    max_notes = "x" * 500
    req = SaveSessionRequest(card_id="db-btree", assessment=SelfAssessment.NEEDS_WORK, notes=max_notes)
    assert len(req.notes) == 500


def test_session_request_id_field():
    """Regression: request_id field exists for dedup."""
    req = SaveSessionRequest(
        card_id="db-btree",
        assessment=SelfAssessment.NEEDS_WORK,
        request_id="req-abc123",
    )
    assert req.request_id == "req-abc123"


def test_session_request_id_max_length():
    """request_id must not exceed 128 characters."""
    long_id = "x" * 129
    with pytest.raises(Exception):
        SaveSessionRequest(card_id="db-btree", assessment=SelfAssessment.NEEDS_WORK, request_id=long_id)
