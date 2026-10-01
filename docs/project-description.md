# LifePilot — Project Description

**Competition:** HackNowa Global Hackathon 2026  
**Selected direction:** AI for Everyday Life  
**Stage:** Local, single-user prototype

## Submission description

Everyday plans often break when a task takes longer than expected. A list can record what needs doing, but it does not show how a change affects the rest of the day.

LifePilot turns a small set of tasks into a prioritized timeline and revises that timeline as the user reports progress. The user loads or enters a scenario, reviews the extracted tasks, and generates a plan. If a task needs another hour, **Needs 60m more** adds 60 minutes to its remaining work and triggers replanning. The dashboard displays the new plan version, changes to scheduled start times, and an explanation. Users can also mark tasks complete or skip them. Work that cannot fit is surfaced for attention.

The scheduling engine uses deterministic Python rules. Its priority score combines urgency, importance, deadline information when supplied, dependency impact, and effort. It attempts to place work within the supplied availability and reports unscheduled work. A FastAPI backend stores tasks, plans, and execution events in SQLite; a Next.js dashboard provides the interaction and comparison views.

The current prototype uses **rule-based offline extraction, with no LLM integration yet**. It handles tested action phrases, explicit times and durations, tomorrow date context, and before/after dependencies. Missing durations use default estimates, and fixed events with insufficient timing information remain under Needs attention. This makes the demonstrated behavior reproducible without an AI API key; unfamiliar language still requires review.

Completed prerequisites allow dependent tasks to proceed, while skipped prerequisites keep them blocked. Replanning retains the selected plan's saved availability, including future-date windows. Local verification at implementation checkpoint `c5aeabf` passed 69 backend tests, 7 frontend tests, TypeScript checks, and a production build, alongside manual browser acceptance of the key flows.

LifePilot's focus is the visible execution loop: review a plan, report what changed, and inspect the revised result. The current submission demonstrates that loop locally. Public deployment, account management, calendar integration, and a general-purpose AI extractor are future work.

## Short summary

LifePilot is a local personal-planning prototype that creates prioritized timelines and replans when tasks need more work, are completed, or are skipped. It combines a Next.js dashboard, FastAPI, SQLite, and deterministic scheduling. The current extractor is rule-based and offline; no LLM is connected yet.

## Submission assets

- **GitHub Repository:** https://github.com/genghuangzhi-cloud/lifepilot
- **Demo Video:** Add the actual recording URL after uploading and checking viewer access.
- **Live Demo:** No public deployment is claimed. Leave this optional field empty until a working public deployment is available.

Do not paste the asset instructions above into URL fields. Re-check the organizer's current field limits and submission requirements before uploading.
