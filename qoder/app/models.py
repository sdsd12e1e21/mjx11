"""Pydantic models for the StudyRelay application."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SelfAssessment(str, Enum):
    NEEDS_WORK = "needs_work"
    MASTERED = "mastered"


class ReviewCard(BaseModel):
    id: str
    topic: str
    question: str
    answer: str
    difficulty: int = Field(default=3, ge=1, le=5)


class StudyPreferences(BaseModel):
    daily_minutes: int = Field(ge=5, le=120)
    learning_goal: str = Field(min_length=1, max_length=500)
    created_at: str
    updated_at: str


class StudyRecord(BaseModel):
    record_id: str
    date: str
    card_id: str
    assessment: SelfAssessment
    next_review_date: str
    notes: Optional[str] = None
    created_at: str
    artifact_id: Optional[str] = None
    revision: Optional[int] = None
    scope_id: Optional[str] = None


class LearningSpace(BaseModel):
    space_id: str
    name: str
    scope_id: Optional[str] = None
    is_synthetic: bool = True


class ScheduleItem(BaseModel):
    card: ReviewCard
    priority: str
    reason: str
    last_assessment: Optional[SelfAssessment] = None
    last_review_date: Optional[str] = None


class StudyPlan(BaseModel):
    space_id: str
    date: str
    items: list[ScheduleItem]
    total_estimated_minutes: int
    memory_references: list[dict] = Field(default_factory=list)


class SaveSessionRequest(BaseModel):
    card_id: str
    assessment: SelfAssessment
    notes: Optional[str] = Field(default=None, max_length=500)
    request_id: Optional[str] = Field(default=None, max_length=128)


class SaveSessionResponse(BaseModel):
    record: StudyRecord
    elapsed_ms: float
    memory_citation: dict


class SetupPreferencesRequest(BaseModel):
    daily_minutes: int = Field(ge=5, le=120)
    learning_goal: str = Field(min_length=1, max_length=500)


class ExportFormat(str, Enum):
    JSON = "json"
    MARKDOWN = "markdown"


class MemoryRef(BaseModel):
    artifact_id: str
    revision: int
    scope_id: str
    state: str
    state_version: int
