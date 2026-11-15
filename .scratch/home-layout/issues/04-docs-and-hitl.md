# 04: Documentation updates and a user check (HITL)

**What to build:** Update `README.md` and `GLOSSARY.md`. The user looks at the new layout and the merged recent races on real data and says whether it reads well.

**Blocked by:** 01–03

**Status:** open

Source: "Docs" under Implementation Decisions, and Further Notes, in the [implementation spec](../spec.md).

- [x] `README.md`: recent races merge `races.csv` with parkruns
- [x] `GLOSSARY.md`: a parkrun entry (what counts as a parkrun; shown in recent races and used as the prediction fallback)
- [x] Any design doc that records the page width or band layout is updated
- [ ] User check on real data (the agent reports only aggregate numbers, such as row counts by source, and never activity names): home page at a wide window and at phone width; the 5K plan, plan review and parkrun tables; recent races
- [x] The user says whether parkruns crowd out `races.csv` races in the 10 rows; if so, record the follow-up they choose

## Outcome (implementation notes)

- `README.md`: the `races.csv` section says predictions fall back to the parkruns of the last 6 months, and a new paragraph describes the home page's recent races: `races.csv` past races merged with parkruns from `running.sqlite` (the rule from `running.races.parkruns`), newest first, 10 rows, `source` per row, one row per `activity_id` with `races.csv` winning, parkruns listed even when `races.csv` is missing or malformed; the aerobic chart marks only `races.csv` races.
- `GLOSSARY.md`: new **parkrun** entry after **比赛**: the rule, shown in recent races (deduplicated against `races.csv`), and the prediction fallback.
- No other doc recorded 1560 px, 980 px or the three-column band (searched the whole repository); nothing else to update.
- The two user checks are left for the user.
- User check (2026-11-15): on real data all 10 rows were parkruns. The user chose: always keep the newest `races.csv` races and fill the 10 rows with parkruns. Done in `static/races.js` (`shownRaces`, tested in `tests/js/races.test.mjs`); `/api/races` still sends the whole merged list.
