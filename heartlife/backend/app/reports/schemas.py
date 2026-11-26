from __future__ import annotations

from pydantic import BaseModel


class PlanDueItem(BaseModel):
    id: str
    title: str
    completed: bool


class PlansSummary(BaseModel):
    due_count: int
    completed_count: int
    items: list[PlanDueItem]


class TodayJournalSummary(BaseModel):
    recorded: bool
    local_date: str
    sleep_minutes: int | None
    activity_minutes: int | None
    mood: str | None
    symptom_tags: list[str]


class SleepSummary(BaseModel):
    valid_days: int
    mean_minutes: float | None


class ActivitySummary(BaseModel):
    valid_days: int
    total_minutes: int | None


class WeeklyPlansSummary(BaseModel):
    due: int
    completed: int
    completion_rate: float | None
