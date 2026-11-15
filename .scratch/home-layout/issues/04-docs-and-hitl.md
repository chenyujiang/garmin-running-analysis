# 04: Documentation updates and a user check (HITL)

**What to build:** Update `README.md` and `GLOSSARY.md`. The user looks at the new layout and the merged recent races on real data and says whether it reads well.

**Blocked by:** 01–03

**Status:** open

Source: "Docs" under Implementation Decisions, and Further Notes, in the [implementation spec](../spec.md).

- [ ] `README.md`: recent races merge `races.csv` with parkruns
- [ ] `GLOSSARY.md`: a parkrun entry (what counts as a parkrun; shown in recent races and used as the prediction fallback)
- [ ] Any design doc that records the page width or band layout is updated
- [ ] User check on real data (the agent reports only aggregate numbers, such as row counts by source, and never activity names): home page at a wide window and at phone width; the 5K plan, plan review and parkrun tables; recent races
- [ ] The user says whether parkruns crowd out `races.csv` races in the 10 rows; if so, record the follow-up they choose
