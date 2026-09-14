# LifePilot — Project Description

**Competition:** HackNowa Global Hackathon 2026  
**Selected direction:** AI for Everyday Life  
**Stage:** Local, single-user prototype

## Submission description

Everyday plans often break when a task takes longer than expected. A list can record what needs doing, but it does not show how a change affects the rest of the day.

LifePilot turns a small set of tasks into a prioritized timeline and revises that timeline as the user reports progress. The user loads or enters a scenario, reviews the extracted tasks, and generates a plan. If a task needs another hour, **Needs 60m more** adds 60 minutes to its remaining work and triggers replanning. The dashboard displays the new plan version, changes to scheduled start times, and an explanation. Users can also mark tasks complete or skip them. Work that cannot fit is surfaced for attention.

The scheduling engine uses deterministic Python rules. Its priority score combines urgency, importance, deadline information when supplied, dependency impact, and effort. It attempts to place work within the supplied availability and reports unscheduled work. A FastAPI backend stores tasks, plans, and execution events in SQLite; a Next.js dashboard provides the interaction and comparison views.

The current prototype uses **rule-based offline extraction, with no LLM integration yet**. The featured demo scenario uses predefined task estimates and priorities. Other input receives basic text splitting and default estimates; the prototype does not infer reliable deadlines from natural language. This makes the demonstrated behavior reproducible without an AI API key, while keeping extraction replaceable by a structured language-model adapter in a future version.

LifePilot's focus is the visible execution loop: review a plan, report what changed, and inspect the revised result. The current submission demonstrates that loop locally. Public deployment, account management, calendar integration, and a general-purpose AI extractor are future work.

## Short summary

LifePilot is a local personal-planning prototype that creates prioritized timelines and replans when tasks need more work, are completed, or are skipped. It combines a Next.js dashboard, FastAPI, SQLite, and deterministic scheduling. The current extractor is rule-based and offline; no LLM is connected yet.

## Submission assets

- **GitHub Repository:** Add the actual repository URL after publishing and checking public access.
- **Demo Video:** Add the actual recording URL after uploading and checking viewer access.
- **Live Demo:** No public deployment is claimed. Leave this optional field empty until a working public deployment is available.

Do not paste the asset instructions above into URL fields. Re-check the organizer's current field limits and submission requirements before uploading.
