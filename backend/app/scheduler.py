from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
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
    fixed_tasks = [t for t in task_list if t.kind == "fixed_event" and t.start_time is not None]
    task_by_id = {t.id: t for t in task_list}
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
    # A task referenced by a fixed event is a prerequisite that must finish
    # before that event starts.  Keep this temporal bound separate from the
    # dependency direction so splittable work cannot resume after the anchor.
    fixed_prerequisite_deadlines: dict = {}

    # Fixed events are immutable anchors.  Schedule them first and carve their
    # occupied intervals out of the available slots so flexible work can never
    # overlap them.  A fixed event outside availability is reported explicitly.
    fixed_tasks = sorted((t for t in task_list if t.kind == "fixed_event"), key=lambda t: t.start_time or now)
    for task in fixed_tasks:
        if task.start_time is None:
            unscheduled.append(UnscheduledItem(task_id=task.id, reason="fixed event is missing a start time"))
            continue
        if task.end_time is None:
            unscheduled.append(UnscheduledItem(task_id=task.id, reason="fixed event is missing an end time"))
            continue
        start = task.start_time
        end = task.end_time
        containing = next((idx for idx, (ws, we) in enumerate(slots) if start >= ws and end <= we), None)
        if containing is None:
            unscheduled.append(UnscheduledItem(task_id=task.id, reason="fixed event falls outside available time windows"))
            continue
        # Ensure fixed events do not overlap one another.
        if any(item.start < end and start < item.end for item in items):
            unscheduled.append(UnscheduledItem(task_id=task.id, reason="fixed event overlaps another fixed event"))
            continue
        items.append(PlanItem(task_id=task.id, start=start, end=end, state="frozen", reason="fixed event anchors the schedule"))
        scheduled_task_ids.add(task.id)
        end_by_task[task.id] = end
        ws, we = slots[containing]
        replacement: list[tuple[datetime, datetime]] = []
        if ws < start:
            replacement.append((ws, start))
        if end < we:
            replacement.append((end, we))
        slots[containing:containing + 1] = replacement
    for fixed in fixed_tasks:
        # The anchor's start is a prerequisite deadline even when the fixed
        # event itself is outside the requested availability.  Otherwise a
        # ``Before fixed event`` task could be placed after the anchor simply
        # because the anchor was reported unscheduled.
        if fixed.start_time is None:
            continue
        for prerequisite_id in fixed.dependency_ids:
            previous = fixed_prerequisite_deadlines.get(prerequisite_id)
            if previous is None or fixed.start_time < previous:
                fixed_prerequisite_deadlines[prerequisite_id] = fixed.start_time
    for task in ordered:
        if task.kind == "fixed_event":
            continue
        remaining = task.effective_remaining()
        original_remaining = remaining
        missing_dependencies = [dep for dep in task.dependency_ids if dep not in task_by_id or dep not in scheduled_task_ids]
        if missing_dependencies:
            unscheduled.append(UnscheduledItem(task_id=task.id, reason="dependency task is missing or could not be scheduled first"))
            continue
        dependency_end = max((end_by_task[dep] for dep in task.dependency_ids if dep in end_by_task), default=now)
        effective_deadline = task.deadline
        anchor_deadline = fixed_prerequisite_deadlines.get(task.id)
        if anchor_deadline is not None and (effective_deadline is None or anchor_deadline < effective_deadline):
            effective_deadline = anchor_deadline
        for index, (cursor, window_end) in enumerate(slots):
            if remaining <= 0:
                break
            cursor = max(cursor, now, dependency_end)
            if cursor >= window_end or (effective_deadline and cursor >= effective_deadline):
                continue
            available = int((window_end - cursor).total_seconds() // 900) * 15
            if effective_deadline:
                available = min(available, int((effective_deadline - cursor).total_seconds() // 900) * 15)
            if available <= 0:
                continue
            if not task.splittable and available < remaining:
                continue
            chunk = remaining if available >= remaining else available
            if effective_deadline:
                until_deadline = int((effective_deadline - cursor).total_seconds() // 900) * 15
                if not task.splittable and until_deadline < remaining:
                    continue
                chunk = min(chunk, until_deadline)
            if chunk < 15:
                continue
            end = cursor + timedelta(minutes=chunk)
            reason = "priority and earliest feasible slot" if chunk == remaining else "split to fit availability"
            if effective_deadline:
                hours = (effective_deadline - now).total_seconds() / 3600
                if hours <= 24:
                    reason += "; deadline pressure increased priority"
            items.append(PlanItem(task_id=task.id, start=cursor, end=end, reason=reason))
            remaining -= chunk
            end_by_task[task.id] = end
            slots[index] = (end + timedelta(minutes=10), window_end)
        if remaining > 0:
            # Keep the task estimate intact; the plan reports unscheduled residue without mutating domain state.
            unscheduled.append(UnscheduledItem(task_id=task.id, reason=f"needs {remaining} more minutes after scheduling {original_remaining - remaining}"))
        else:
            scheduled_task_ids.add(task.id)
    # Return chronological blocks for a stable, explainable UI.
    items.sort(key=lambda item: (item.start, item.end, str(item.task_id)))
    rationale = ["Deterministic priority score: urgency 30%, importance 25%, deadline 30%, dependency impact 10%, effort fit 5%."]
    if fixed_tasks:
        rationale.append("Fixed events were placed first and treated as immovable schedule anchors.")
    if unscheduled:
        rationale.append("Some tasks remain unscheduled because the available capacity or deadline constraints were insufficient.")
    return Plan(version=version, task_ids=[task.id for task in all_tasks], windows=[AvailabilityWindow(start=s, end=e) for s, e in normalized_windows], items=items, unscheduled=unscheduled, rationale=rationale)


def fallback_extract(
    text: str,
    now: datetime | None = None,
    debug: dict[str, object] | None = None,
) -> tuple[list[Task], list[str]]:
    """Deterministic offline extraction used when no LLM provider is configured.

    The extractor intentionally returns structured hints (kind, time, duration,
    confidence) while leaving final scheduling to :func:`schedule_tasks`.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must include a timezone offset")

    # Keep parsing deliberately local and deterministic.  We first scan for
    # event phrases, then parse temporal entities from the text belonging to
    # each event.  This avoids the old ``split(',')`` path which merged
    # ``and another class`` and turned the global word ``Tomorrow`` into a
    # task of its own.
    time_token = r"(?:\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?|noon|midnight)"
    has_date_context = bool(re.search(r"\b(?:tomorrow)\b|明天", text, re.I))
    context_date = now + timedelta(days=1) if has_date_context else now

    def parse_clock(value: str, date: datetime, forced_meridiem: str | None = None) -> datetime | None:
        value = value.strip().lower().replace(".", "")
        if value == "noon":
            hour, minute = 12, 0
        elif value == "midnight":
            hour, minute = 0, 0
        else:
            match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", value)
            if not match:
                return None
            hour, minute = int(match.group(1)), int(match.group(2) or 0)
            meridiem = match.group(3) or forced_meridiem
            if meridiem == "pm" and hour < 12:
                hour += 12
            if meridiem == "am" and hour == 12:
                hour = 0
            if hour > 23 or minute > 59:
                return None
        return date.replace(hour=hour, minute=minute, second=0, microsecond=0)

    def parse_duration(chunk: str) -> tuple[int, str]:
        match = re.search(r"(?:for\s*)?(\d+(?:\.5)?)\s*(hours?|hrs?|h|minutes?|mins?|m|小时|分钟)", chunk, re.I)
        if not match:
            return 30, "default"
        amount, unit = float(match.group(1)), match.group(2).lower()
        minutes = round(amount * 60) if unit.startswith(("hour", "hr")) or unit == "h" or "小时" in unit else round(amount)
        return max(15, min(minutes, 24 * 60)), "explicit"

    invalid_temporal_ranges: list[str] = []

    def parse_temporal(chunk: str) -> tuple[datetime | None, datetime | None, datetime | None, int | None, str]:
        """Parse only the temporal entities in one event span."""
        range_re = rf"(?:\b(?:from|between)\s+)?(?P<start>{time_token})\s*(?:to|and|[-–—])\s*(?P<end>{time_token})"
        match = re.search(range_re, chunk, re.I)
        if match:
            start_raw, end_raw = match.group("start"), match.group("end")
            # A pair of bare integers in ordinary prose is not a clock range:
            # ``chapters 7 and 8`` must stay in the task title.  Bare clocks
            # remain valid when the expression has a range prefix, a clock
            # separator, or another explicit clock marker (``2 PM to 3``).
            range_prefix = bool(re.search(r"\b(?:from|between)\b", match.group(0), re.I))
            clock_marker = bool(re.search(r"(?::\d{2}|\b(?:am|pm)\b|\b(?:noon|midnight)\b)", match.group(0), re.I))
            clock_separator = bool(re.search(r"[-–—]", match.group(0)))
            if not (range_prefix or clock_marker or clock_separator):
                match = None
        if match:
            start_raw, end_raw = match.group("start"), match.group("end")
            start_meridiem = re.search(r"\b(am|pm)\b", start_raw, re.I)
            end_meridiem = re.search(r"\b(am|pm)\b", end_raw, re.I)
            # A bare end clock inherits the start meridiem (``2 PM to 3``).
            # ``12`` after an AM start is conventionally noon, rather than
            # midnight, so keep it as a local 12:00 wall-clock value.
            forced_end = start_meridiem.group(1).lower() if start_meridiem and not end_meridiem else None
            if forced_end == "am" and re.match(r"^\s*12(?:\D|$)", end_raw):
                forced_end = None
            start = parse_clock(start_raw, context_date)
            end = parse_clock(end_raw, context_date, forced_meridiem=forced_end)
            # Explicit meridiem ranges may cross midnight.  Never return an
            # end before the start: either move the end to the next local day
            # or mark the range invalid so Task validation cannot raise 500.
            crosses_midnight = bool(
                start
                and end
                and end <= start
                and start_meridiem
                and start_meridiem.group(1).lower() == "pm"
                and (not end_meridiem or end_meridiem.group(1).lower() == "am")
            )
            if crosses_midnight:
                end += timedelta(days=1)
            if not start or not end or end <= start:
                invalid_temporal_ranges.append(chunk)
                return None, None, None, None, "unknown"
            duration = int((end - start).total_seconds() // 60)
            return start, end, None, max(15, duration), "explicit"

        start = None
        start_match = re.search(rf"\b(?:at|@)\s*(?P<time>{time_token})", chunk, re.I)
        if start_match:
            start = parse_clock(start_match.group("time"), context_date)
        end = None
        until_match = re.search(rf"\buntil\s+(?P<time>{time_token})", chunk, re.I)
        if until_match:
            end = parse_clock(until_match.group("time"), context_date)
        deadline = None
        deadline_match = re.search(rf"\b(?:by|due)\s+(?P<time>{time_token})", chunk, re.I)
        if deadline_match:
            deadline_value = deadline_match.group("time")
            if deadline_value.strip().lower() == "midnight":
                deadline = context_date.replace(hour=23, minute=59, second=0, microsecond=0)
            else:
                deadline = parse_clock(deadline_value, context_date)
        if deadline is None:
            if re.search(r"\b(today|tonight)\b|今天|今晚", chunk, re.I):
                deadline = now.replace(hour=23, minute=59, second=0, microsecond=0)
            elif re.search(r"\b(tomorrow)\b|明天", chunk, re.I):
                deadline = context_date.replace(hour=23, minute=59, second=0, microsecond=0)
        iso = re.search(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", chunk)
        if iso:
            deadline = context_date.replace(year=int(iso.group(1)), month=int(iso.group(2)), day=int(iso.group(3)), hour=23, minute=59, second=0, microsecond=0)
        duration, source = parse_duration(chunk)
        if start and end and end > start:
            duration, source = int((end - start).total_seconds() // 60), "explicit"
        return start, end, deadline, duration, source

    # Longest-first matching prevents ``class`` from stealing the span in
    # ``continue with classes`` and ``go to sleep`` from stealing ``sleep``.
    action_patterns: list[tuple[str, str]] = [
        ("Study", r"\bstudy\b"),
        ("Get up", r"\b(?:get|wake)\s+up\b"),
        ("Wash up", r"\bwash\s+up\b"),
        ("Breakfast", r"\b(?:have\s+)?breakfast\b"),
        ("Go to school", r"\bgo(?:ing)?\s+to\s+school\b"),
        ("Go to dorm", r"\bgo\s+to\s+(?:the\s+)?dorm\b"),
        ("Go back to the dorm", r"\bgo\s+back\s+to\s+(?:the\s+)?dorm\b"),
        ("Go to lunch", r"\bgo\s+to\s+lunch\b"),
        ("Class", r"\b(?:continue\s+(?:with\s+)?classes?|have\s+classes?|another\s+class|classes?|class|lecture|lesson)\b"),
        # Some natural language omits the repeated noun: ``another from 1 PM
        # to 6 PM``.  Treat the anaphoric marker as a second Class event when
        # it is immediately followed by a temporal expression.
        ("Class", r"\banother\b(?=\s+(?:from|at|\d))"),
        ("Lunch", r"\b(?:have\s+)?lunch\b"),
        ("Return to dorm", r"\breturn\s+to\s+(?:the\s+)?dorm\b"),
        # ``go home`` is a distinct action that commonly follows a known
        # event (``After the exam, I will go home``).  Keep it as its own
        # match so the relation scanner can attach the prerequisite rather
        # than allowing the reference phrase to consume the action.
        ("Go home", r"\bgo\s+home\b|\breturn\s+home\b"),
        ("Dinner", r"\b(?:have\s+)?dinner\b"),
        ("Shower", r"\btake\s+a\s+shower\b|\bshower\b"),
        ("Sleep", r"\bgo\s+to\s+sleep\b|\bsleep\b"),
        ("Meeting", r"\bmeeting\b"),
        ("Exam", r"\bexam\b"),
        ("Presentation", r"\bpresentation\b"),
        ("Job interview", r"\bjob\s+interview\b"),
        ("Interview", r"\binterview\b"),
        ("Appointment", r"\bappointment\b"),
    ]

    # Generic work actions are scanned alongside the known event vocabulary.
    # They deliberately match only an action anchor; the object belongs to
    # the span up to the next action/boundary and is turned into the title
    # below.  This keeps a known event such as ``Exam`` from swallowing the
    # rest of a sentence.
    generic_action_patterns: list[tuple[str, str]] = [
        ("Review", r"\breview\b"),
        ("Read", r"\bread\b"),
        ("Charge", r"\bcharge\b"),
        ("Grab", r"\bgrab\b"),
        ("Send a message", r"\bsend\s+(?:a|the)\s+message\b"),
        ("Submit", r"\bsubmit\b"),
        ("Buy", r"\bbuy\b"),
        ("Reply", r"\breply\b"),
        ("Write", r"\bwrite\b"),
        ("Finish", r"\bfinish\b"),
        ("Update", r"\bupdate\b"),
        ("Pack", r"\bpack\b"),
        ("Send", r"\bsend\b"),
        ("Email", r"\bemail\b"),
        ("Message", r"\bmessage\b"),
        ("Print", r"\bprint\b"),
        ("Call", r"\bcall\b"),
        ("Head back home", r"\bhead\s+back\s+home\b"),
        ("Text", r"\btext\b"),
        ("Do", r"\bdo\b(?=\s+\d|\s+(?:the|my|a|an)\b)"),
        ("Rehearse", r"\brehearse\b"),
        ("Prepare", r"\bprepare\b"),
        ("Shop", r"\bshop\b"),
        ("Exercise", r"\bexercise\b"),
        ("Emails", r"\bemails?\b"),
        ("Grocery shopping", r"\bgrocery\s+shopping\b"),
    ]

    # Duration-led clauses are actionable events in their own right.  They
    # must be scanned before generic verbs so a later duration cannot leak
    # backward into the preceding task (for example ``1 hour to study``).
    duration_clause_re = re.compile(
        r"(?P<duration>\d+(?:\.5)?\s*(?:hours?|hrs?|h|minutes?|mins?|m))\s+"
        r"(?P<connector>for|to)\s+(?P<object>[^,.;]+?)"
        r"(?=\s*(?:,|;|\.|\bplus\b|\band\s+(?:\d+(?:\.5)?\s*(?:hours?|hrs?|h|minutes?|mins?|m)\b)))",
        re.I,
    )

    def duration_clause_title(object_text: str) -> str:
        object_text = re.sub(r"\b(?:by|due)\s+(?:midnight|tonight|today)\b.*$", "", object_text, flags=re.I)
        value = re.sub(r"\b(?:a|an|the|my|our|some|few)\b", " ", object_text, flags=re.I)
        value = re.sub(r"\b(?:programming|presentation)\s+assignment\b", "Programming assignment", value, flags=re.I)
        value = re.sub(r"\bslides\b", "Prepare slides", value, flags=re.I)
        value = re.sub(r"\brehearse\b", "Rehearse", value, flags=re.I)
        value = re.sub(r"\bstudy\b", "Study", value, flags=re.I)
        value = re.sub(r"\bshop(?:ping)?\b", "Shopping", value, flags=re.I)
        value = re.sub(r"\bexercise\b", "Exercise", value, flags=re.I)
        value = re.sub(r"\s+", " ", value).strip(" ,.-")
        return value[:200].capitalize() if value else "Task"

    def duration_clause_matches(value: str) -> list[tuple[int, int, str]]:
        found: list[tuple[int, int, str]] = []
        for match in duration_clause_re.finditer(value):
            title = duration_clause_title(match.group("object"))
            found.append((match.start(), match.end(), title))
        return found

    def event_matches(value: str) -> list[tuple[int, int, str]]:
        matches: list[tuple[int, int, str]] = []
        for title, pattern in [*action_patterns, *generic_action_patterns]:
            for match in re.finditer(pattern, value, re.I):
                if title == "Interview" and re.search(r"\bjob\s+$", value[max(0, match.start() - 8):match.start()], re.I):
                    continue
                if title == "Emails" and re.search(r"\breply\b", value[max(0, match.start() - 48):match.start()], re.I):
                    continue
                if title == "Message" and re.search(r"\bsend\s+(?:a|the)\s+$", value[max(0, match.start() - 48):match.start()], re.I):
                    continue
                # In ``reply to the important email`` the final ``email`` is
                # the object of Reply, not a second Email action.  Keep the
                # verb form (``I will email my professor``) while preventing
                # this noun from creating a duplicate event.
                # In ``buy lunch``, Lunch is the object of Buy. Suppress only
                # this structural noun match; standalone ``lunch`` remains valid.
                if title == "Lunch" and re.search(
                    r"\bbuy\s+(?:(?:the|my|a|an)\s+)?$",
                    value[max(0, match.start() - 48):match.start()], re.I,
                ):
                    continue
                if title == "Dinner" and re.search(
                    r"\bbuy\s+(?:(?:the|my|a|an)\s+)?$",
                    value[max(0, match.start() - 48):match.start()], re.I,
                ):
                    continue
                if title == "Email" and re.search(r"\breply\s+to\b", value[max(0, match.start() - 64):match.start()], re.I):
                    continue
                if title == "Presentation" and re.search(
                    r"\b(?:finish|prepare|review|submit|write|make|create)\s+(?:(?:my|the|a|an)\s+)?$",
                    value[max(0, match.start() - 64):match.start()], re.I,
                ):
                    continue
                if title == "Study" and re.match(r"\s+materials\b", value[match.end():], re.I) and re.search(
                    r"\bprint\s+(?:(?:my|the|a|an)\s+)?$",
                    value[max(0, match.start() - 64):match.start()], re.I,
                ):
                    continue
                matches.append((match.start(), match.end(), title))
        matches.extend(duration_clause_matches(value))
        selected: list[tuple[int, int, str]] = []
        for candidate in sorted(matches, key=lambda item: (item[0], -(item[1] - item[0]))):
            if any(candidate[0] < prior[1] and prior[0] < candidate[1] for prior in selected):
                continue
            selected.append(candidate)
        return sorted(selected)

    def clean_generic_title(value: str) -> str:
        value = re.sub(r"\b(?:i\s+have|i\s+need\s+to|please|a|an|the|tomorrow|today|then|before|after)\b", " ", value, flags=re.I)
        # Remove explicit durations before the broad clock token.  The clock
        # grammar accepts a bare one/two digit hour (for ``9:00`` and similar
        # forms); running it first would strip the ``90`` from ``90 minutes``
        # and leave an incorrect title such as ``Study calculus for minutes``.
        duration_consumed = bool(re.search(r"\d+(?:\.5)?\s*(?:hours?|hrs?|h|minutes?|mins?|m|\u5c0f\u65f6|\u5206\u949f)\s+(?:for|to)\b", value, re.I))
        # Consume deadline connectors before removing the clock token.  This
        # prevents ``by midnight`` from leaving a dangling ``by`` in titles.
        value = re.sub(r"\b(?:by|due)\s+(?:midnight|tonight|today)\b", " ", value, flags=re.I)
        value = re.sub(r"\b(?:for|to)\s+(?=\d+(?:\.5)?\s*(?:hours?|hrs?|h|minutes?|mins?|m|\u5c0f\u65f6|\u5206\u949f)\b)", " ", value, flags=re.I)
        value = re.sub(r"\d+(?:\.5)?\s*(?:hours?|hrs?|h|minutes?|mins?|m|\u5c0f\u65f6|\u5206\u949f)", " ", value, flags=re.I)
        # Only remove clock tokens that were actually recognized as temporal
        # entities.  Bare numbers such as ``chapters 7 and 8`` remain title
        # content rather than being mistaken for times.
        value = re.sub(r"(?:\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)|noon|midnight)", " ", value, flags=re.I)
        if duration_consumed:
            value = re.sub(r"^\s*(?:for|to)\s+", " ", value, flags=re.I)
            value = re.sub(r"\bfor\b(?=\s*$)", " ", value, flags=re.I)
        # Conjunctions and relation markers are span delimiters, not part of
        # the task title.  Only strip them at the edges so objects such as
        # ``reply to the important email`` remain intact.
        value = re.sub(r"^[,;:]?\s*(?:and|or|but|then)\s+", "", value, flags=re.I)
        value = re.sub(r"\s*[,;:]?\s+(?:and|or|but|then)\s*$", "", value, flags=re.I)
        value = re.sub(r"\s+", " ", value).strip(" -:,.?!")
        if not value:
            return "Task"
        # ``str.capitalize`` lower-cases every subsequent character, which
        # corrupts user-provided names (``English assignment`` became
        # ``english assignment``).  Normalize only the first character.
        value = value[:200]
        return value[0].upper() + value[1:] if value else "Task"

    def kind_for(raw: str, title: str, start: datetime | None, end: datetime | None) -> str:
        if start is not None and end is not None:
            return "fixed_event"
        if title in {"Class", "Meeting", "Exam", "Appointment", "Presentation", "Interview"}:
            return "fixed_event"
        if title in {"Get up", "Wash up", "Breakfast", "Go to school", "Go to lunch", "Go back to the dorm", "Lunch", "Dinner", "Return to dorm", "Shower", "Sleep", "Exercise"}:
            return "habit"
        if re.search(r"\b(?:daily|every day|weekly|habit|exercise)\b|每天|每日|每周|习惯", raw, re.I):
            return "habit"
        return "flexible_task"

    matches = event_matches(text)
    # A known event mentioned after a relation word is normally a reference,
    # not a new event.  Keep a relation reference only when no earlier event
    # with the same semantic title exists; this preserves useful placeholders
    # for standalone inputs such as ``Lunch after class`` while preventing
    # ``After the exam`` from creating a second anonymous Exam.
    known_event_titles = {"Class", "Meeting", "Exam", "Appointment", "Presentation", "Interview", "Job interview", "Dinner", "Lunch"}
    filtered_matches: list[tuple[int, int, str]] = []
    for candidate in matches:
        start_offset, end_offset, title = candidate
        before = text[max(0, start_offset - 40):start_offset]
        relation_ref = bool(
            re.search(r"\b(?:before|after)\s+(?:(?:the|my|an?|this|that)\s+)?$", before, re.I)
        )
        if relation_ref and title in known_event_titles:
            semantic_title = "Job interview" if title in {"Interview", "Job interview"} else title
            same_title_before = any(
                ("Job interview" if prior_title in {"Interview", "Job interview"} else prior_title) == semantic_title
                and prior_start < start_offset
                for prior_start, _prior_end, prior_title in filtered_matches
            )
            if same_title_before:
                continue
        filtered_matches.append(candidate)
    matches = filtered_matches

    # A clock that appears before the first action is a pending temporal
    # constraint for that action.  ``parse_temporal`` only sees the action's
    # own span, so retain this prefix explicitly rather than relying on the
    # action span to include it.  In particular, the date marker and polite
    # lead-in in ``Tomorrow at 8 AM, I need to wake up`` must not cause the
    # 08:00 value to be lost (or leak into later events).
    leading_start: datetime | None = None
    if matches:
        first_action_start = matches[0][0]
        leading_prefix = text[:first_action_start]
        leading_match = re.search(
            rf"^\s*(?:(?:tomorrow|today|明天|今天)\s*)?(?:at|@)\s*(?P<time>{time_token})\s*,?\s*"
            rf"(?:i\s+(?:need|have)\s+to\s+)?$",
            leading_prefix,
            re.I,
        )
        if leading_match:
            leading_start = parse_clock(leading_match.group("time"), context_date)
    if debug is not None:
        debug["detected_actionable_spans"] = len(matches)
        debug["actionable_span_texts"] = [text[start:end].strip(" ,.;。；") for start, end, _ in matches]
    assumptions: list[str] = []
    tasks: list[Task] = []
    if matches:
        # A leading clock is a one-shot context for the first action.  For
        # example, ``Tomorrow at 8 AM, I need to wake up`` has no clock in
        # the action's own span, so keep this pending value until that span
        # is constructed and consume it exactly once.
        leading_context_time: datetime | None = None
        leading_context = re.match(
            rf"\s*(?:tomorrow\s+|today\s+)?(?:at|@)\s*(?P<time>{time_token})\s*,",
            text,
            re.I,
        )
        if leading_context:
            leading_context_time = parse_clock(leading_context.group("time"), context_date)
        for index, (start_offset, end_offset, title) in enumerate(matches):
            next_offset = matches[index + 1][0] if index + 1 < len(matches) else len(text)
            # Start at the action itself so a later event cannot re-use an
            # earlier range (``class ... and another class from 1 PM ...``).
            # Include only a directly preceding ``at 8 AM,`` prefix; this
            # binds leading clocks to their own action without swallowing the
            # previous event's ``from 9 AM to 12 PM`` range.
            raw_start = start_offset
            prefix_start = matches[index - 1][1] if index else 0
            prefix = text[prefix_start:start_offset]
            leading_clock = re.search(
                # ``at 9 AM, have breakfast`` leaves the verb's ``have`` in
                # the inter-action prefix because the action anchor matches
                # only ``breakfast``.  Accept that optional auxiliary while
                # still requiring the clock to be the immediately preceding
                # temporal prefix.
                rf"(?:^|[;,])\s*(?:at|@)\s*{time_token}\s*,?\s*(?:have\s+)?$",
                prefix,
                re.I,
            )
            if leading_clock:
                raw_start = prefix_start + leading_clock.start()
            # The next action anchor usually bounds this span.  Also honor a
            # sentence/semicolon boundary that occurs before that anchor so
            # a leading clock for the *next* action is not retained in the
            # current event's raw text.  Periods in ``a.m.``/``p.m.`` are
            # clock-token punctuation and must be skipped.
            raw_segment = text[raw_start:next_offset]
            boundary_at: int | None = None
            for punctuation in re.finditer(r"[.;。；]", raw_segment):
                # The delimiter can be part of the directly preceding
                # action prefix (for example ``; at 9 AM, have breakfast``)
                # when we intentionally include a leading clock.  It is not
                # a boundary for this span in that position.
                if punctuation.start() == 0:
                    continue
                if punctuation.group() == ".":
                    pos = punctuation.start()
                    lower_segment = raw_segment.lower()
                    # First dot in ``a.m.``/``p.m.`` (before ``m``).
                    if pos + 1 < len(raw_segment) and lower_segment[pos - 1:pos + 2] in {"a.m", "p.m"}:
                        continue
                    # Final dot in ``a.m.``/``p.m.`` (after ``m``).
                    if pos >= 3 and lower_segment[pos - 3:pos] in {"a.m", "p.m"}:
                        continue
                boundary_at = punctuation.start()
                break
            if boundary_at is not None:
                raw_segment = raw_segment[:boundary_at]
            relation_boundary = re.search(r",\s+and\s+(?:before|after(?:ward)?)\b", raw_segment, re.I)
            if relation_boundary:
                raw_segment = raw_segment[:relation_boundary.start()]
            raw = raw_segment.strip(" ,.;。；")
            raw = re.sub(r"\s*,?\s+and\s*$", "", raw, flags=re.I).strip()
            start, end, deadline, duration, duration_source = parse_temporal(raw)
            if index == 0 and leading_context_time is not None:
                start = leading_context_time
                leading_context_time = None
            # Consume a leading clock exactly once.  It belongs to the first
            # action following the prefix; subsequent events must not inherit
            # it as a global/default time.
            if index == 0 and leading_start is not None:
                start = leading_start
                # A habit/event with a leading start but no end remains a
                # partial event.  Keep the normal estimated effort for habits
                # while fixed events are made duration-unknown below.
                if duration_source == "default":
                    duration_source = "estimated"
            if title in {"Study", "Read", "Charge", "Grab", "Send a message", "Review", "Submit", "Buy", "Reply", "Write", "Finish", "Update", "Send", "Email", "Print", "Call", "Head back home", "Text", "Do", "Prepare", "Pack", "Message", "Emails", "Grocery shopping"}:
                # Keep the object of the study action while dropping a
                # trailing relation clause such as ``before my afternoon
                # class``.  This produces ``Study physics`` as a stable task
                # title for the structured output.
                action_clause = re.split(r"\b(?:before|after|then)\b", raw, maxsplit=1, flags=re.I)[0]
                title = clean_generic_title(action_clause)
                if title == "Print copy" and re.search(r"\bprint\s+a\s+copy\b", action_clause, re.I):
                    title = "Print a copy"
                if re.search(r"\bsend\s+a\s+message\b", action_clause, re.I):
                    title = re.sub(r"^Send\s+message\b", "Send a message", title, flags=re.I)
            kind = kind_for(raw, title, start, end)
            if title == "Class" and (start is not None or end is not None):
                kind = "fixed_event"
            if kind == "fixed_event" and not (start is not None and end is not None):
                duration, duration_source = None, "unknown"
            confidence = 0.72 + (0.15 if start and end else 0.08 if start or end else 0.0)
            task = Task(title=title, kind=kind, start_time=start, end_time=end, deadline=deadline,
                        estimated_minutes=duration, duration_source=duration_source,
                        confidence=min(confidence, 0.99), urgency=5 if kind == "fixed_event" or deadline else 3,
                        importance=4 if kind == "fixed_event" else 3, source_text=raw)
            tasks.append(task)

        # Build dependencies from semantic relation clauses.  The old
        # implementation inferred edges from every inter-anchor gap, which
        # made ``before`` point in the wrong direction and leaked a relation
        # into a later ``and`` clause.  Each relation below is scoped to the
        # current sentence/clause and consumes only the action text that
        # follows it.
        routine_titles = {"Get up", "Wash up", "Breakfast", "Go to school", "Go to dorm", "Class", "Lunch", "Dinner", "Return to dorm", "Shower", "Sleep"}

        def add_dependency(dependent: Task, prerequisite: Task | None) -> None:
            if prerequisite is None or dependent.id == prerequisite.id:
                return
            if prerequisite.id not in dependent.dependency_ids:
                dependent.dependency_ids.append(prerequisite.id)

        def hard_boundaries(value: str, start: int = 0) -> list[int]:
            """Return sentence/semicolon boundaries, ignoring a.m./p.m. dots."""
            result: list[int] = []
            for punctuation in re.finditer(r"[.;。；]", value[start:]):
                position = start + punctuation.start()
                if punctuation.group() == ".":
                    lower = value.lower()
                    if position + 1 < len(value) and lower[position - 1:position + 2] in {"a.m", "p.m"}:
                        continue
                    if position >= 3 and lower[position - 3:position] in {"a.m", "p.m"}:
                        continue
                result.append(position)
            return result

        def next_boundary(position: int) -> int:
            return next((item for item in hard_boundaries(text, position) if item >= position), len(text))

        def reference_task(relation_end: int, relation_match: re.Match[str]) -> tuple[Task | None, int]:
            """Resolve ``the meeting``/``my afternoon class`` to its match."""
            suffix = text[relation_end:]
            reference = re.match(
                r"\s+(?:(?:the|my|an?|this|that)\s+)?(?:(?:afternoon|morning)\s+)?"
                r"(?P<name>class(?:es)?|lecture|meeting|exam|interview|dinner|lunch|presentation|appointment)\b",
                suffix,
                re.I,
            )
            if not reference:
                return None, relation_end
            phrase_end = relation_end + reference.end()
            name = reference.group("name").lower()
            if name.startswith("class") or name == "lecture":
                canonical = "Class"
            elif name == "interview":
                canonical = "Job interview"
            else:
                canonical = name.rstrip("s").capitalize()
            candidates = [
                index for index, (match_start, match_end, _title) in enumerate(matches)
                if match_start < phrase_end and match_end > relation_end
            ]
            if candidates:
                return tasks[candidates[-1]], phrase_end
            # A previously constructed event can be referenced from a later
            # clause (``..., and after the meeting ...``).
            same_title = [task for task in tasks if task.title.lower() == canonical.lower()]
            if same_title:
                return same_title[-1], phrase_end
            return None, phrase_end

        relation_matches = list(re.finditer(r"\b(?P<relation>before|after(?:ward)?)\b", text, re.I))
        for relation_index, relation in enumerate(relation_matches):
            relation_word = relation.group("relation").lower()
            if relation_word.startswith("after"):
                relation_word = "after"
            relation_start, relation_end = relation.span()
            referenced, reference_end = reference_task(relation_end, relation)
            if referenced is None and relation.group("relation").lower().startswith("after"):
                prior_fixed = [
                    task for task in tasks
                    if task.kind == "fixed_event" and matches[tasks.index(task)][0] < relation_start
                ]
                if prior_fixed:
                    referenced = prior_fixed[-1]
            # A relation at sentence/clause start is a prefix relation.  The
            # conjunction form (``..., and after ...``) is also a new clause;
            # an inline ``lunch after class`` is not.
            previous_boundary = max([item for item in hard_boundaries(text) if item < relation_start] or [-1])
            before_relation = text[previous_boundary + 1:relation_start].strip(" \t,:")
            is_prefix = not before_relation or bool(re.search(r"\band\s*$", before_relation, re.I))

            later_relation_start = (
                relation_matches[relation_index + 1].start()
                if relation_index + 1 < len(relation_matches)
                else len(text)
            )
            clause_end = min(next_boundary(relation_start), later_relation_start)

            if is_prefix:
                # All action anchors in this clause share the prefix
                # relation.  This is what makes both ``send ...`` and ``go to
                # lunch`` depend on the same Meeting rather than on one
                # another.  The reference event itself is excluded.
                action_start = reference_end
                clause_tasks = [
                    index for index, (match_start, _match_end, _title) in enumerate(matches)
                    if match_start >= action_start and match_start < clause_end
                ]
                if relation_word == "after":
                    for index in clause_tasks:
                        add_dependency(tasks[index], referenced)
                elif relation_word == "before" and referenced is not None:
                    for index in clause_tasks:
                        add_dependency(referenced, tasks[index])
                continue

            # Inline relations attach the preceding action to the explicit
            # reference (``lunch after class``), or attach the next action to
            # the preceding action (``breakfast before going to school``).
            preceding = [index for index, (_start, match_end, _title) in enumerate(matches) if match_end <= relation_start]
            preceding_index = preceding[-1] if preceding else None
            following = [index for index, (match_start, _end, _title) in enumerate(matches) if match_start >= relation_end]
            target_index = None
            if referenced is not None:
                target_index = next((index for index in following if tasks[index].id == referenced.id), None)
            if target_index is None and following:
                target_index = following[0]
            if preceding_index is None or target_index is None:
                continue
            if relation_word == "after":
                add_dependency(tasks[preceding_index], tasks[target_index])
            else:
                add_dependency(tasks[target_index], tasks[preceding_index])

        # Routine prose retains its established sequential semantics.  Apply
        # this after explicit relations so a coordinated prefix such as
        # ``after meeting, send ... and go to lunch`` does not make lunch wait
        # for Send, while ``dinner -> shower -> sleep`` remains a chain.
        for index in range(1, len(tasks)):
            previous, current = tasks[index - 1], tasks[index]
            gap = text[matches[index - 1][1]:matches[index][0]]
            if previous.title in routine_titles and current.title in routine_titles:
                if re.search(r"\banother(?:\s+class)?\b", gap, re.I):
                    continue
                if previous.title == "Class" and current.title == "Class" and previous.start_time is not None and current.start_time is not None:
                    continue
                # An explicit relation has already been resolved above.  Do
                # not overwrite an embedded ``after`` edge such as
                # ``Lunch after class`` with the textual sequence Class
                # depending on Lunch.
                if re.search(r"\b(?:before|after)\b", gap, re.I) and not re.search(r"[.;]\s*(?:before|after)\b", gap, re.I):
                    continue
                # A routine chain is intentionally the direct predecessor;
                # explicit relations on the current task still take priority
                # when the pair is not a normal sequence.
                current.dependency_ids = [previous.id]
    else:
        # Generic fallback for free-form work items (study, homework, etc.).
        # This path is intentionally used only when no known event phrase was
        # found; it preserves the existing single-task API contract.
        chunks = [part.strip(" ，,。.;；") for part in re.split(r"[\n。；;]+|,(?=\s)|\bthen\b", text, flags=re.I) if part.strip(" ，,。.;；")]
        for raw in chunks[:12]:
            start, end, deadline, duration, duration_source = parse_temporal(raw)
            title = clean_generic_title(raw)
            kind = kind_for(raw, title, start, end)
            if kind == "fixed_event" and not (start is not None and end is not None):
                duration, duration_source = None, "unknown"
            tasks.append(Task(title=title, kind=kind, start_time=start, end_time=end, deadline=deadline,
                              estimated_minutes=duration, duration_source=duration_source,
                              confidence=0.65, urgency=5 if deadline else 3, importance=3, source_text=text))

    if not tasks:
        tasks = [Task(title=clean_generic_title(text), source_text=text, duration_source="default", confidence=0.4)]
    if debug is not None:
        debug["parsed_actionable_spans"] = len(tasks)
        spans = list(debug.get("actionable_span_texts", []))
        sources = [task.source_text.lower() for task in tasks]
        debug["unparsed_actionable_spans"] = [
            span for span in spans
            if span and not any(span.lower() in source or source in span.lower() for source in sources)
        ]
        if debug["unparsed_actionable_spans"]:
            assumptions.append(
                "Some actionable text needs review: "
                + "; ".join(str(item) for item in debug["unparsed_actionable_spans"])
            )
    if not any(task.deadline for task in tasks):
        if all(task.duration_source in {"default", "estimated"} for task in tasks):
            assumptions.append("No explicit deadline was detected; each item defaults to 30 minutes.")
        else:
            assumptions.append("No explicit deadline was detected; confirm due dates before generating the plan.")
    elif any(task.duration_source == "default" for task in tasks):
        assumptions.append("No duration was provided for some items; those items default to 30 minutes.")
    if any(task.kind == "fixed_event" and not task.start_time for task in tasks):
        assumptions.append("A fixed event was detected without a start time; confirm its time before generating the plan.")
    if has_date_context:
        assumptions.append(f"Date context applied to all events: {context_date.date().isoformat()}.")
    if len(tasks) > 1 and any(task.dependency_ids for task in tasks):
        assumptions.append("Temporal sequence words were converted into task dependencies.")
    return tasks, assumptions

