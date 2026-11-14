# 02: Detail page skeleton: summary and entry links

**What to build:** `#/run/<id>` shows the summary of a single activity; rows in the activity list, the home page's long-run table and the recent races table all link here. A nonexistent id gives a clear message.

**Blocked by:** 01

**Status:** done

Source: User Stories 6–9, and `running/detail.py` and "Non-running activities" under Implementation Decisions, in the [implementation spec](../spec.md).

- [x] `running/detail.py`: `activity_detail(activity_id, root)`, with only the summary at first
- [x] Summary: distance, duration, running pace (reusing `runwalk`), Garmin average pace as a reference, average and maximum heart rate, average spm, total ascent, air temperature (reusing `aerobic.air_temperature`)
- [x] `GET /api/activities/{activity_id}`; 404 when it does not exist, with a Chinese explanation in the JSON
- [x] Non-running activities: running-specific fields are null, with the reason "仅跑步类活动" (running activities only)
- [x] `static/run.js`: summary section; links added to list rows, the long-run table and the recent races table (when there is an `activity_id`)
- [x] Seam 3 tests: summary values; 404; nulls and reasons for non-running activities

## Outcome (implementation notes)

- Module `analysis/src/running/detail.py`: `activity_detail(activity_id, root=None)` returns None when the activity does not exist (or there is no analysis database); endpoint `GET /api/activities/{activity_id}` returns 404 on None, with `{"detail": "没有编号为 <id> 的活动。"}` (no activity with id <id>).
- Returns `activity{activity_id, activity_type, activity_name, start_time_local, is_running}` plus one key per section; this ticket has only `summary`.
- **Structure prepared for the parallel tickets 03–06**:
  - Backend: each section is a builder `(DetailInputs) -> dict`, registered in the `SECTIONS` dict at the end of the file. The dict has one comment line reserved per later ticket (`# series (ticket 03)` and so on); each ticket adds its entry **on the line after its own comment**; functions go in their own `# --- ... (ticket 0N) ---` block in the middle of the file. The comment lines keep each ticket's edits apart and reduce merge conflicts.
  - `DetailInputs` carries `db`, `config`, `activity` (the whole `activities` row), `is_running`, and `records`, loaded once on demand (`aerobic.load_records` + `runwalk.classify_records`, with `spm, dt_s, dd_m, running`). It has no `lat/lon`; the route ticket queries those itself.
  - Frontend `static/run.js`: `runPage(id)` reads the endpoint once; each item of the `RENDERERS` array is `(detail) => Node | null`, again with one comment slot per ticket (report 07 comes before the summary); functions go in their own blocks. `fmtDur`, `fmtPace` and `how` are exported for later sections to reuse.
- Summary fields: `distance_m, duration_s, running_pace_s_per_km, garmin_pace_s_per_km, avg_hr_bpm, max_hr_bpm, avg_cadence_spm, elevation_gain_m, air_temperature_c, unavailable{field: reason}, method`.
  - Running pace and Garmin average pace both come from `runwalk.running_summaries(activity_ids=[id])`; without cadence data it falls back to Garmin's totals as before.
  - **Heart rate (our choice)**: average heart rate is weighted by `dt_s` of the per-second records (pauses and the first sample excluded); maximum heart rate is the per-second maximum; without per-second heart rate, Garmin's values from the `activities` table are used.
  - **Cadence (our choice)**: running seconds only (`running` true), weighted by `dt_s`, the same definition as running pace; Garmin's average cadence includes walking and is not used.
  - Distance, duration and total ascent come from Garmin's values in the `activities` table, not recomputed from per-second altitude (barometer noise is large).
  - Air temperature: `aerobic.air_temperature`, null without weather data.
- **Non-running activities (scope we chose)**: `running_pace_s_per_km`, `garmin_pace_s_per_km` and `avg_cadence_spm` are null, each with "仅跑步类活动" (running activities only) in `unavailable`. Garmin average pace and cadence also count as running-specific: cycling cadence is rpm, and ×2 is not spm; pace has no meaning for non-running. The other fields are given as usual. For running activities `unavailable` is an empty dict; when a field is null for lack of data (e.g. no air temperature) no reason is written.
- Frontend: `#/run/<id>` in `app.js` switches to `runPage`; on 404 it shows "找不到这个活动" (activity not found) with the endpoint's explanation and a link back to all activities. The summary uses `.stat-line`; null values show the reason or "—" (grey). The dates in the home page's long-run table, and in the recent races table for rows with an `activity_id`, link to the detail page (list rows were linked in ticket 01). CSS is in the run-detail ticket 02 block at the end of `style.css`.
- Tests `analysis/tests/test_detail_api.py` (Seam 3, 5 tests): summary values for a run with 5 minutes of walking (running pace about 333 s/km, Garmin 373.1 s/km, average heart rate 144, max 150, cadence about 170, ascent, interpolated air temperature 12.42 °C); 404 and Chinese explanation for a nonexistent id; 404 without an analysis database; the three nulls and reasons for cycling, other fields as usual; a treadmill run without per-second records falls back to Garmin's totals and heart rate. Running pace and cadence allow ±1: the 15-second trailing smooth counts the first few seconds of walking as running (same example as ticket 01).
