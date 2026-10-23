# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

FastAPI (localhost only, 127.0.0.1) serving JSON computed by the Python package `analysis/src/running/` (polars + DuckDB, analysis database opened read-only), plus a static frontend: plain HTML, native ES modules and hand-written SVG charts, no node build step, fonts self-hosted. Decided in ticket 08 after a Streamlit comparison prototype could not reproduce the editorial annotations and typography without fragile CSS overrides.

## Users

One person: the owner of the Garmin account, a recreational runner who analyses their own data. They run `runsync sync` by hand on their desktop computer, then open the dashboard about once or twice a week, typically after a long run or for a weekend review. Each visit lasts a few minutes on a desktop monitor. Not used on a phone. Deeper digging happens in Jupyter, not in the dashboard.

## Product Purpose

Show, at a glance, whether training is on track, using models the user computes themselves (transparent, tunable) rather than Garmin's black-box numbers. Garmin's own figures appear only as a reference.

Priority on open:

1. Recent load: is the current training enough or too much (CTL/ATL/TSB, this week's running distance, load-spike warning when ATL/CTL > 1.5).
2. Aerobic fitness trend over months and years (running pace at reference HR 145 bpm, weekly median plus 4-week rolling median, weekly mean temperature shown alongside, EF and decoupling as supporting metrics).
3. Race prediction as a small card (VDOT primary, Riegel comparison, marathon with mileage adjustment, Garmin prediction as reference, "stale" state when there is no recent race).

## Positioning

A personal, self-computed view of the user's own running: every number traceable to a documented formula and configurable parameters, built from the user's full Garmin history since 2021-08.

## Operating Context

- Data comes from a local SQLite analysis database written by the Rust importer; the dashboard opens it read-only.
- Runs on localhost only. Single user, no accounts, no cloud.
- The user watch is not worn at night, so there is no HRV or sleep data; resting HR is partial.

## Capabilities and Constraints

- Interface text in Chinese; metric abbreviations (CTL, ATL, TSB, VDOT, EF, TRIMP) stay in English.
- Units: pace in min/km, distance in km, heart rate in bpm.
- Terminology follows `GLOSSARY.md` (e.g. 跑步配速, 周跑量, 有氧能力, 参考心率).
- States to handle: no data synced yet; weeks with fewer than 2 qualifying runs (aerobic value left blank); no recent race (prediction marked stale).

## Evidence on Hand

Real data exists only in the user's data directory (outside the repo). Prototypes use illustrative data. Do not commit real activity data or GPS traces.

## Product Principles

- Decision first: the top of the screen answers "what should I do this week".
- Every number explains itself: formula and parameters are reachable, Garmin values shown as reference, never as the headline.
- Honest gaps: missing or insufficient data is shown as missing, not interpolated.
- Glanceable in minutes; depth belongs in Jupyter.
