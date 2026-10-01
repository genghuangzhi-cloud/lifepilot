# LifePilot — Demo Script

**Suggested duration:** About 3 minutes, plus an optional 30–45 second Skip example

**Language:** English

**Main demonstration:** Extract → Save → tomorrow plan → additional work → revised plan → completed prerequisite

## Before recording

- Run the backend and frontend, then open `http://127.0.0.1:3000/`.
- Start a fresh inbox for each example. An isolated demo database is optional; do not delete existing data to prepare the recording.
- Verify the full flow once with the current build. The effort-change button should read **Needs 60m more**.
- Make sure the scheduling window has room for the scenario and its extra hour. Check the displayed clock and timeline times before recording.
- Keep the task inbox, timeline, plan version, and comparison panel readable. Avoid showing account details, keys, unrelated browser tabs, or console output.
- The demonstration runs locally and requires no AI API key. Do not describe it as a public live deployment or an LLM-powered extractor.

## Recording sequence

| Time | Screen action | Spoken narration |
| --- | --- | --- |
| 0–15 s | Start on the dashboard with the LifePilot name visible. | “Everyday tasks pile up, and when one takes longer than expected, the rest of the plan changes too. LifePilot adapts a timeline as you report progress.” |
| 15–35 s | Click **Load demo scenario**, show the input, then **Extract tasks**. | “Here is an exam tomorrow, revision, an assignment, shopping, and an email. This prototype uses local rule-based extraction without a connected language model.” |
| 35–55 s | Show five tasks and the assumptions. | “Missing durations use default estimates. The exam has a date but no start time, so it needs confirmation instead of receiving an invented time.” |
| 55–78 s | Click **Save tasks**, then **Generate adaptive plan**. | “Four tasks appear on tomorrow's timeline. The exam remains under Needs attention, so missing information stays visible.” |
| 78–112 s | Click **Needs 60m more** on Review calculus chapters; show v2 and **What changed**. | “Revision needs another hour of remaining work. LifePilot recalculates the plan and explains the changed times.” |
| 112–160 s | Extract and save the Dinner/Shower example below, generate v1, then **Complete Dinner**. | “Dinner is scheduled first. Once it is complete, it is not scheduled again, and Shower remains eligible because its prerequisite is satisfied.” |
| 160–180 s | End with the revised timeline and comparison panel visible. | “Tasks, plans, and progress events are stored locally in SQLite. LifePilot makes plan changes and unscheduled work visible. Richer extraction and calendar integration are future improvements.” |

The timings are guides. Let the requests finish and show the actual result; do not claim an outcome that is absent from the screen. If the plan reports insufficient capacity, briefly point to that message instead of saying every task fits.

## Demo input

```text
Exam tomorrow: review calculus chapters and submit English assignment. Buy shampoo and reply to the important email.
```

The extracted task titles are:

- Exam
- Review calculus chapters
- Submit English assignment
- Buy shampoo
- Reply to important email

The exam's date context is recognized, but its start time is unknown. Expect five extracted tasks, four scheduled tasks, and Exam under Needs attention. Tomorrow is relative to the extraction clock; do not hard-code a date into the narration.

## Dependency example

```text
Tomorrow, after dinner, take a shower.
```

Extract, save, and generate a new plan. Completing Dinner satisfies Shower's prerequisite; the revised plan contains Shower and records one completed task. The example specifies a date and order, not a dinner time; 09:00 comes from the default availability window.

For the optional Skip clip, extract and save a fresh batch, generate v1, then skip Dinner. Wait for v2 before explaining that Shower is blocked. The empty timeline and dependency reason mean no task is eligible, not that saved tasks were deleted.

## Capture and upload checks

- Record the working interface and audible narration at a readable resolution.
- Rewatch the exported video to check timing, text visibility, audio, and the visible replan result.
- Upload only after the recording is ready. Verify the resulting link works for viewers who are not signed in to the owner's account.
- Keep captions short and place them clear of task cards, the version number, and What changed.
- Check the competition's current video requirements before submitting. The suggested duration and English narration are production choices, not verified organizer requirements.
