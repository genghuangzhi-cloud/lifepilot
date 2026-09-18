from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator


TaskStatus = Literal["inbox", "planned", "in_progress", "completed", "skipped", "blocked", "overdue"]
TaskKind = Literal["fixed_event", "flexible_task", "habit"]
DurationSource = Literal["explicit", "estimated", "default", "unknown"]
# These are the event transitions implemented by the API.  Keeping the
# contract aligned with the state machine prevents silently recorded no-op
# events that would otherwise look successful to clients.
EventType = Literal["complete", "delay", "skip"]


class TaskCreate(BaseModel):
    # Extraction clients send the generated id back when persisting a batch.
    # Keeping it stable preserves dependency_ids between extraction and save.
    id: UUID | None = None
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    urgency: int = Field(default=3, ge=1, le=5)
    importance: int = Field(default=3, ge=1, le=5)
    deadline: datetime | None = None
    estimated_minutes: int | None = Field(default=30, ge=15, le=24 * 60)
    remaining_minutes: int | None = Field(default=None, ge=0, le=24 * 60)
    splittable: bool = True
    dependency_ids: list[UUID] = Field(default_factory=list)
    source_text: str = ""
    # Extraction metadata used by the agent pipeline.  Defaults preserve the
    # original manual-task API while making assumptions explicit for demos.
    kind: TaskKind = "flexible_task"
    start_time: datetime | None = None
    end_time: datetime | None = None
    duration_source: DurationSource = "estimated"
    confidence: float = Field(default=0.65, ge=0, le=1)
    assumptions: list[str] = Field(default_factory=list)
    @model_validator(mode="after")
    def validate_start_time(self) -> "TaskCreate":
        if self.start_time is not None and (self.start_time.tzinfo is None or self.start_time.utcoffset() is None):
            raise ValueError("start_time must include a timezone offset")
        if self.end_time is not None and (self.end_time.tzinfo is None or self.end_time.utcoffset() is None):
            raise ValueError("end_time must include a timezone offset")
        if self.start_time is not None and self.end_time is not None and self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class Task(TaskCreate):
    id: UUID = Field(default_factory=uuid4)
    status: TaskStatus = "inbox"
    priority_score: float = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def effective_remaining(self) -> int:
        return self.remaining_minutes if self.remaining_minutes is not None else (self.estimated_minutes or 30)


class TaskPatch(BaseModel):
    status: TaskStatus | None = None
    remaining_minutes: int | None = Field(default=None, ge=0, le=24 * 60)
    urgency: int | None = Field(default=None, ge=1, le=5)
    importance: int | None = Field(default=None, ge=1, le=5)


class AvailabilityWindow(BaseModel):
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def validate_window(self) -> "AvailabilityWindow":
        for label, value in (("start", self.start), ("end", self.end)):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"availability {label} must include a timezone offset")
        if self.end <= self.start:
            raise ValueError("availability end must be after start")
        return self


class PlanItem(BaseModel):
    task_id: UUID
    start: datetime
    end: datetime
    state: Literal["planned", "moved", "frozen", "done"] = "planned"
    reason: str = ""


class UnscheduledItem(BaseModel):
    task_id: UUID
    reason: str


class Plan(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    version: int = 1
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    timezone: str = "Asia/Shanghai"
    task_ids: list[UUID] = Field(default_factory=list)
    windows: list[AvailabilityWindow] = Field(default_factory=list)
    items: list[PlanItem] = Field(default_factory=list)
    unscheduled: list[UnscheduledItem] = Field(default_factory=list)
    rationale: list[str] = Field(default_factory=list)


class ExtractRequest(BaseModel):
    text: str = Field(min_length=1)
    now: datetime | None = None
    timezone: str = "Asia/Shanghai"

    @model_validator(mode="after")
    def validate_text_not_blank(self) -> "ExtractRequest":
        if not self.text.strip():
            raise ValueError("text must not be blank")
        return self


class ParserEventDebug(BaseModel):
    task_id: UUID
    raw_text: str = ""
    title: str
    kind: TaskKind
    start_time: datetime | None = None
    end_time: datetime | None = None
    deadline: datetime | None = None
    duration_minutes: int | None = None
    duration_source: DurationSource = "unknown"
    dependency_ids: list[UUID] = Field(default_factory=list)
    temporal_constraints: list[dict[str, str]] = Field(default_factory=list)
    confidence: float
    validation: Literal["ok", "needs_start_time", "needs_time", "invalid"]


class ExtractResponse(BaseModel):
    tasks: list[Task]
    assumptions: list[str] = Field(default_factory=list)
    provider: Literal["fallback"] = "fallback"
    parser_version: str = "multi-event-v1"
    date_context: date | None = None
    timezone: str = "Asia/Shanghai"
    events: list[ParserEventDebug] = Field(default_factory=list)
    # Coverage telemetry prevents actionable text from disappearing silently
    # between extraction and task construction.
    detected_actionable_spans: int = 0
    parsed_actionable_spans: int = 0
    unparsed_actionable_spans: list[str] = Field(default_factory=list)


class GeneratePlanRequest(BaseModel):
    task_ids: list[UUID] = Field(default_factory=list)
    windows: list[AvailabilityWindow] = Field(default_factory=list)
    now: datetime | None = None
    timezone: str = "Asia/Shanghai"


class EventRequest(BaseModel):
    task_id: UUID
    type: EventType
    minutes: int = Field(default=0, ge=0, le=24 * 60)
    note: str = ""
    at: datetime | None = None


class ReplanResponse(BaseModel):
    plan: Plan
    changes: list[str] = Field(default_factory=list)
    explanation: str
