from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import sys
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.store import SQLiteStore


LOCAL_NOW = datetime(2026, 9, 14, 9, tzinfo=timezone(timedelta(hours=8)))
LOCAL_END = datetime(2026, 9, 14, 21, tzinfo=timezone(timedelta(hours=8)))


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "isolated.db"
    monkeypatch.setenv("LIFEPILOT_DB_PATH", str(db_path))
    import app.main as main

    monkeypatch.setattr(main, "STORE", SQLiteStore())
    assert main.STORE.path == db_path
    with TestClient(main.app) as client:
        yield client, db_path, main


def create_task(client: TestClient, title: str, minutes: int = 30, urgency: int = 3) -> dict:
    response = client.post("/api/tasks", json={"title": title, "estimated_minutes": minutes, "urgency": urgency})
    assert response.status_code == 200, response.text
    return response.json()


def generate(client: TestClient, task_ids: list[str], now: datetime = LOCAL_NOW) -> dict:
    response = client.post(
        "/api/plans/generate",
        json={
            "task_ids": task_ids,
            "now": now.isoformat(),
            "timezone": "Asia/Shanghai",
            "windows": [{"start": LOCAL_NOW.isoformat(), "end": LOCAL_END.isoformat()}],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_api_isolated_lifecycle_and_sqlite_persistence(api):
    client, db_path, _main = api
    assert client.get("/api/health").json()["tasks"] == 0
    extracted = client.post("/api/tasks/extract", json={"text": "study, email", "now": LOCAL_NOW.isoformat()})
    assert extracted.status_code == 200
    assert extracted.json()["provider"] == "fallback"
    assert extracted.json()["assumptions"] == ["No explicit deadline was detected; each item defaults to 30 minutes."]
    assert client.get("/api/tasks").json() == []

    first = create_task(client, "first", 30, urgency=5)
    second = create_task(client, "second", 30)
    plan = generate(client, [first["id"], second["id"]])
    assert set(plan["task_ids"]) == {first["id"], second["id"]}
    assert plan["windows"] == [{"start": LOCAL_NOW.isoformat(), "end": LOCAL_END.isoformat()}]
    assert client.get(f"/api/plans/{plan['id']}").json() == plan

    delayed = client.post(
        f"/api/plans/{plan['id']}/events",
        json={"task_id": first["id"], "type": "delay", "minutes": 60, "at": LOCAL_NOW.isoformat()},
    )
    assert delayed.status_code == 200, delayed.text
    revised = delayed.json()["plan"]
    assert revised["id"] != plan["id"]
    assert revised["version"] == plan["version"] + 1
    assert revised["windows"] == plan["windows"]
    assert revised["task_ids"] == plan["task_ids"]
    assert "Added 60 minutes of remaining work" in delayed.json()["explanation"]
    old_second = next(item for item in plan["items"] if item["task_id"] == second["id"])
    new_second = next(item for item in revised["items"] if item["task_id"] == second["id"])
    assert datetime.fromisoformat(new_second["start"]) >= datetime.fromisoformat(old_second["start"])
    ordered = sorted(revised["items"], key=lambda item: item["start"])
    for item in ordered:
        assert LOCAL_NOW <= datetime.fromisoformat(item["start"]) < datetime.fromisoformat(item["end"]) <= LOCAL_END
    for before, after in zip(ordered, ordered[1:]):
        assert datetime.fromisoformat(before["end"]) <= datetime.fromisoformat(after["start"])
    assert client.get(f"/api/plans/{plan['id']}").json() == plan
    first_after_delay = next(task for task in client.get("/api/tasks").json() if task["id"] == first["id"])
    assert first_after_delay["remaining_minutes"] == 90

    completed = client.post(
        f"/api/plans/{revised['id']}/events",
        json={"task_id": first["id"], "type": "complete", "at": "2026-09-14T11:00:00+08:00"},
    )
    assert completed.status_code == 200
    assert completed.json()["plan"]["version"] == 3
    assert all(item["task_id"] != first["id"] for item in completed.json()["plan"]["items"])
    skipped = client.post(
        f"/api/plans/{completed.json()['plan']['id']}/events",
        json={"task_id": second["id"], "type": "skip", "at": "2026-09-14T12:00:00+08:00"},
    )
    assert skipped.status_code == 200
    assert skipped.json()["plan"]["items"] == []
    assert skipped.json()["plan"]["version"] == 4
    assert set(skipped.json()["plan"]["task_ids"]) == {first["id"], second["id"]}
    assert client.get("/api/dashboard").json()["metrics"] == {"total": 2, "completed": 1, "planned": 0}

    reopened = SQLiteStore(db_path)
    assert len(reopened.list_tasks()) == 2
    assert reopened.get_plan(uuid4()) is None
    assert reopened.get_plan(UUID(plan["id"])).model_dump(mode="json") == plan
    assert reopened.get_plan(UUID(revised["id"])).model_dump(mode="json") == revised
    assert reopened.get_plan(UUID(skipped.json()["plan"]["id"])).model_dump(mode="json") == skipped.json()["plan"]
    assert reopened.get_task(UUID(first["id"])).status == "completed"
    assert reopened.get_task(UUID(first["id"])).remaining_minutes == 0
    assert reopened.get_task(UUID(second["id"])).status == "skipped"
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM plans").fetchone()[0] == 4
        assert [row[0] for row in db.execute("SELECT event_type FROM events ORDER BY id")] == ["delay", "complete", "skip"]


def test_extract_uses_declared_timezone_for_parser_clock(api):
    client, _db_path, _main = api
    response = client.post(
        "/api/tasks/extract",
        json={
            "text": "I have class from 9 AM to 12 PM",
            "now": "2026-09-15T01:00:00+00:00",
            "timezone": "Asia/Shanghai",
        },
    )
    assert response.status_code == 200, response.text
    task = response.json()["tasks"][0]
    assert task["kind"] == "fixed_event"
    assert task["start_time"] == "2026-09-15T09:00:00+08:00"
    assert task["end_time"] == "2026-09-15T12:00:00+08:00"
    assert task["estimated_minutes"] == 180
    payload = response.json()
    assert payload["parser_version"] == "multi-event-v1"
    assert payload["date_context"] is None
    assert payload["timezone"] == "Asia/Shanghai"
    assert payload["events"][0]["duration_minutes"] == 180
    assert payload["events"][0]["validation"] == "ok"


def test_extract_rejects_blank_text(api):
    client, _db_path, _main = api
    response = client.post("/api/tasks/extract", json={"text": "   "})
    assert response.status_code == 422
    assert "text must not be blank" in response.text


def test_extract_keeps_known_event_and_residual_actions(api):
    client, _db_path, _main = api
    response = client.post(
        "/api/tasks/extract",
        json={
            "text": (
                "Exam tomorrow: review calculus chapters and submit English assignment. "
                "Buy shampoo and reply to the important email."
            ),
            "now": "2026-09-15T07:00:00+08:00",
            "timezone": "Asia/Shanghai",
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert [task["title"] for task in payload["tasks"]] == [
        "Exam",
        "Review calculus chapters",
        "Submit English assignment",
        "Buy shampoo",
        "Reply to important email",
    ]
    assert payload["date_context"] == "2026-09-16"
    assert all(task["title"].lower() != "tomorrow" for task in payload["tasks"])
    assert all(not task["dependency_ids"] for task in payload["tasks"])
    assert len(payload["events"]) == 5


def test_generate_plan_uses_future_task_date_for_default_windows(api):
    """A future-dated fixed event must not fall back into today's window.

    Omitting ``windows`` exercises the API's default-window construction, which
    previously used only ``now`` and therefore left tomorrow's event
    unscheduled.
    """
    client, _db_path, _main = api
    now = datetime(2026, 9, 16, 10, 0, tzinfo=timezone(timedelta(hours=8)))
    start = now + timedelta(days=1, hours=1)  # tomorrow at 11:00 local time
    end = start + timedelta(hours=1)
    response = client.post(
        "/api/tasks",
        json={
            "title": "Class",
            "kind": "fixed_event",
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "estimated_minutes": 60,
            "duration_source": "explicit",
        },
    )
    assert response.status_code == 200, response.text
    task = response.json()

    plan_response = client.post(
        "/api/plans/generate",
        json={
            "task_ids": [task["id"]],
            "now": now.isoformat(),
            "timezone": "Asia/Shanghai",
        },
    )
    assert plan_response.status_code == 200, plan_response.text
    plan = plan_response.json()

    item = next(item for item in plan["items"] if item["task_id"] == task["id"])
    assert item["state"] == "frozen"
    assert item["start"] == start.isoformat()
    assert item["end"] == end.isoformat()
    assert datetime.fromisoformat(plan["windows"][0]["start"]).date() == start.date()
    assert not plan["unscheduled"]


def test_extract_save_preserves_dependency_ids_for_future_plan(api):
    client, _db_path, _main = api
    now = datetime(2026, 9, 16, 9, 0, tzinfo=timezone(timedelta(hours=8)))
    text = (
        "Tomorrow I have a doctor's appointment from 3 PM to 4 PM. Before the appointment, I need to "
        "prepare my documents for 30 minutes and pack my bag, and after the appointment I will buy dinner "
        "and text my roommate."
    )
    extracted = client.post("/api/tasks/extract", json={"text": text, "now": now.isoformat(), "timezone": "Asia/Shanghai"})
    assert extracted.status_code == 200, extracted.text
    parsed = extracted.json()
    saved = []
    for task in parsed["tasks"]:
        response = client.post("/api/tasks", json=task)
        assert response.status_code == 200, response.text
        saved.append(response.json())
    ids = {task["id"] for task in saved}
    assert all(dependency in ids for task in saved for dependency in task["dependency_ids"])

    plan_response = client.post(
        "/api/plans/generate",
        json={"task_ids": list(ids), "now": now.isoformat(), "timezone": "Asia/Shanghai"},
    )
    assert plan_response.status_code == 200, plan_response.text
    plan = plan_response.json()
    assert datetime.fromisoformat(plan["windows"][0]["start"]).date().isoformat() == "2026-09-17"
    assert not plan["unscheduled"]


@pytest.mark.parametrize("event_type", ["complete", "skip"])
def test_undated_tomorrow_routine_keeps_explicit_window_on_replan(api, event_type):
    client, _db_path, _main = api
    now = "2026-09-30T17:36:00+08:00"
    extracted = client.post(
        "/api/tasks/extract",
        json={"text": "Tomorrow, after dinner, take a shower.", "now": now, "timezone": "Asia/Shanghai"},
    )
    assert extracted.status_code == 200, extracted.text
    payload = extracted.json()
    assert payload["date_context"] == "2026-10-01"
    assert payload["unparsed_actionable_spans"] == []
    assert [task["title"] for task in payload["tasks"]] == ["Dinner", "Shower"]
    saved = []
    for task in payload["tasks"]:
        assert task["start_time"] is None and task["deadline"] is None
        response = client.post("/api/tasks", json=task)
        assert response.status_code == 200, response.text
        assert response.json()["id"] == task["id"]
        saved.append(response.json())
    dinner, shower = saved
    assert dinner["dependency_ids"] == []
    assert shower["dependency_ids"] == [dinner["id"]]
    ids = {UUID(task["id"]) for task in saved}
    assert len(ids) == 2

    # The frontend sends an explicit 09:00-21:00 window in the extraction
    # timezone while retaining the actual current time and unchanged tasks.
    windows = [{"start": "2026-10-01T01:00:00.000Z", "end": "2026-10-01T13:00:00.000Z"}]
    generated = client.post(
        "/api/plans/generate",
        json={"task_ids": [task["id"] for task in saved], "now": now, "timezone": payload["timezone"], "windows": windows},
    )
    assert generated.status_code == 200, generated.text
    plan = generated.json()
    assert plan["version"] == 1
    assert plan["timezone"] == "Asia/Shanghai"
    assert not plan["unscheduled"]
    assert [item["task_id"] for item in plan["items"]] == [dinner["id"], shower["id"]]
    assert datetime.fromisoformat(plan["items"][0]["end"]) <= datetime.fromisoformat(plan["items"][1]["start"])

    response = client.post(
        f"/api/plans/{plan['id']}/events",
        json={"task_id": dinner["id"], "type": event_type, "at": now},
    )
    assert response.status_code == 200, response.text
    revised = response.json()["plan"]
    assert revised["version"] == 2
    assert revised["windows"] == plan["windows"]
    assert revised["task_ids"] == plan["task_ids"]
    assert all(item["task_id"] != dinner["id"] for item in revised["items"])
    if event_type == "complete":
        assert [item["task_id"] for item in revised["items"]] == [shower["id"]]
        assert not revised["unscheduled"]
    else:
        assert revised["items"] == []
        assert revised["unscheduled"] == [{
            "task_id": shower["id"], "reason": "dependency task is missing or could not be scheduled first",
        }]
    local_zone = timezone(timedelta(hours=8))
    for snapshot in (plan, revised):
        window = snapshot["windows"][0]
        start, end = (datetime.fromisoformat(window[key]) for key in ("start", "end"))
        assert start.astimezone(local_zone).isoformat() == "2026-10-01T09:00:00+08:00"
        assert end.astimezone(local_zone).isoformat() == "2026-10-01T21:00:00+08:00"
        for item in snapshot["items"]:
            assert UUID(item["task_id"]) in ids
            assert start <= datetime.fromisoformat(item["start"]) < datetime.fromisoformat(item["end"]) <= end
        assert client.get(f"/api/plans/{snapshot['id']}").json() == snapshot
    stored = {task["id"]: task for task in client.get("/api/tasks").json()}
    assert stored[dinner["id"]]["status"] == ("completed" if event_type == "complete" else "skipped")
    assert stored[shower["id"]]["dependency_ids"] == [dinner["id"]]
    assert all(task["start_time"] is None and task["deadline"] is None for task in stored.values())


def test_api_rejects_missing_members_and_invalid_inputs(api):
    client, _db_path, _main = api
    task = create_task(client, "member")
    outsider = create_task(client, "outsider")
    plan = generate(client, [task["id"]])
    foreign_event = client.post(
        f"/api/plans/{plan['id']}/events",
        json={"task_id": outsider["id"], "type": "complete"},
    )
    assert foreign_event.status_code == 404
    assert next(item for item in client.get("/api/tasks").json() if item["id"] == outsider["id"])["status"] == "inbox"
    assert client.post(f"/api/plans/{uuid4()}/events", json={"task_id": task["id"], "type": "complete"}).status_code == 404
    assert client.post(f"/api/plans/{plan['id']}/events", json={"task_id": str(uuid4()), "type": "complete"}).status_code == 404
    assert client.get(f"/api/plans/{uuid4()}").status_code == 404
    assert client.patch(f"/api/tasks/{uuid4()}", json={"status": "completed"}).status_code == 404
    invalid = client.post("/api/tasks", json={"title": "bad", "estimated_minutes": 10})
    assert invalid.status_code == 422
    assert client.get("/api/plans/not-a-uuid").status_code == 422
    assert client.post(f"/api/plans/{plan['id']}/events", json={"task_id": task["id"], "type": "delay", "minutes": -1}).status_code == 422


def test_replan_preserves_disjoint_windows_and_excludes_unrelated_tasks(api):
    client, _db_path, _main = api
    member = create_task(client, "member", 120)
    outsider = create_task(client, "outsider", 30)
    windows = [
        {"start": "2026-09-14T09:00:00+08:00", "end": "2026-09-14T10:00:00+08:00"},
        {"start": "2026-09-14T14:00:00+08:00", "end": "2026-09-14T16:00:00+08:00"},
    ]
    response = client.post("/api/plans/generate", json={"task_ids": [member["id"]], "windows": windows, "now": LOCAL_NOW.isoformat()})
    assert response.status_code == 200
    old = response.json()
    result = client.post(f"/api/plans/{old['id']}/events", json={"task_id": member["id"], "type": "delay", "minutes": 60, "at": "2026-09-14T12:00:00+08:00"})
    assert result.status_code == 200
    revised = result.json()["plan"]
    assert revised["windows"] == windows
    assert revised["task_ids"] == [member["id"]]
    assert all(item["task_id"] != outsider["id"] for item in revised["items"])
    assert revised["items"]
    assert all(datetime.fromisoformat(item["start"]) >= datetime.fromisoformat(windows[1]["start"]) and datetime.fromisoformat(item["end"]) <= datetime.fromisoformat(windows[1]["end"]) for item in revised["items"])
    # Booking work is not completing it, even when capacity only covers part.
    stored_member = next(item for item in client.get("/api/tasks").json() if item["id"] == member["id"])
    assert stored_member["remaining_minutes"] == 180
    assert revised["unscheduled"]
    assert client.get(f"/api/plans/{old['id']}").json() == old


def test_partial_plan_generation_keeps_unfinished_workload(api):
    client, _db_path, _main = api
    member = create_task(client, "long", 120)
    response = client.post("/api/plans/generate", json={"task_ids": [member["id"]], "now": LOCAL_NOW.isoformat(), "windows": [{"start": LOCAL_NOW.isoformat(), "end": (LOCAL_NOW + timedelta(minutes=90)).isoformat()}]})
    assert response.status_code == 200
    assert response.json()["unscheduled"]
    stored_member = client.get("/api/tasks").json()[0]
    assert stored_member["remaining_minutes"] is None
    assert stored_member["estimated_minutes"] == 120


def test_api_rejects_naive_datetimes_before_mutation(api):
    client, _db_path, _main = api
    task = create_task(client, "aware only")
    response = client.post(
        "/api/plans/generate",
        json={
            "task_ids": [task["id"]],
            "now": "2026-09-14T09:00:00",
            "windows": [{"start": "2026-09-14T09:00:00", "end": "2026-09-14T21:00:00"}],
        },
    )
    assert response.status_code == 422


def test_api_rejects_unknown_task_ids_and_invalid_windows(api):
    client, _db_path, _main = api
    task = create_task(client, "known")
    unknown = str(uuid4())
    missing = client.post(
        "/api/plans/generate",
        json={"task_ids": [task["id"], unknown], "now": LOCAL_NOW.isoformat()},
    )
    assert missing.status_code == 404
    invalid_window = client.post(
        "/api/plans/generate",
        json={
            "task_ids": [task["id"]],
            "now": LOCAL_NOW.isoformat(),
            "windows": [{"start": LOCAL_NOW.isoformat(), "end": LOCAL_NOW.isoformat()}],
        },
    )
    assert invalid_window.status_code == 422


def test_api_rejects_unsupported_event_types(api):
    client, _db_path, _main = api
    task = create_task(client, "event")
    plan = generate(client, [task["id"]])
    response = client.post(
        f"/api/plans/{plan['id']}/events",
        json={"task_id": task["id"], "type": "start"},
    )
    assert response.status_code == 422


def test_unscheduled_tasks_do_not_remain_planned(api):
    client, _db_path, _main = api
    task = create_task(client, "too long", minutes=120)
    plan = client.post(
        "/api/plans/generate",
        json={
            "task_ids": [task["id"]],
            "now": LOCAL_NOW.isoformat(),
            "windows": [{"start": LOCAL_NOW.isoformat(), "end": (LOCAL_NOW + timedelta(minutes=30)).isoformat()}],
        },
    )
    assert plan.status_code == 200
    assert plan.json()["unscheduled"]
    stored = next(item for item in client.get("/api/tasks").json() if item["id"] == task["id"])
    assert stored["status"] == "inbox"
