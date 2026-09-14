from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable

from .schemas import AvailabilityWindow, Plan, PlanItem, Task, UnscheduledItem


def _deadline_score(deadline: datetime | None, now: datetime) -> float:
    if deadline is None:
        return 20.0
    hours = (deadline - now).total_seconds() / 3600
    if hours <= 2:
        return 100.0
    if hours <= 24:
        return 85.0
    if hours <= 72:
        return 65.0
    return max(20.0, 65.0 - min(hours / 24, 30.0))


def priority_score(task: Task, now: datetime, blocker_count: int = 0) -> float:
    urgency = (task.urgency - 1) / 4 * 100
    importance = (task.importance - 1) / 4 * 100
    deadline = _deadline_score(task.deadline, now)
    blocker = min(100.0, blocker_count * 25.0)
    effort_fit = max(0.0, 100.0 - task.effective_remaining() / 8.0)
    return round(0.30 * urgency + 0.25 * importance + 0.30 * deadline + 0.10 * blocker + 0.05 * effort_fit, 2)


def _task_sort_key(task: Task, now: datetime, blockers: dict) -> tuple:
    deadline = task.deadline or datetime.max.replace(tzinfo=timezone.utc)
    return (-priority_score(task, now, blockers.get(task.id, 0)), deadline, -task.importance, task.effective_remaining())


def _topological_ready(tasks: list[Task], now: datetime, blockers: dict) -> tuple[list[Task], set]:
    remaining = {task.id: task for task in tasks}
    completed: set = set()
    ordered: list[Task] = []
    while remaining:
        ready = [t for t in remaining.values() if all(dep in completed or dep not in remaining for dep in t.dependency_ids)]
        if not ready:
            return ordered, set(remaining)
        for task in sorted(ready, key=lambda t: _task_sort_key(t, now, blockers)):
            ordered.append(task)
            completed.add(task.id)
            remaining.pop(task.id, None)
    return ordered, set()


def schedule_tasks(tasks: Iterable[Task], windows: Iterable[AvailabilityWindow], now: datetime | None = None, version: int = 1) -> Plan:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must include a timezone offset")
    all_tasks = list(tasks)
    windows = list(windows)
    task_list = [t for t in all_tasks if t.status not in {"completed", "skipped"}]
    blocker_counts = {t.id: sum(t.id in other.dependency_ids for other in task_list) for t in task_list}
    ordered, cycles = _topological_ready(task_list, now, blocker_counts)
    if cycles:
        ordered.extend(t for t in task_list if t.id in cycles)

    normalized_windows: list[tuple[datetime, datetime]] = []
    for window in windows:
        start, end = window.start, window.end
        if start.tzinfo is None or start.utcoffset() is None or end.tzinfo is None or end.utcoffset() is None:
            raise ValueError("availability windows must include timezone offsets")
        if end <= start:
            raise ValueError("availability end must be after start")
    for start, end in sorted(((w.start, w.end) for w in windows), key=lambda pair: pair[0]):
        if normalized_windows and start <= normalized_windows[-1][1]:
            normalized_windows[-1] = (normalized_windows[-1][0], max(normalized_windows[-1][1], end))
        else:
            normalized_windows.append((start, end))
    slots = list(normalized_windows)
    items: list[PlanItem] = []
    unscheduled: list[UnscheduledItem] = []
    scheduled_task_ids: set = set()
    end_by_task: dict = {}
    for task in ordered:
        remaining = task.effective_remaining()
        original_remaining = remaining
        missing_dependencies = [dep for dep in task.dependency_ids if dep in {candidate.id for candidate in task_list} and dep not in scheduled_task_ids]
        if missing_dependencies:
            unscheduled.append(UnscheduledItem(task_id=task.id, reason="dependency task could not be scheduled first"))
            continue
        dependency_end = max((end_by_task[dep] for dep in task.dependency_ids if dep in end_by_task), default=now)
        for index, (cursor, window_end) in enumerate(slots):
            if remaining <= 0:
                break
            cursor = max(cursor, now, dependency_end)
            if cursor >= window_end or (task.deadline and cursor >= task.deadline):
                continue
            available = int((window_end - cursor).total_seconds() // 900) * 15
            if available <= 0:
                continue
            if not task.splittable and available < remaining:
                continue
            chunk = remaining if available >= remaining else available
            if task.deadline:
                until_deadline = int((task.deadline - cursor).total_seconds() // 900) * 15
                if not task.splittable and until_deadline < remaining:
                    continue
                chunk = min(chunk, until_deadline)
            if chunk < 15:
                continue
            end = cursor + timedelta(minutes=chunk)
            reason = "priority and earliest feasible slot" if chunk == remaining else "split to fit availability"
            items.append(PlanItem(task_id=task.id, start=cursor, end=end, reason=reason))
            remaining -= chunk
            end_by_task[task.id] = end
            slots[index] = (end + timedelta(minutes=10), window_end)
        if remaining > 0:
            # Keep the task estimate intact; the plan reports unscheduled residue without mutating domain state.
            unscheduled.append(UnscheduledItem(task_id=task.id, reason=f"needs {remaining} more minutes after scheduling {original_remaining - remaining}"))
        else:
            scheduled_task_ids.add(task.id)
    rationale = ["Deterministic priority score: urgency 30%, importance 25%, deadline 30%, dependency impact 10%, effort fit 5%."]
    if unscheduled:
        rationale.append("Some tasks remain unscheduled because the available capacity or deadline constraints were insufficient.")
    return Plan(version=version, task_ids=[task.id for task in all_tasks], windows=[AvailabilityWindow(start=s, end=e) for s, e in normalized_windows], items=items, unscheduled=unscheduled, rationale=rationale)


def fallback_extract(text: str, now: datetime | None = None) -> tuple[list[Task], list[str]]:
    """Offline extractor for the demo; an LLM adapter can replace this later."""
    now = now or datetime.now(timezone.utc)
    lowered = text.lower()
    demo = any(word in lowered for word in ("考试", "exam", "洗发水", "shampoo"))
    if demo:
        english_input = any(word in lowered for word in ("exam", "shampoo", "assignment", "email")) and not any(char in text for char in "考试洗发水作业邮件")
        titles = (["Review exam topics", "Submit English assignment", "Buy household supplies", "Reply to important email"]
                  if english_input else ["复习考试重点", "提交英语作业", "购买生活用品", "回复重要邮件"])
        durations = [90, 30, 30, 30]
        urgencies = [5, 4, 2, 3]
        importances = [5, 4, 2, 3]
        tasks = [Task(title=title, urgency=u, importance=i, estimated_minutes=d, source_text=text) for title, d, u, i in zip(titles, durations, urgencies, importances)]
        assumptions = ("Offline demo parsing was used; confirm the exam time and available hours before generating the plan."
                      if english_input else "使用离线演示解析；考试时间和可用时间需要在生成计划前确认。")
        return tasks, [assumptions]
    chunks = [chunk.strip(" ，,。.;；") for chunk in text.replace("、", ",").replace("和", ",").split(",") if chunk.strip(" ，,。.;；")]
    tasks = [Task(title=chunk[:200], estimated_minutes=30, source_text=text) for chunk in chunks[:12]]
    assumption = "未检测到明确截止时间，默认每项任务 30 分钟。" if any("\u4e00" <= char <= "\u9fff" for char in text) else "No explicit deadline was detected; each item defaults to 30 minutes."
    return tasks or [Task(title=text[:200], source_text=text)], [assumption]



