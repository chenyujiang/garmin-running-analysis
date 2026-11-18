# Coding standards

Judgement rules for review. Mechanical rules live in the checks of `.github/workflows/check.yml` (rustfmt, clippy, ruff), not here.

## Tests

- **Synthetic FIT messages carry the reference fields a real watch writes.** fitparser names a field by its subfield, and the subfield depends on a reference field in the same message: a lap's `sport` turns field 17 from `avg_cadence` into `avg_running_cadence`. A test message without `sport` exercises a name the watch never sends, so the test passes while real data comes back `NULL`. When a test checks a field that has subfields, the message includes the field that selects them, set as the watch sets it.
