# Deviations from the spec

## Deviations confirmed and kept

The five items below are trade-offs made during implementation and left unchanged in code review. On 2026-10-31 the user confirmed keeping all of them, and the spec was updated to match.

1. **There are 9 running types** (`RUNNING_TYPES`): besides the ones the spec named, they include Garmin's other running subtypes (track, trail, treadmill, virtual run and so on). Load, weekly volume and long runs all count these 9.
2. **TSB uses yesterday's CTL/ATL**: TSB = CTL(yesterday) − ATL(yesterday), i.e. the state before today's training (the TrainingPeaks convention). The spec said same-day CTL − ATL.
3. **The Riegel exponent k is clamped to [1.01, 1.20]**: a k fitted from two races that falls outside this range is clamped, so odd data does not give odd predictions.
4. **`MetricsSource` is a separate trait**: syncing Garmin's three reference metrics uses its own trait instead of sharing one source abstraction with activity sync.
5. **Exit code 0 during a cooldown**: after a Garmin rate limit there is a 24-hour cooldown. During it, `runsync sync` skips the Garmin metrics, prints a notice and still exits 0; this is not a failure.

The two items below come from pushing the 5K plan to Garmin Connect (PR #10, `running-push-plan`) and were raised in code review. On 2026-11-09 the user confirmed keeping them, and the spec was updated to match.

6. **Python calls the importer's garminconnect script**: the spec originally said the two sides exchange data only through the data directory. Pushing needs garminconnect's tokens and client, which live only in `importer/garminconnect/garmin_metrics.py`, so `running-push-plan --apply` starts its `push` subcommand with `uv run --script` and exchanges JSON over stdin/stdout. The analysis database stays read-only. In tests, `push_plan.main` takes a `runner` argument that wires the importer script's `push()` to a fake Garmin client; another test runs the script's `push` subcommand for real with a stub `garminconnect` package, checking that Chinese names survive any console code page.
7. **Python writes `state/`**: the spec originally said the analysis package is read-only and `state/` only holds the cooldown marker. The push writes the ids Garmin returns into `state/plan5k_push.json` (to prevent duplicates, and so `--replace` deletes only what it created); on a rate limit it writes `state/garminconnect.cooldown.json` in the same format as `runsync sync`, and it refuses to push during a cooldown.

## Other confirmed decisions

- **One spelling for training status** (2026-10-31): the API's `trainingStatusFeedbackPhrase` has a numeric suffix (`PRODUCTIVE_1`); the export does not (`PRODUCTIVE`). `garmin_metrics.training_status` always stores the name without the suffix (`training_status_name` in `importer/src/garmin_metrics.rs`).
