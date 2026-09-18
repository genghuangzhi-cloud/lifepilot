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


def test_fixed_event_is_frozen_and_carves_capacity():
    now = datetime(2026, 9, 14, 8, tzinfo=timezone.utc)
    fixed = Task(
        title="lecture",
        kind="fixed_event",
        start_time=now + timedelta(hours=1),
        end_time=now + timedelta(hours=2),
        estimated_minutes=60,
    )
    flexible = Task(title="study", estimated_minutes=120)
    plan = schedule_tasks(
        [flexible, fixed],
        [AvailabilityWindow(start=now, end=now + timedelta(hours=4))],
        now=now,
    )
    fixed_item = next(item for item in plan.items if item.task_id == fixed.id)
    assert fixed_item.state == "frozen"
    assert fixed_item.start == fixed.start_time
    assert all(
        item.task_id == fixed.id or item.end <= fixed_item.start or item.start >= fixed_item.end
        for item in plan.items
    )


def test_missing_dependency_is_explicitly_unscheduled():
    now = datetime(2026, 9, 14, 8, tzinfo=timezone.utc)
    missing = Task(title="blocked", estimated_minutes=30, dependency_ids=[Task(title="unknown").id])
    plan = schedule_tasks(
        [missing],
        [AvailabilityWindow(start=now, end=now + timedelta(hours=1))],
        now=now,
    )
    assert not plan.items
    assert plan.unscheduled[0].task_id == missing.id
    assert "missing" in plan.unscheduled[0].reason


def test_partial_fixed_event_is_not_scheduled_with_guessed_duration():
    now = datetime(2026, 9, 14, 8, tzinfo=timezone.utc)
    partial = Task(title="class", kind="fixed_event", start_time=now + timedelta(hours=1), estimated_minutes=None, duration_source="unknown")
    plan = schedule_tasks(
        [partial],
        [AvailabilityWindow(start=now, end=now + timedelta(hours=4))],
        now=now,
    )
    assert not plan.items
    assert plan.unscheduled[0].task_id == partial.id
    assert "missing an end time" in plan.unscheduled[0].reason


def test_fixed_event_prerequisite_cannot_resume_after_anchor():
    now = datetime(2026, 9, 19, 7, tzinfo=timezone(timedelta(hours=8)))
    prerequisite = Task(title="read chapter", estimated_minutes=40)
    fixed = Task(
        title="lecture",
        kind="fixed_event",
        start_time=now + timedelta(hours=1),
        end_time=now + timedelta(hours=3),
        estimated_minutes=120,
        dependency_ids=[prerequisite.id],
    )
    plan = schedule_tasks(
        [prerequisite, fixed],
        [AvailabilityWindow(start=now, end=now + timedelta(hours=14))],
        now=now,
    )
    prerequisite_items = [item for item in plan.items if item.task_id == prerequisite.id]
    assert prerequisite_items
    assert all(item.end <= fixed.start_time for item in prerequisite_items)
    assert not any(item.start >= fixed.end_time for item in prerequisite_items)


def test_prerequisite_stays_unscheduled_when_fixed_anchor_is_outside_window():
    now = datetime(2026, 9, 19, 9, tzinfo=timezone(timedelta(hours=8)))
    prerequisite = Task(title="read chapter", estimated_minutes=40)
    fixed = Task(
        title="lecture",
        kind="fixed_event",
        start_time=datetime(2026, 9, 19, 8, tzinfo=timezone(timedelta(hours=8))),
        end_time=datetime(2026, 9, 19, 10, tzinfo=timezone(timedelta(hours=8))),
        estimated_minutes=120,
        dependency_ids=[prerequisite.id],
    )
    plan = schedule_tasks(
        [prerequisite, fixed],
        [AvailabilityWindow(
            start=datetime(2026, 9, 19, 9, tzinfo=timezone(timedelta(hours=8))),
            end=datetime(2026, 9, 19, 21, tzinfo=timezone(timedelta(hours=8))),
        )],
        now=now,
    )
    assert not [item for item in plan.items if item.task_id == prerequisite.id]
    assert any(entry.task_id == prerequisite.id for entry in plan.unscheduled)
    assert any(entry.task_id == fixed.id for entry in plan.unscheduled)
