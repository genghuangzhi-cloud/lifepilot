# LifePilot

**A personal planning prototype for HackNowa Global Hackathon 2026 — AI for Everyday Life.**

When a task takes longer than expected, the rest of the day needs to change too. LifePilot turns a task inbox into a prioritized timeline, records progress in SQLite, and shows how the plan changes after additional work, completion, or skipping a task.

The current version uses **rule-based offline extraction and deterministic scheduling**. No language model is connected yet. The demo runs locally without an AI API key.

Repository: [genghuangzhi-cloud/lifepilot](https://github.com/genghuangzhi-cloud/lifepilot). A hosted demo video link will be added after upload; no public application deployment is currently available.

## Try the demo

1. Start the API and frontend below, then open `http://127.0.0.1:3000`.
2. Click **Load demo scenario**, then **Extract tasks**. The demo uses a clearly labeled simulated 09:00 start so it can be recorded at any time.
3. Review the task estimates and assumptions. Click **Save tasks**, then **Generate adaptive plan**. Generating directly also saves the tasks.
4. Click **Needs 60m more** on **Review calculus chapters** in the timeline. This adds an hour of remaining work, then recalculates the plan.
5. Inspect version 2, **What changed**, the explanation, and any work that could not fit. **Complete** and **Skip** also revise the plan.

Loading a new scenario starts a new inbox; existing records stay in SQLite. Each generated plan uses only its selected tasks. Saving a batch again reuses its saved IDs during the current session. A browser reload resets the visible session; saved plans remain accessible through the API.

The demo extracts five tasks: **Exam**, **Review calculus chapters**, **Submit English assignment**, **Buy shampoo**, and **Reply to important email**. The exam has no explicit start time, so it stays under **Needs attention**; the other four tasks can be scheduled. The timeline uses tomorrow's date relative to the extraction clock.

To try a dependency, enter `Tomorrow, after dinner, take a shower.`, then extract, save, and generate a fresh plan. Completing **Dinner** satisfies **Shower**'s prerequisite; skipping Dinner leaves Shower blocked. Use a fresh extraction for each case. This example specifies order and date, not a dinner time: the default availability is 09:00–21:00 in the request timezone. Replanning keeps the saved window.

## Local setup (PowerShell)

Tested with Python 3.12 and Node.js 24. Use Node.js 24 for the built-in TypeScript test runner. Internet access is needed once to install dependencies.

From the repository root, start the backend:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In another terminal, from the repository root:

```powershell
cd frontend
npm ci
npm run dev
```

After installing both sets of dependencies, for one-click local startup from a Windows terminal, run the repository's
`start.bat`. It locates `backend`, `frontend`, and `backend\.venv` relative to
the script, opens a Backend and Frontend terminal, and opens the dashboard at
`http://127.0.0.1:3000/`:

```powershell
.\start.bat
```

By default the script uses `backend\data\lifepilot.db`. Set
`LIFEPILOT_DB_PATH` before launching it when you want an isolated demo or
acceptance database:

```powershell
$env:LIFEPILOT_DB_PATH = Join-Path $PWD 'backend\data\acceptance.db'
.\start.bat
```

The frontend defaults to `http://127.0.0.1:8000/api`. Copy `frontend/.env.example` to `frontend/.env.local` to configure `NEXT_PUBLIC_API_URL`, then restart the frontend. Public environment variables must not contain secrets.

The default database is `backend/data/lifepilot.db`, independent of the shell's working directory. Set `LIFEPILOT_DB_PATH` before starting the API to select a separate database, for example for a recording:

```powershell
# From backend/, before starting uvicorn
$env:LIFEPILOT_DB_PATH = Join-Path $PWD 'data/recording.db'
```

## Verification

```powershell
# From backend/
.venv\Scripts\python.exe -m pytest tests\test_parser.py tests\test_api.py tests\test_scheduler.py -q

# From frontend/
npm test
npx tsc --noEmit --incremental false
npm run build
```

Backend tests use temporary databases. See [validation notes](docs/validation.md) for the most recent results and remaining limits.

The validated implementation checkpoint is `c5aeabf`: **69 backend tests**, **7 frontend tests**, TypeScript, and the production build passed locally. Later documentation commits do not change this implementation.

## How it works

- **Next.js + React:** task inbox, timeline, progress controls, and comparison with the original plan.
- **FastAPI + Pydantic:** validated task and plan requests.
- **SQLite:** task records, immutable saved plan snapshots, and execution events.
- **Python rules:** weighted priority, dependency ordering, availability and deadline checks, and explicit unscheduled work.

Priority weights are urgency 30%, importance 25%, supplied deadline 30%, dependency impact 10%, and effort fit 5%. Replanning uses the selected plan's tasks and availability. Completed and skipped tasks remain recorded but leave the active schedule. Completed prerequisites satisfy dependencies; skipped or missing prerequisites keep dependent tasks blocked.

## API

| Endpoint | Purpose |
| --- | --- |
| `GET /api/health` | Health and task count |
| `POST /api/tasks/extract` | Extract drafts without saving |
| `POST /api/tasks` | Save a task |
| `GET /api/tasks` | List stored tasks |
| `PATCH /api/tasks/{id}` | Update a task |
| `POST /api/plans/generate` | Generate and save a plan |
| `GET /api/plans/{id}` | Read a saved plan snapshot |
| `POST /api/plans/{id}/events` | Record a progress change and revise the plan |
| `GET /api/dashboard` | Stored task metrics |

Interactive API documentation: `http://127.0.0.1:8000/docs`.

## Current limits

Extraction supports a tested set of action patterns, explicit times and durations, date context such as tomorrow, and before/after relations. It is not a general-purpose natural-language model. Missing task durations commonly default to 30 minutes, and fixed events without sufficient timing information remain unscheduled. Review the displayed assumptions and confirm dates, times, and dependencies for unfamiliar phrasing; a future structured LLM adapter could broaden coverage.

This is a local, single-user prototype. There is no authentication, calendar integration, public deployment, or automatic recovery of the visible dashboard after a browser reload. Public deployment requires persistent storage, access isolation, and an appropriate CORS configuration. Completed work is recorded through user events rather than a running timer.

## Competition materials

- [Project description](docs/project-description.md)
- [Demo recording script](docs/demo-script.md)
- [Submission checklist](docs/submission-checklist.md)
- [Competition information and unresolved rule checks](docs/competition-audit.md)

Use the actual repository and hosted video URLs in the submission form. Leave the optional live deployment field blank unless a public deployment is available. Deadline timezone and code-start rules still require verification on the official competition page.
