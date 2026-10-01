# Validation notes

Implementation checkpoint: `c5aeabf` — Preserve extraction date context for undated plans. The local regression gates below were completed on 30 September 2026, followed by user UI acceptance.

- Backend: `69 passed` with temporary SQLite databases.
- Frontend: `7 passed` with Node.js 24, including Extract → Save → Generate request handling.
- TypeScript: `tsc --noEmit --incremental false` passed.
- Next.js: `next build` passed and generated a static `/` page.
- Parser A–H direct/API comparisons passed in the preceding core acceptance gate; Parser logic remained unchanged during the completed-prerequisite and frontend date-context fixes.
- UI acceptance: Demo extraction, saving and planning; Tomorrow Dinner/Shower planning; Complete Dinner → Shower schedulable; Skip Dinner → Shower blocked. Replanning increments the version and retains task IDs and the saved availability.
- With the test clock at 2026-09-30 in Asia/Shanghai, the undated Tomorrow routine uses a 2026-10-01 09:00–21:00 window. API readback confirmed that the same window is retained after Complete and Skip, including an empty revised plan.

The final run reported an existing Starlette deprecation warning and a CSS autoprefixer build warning. Neither failed the gates. These results describe the recorded local run, not a claim that GitHub Actions has already passed.

## Reproduce

```powershell
# From backend/
.venv\Scripts\python.exe -m pytest tests -q

# From frontend/ (Node.js 24)
npm test
npx tsc --noEmit --incremental false
npm run build
```

Automated backend tests use isolated temporary databases. Manual browser acceptance used the running local database, with newly extracted task batches; it did not use an empty database. Existing saved plans are not migrated by the date-context fix. Re-extract, save, and generate a new plan to exercise the updated request flow.

The current verification is local and single-user. It does not claim public deployment, account isolation, calendar integration, or LLM extraction.
