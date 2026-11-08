# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "garminconnect==0.3.20",
#     "tzdata; sys_platform == 'win32'",
# ]
# ///
"""garminconnect data source for `runsync`. Run with `uv run --script`.

Subcommands:

- ``login --token-dir DIR``: ask for email, password (getpass) and MFA code
  on the terminal, log in once and store only the token in DIR. The
  password is never stored.
- ``serve --token-dir DIR --interval S``: load the token from DIR (never
  logs in with credentials), then read requests ``<metric> <YYYY-MM-DD>``
  from stdin, one per line, and answer each with the raw API response as
  one line of JSON on stdout. Requests are sent one at a time with at
  least S seconds between them. stdout carries only JSON; messages go to
  stderr.
- ``push --token-dir DIR --interval S``: load the token the same way, read
  one JSON object ``{"delete": [workout ids], "workouts": [{"date":
  "YYYY-MM-DD", "workout": {...}}]}`` from stdin, delete the listed workouts
  (ones an earlier push created), then upload each workout and schedule it
  on its date in the Garmin Connect calendar. Each result is one JSON line on
  stdout as soon as it is done: ``{"deleted": id}`` or ``{"date": ...,
  "workout_id": ..., "schedule_id": ...}``. Finally asks Garmin to send the
  scheduled workouts to the devices (best effort).

Exit codes: 0 ok, 1 other error, 3 token missing/expired or rejected,
4 rate limited (HTTP 429) or CAPTCHA required. The first error ends the
process; nothing is retried here.
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
import time
from datetime import date
from pathlib import Path

EXIT_OK = 0
EXIT_OTHER = 1
EXIT_AUTH = 3
EXIT_RATE_LIMITED = 4


def main() -> int:
    parser = argparse.ArgumentParser(prog="garmin_metrics.py")
    sub = parser.add_subparsers(dest="command", required=True)
    login = sub.add_parser("login")
    login.add_argument("--token-dir", required=True, type=Path)
    serve = sub.add_parser("serve")
    serve.add_argument("--token-dir", required=True, type=Path)
    serve.add_argument("--interval", type=float, default=5.0)
    push_cmd = sub.add_parser("push")
    push_cmd.add_argument("--token-dir", required=True, type=Path)
    push_cmd.add_argument("--interval", type=float, default=2.0)
    args = parser.parse_args()
    try:
        if args.command == "login":
            return do_login(args.token_dir)
        if args.command == "push":
            return do_push(args.token_dir, args.interval)
        return do_serve(args.token_dir, args.interval)
    except Exception as err:  # noqa: BLE001 - mapped to an exit code
        return report_error(err)


def do_login(token_dir: Path) -> int:
    from garminconnect import Garmin

    email = input("Garmin Connect email: ").strip()
    password = getpass.getpass("Garmin Connect password: ")
    token_dir.mkdir(parents=True, exist_ok=True)
    garmin = Garmin(
        email=email,
        password=password,
        prompt_mfa=lambda: input("MFA code: ").strip(),
    )
    garmin.login(str(token_dir))
    garmin.client.dump(str(token_dir))
    print(f"token stored in {token_dir}", file=sys.stderr)
    return EXIT_OK


def load_token(token_dir: Path):
    """A logged-in client from the stored token, or None when there is none."""
    from garminconnect import Garmin

    if not token_dir.is_dir() or not any(token_dir.iterdir()):
        print(
            f"no garminconnect token in {token_dir}; run `runsync login`",
            file=sys.stderr,
        )
        return None
    # No credentials: this only loads the token and fails if it is unusable.
    garmin = Garmin()
    garmin.login(str(token_dir))
    return garmin


def save_token(garmin, token_dir: Path) -> None:
    """Keep a refreshed token for the next run."""
    try:
        garmin.client.dump(str(token_dir))
    except Exception as err:  # noqa: BLE001 - best effort
        print(f"could not save the refreshed token: {err}", file=sys.stderr)


def do_serve(token_dir: Path, interval: float) -> int:
    garmin = load_token(token_dir)
    if garmin is None:
        return EXIT_AUTH

    queries = {
        "training_status": lambda d: garmin.get_training_status(d),
        "vo2max": lambda d: garmin.get_max_metrics(d),
        "race_predictor": lambda d: garmin.get_race_predictions(d, d, "daily"),
    }
    last_request = 0.0
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            metric, _, day = line.partition(" ")
            if metric not in queries:
                raise ValueError(f"unknown metric {metric!r}")
            day = date.fromisoformat(day).isoformat()
            wait = last_request + interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            last_request = time.monotonic()
            response = queries[metric](day)
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    finally:
        save_token(garmin, token_dir)
    return EXIT_OK


def do_push(token_dir: Path, interval: float) -> int:
    request = json.loads(sys.stdin.read())
    garmin = load_token(token_dir)
    if garmin is None:
        return EXIT_AUTH
    try:
        push(garmin, request, emit, Pacer(interval))
    finally:
        save_token(garmin, token_dir)
    return EXIT_OK


def emit(result: dict) -> None:
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    sys.stdout.flush()


class Pacer:
    """Call before each request: waits until `interval` s since the last one."""

    def __init__(self, interval: float, clock=time.monotonic, sleep=time.sleep):
        self.interval, self.clock, self.sleep = interval, clock, sleep
        self.last = None

    def __call__(self) -> None:
        if self.last is not None:
            wait = self.last + self.interval - self.clock()
            if wait > 0:
                self.sleep(wait)
        self.last = self.clock()


def push(garmin, request: dict, emit, pace) -> None:
    """Delete, then upload and schedule; one `emit` per finished item. The
    first error propagates, so everything emitted so far really happened."""
    for workout_id in request.get("delete", []):
        pace()
        try:
            garmin.delete_workout(workout_id)
        except Exception as err:
            if "404" not in str(err):
                raise
            # Already deleted in the Garmin Connect app.
        emit({"deleted": workout_id})
    for item in request.get("workouts", []):
        day = date.fromisoformat(item["date"]).isoformat()
        pace()
        uploaded = garmin.upload_workout(item["workout"])
        workout_id = uploaded["workoutId"]
        pace()
        try:
            scheduled = garmin.schedule_workout(workout_id, day)
        except Exception:
            emit({"date": day, "workout_id": workout_id, "schedule_id": None})
            raise
        emit(
            {
                "date": day,
                "workout_id": workout_id,
                "schedule_id": (scheduled or {}).get("workoutScheduleId"),
            }
        )
    if request.get("workouts"):
        pace()
        try:
            garmin.send_scheduled_workouts_to_devices()
        except Exception as err:  # noqa: BLE001 - the watch also syncs the calendar itself
            print(f"could not ask Garmin to send the workouts to the watch: {err}", file=sys.stderr)


def report_error(err: Exception) -> int:
    try:
        from garminconnect import (
            GarminConnectAuthenticationError,
            GarminConnectTooManyRequestsError,
        )
    except ImportError:
        GarminConnectAuthenticationError = GarminConnectTooManyRequestsError = ()

    text = str(err)
    if isinstance(err, GarminConnectTooManyRequestsError) or (
        "CAPTCHA" in text.upper() or "429" in text
    ):
        print(f"rate limited: {text}", file=sys.stderr)
        return EXIT_RATE_LIMITED
    if isinstance(err, GarminConnectAuthenticationError):
        print(f"authentication failed: {text}", file=sys.stderr)
        return EXIT_AUTH
    print(f"error: {type(err).__name__}: {text}", file=sys.stderr)
    return EXIT_OTHER


if __name__ == "__main__":
    sys.exit(main())
