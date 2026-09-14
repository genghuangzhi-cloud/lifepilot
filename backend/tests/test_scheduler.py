import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.schemas import AvailabilityWindow, Task
from app.scheduler import priority_score, schedule_tasks


def test_deadline_and_urgency_raise_priority():
    now = datetime(2026, 9, 14, 8, tzinfo=timezone.utc)
    urgent = Task(title="exam", urgency=5, importance=5, deadline=now + timedelta(hours=1), estimated_minutes=30)
    routine = Task(title="shopping", urgency=2, importance=2, estimated_minutes=30)
    assert priority_score(urgent, now) > priority_score(routine, now)


def test_capacity_overflow_is_explicit():
    now = datetime(2026, 9, 14, 8, tzinfo=timezone.utc)
    tasks = [Task(title="long", estimated_minutes=120), Task(title="second", estimated_minutes=60)]
    plan = schedule_tasks(tasks, [AvailabilityWindow(start=now, end=now + timedelta(minutes=90))], now=now)
    assert sum(int((item.end - item.start).total_seconds() // 60) for item in plan.items) <= 90
    assert len(plan.unscheduled) == 1


def test_deadline_is_never_violated():
    now = datetime(2026, 9, 14, 8, tzinfo=timezone.utc)
    task = Task(title="deadline", estimated_minutes=60, deadline=now + timedelta(minutes=30), splittable=False)
    plan = schedule_tasks([task], [AvailabilityWindow(start=now, end=now + timedelta(hours=2))], now=now)
    assert plan.unscheduled


def test_dependencies_are_scheduled_in_order():
    now = datetime(2026, 9, 14, 8, tzinfo=timezone.utc)
    prerequisite = Task(title="prepare", estimated_minutes=30)
    dependent = Task(title="practice", estimated_minutes=30, dependency_ids=[prerequisite.id])
    plan = schedule_tasks([dependent, prerequisite], [AvailabilityWindow(start=now, end=now + timedelta(hours=2))], now=now)
    blocks = {item.task_id: item for item in plan.items}
    assert blocks[prerequisite.id].end <= blocks[dependent.id].start

def test_planning_does_not_mark_work_as_completed():
    now = datetime(2026, 9, 14, 8, tzinfo=timezone.utc)
    task = Task(title="long", estimated_minutes=120)
    plan = schedule_tasks([task], [AvailabilityWindow(start=now, end=now + timedelta(minutes=90))], now=now)
    assert plan.unscheduled
    assert task.effective_remaining() == 120


def test_unsplittable_task_is_not_cut_at_deadline():
    now = datetime(2026, 9, 14, 8, tzinfo=timezone.utc)
    task = Task(title="focus", estimated_minutes=60, deadline=now + timedelta(minutes=30), splittable=False)
    plan = schedule_tasks([task], [AvailabilityWindow(start=now, end=now + timedelta(hours=2))], now=now)
    assert plan.unscheduled
    assert not plan.items
