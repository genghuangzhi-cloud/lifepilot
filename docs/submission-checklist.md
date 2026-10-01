# HackNowa submission checklist

## Official page facts to re-check at upload time

- Competition: HackNowa Global Hackathon 2026, Innovation Hacks.
- Track: AI for Everyday Life.
- Participation: individual participation is allowed.
- Technology: any suitable technology, programming language, framework, or AI tools are allowed according to the page text.
- Required fields in the form supplied on 1 October 2026: Project Title, Problem Statement Selected, Project Description, GitHub Repository, and Demo Video Link. Live Deployment Link is optional.
- Final Submission window shown on the page: 01 Oct 2026 04:50 AM through 11 Oct 2026 02:15 AM. Confirm the displayed timezone and live countdown immediately before uploading.
- The page also shows 11 Oct 26, 02:21 AM for Submission Ends, conflicting with the stage's 02:15 AM. No consistent timezone was supplied. Treat the live submission countdown and organizer announcements as authoritative and submit early.
- The supplied form does not specify video duration, language, or hosting platform. Verify any additional requirements before submitting.

## Project assets

- [ ] Public GitHub repository URL works in an incognito window.
- [ ] README explains the problem, solution, architecture, local setup, and demo flow.
- [ ] Demo video shows extraction, the initial plan, 60 minutes of additional work, the revised plan, and the explanation panel.
- [ ] Live demo URL is reachable, or leave the optional field empty.
- [ ] No API keys, `.venv`, `node_modules`, `.next`, logs, or personal data are committed.
- [ ] Local databases and recordings are excluded from the Git repository; preserve existing local records.

## Submission values

- **Project Title:** LifePilot — Adaptive Task Planning and Replanning
- **Problem Statement Selected:** AI for Everyday Life
- **Project Description:** See [project-description.md](project-description.md).
- **GitHub Repository:** https://github.com/genghuangzhi-cloud/lifepilot
- **Demo Video Link:** Add the hosted main recording URL after checking viewer access.
- **Live Deployment Link:** Leave blank unless a public application is available; localhost is not a public deployment.

## Recording outline

1. “LifePilot turns everyday tasks into an adaptive execution plan.”
2. Load the scenario: exam review, English assignment, household shopping, and an important email.
3. Extract tasks and point out urgency, importance, and effort.
4. Generate the first timeline and explain that the scheduler is deterministic and offline-ready.
5. Add 60 minutes of remaining effort to Review calculus chapters.
6. Show the new plan version, the moved task, and the explanation of what changed.
7. Show Complete Dinner → Shower remains schedulable; use a fresh batch for the optional Skip → Shower blocked example.
8. Close with: “LifePilot makes plan changes and unscheduled work visible.”
