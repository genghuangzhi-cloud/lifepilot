from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .schemas import AvailabilityWindow, EventRequest, ExtractRequest, ExtractResponse, GeneratePlanRequest, Plan, ReplanResponse, Task, TaskCreate, TaskPatch
from .scheduler import fallback_extract, priority_score, schedule_tasks
from .store import SQLiteStore

app = FastAPI(title="LifePilot API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"], allow_methods=["*"], allow_headers=["*"])
STORE = SQLiteStore()

def _require_aware(value: datetime | None, label: str) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise HTTPException(status_code=422, detail=f"{label} must include a timezone offset")

def _zone_or_422(name: str):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        if name == "Asia/Shanghai":
            return timezone(timedelta(hours=8), name=name)
        raise HTTPException(status_code=422, detail=f"Unknown timezone: {name}")

def _validate_windows(windows: list[AvailabilityWindow]) -> None:
    for window in windows:
        _require_aware(window.start, "availability.start")
        _require_aware(window.end, "availability.end")
        if window.end <= window.start:
            raise HTTPException(status_code=422, detail="availability.end must be after availability.start")

@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "service": "lifepilot-api", "tasks": len(STORE.list_tasks())}

@app.post("/api/tasks/extract", response_model=ExtractResponse)
def extract(request: ExtractRequest) -> ExtractResponse:
    _require_aware(request.now, "now")
    tasks, assumptions = fallback_extract(request.text, request.now)
    now = request.now or datetime.now(timezone.utc)
    for task in tasks: task.priority_score = priority_score(task, now)
    return ExtractResponse(tasks=tasks, assumptions=assumptions)

@app.post("/api/tasks", response_model=Task)
def create_task(payload: TaskCreate) -> Task:
    _require_aware(payload.deadline, "deadline")
    task = Task(**payload.model_dump()); task.priority_score = priority_score(task, datetime.now(timezone.utc)); STORE.save_task(task); return task

@app.get("/api/tasks", response_model=list[Task])
def list_tasks() -> list[Task]: return STORE.list_tasks()

@app.get("/api/dashboard")
def dashboard() -> dict:
    tasks = STORE.list_tasks()
    return {"tasks": tasks, "metrics": {"total": len(tasks), "completed": sum(t.status == "completed" for t in tasks), "planned": sum(t.status == "planned" for t in tasks)}}

@app.patch("/api/tasks/{task_id}", response_model=Task)
def patch_task(task_id: UUID, payload: TaskPatch) -> Task:
    task = STORE.get_task(task_id)
    if not task: raise HTTPException(status_code=404, detail="Task not found")
    for key, value in payload.model_dump(exclude_unset=True).items(): setattr(task, key, value)
    task.updated_at = datetime.now(timezone.utc); task.priority_score = priority_score(task, task.updated_at); STORE.save_task(task); return task

@app.post("/api/plans/generate", response_model=Plan)
def generate_plan(request: GeneratePlanRequest) -> Plan:
    stored_tasks = STORE.list_tasks(); task_ids = request.task_ids or [t.id for t in stored_tasks]; by_id = {t.id:t for t in stored_tasks}
    missing = [i for i in task_ids if i not in by_id]
    if missing: raise HTTPException(status_code=404, detail=f"Task(s) not found: {', '.join(map(str, missing))}")
    _require_aware(request.now, "now"); zone = _zone_or_422(request.timezone); now = request.now or datetime.now(timezone.utc)
    windows = request.windows or [AvailabilityWindow(start=now.astimezone(zone).replace(hour=9, minute=0, second=0, microsecond=0), end=now.astimezone(zone).replace(hour=21, minute=0, second=0, microsecond=0))]
    _validate_windows(windows); tasks = [by_id[i] for i in task_ids]; plan = schedule_tasks(tasks, windows, now=now); plan.task_ids=list(task_ids); plan.windows=list(windows); plan.timezone=request.timezone
    scheduled={i.task_id for i in plan.items}
    incomplete={entry.task_id for entry in plan.unscheduled}
    for task in tasks:
        if task.status not in {"completed","skipped"}: task.status = "planned" if task.id in scheduled - incomplete else "inbox"
    STORE.save_tasks(tasks); STORE.save_plan(plan); return plan

@app.get("/api/plans/{plan_id}", response_model=Plan)
def get_plan(plan_id: UUID) -> Plan:
    plan=STORE.get_plan(plan_id)
    if not plan: raise HTTPException(status_code=404, detail="Plan not found")
    return plan

@app.post("/api/plans/{plan_id}/events", response_model=ReplanResponse)
def apply_event(plan_id: UUID, event: EventRequest) -> ReplanResponse:
    old_plan=STORE.get_plan(plan_id); task=STORE.get_task(event.task_id)
    if not old_plan or not task: raise HTTPException(status_code=404, detail="Plan or task not found")
    if not old_plan.task_ids or not old_plan.windows: raise HTTPException(status_code=409, detail="Generate a new plan before applying events; this older plan has no saved task membership or availability.")
    if event.task_id not in old_plan.task_ids: raise HTTPException(status_code=404, detail="Task does not belong to this plan")
    _require_aware(event.at, "event.at"); _validate_windows(old_plan.windows); now=event.at or datetime.now(timezone.utc); added=0
    if event.type=="complete": task.status="completed"; task.remaining_minutes=0
    elif event.type=="skip": task.status="skipped"
    else:
        prev=task.effective_remaining(); task.remaining_minutes=min(24*60, prev+event.minutes); added=task.remaining_minutes-prev
    task.updated_at=now; members=[task if c.id==task.id else c for c in STORE.list_tasks() if c.id in old_plan.task_ids]; new_plan=schedule_tasks(members, old_plan.windows, now=now, version=old_plan.version+1); new_plan.task_ids=list(old_plan.task_ids); new_plan.timezone=old_plan.timezone
    scheduled={i.task_id for i in new_plan.items}
    incomplete={entry.task_id for entry in new_plan.unscheduled}
    for member in members:
        if member.status not in {"completed","skipped"}: member.status="planned" if member.id in scheduled - incomplete else "inbox"
    STORE.save_tasks(members); STORE.save_plan(new_plan); STORE.save_event(plan_id,event.task_id,event.type,event.model_dump(mode="json")); changes=[f"{i.task_id}: schedule recalculated after {event.type} event" for i in new_plan.items]
    explanation=(f"Added {added} minutes of remaining work to '{task.title}' and recalculated from the update time within the plan's saved availability." if event.type=="delay" else f"The plan was recalculated after {event.type} on '{task.title}' within its saved availability. Completed and skipped tasks are excluded from the revised schedule.")
    if event.note: explanation += f" Note: {event.note}"
    return ReplanResponse(plan=new_plan, changes=changes, explanation=explanation)
