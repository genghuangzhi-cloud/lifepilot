# LifePilot — Demo Script

**Target duration:** 90–120 seconds  
**Language:** English  
**Main demonstration:** Original plan → additional work → revised plan

## Before recording

- Run the backend and frontend, then open `http://127.0.0.1:3000/`.
- Use a disposable demo instance or a clean demo database. Preserve existing personal data separately; do not delete it to prepare the recording.
- Verify the full flow once with the current build. The effort-change button should read **Needs 60m more**.
- Make sure the scheduling window has room for the scenario and its extra hour. Check the displayed clock and timeline times before recording.
- Keep the task inbox, timeline, plan version, and comparison panel readable. Avoid showing account details, keys, unrelated browser tabs, or console output.
- The demonstration runs locally and requires no AI API key. Do not describe it as a public live deployment or an LLM-powered extractor.

## Recording sequence

| Time | Screen action | Spoken narration |
| --- | --- | --- |
| 0–12 s | Start on the empty dashboard with the LifePilot name visible. | “Everyday plans change when work takes longer than expected. LifePilot helps you see what that change means for the rest of your tasks.” |
| 12–27 s | Click **Load demo scenario**, pause over the input, then click **Extract tasks**. | “Here is a familiar scenario: exam review, an assignment, shopping, and an important email. This prototype uses a rule-based offline extractor. It has no LLM connected yet.” |
| 27–43 s | Show the task inbox, estimates, priority scores, and assumptions. | “The demo provides predefined estimates and priorities for review. General input uses simpler defaults, and natural-language deadlines are not inferred reliably. The assumptions are visible before planning.” |
| 43–59 s | Click **Generate adaptive plan** and show version 1. | “The deterministic scheduler turns these tasks into a timeline. It considers urgency, importance, effort, and any supplied deadline or dependency information. Work that cannot fit is reported for attention.” |
| 59–77 s | On the first scheduled task, click **Needs 60m more**. | “Suppose this task needs another hour of work. This control adds sixty minutes to the task's remaining effort. LifePilot then recalculates the schedule.” |
| 77–98 s | Show the revised version, later task times, **What changed**, and the explanation panel. | “The plan now has a new version. Here we can inspect the revised times and compare changed start times with the original plan. Completing or skipping a task also triggers replanning.” |
| 98–113 s | End with the timeline and comparison panel visible. | “Tasks, plans, and execution events are stored locally in SQLite. LifePilot makes scheduling trade-offs visible and helps you adapt your plan. This is the current local prototype; language-model extraction and public deployment are future work.” |

The timings are guides. Let the requests finish and show the actual result; do not claim an outcome that is absent from the screen. If the plan reports insufficient capacity, briefly point to that message instead of saying every task fits.

## Demo input

```text
Exam tomorrow: review calculus chapters and submit English assignment. Buy shampoo and reply to the important email.
```

The predefined extracted task titles are:

- Review exam topics
- Submit English assignment
- Buy household supplies
- Reply to important email

“Exam tomorrow” is part of the scenario text, not evidence that the current extractor has parsed an exam deadline.

## Capture and upload checks

- Record the working interface and audible narration at a readable resolution.
- Rewatch the exported video to check timing, text visibility, audio, and the visible replan result.
- Upload only after the recording is ready. Verify the resulting link works for viewers who are not signed in to the owner's account.
- Check the competition's current video requirements before submitting. The 90–120 second length is a project recommendation, not a verified organizer requirement.
