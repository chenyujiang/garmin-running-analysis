# 06: Metrics for this run: TRIMP, heart-rate zones, aerobic fitness value, EF, decoupling

**What to build:** the detail page's "本次指标" (metrics for this run) section: TRIMP, time in each heart-rate zone, this run's aerobic fitness value (or the reason it does not count), EF, and decoupling for runs of 60 minutes or more, each with "怎么算的" (how it is computed).

**Blocked by:** 02

**Status:** done

Source: User Stories 17–20, and "Heart-rate zones" and the notes on reuse under Implementation Decisions, in the [implementation spec](../spec.md).

- [x] Before writing code, check Friel's running LTHR zones against the original source; if they differ, follow the source and record it in the outcome
- [x] New config `[zones]`: `lthr_pct = [85, 90, 95, 100]`; LTHR is taken from the `[[physiology]]` entry in effect on the activity date
- [x] Heart-rate zones count only seconds with heart rate that are not in a pause
- [x] TRIMP reuses `load`'s per-second algorithm; the aerobic fitness value reuses the conditions of `aerobic_runs`, and gives a specific reason when it does not count
- [x] EF and decoupling reuse `longruns`' definitions
- [x] Frontend: zones as horizontal bars, the rest as numbers with "怎么算的" (how it is computed)
- [x] Seam 3 tests: time in each zone; LTHR picked by date after changing `[[physiology]]`; TRIMP matches the same activity in `/api/load`; reasons for not counting towards aerobic fitness; no decoupling at 59 minutes

## Outcome (implementation notes)

- **Source of Friel's zones**: TrainingPeaks, Joe Friel, "Joe Friel's Quick Guide to Setting Zones" (published 2012-05-04, updated 2026-07-18), https://www.trainingpeaks.com/learn/articles/joe-friel-s-quick-guide-to-setting-zones/ . Running LTHR zones: Z1 < 85%, Z2 85–89%, Z3 90–94%, Z4 95–99%, Z5a 100–102%, Z5b 103–106%, Z5c > 106%. Consistent with the spec; the only difference is that the source splits Z5 into 5a–5c, which here are merged into one Z5 (≥ 100%) per the spec, noted in `method.description`. Each zone includes its lower bound and excludes its upper bound (the source uses whole percentages, so half-open intervals are equivalent).
- Endpoint: `GET /api/activities/{id}` gains a `metrics` key (`_metrics` in `detail.py`, registered in the ticket 06 slot of `SECTIONS`). Fields:
  - `trimp`, `trimp_source` (`records` or `summary_hr`).
  - `zones`: `lthr_bpm, physiology_effective_from, lthr_pct, total_s, zones[]{zone, low_bpm, high_bpm, seconds, share}`; Z1's `low_bpm` and Z5's `high_bpm` are null.
  - `aerobic`: `speed_mps, pace_s_per_km, steady_s, mean_hr, reference_hr`.
  - `ef`: `ef, ef_first, ef_second, steady_s, decoupling_pct, decoupling_high`.
  - `unavailable`: reasons for the items that are null (`trimp`, `zones`, `aerobic`, `ef`, `decoupling`); `method{name, description, params}`.
- New config `[zones]` (`Zones` in `config.py`): `lthr_pct` defaults to `[85, 90, 95, 100]`, must be 4 increasing numbers, otherwise `load_config` raises. LTHR is taken by activity date with `load.physiology_on`.
- **Zone timing (our choice)**: each sample owns the second up to it (`dt_s` from `classify_records`); the first sample after a pause and the activity's first sample do not count; only seconds with heart rate count. TRIMP keeps `load`'s definition (the gap to the next sample, capped at `max_sample_gap_s`, the last sample counting as 1 second), so the two total second counts can differ by a second or two.
- **TRIMP**: `load.py` factors out `_trimp_of` and `activity_trimp(db, config, activity)`, so daily load and single activities go through the same code (`_HR_SECONDS_SQL` gains `{where}`). Without per-second heart rate it is estimated from the summary average heart rate (`summary_hr`), as in `/api/load`.
- **Aerobic fitness value**: calls `aerobic.aerobic_runs` directly (for this one start time only), so it matches the point on the aerobic fitness page exactly. When it does not count, the reason is the first that applies, in order: `仅跑步类活动` (running activities only); `不是户外路跑（跑步机和越野不计入）` (not an outdoor road run (treadmill and trail do not count)); `没有逐秒记录` (no per-second records); `没有心率` (no heart rate); `逐秒记录没有 GPS 位置（像跑步机）` (per-second records have no GPS position (like a treadmill)); `逐秒记录没有海拔` (per-second records have no altitude); `GPS 漂移：速度超过 X m/s 的秒有 N 秒（上限 60 秒）` (GPS drift: N seconds faster than X m/s (limit 60 seconds)); `稳态时间 N 分钟，不足 10 分钟` (N minutes of steady state, less than 10 minutes).
- **Heart-rate band for EF and decoupling (differs from the spec)**: the spec says "the same definitions as `longruns` (steady-state segments without the heart-rate band condition)", which was ticket 13's first approach; commit 2845fc1 later changed `longruns` back to steady-state segments with the heart-rate band (145 ± 15). Here `longruns._per_run_ef` is called directly, keeping the current definition, so the detail page and the long-run table show the same numbers; to drop the heart-rate band, change it in one place in `longruns`.
- EF has the same threshold as the aerobic fitness value (outdoor road run, `gps_usable`, steady state ≥ 10 minutes), so activities that do not count towards aerobic fitness get no EF either, with the same reason. Decoupling is given only for activities with a Garmin duration ≥ 60 minutes (`longruns.MIN_DURATION_S`), otherwise the reason is `不足 60 分钟，只给 EF，不算 decoupling` (under 60 minutes: EF only, no decoupling); above 5% (`DECOUPLING_LIMIT_PCT`) `decoupling_high` is true and the frontend marks it red.
- Without physiological parameters the zones' reason is `该日期没有生效的生理参数` (no physiological parameters in effect on this date); with summary heart rate but no per-second heart rate it is `没有逐秒心率` (no per-second heart rate); with neither it is `没有心率` (no heart rate).
- Frontend: `metricsSection` in `static/run.js` (the ticket 06 slot of `RENDERERS`): TRIMP, aerobic fitness (GAP pace), EF and decoupling as numbers, with the reason shown for missing items; heart-rate zones as horizontal bars (zone, bpm range, time, share). CSS is in the ticket 06 block at the end of `style.css`.
- Tests `analysis/tests/test_detail_metrics_api.py` (Seam 3, 22 tests): time and boundaries of each zone; LTHR changed by date; `[zones]` changing the lower bounds; paused seconds and seconds without heart rate not counted; TRIMP matching `/api/load`, the known value for one hour at HRmax, the summary heart-rate estimate; no heart rate; aerobic fitness value matching `/api/aerobic`; 8 reasons for not counting; 60 minutes with EF = 1.2 and decoupling 0; EF and decoupling of a drifting run matching `/api/long-runs` and marked red; 59 minutes with EF but no decoupling; no EF for cycling or treadmill.
- 2026-11-04, the user's decision: EF and decoupling are not limited to the heart-rate band, and `longruns` changes with them. The detail page's EF no longer uses the aerobic fitness value as its threshold; instead it needs an outdoor road run, per-second heart rate, usable GPS, and ≥ 10 minutes of steady state without the heart-rate band.
