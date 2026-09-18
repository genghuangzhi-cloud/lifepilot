"""Minimal contract tests for deterministic natural-language extraction.

These tests intentionally exercise the parser boundary only.  They verify
that temporal and dependency entities are converted into structured ``Task``
objects before any scheduler is involved.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.scheduler import fallback_extract


LOCAL_TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 15, 7, 0, tzinfo=LOCAL_TZ)


def _one(text: str):
    tasks, _assumptions = fallback_extract(text, now=NOW)
    assert len(tasks) == 1
    return tasks[0]


def test_class_time_range_is_fixed_event_with_derived_duration():
    task = _one("I have class from 9 AM to 12 PM.")

    assert task.kind == "fixed_event"
    assert task.start_time == datetime(2026, 9, 15, 9, 0, tzinfo=LOCAL_TZ)
    assert task.end_time == datetime(2026, 9, 15, 12, 0, tzinfo=LOCAL_TZ)
    assert task.estimated_minutes == 180


def test_meeting_time_range_is_fixed_event():
    task = _one("I have a meeting from 2 PM to 3 PM.")

    assert task.kind == "fixed_event"
    assert task.start_time == datetime(2026, 9, 15, 14, 0, tzinfo=LOCAL_TZ)
    assert task.end_time == datetime(2026, 9, 15, 15, 0, tzinfo=LOCAL_TZ)
    assert task.estimated_minutes == 60


def test_explicit_duration_is_preserved_for_flexible_task():
    task = _one("Study calculus for 90 minutes.")

    assert task.kind == "flexible_task"
    assert task.title == "Study calculus"
    assert task.estimated_minutes == 90
    assert task.start_time is None
    assert task.end_time is None


def test_by_clock_time_becomes_same_day_deadline():
    task = _one("Finish my English homework by 8 PM.")

    assert task.kind == "flexible_task"
    assert task.deadline == datetime(2026, 9, 15, 20, 0, tzinfo=LOCAL_TZ)


def test_wake_up_is_a_habit_with_start_time():
    task = _one("Wake up at 8 AM.")

    assert task.kind == "habit"
    assert task.start_time == datetime(2026, 9, 15, 8, 0, tzinfo=LOCAL_TZ)


def test_after_dinner_shower_creates_prerequisite_dependency():
    tasks, _assumptions = fallback_extract("After dinner, take a shower.", now=NOW)

    assert len(tasks) == 2
    dinner, shower = tasks
    assert "dinner" in dinner.title.lower()
    assert "shower" in shower.title.lower()
    assert dinner.kind == "habit"
    assert shower.kind == "habit"
    assert shower.dependency_ids == [dinner.id]


def test_tomorrow_context_applies_to_both_ends_of_fixed_range():
    task = _one("Tomorrow I have class from 9 AM to noon.")

    tomorrow = NOW + timedelta(days=1)
    assert task.kind == "fixed_event"
    assert task.start_time == tomorrow.replace(hour=9, minute=0, second=0, microsecond=0)
    assert task.end_time == tomorrow.replace(hour=12, minute=0, second=0, microsecond=0)
    assert task.estimated_minutes == 180


def test_supported_time_range_forms_are_normalized():
    expected = [
        ("from 9 AM to 12 PM", 9, 12, 180),
        ("from 2 PM to 3 PM", 14, 15, 60),
        ("between 2 PM and 3 PM", 14, 15, 60),
        ("9 AM–12 PM", 9, 12, 180),
        ("9:00-12:00", 9, 12, 180),
    ]
    for text, start_hour, end_hour, minutes in expected:
        task = _one(text)
        assert task.kind == "fixed_event"
        assert task.start_time == NOW.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        assert task.end_time == NOW.replace(hour=end_hour, minute=0, second=0, microsecond=0)
        assert task.estimated_minutes == minutes


def test_event_keywords_are_fixed_when_a_range_is_present():
    for title in ("class", "I have class", "lecture", "meeting", "exam", "appointment"):
        task = _one(f"{title} from 9 AM to 10 AM")
        assert task.kind == "fixed_event"
        assert task.start_time == NOW.replace(hour=9, minute=0, second=0, microsecond=0)
        assert task.end_time == NOW.replace(hour=10, minute=0, second=0, microsecond=0)


def _titles(tasks):
    return [task.title for task in tasks]


def test_multi_event_a_preserves_two_tomorrow_classes():
    tasks, _ = fallback_extract(
        "Tomorrow I have class from 9 AM to 12 PM and another class from 1 PM to 6 PM.",
        now=NOW,
    )

    assert len(tasks) == 2
    assert _titles(tasks) == ["Class", "Class"]
    assert [(task.start_time.hour, task.end_time.hour, task.estimated_minutes) for task in tasks] == [(9, 12, 180), (13, 18, 300)]
    assert all(task.start_time.date() == (NOW + timedelta(days=1)).date() for task in tasks)
    assert all(task.kind == "fixed_event" for task in tasks)
    assert all(not task.dependency_ids for task in tasks)


def test_multi_event_b_propagates_tomorrow_and_sequence_dependencies():
    tasks, _ = fallback_extract(
        "Tomorrow, get up at 8 AM, have breakfast, and go to school.",
        now=NOW,
    )

    assert _titles(tasks) == ["Get up", "Breakfast", "Go to school"]
    assert tasks[0].start_time == NOW.replace(day=16, hour=8)
    assert tasks[1].dependency_ids == [tasks[0].id]
    assert tasks[2].dependency_ids == [tasks[1].id]
    assert all(task.title.lower() != "tomorrow" for task in tasks)


def test_multi_event_c_lunch_depends_on_fixed_class():
    tasks, _ = fallback_extract("I have class from 9 AM to noon, then lunch.", now=NOW)

    assert _titles(tasks) == ["Class", "Lunch"]
    assert tasks[0].kind == "fixed_event"
    assert tasks[0].start_time.hour == 9 and tasks[0].end_time.hour == 12
    assert tasks[1].dependency_ids == [tasks[0].id]


def test_multi_event_d_splits_after_clause_into_dependency_chain():
    tasks, _ = fallback_extract("After dinner, take a shower and go to sleep.", now=NOW)

    assert _titles(tasks) == ["Dinner", "Shower", "Sleep"]
    assert tasks[1].dependency_ids == [tasks[0].id]
    assert tasks[2].dependency_ids == [tasks[1].id]


def test_multi_event_e_golden_input_has_atomic_events_and_no_false_context_task():
    text = (
        "Tomorrow, get up at 8:00 a.m., then wash up and have breakfast before going to school. "
        "Have classes until noon, then have lunch. In the afternoon, continue with classes until 6:00 p.m., "
        "then return to the dorm. After dinner, take a shower and go to sleep."
    )
    tasks, assumptions = fallback_extract(text, now=NOW)

    assert _titles(tasks) == [
        "Get up", "Wash up", "Breakfast", "Go to school", "Class", "Lunch",
        "Class", "Return to dorm", "Dinner", "Shower", "Sleep",
    ]
    assert all(task.title.lower() != "tomorrow" for task in tasks)
    assert all("then" not in task.title.lower() and "before" not in task.title.lower() and "after" not in task.title.lower() for task in tasks)
    assert all(task.start_time is None or task.start_time.date() == (NOW + timedelta(days=1)).date() for task in tasks)
    assert tasks[4].kind == "fixed_event" and tasks[4].end_time.hour == 12
    assert tasks[6].kind == "fixed_event" and tasks[6].end_time.hour == 18
    for previous, current in zip(tasks, tasks[1:]):
        assert current.dependency_ids == [previous.id]
    assert any("Date context applied" in item for item in assumptions)


def test_overnight_and_inherited_meridiem_ranges_are_safe():
    overnight = _one("I have a meeting from 9 PM to 12 AM.")
    assert overnight.start_time == datetime(2026, 9, 15, 21, 0, tzinfo=LOCAL_TZ)
    assert overnight.end_time == datetime(2026, 9, 16, 0, 0, tzinfo=LOCAL_TZ)
    assert overnight.estimated_minutes == 180

    inherited = _one("I have a meeting from 2 PM to 3.")
    assert inherited.start_time == datetime(2026, 9, 15, 14, 0, tzinfo=LOCAL_TZ)
    assert inherited.end_time == datetime(2026, 9, 15, 15, 0, tzinfo=LOCAL_TZ)
    assert inherited.estimated_minutes == 60


def test_postposed_after_relations_point_from_prerequisite_to_dependent():
    tasks, _ = fallback_extract("Lunch after class.", now=NOW)
    assert _titles(tasks) == ["Lunch", "Class"]
    assert tasks[0].dependency_ids == [tasks[1].id]
    assert tasks[1].dependency_ids == []

    tasks, _ = fallback_extract("Take a shower after dinner.", now=NOW)
    assert _titles(tasks) == ["Shower", "Dinner"]
    assert tasks[0].dependency_ids == [tasks[1].id]
    assert tasks[1].dependency_ids == []


def test_leading_clock_is_bound_to_following_action():
    tasks, _ = fallback_extract("At 8 AM, get up; at 9 AM, have breakfast.", now=NOW)
    assert _titles(tasks) == ["Get up", "Breakfast"]
    assert tasks[0].start_time == NOW.replace(hour=8, minute=0, second=0, microsecond=0)
    assert tasks[1].start_time == NOW.replace(hour=9, minute=0, second=0, microsecond=0)


def test_study_before_existing_afternoon_class_does_not_duplicate_class():
    tasks, _ = fallback_extract(
        "Study physics for 90 minutes before my afternoon class from 2 PM to 5 PM.",
        now=NOW,
    )
    assert _titles(tasks) == ["Study physics", "Class"]
    assert tasks[0].estimated_minutes == 90
    assert tasks[1].start_time == NOW.replace(hour=14, minute=0, second=0, microsecond=0)
    assert tasks[1].end_time == NOW.replace(hour=17, minute=0, second=0, microsecond=0)
    assert tasks[0].dependency_ids == []
    assert tasks[1].dependency_ids == [tasks[0].id]


def test_another_without_repeated_class_keeps_second_event():
    tasks, _ = fallback_extract(
        "I have class from 9 AM to noon and another from 1 PM to 6 PM.", now=NOW
    )
    assert _titles(tasks) == ["Class", "Class"]
    assert [(task.start_time.hour, task.end_time.hour) for task in tasks] == [(9, 12), (13, 18)]


def test_known_event_does_not_swallow_residual_actions():
    text = (
        "Exam tomorrow: review calculus chapters and submit English assignment. "
        "Buy shampoo and reply to the important email."
    )
    tasks, _ = fallback_extract(text, now=NOW)

    assert len(tasks) == 5
    assert _titles(tasks) == [
        "Exam",
        "Review calculus chapters",
        "Submit English assignment",
        "Buy shampoo",
        "Reply to important email",
    ]
    assert all(task.title.lower() != "tomorrow" for task in tasks)
    assert all(not task.dependency_ids for task in tasks)
    assert tasks[0].kind == "fixed_event"
    assert tasks[0].deadline == (NOW + timedelta(days=1)).replace(hour=23, minute=59, second=0, microsecond=0)


def _find_title(tasks, fragment: str):
    """Return the single task whose title contains ``fragment`` (case-insensitive)."""
    matches = [task for task in tasks if fragment.lower() in task.title.lower()]
    assert len(matches) == 1, f"expected one task containing {fragment!r}, got {_titles(tasks)!r}"
    return matches[0]


def test_real_input_one_keeps_all_calculus_exam_actions_and_deadline():
    """A known Exam event must not swallow the residual action clauses."""
    text = (
        "I have a calculus exam tomorrow at 2 PM. I need to review chapters 7 and 8, "
        "do 20 practice problems, submit my English essay by midnight, and buy shampoo."
    )
    tasks, _ = fallback_extract(text, now=NOW)
    tomorrow = NOW + timedelta(days=1)

    assert len(tasks) == 5
    exam = _find_title(tasks, "exam")
    assert exam.kind == "fixed_event"
    assert exam.start_time == tomorrow.replace(hour=14, minute=0, second=0, microsecond=0)
    assert exam.end_time is None
    assert exam.estimated_minutes is None

    review = _find_title(tasks, "chapters 7 and 8")
    assert review.kind == "flexible_task"
    assert "and" in review.title.lower()

    practice = _find_title(tasks, "practice problems")
    assert practice.kind == "flexible_task"

    essay = _find_title(tasks, "english essay")
    assert essay.kind == "flexible_task"
    assert "by" not in essay.title.lower()
    assert essay.deadline == tomorrow.replace(hour=23, minute=59, second=0, microsecond=0)

    shampoo = _find_title(tasks, "shampoo")
    assert shampoo.kind == "flexible_task"
    assert all(not task.dependency_ids for task in tasks)


def test_real_input_two_splits_presentation_and_duration_led_preparation_tasks():
    text = (
        "My presentation is tomorrow at 3 PM. I need 2 hours for slides and 1 hour to rehearse, "
        "plus a few emails and grocery shopping."
    )
    tasks, _ = fallback_extract(text, now=NOW)
    tomorrow = NOW + timedelta(days=1)

    assert len(tasks) == 5
    presentation = _find_title(tasks, "presentation")
    assert presentation.kind == "fixed_event"
    assert presentation.start_time == tomorrow.replace(hour=15, minute=0, second=0, microsecond=0)
    assert presentation.end_time is None
    assert presentation.estimated_minutes is None

    slides = _find_title(tasks, "slides")
    assert slides.kind == "flexible_task"
    assert slides.estimated_minutes == 120

    rehearse = _find_title(tasks, "rehearse")
    assert rehearse.kind == "flexible_task"
    assert rehearse.estimated_minutes == 60

    emails = _find_title(tasks, "emails")
    assert emails.kind == "flexible_task"
    assert emails.estimated_minutes == 30

    grocery = _find_title(tasks, "grocery")
    assert grocery.kind == "flexible_task"
    assert grocery.estimated_minutes == 30


def test_real_input_three_preserves_programming_assignment_and_all_durations():
    text = (
        "I only have 4 free hours today. I need 3 hours for a programming assignment due tonight, "
        "1 hour to study, 45 minutes to shop, and 1 hour to exercise."
    )
    tasks, _ = fallback_extract(text, now=NOW)
    today_deadline = NOW.replace(hour=23, minute=59, second=0, microsecond=0)

    assert len(tasks) == 4
    assert all("free hours" not in task.title.lower() for task in tasks)

    assignment = _find_title(tasks, "programming assignment")
    assert assignment.kind == "flexible_task"
    assert assignment.estimated_minutes == 180
    assert assignment.deadline == today_deadline

    study = _find_title(tasks, "study")
    assert study.estimated_minutes == 60

    shop = _find_title(tasks, "shop")
    assert shop.estimated_minutes == 45

    exercise = _find_title(tasks, "exercise")
    assert exercise.kind == "habit"
    assert exercise.estimated_minutes == 60


def test_cross_midnight_range_from_11_pm_to_1_am_is_normalized():
    task = _one("I have a meeting from 11 PM to 1 AM.")

    assert task.start_time == NOW.replace(hour=23, minute=0, second=0, microsecond=0)
    assert task.end_time == (NOW + timedelta(days=1)).replace(hour=1, minute=0, second=0, microsecond=0)
    assert task.estimated_minutes == 120


def test_duration_connectors_are_consumed_without_corrupting_task_titles():
    study = _one("I need 1 hour to study.")
    assert study.title == "Study"
    assert study.estimated_minutes == 60

    review = _one("Review chapters 7 and 8 for 30 minutes.")
    assert "chapters 7 and 8" in review.title.lower()
    assert review.estimated_minutes == 30

    reply = _one("Reply to the important email.")
    assert "reply to" in reply.title.lower()
    assert "important email" in reply.title.lower()


def test_partial_fixed_events_do_not_receive_a_fake_default_duration():
    starts_only = _one("Class at 9 AM.")
    assert starts_only.kind == "fixed_event"
    assert starts_only.start_time == NOW.replace(hour=9, minute=0, second=0, microsecond=0)
    assert starts_only.end_time is None
    assert starts_only.estimated_minutes is None

    ends_only = _one("Classes until noon.")
    assert ends_only.kind == "fixed_event"
    assert ends_only.start_time is None
    assert ends_only.end_time == NOW.replace(hour=12, minute=0, second=0, microsecond=0)
    assert ends_only.estimated_minutes is None


def test_tomorrow_leading_clock_binds_to_get_up_and_class_reference_is_deduplicated():
    """A leading date/time must survive extraction and ``after class`` must
    reference the one timed Class event rather than creating an anonymous
    duplicate.

    This is deliberately a parser-boundary test: the scheduler should receive
    complete, next-day datetimes and valid dependency IDs from this result.
    """
    now = datetime(2026, 9, 16, 10, 0, tzinfo=LOCAL_TZ)
    text = (
        "Tomorrow at 8 AM, I need to wake up, finish my math homework for 90 "
        "minutes before class at 11 AM, then have lunch after class and buy "
        "groceries on my way home."
    )

    tasks, assumptions = fallback_extract(text, now=now)
    tomorrow = now + timedelta(days=1)

    def find(fragment: str):
        matches = [task for task in tasks if fragment.lower() in task.title.lower()]
        assert len(matches) == 1, f"expected one {fragment!r}, got {_titles(tasks)!r}"
        return matches[0]

    get_up = find("get up")
    homework = find("math homework")
    classes = [task for task in tasks if task.title.lower() == "class"]
    lunch = find("lunch")
    groceries = find("buy groceries")

    assert len(classes) == 1
    class_event = classes[0]
    assert get_up.kind == "habit"
    assert get_up.start_time == tomorrow.replace(hour=8, minute=0, second=0, microsecond=0)
    assert homework.estimated_minutes == 90
    assert class_event.kind == "fixed_event"
    assert class_event.start_time == tomorrow.replace(hour=11, minute=0, second=0, microsecond=0)
    assert class_event.end_time is None
    assert class_event.estimated_minutes is None
    assert class_event.dependency_ids == [homework.id]
    assert lunch.dependency_ids == [class_event.id]
    assert "then" not in groceries.title.lower()
    assert all(
        value is None or value.date() == tomorrow.date()
        for task in tasks
        for value in (task.start_time, task.end_time, task.deadline)
    )
    assert any("Date context applied" in item for item in assumptions)


def test_after_existing_exam_continues_scanning_go_home_and_reuses_real_event():
    debug = {}
    tasks, _ = fallback_extract(
        "I have an exam at 2 PM. After the exam, I will go home.",
        now=NOW,
        debug=debug,
    )

    assert _titles(tasks) == ["Exam", "Go home"]
    exam, go_home = tasks
    assert exam.kind == "fixed_event"
    assert exam.start_time == NOW.replace(hour=14, minute=0)
    assert exam.end_time is None
    assert exam.estimated_minutes is None
    assert exam.dependency_ids == []
    assert go_home.kind in {"flexible_task", "habit"}
    assert go_home.source_text == "go home"
    assert go_home.dependency_ids == [exam.id]
    assert all(dependency in {task.id for task in tasks} for task in tasks for dependency in task.dependency_ids)
    assert debug["unparsed_actionable_spans"] == []


def test_after_existing_exam_continues_with_new_action_and_real_dependency():
    """An ``after`` reference reuses the timed event and does not swallow the action."""
    tasks, _assumptions = fallback_extract(
        "I have an exam at 2 PM. After the exam, I will go home.",
        now=NOW,
    )

    exams = [task for task in tasks if task.title.lower() == "exam"]
    assert len(exams) == 1
    exam = exams[0]
    assert exam.kind == "fixed_event"
    assert exam.start_time == NOW.replace(hour=14, minute=0, second=0, microsecond=0)

    go_home = [task for task in tasks if task.title.lower() == "go home"]
    assert len(go_home) == 1
    assert go_home[0].dependency_ids == [exam.id]
    task_ids = {task.id for task in tasks}
    assert all(dependency in task_ids for dependency in go_home[0].dependency_ids)


def test_after_event_reference_creates_following_dorm_action():
    tasks, _ = fallback_extract("After class, I will go to the dorm.", now=NOW)

    assert _titles(tasks) == ["Class", "Go to dorm"]
    assert tasks[1].dependency_ids == [tasks[0].id]


def test_before_meeting_continues_with_prepare_action_and_duration():
    tasks, _ = fallback_extract(
        "Before the meeting, I need to prepare the report for 60 minutes.",
        now=NOW,
    )

    meeting = _find_title(tasks, "meeting")
    prepare = _find_title(tasks, "prepare")
    assert prepare.estimated_minutes == 60
    assert meeting.dependency_ids == [prepare.id]


def test_after_meeting_continues_with_send_action_and_dependency():
    """A single after-reference must preserve the following action."""
    tasks, _ = fallback_extract(
        "After the meeting, I will send the report to my professor.",
        now=NOW,
    )

    assert _titles(tasks) == ["Meeting", "Send report to my professor"]
    meeting, send = tasks
    assert meeting.kind == "fixed_event"
    assert meeting.dependency_ids == []
    assert send.dependency_ids == [meeting.id]


def test_after_meeting_splits_send_and_go_to_lunch():
    tasks, _ = fallback_extract(
        "After the meeting, I will send the report to my professor and go to lunch.",
        now=NOW,
    )

    assert _titles(tasks) == ["Meeting", "Send report to my professor", "Go to lunch"]
    meeting, send, lunch = tasks
    assert send.dependency_ids == [meeting.id]
    assert lunch.dependency_ids == [meeting.id]


def test_full_before_after_meeting_case_has_atomic_events_and_valid_relations():
    text = (
        "Tomorrow I have a meeting from 10 AM to 11 AM. Before the meeting, I need to prepare the report for 60 minutes, "
        "and after the meeting I will send the report to my professor and go to lunch."
    )
    tasks, _ = fallback_extract(text, now=NOW)

    assert _titles(tasks) == ["Meeting", "Prepare report", "Send report to my professor", "Go to lunch"]
    meeting, prepare, send, lunch = tasks
    assert meeting.start_time == (NOW + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    assert meeting.end_time == (NOW + timedelta(days=1)).replace(hour=11, minute=0, second=0, microsecond=0)
    assert prepare.estimated_minutes == 60
    assert meeting.dependency_ids == [prepare.id]
    assert send.dependency_ids == [meeting.id]
    assert lunch.dependency_ids == [meeting.id]
    ids = {task.id for task in tasks}
    assert all(dependency in ids for task in tasks for dependency in task.dependency_ids)
    graph = {task.id: list(task.dependency_ids) for task in tasks}
    visiting: set = set()
    visited: set = set()

    def visit(node):
        assert node not in visiting, "dependency graph contains a cycle"
        if node in visited:
            return
        visiting.add(node)
        for dependency in graph[node]:
            visit(dependency)
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node)
    assert all(" before " not in task.title.lower() and " after " not in task.title.lower() for task in tasks)


def test_regression_b_finish_presentation_and_return():
    text = "I have a meeting from 2 PM to 3 PM. Before the meeting, I need to finish my presentation for 60 minutes, and after the meeting I will email my professor and return to the dorm."
    tasks, _ = fallback_extract(text, now=NOW)
    assert _titles(tasks) == ["Meeting", "Finish my presentation", "Email my professor", "Return to dorm"]
    meeting, finish, email, return_home = tasks
    assert finish.estimated_minutes == 60
    assert meeting.dependency_ids == [finish.id]
    assert email.dependency_ids == [meeting.id]
    assert return_home.dependency_ids == [meeting.id]


def test_regression_c_review_print_lunch_call():
    text = "I have an exam at 10 AM. Before the exam, I need to review my notes for 90 minutes and print my study materials, and after the exam I will have lunch and call my professor."
    tasks, _ = fallback_extract(text, now=NOW)
    assert _titles(tasks) == ["Exam", "Review my notes", "Print my study materials", "Lunch", "Call my professor"]
    exam, review, print_materials, lunch, call = tasks
    assert review.estimated_minutes == 90
    assert exam.dependency_ids == [review.id, print_materials.id]
    assert lunch.dependency_ids == [exam.id]
    assert call.dependency_ids == [exam.id]

def test_regression_d_class_before_after_parallel_actions():
    text = (
        "I have a class from 9 AM to 11 AM. Before class, I need to finish my homework for 45 minutes "
        "and pack my laptop, and after class I will buy lunch and message my teammate."
    )
    debug = {}
    tasks, _assumptions = fallback_extract(text, now=NOW, debug=debug)

    assert [task.title for task in tasks] == [
        "Class",
        "Finish my homework",
        "Pack my laptop",
        "Buy lunch",
        "Message my teammate",
    ]
    class_event, homework, laptop, buy_lunch, message = tasks
    assert class_event.kind == "fixed_event"
    assert class_event.start_time == NOW.replace(hour=9, minute=0, second=0, microsecond=0)
    assert class_event.end_time == NOW.replace(hour=11, minute=0, second=0, microsecond=0)
    assert homework.estimated_minutes == 45
    assert class_event.dependency_ids == [homework.id, laptop.id]
    assert buy_lunch.dependency_ids == [class_event.id]
    assert message.dependency_ids == [class_event.id]
    ids = {task.id for task in tasks}
    assert all(dependency in ids for task in tasks for dependency in task.dependency_ids)
    assert debug["unparsed_actionable_spans"] == []
    assert all(
        not any(word in task.title.lower().split() for word in ("before", "after", "then", "will"))
        and "and" not in task.title.lower()
        for task in tasks
    )


def test_regression_e_interview_afterward_parallel_actions():
    text = (
        "Tomorrow I have a job interview from 10 AM to 11 AM. Before the interview, I need to "
        "update my résumé for 45 minutes and print a copy, and afterward I will call my mentor "
        "and head back home."
    )
    debug = {}
    tasks, _ = fallback_extract(text, now=NOW, debug=debug)
    assert [task.title for task in tasks] == [
        "Job interview", "Update my résumé", "Print a copy", "Call my mentor", "Head back home"
    ]
    interview, update, printed, call, home = tasks
    assert interview.start_time == (NOW + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    assert interview.end_time == (NOW + timedelta(days=1)).replace(hour=11, minute=0, second=0, microsecond=0)
    assert update.estimated_minutes == 45
    assert interview.dependency_ids == [update.id, printed.id]
    assert call.dependency_ids == [interview.id]
    assert home.dependency_ids == [interview.id]
    assert debug["unparsed_actionable_spans"] == []


def test_regression_f_appointment_after_parallel_actions():
    text = (
        "Tomorrow I have a doctor's appointment from 3 PM to 4 PM. Before the appointment, I need to "
        "prepare my documents for 30 minutes and pack my bag, and after the appointment I will buy dinner "
        "and text my roommate."
    )
    debug = {}
    tasks, _ = fallback_extract(text, now=NOW, debug=debug)
    assert [task.title for task in tasks] == [
        "Appointment", "Prepare my documents", "Pack my bag", "Buy dinner", "Text my roommate"
    ]
    appointment, prepare, bag, dinner, text_roommate = tasks
    assert appointment.start_time == (NOW + timedelta(days=1)).replace(hour=15, minute=0, second=0, microsecond=0)
    assert appointment.end_time == (NOW + timedelta(days=1)).replace(hour=16, minute=0, second=0, microsecond=0)
    assert prepare.estimated_minutes == 30
    assert appointment.dependency_ids == [prepare.id, bag.id]
    assert dinner.dependency_ids == [appointment.id]
    assert text_roommate.dependency_ids == [appointment.id]
    assert debug["unparsed_actionable_spans"] == []


def test_regression_g_meeting_grab_and_call():
    text = (
        "Tomorrow I have a team meeting from 1 PM to 2 PM. Before the meeting, I need to "
        "prepare the agenda for 30 minutes and send the documents to my teammates, and after "
        "the meeting I will grab some coffee and call my project partner."
    )
    debug = {}
    tasks, _ = fallback_extract(text, now=NOW, debug=debug)
    assert [task.title for task in tasks] == [
        "Meeting", "Prepare agenda", "Send documents to my teammates", "Grab some coffee", "Call my project partner"
    ]
    meeting, prepare, send, coffee, call = tasks
    assert meeting.start_time == (NOW + timedelta(days=1)).replace(hour=13, minute=0, second=0, microsecond=0)
    assert meeting.end_time == (NOW + timedelta(days=1)).replace(hour=14, minute=0, second=0, microsecond=0)
    assert meeting.dependency_ids == [prepare.id, send.id]
    assert coffee.dependency_ids == [meeting.id]
    assert call.dependency_ids == [meeting.id]
    assert debug["unparsed_actionable_spans"] == []


def test_regression_h_lecture_read_charge_and_message():
    text = (
        "Tomorrow I have a lecture from 8 AM to 10 AM. Before the lecture, I need to read the assigned "
        "chapter for 40 minutes and charge my laptop, and after the lecture I will have breakfast and "
        "send a message to my classmate."
    )
    debug = {}
    tasks, _ = fallback_extract(text, now=NOW, debug=debug)
    assert [task.title for task in tasks] == [
        "Class", "Read assigned chapter", "Charge my laptop", "Breakfast", "Send a message to my classmate"
    ]
    lecture, read, charge, breakfast, message = tasks
    assert lecture.start_time == (NOW + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
    assert lecture.end_time == (NOW + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    assert read.estimated_minutes == 40
    assert lecture.dependency_ids == [read.id, charge.id]
    assert breakfast.dependency_ids == [lecture.id]
    assert message.dependency_ids == [lecture.id]
    assert debug["unparsed_actionable_spans"] == []
