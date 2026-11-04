"""Data directory and `config.toml`, shared with the Rust importer.

The data directory is `RUNNING_DATA_DIR`, default `%USERPROFILE%\\running-data`.
"""

import os
import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

ENV_VAR = "RUNNING_DATA_DIR"


class ConfigError(Exception):
    """The data directory or `config.toml` is missing or malformed."""


@dataclass(frozen=True)
class Physiology:
    effective_from: date
    hr_max: int
    hr_rest: int
    lthr: int


@dataclass(frozen=True)
class RunWalk:
    """`[run_walk]` in config.toml: how each second is classified as running."""

    cadence_spm: float = 140.0  # smoothed cadence (both feet) at or above this is running
    smoothing_s: int = 10  # trailing window for the cadence mean
    min_walk_s: int = 10  # walking stretches shorter than this still count as running
    pause_gap_s: int = 10  # a gap between samples longer than this is a pause, not time


@dataclass(frozen=True)
class Aerobic:
    """`[aerobic]` in config.toml: steady-state filter and GAP settings."""

    reference_hr: int = 145  # the fitted GAP speed is read off at this HR
    warmup_s: int = 600  # moving time dropped at the start of each run
    smoothing_s: int = 30  # trailing window for HR, speed and altitude means
    hr_band_bpm: float = 15.0  # steady seconds have smoothed HR within reference_hr +- this
    speed_window_s: int = 60  # window for the speed-stability check
    max_speed_change: float = 0.05  # (max - min) / mean of smoothed speed in that window
    min_hr_spm_gap: float = 5.0  # |HR - spm| below this looks like cadence lock
    min_steady_s: int = 600  # runs with less steady time are left out
    grade_window_s: int = 30  # grade = rise / distance over this many seconds
    max_grade: float = 0.15  # grade is clipped to +- this before Cr(i)
    min_runs_per_week: int = 2  # weeks with fewer valid runs stay empty
    rolling_weeks: int = 4  # rolling median over this many weeks
    max_speed_mps: float = 7.0  # per-second speed above this is suspect (GPS drift)
    max_fast_s: int = 60  # runs with more seconds above max_speed_mps are left out
    hot_week_c: float = 22.0  # weeks with median air temperature at or above this are hot


@dataclass(frozen=True)
class Load:
    """`[load]` in config.toml: training-load (TRIMP) settings."""

    max_sample_gap_s: float = 10.0  # a longer gap between HR samples counts only this long


@dataclass(frozen=True)
class Zones:
    """`[zones]` in config.toml: HR zone floors in percent of LTHR (Friel's
    running zones). Four floors make five zones: Z1 below the first floor,
    Z5 at or above the last."""

    lthr_pct: tuple[float, ...] = (85.0, 90.0, 95.0, 100.0)


@dataclass(frozen=True)
class Report:
    """`[report]` in config.toml: thresholds of the detail page's report rules.
    The heat threshold is `[aerobic].hot_week_c`."""

    interval_speed_ratio: float = 0.15  # a rep is this much faster than the run's median speed
    interval_min_s: int = 60  # a rep lasts at least this long
    interval_min_reps: int = 3  # an interval session has at least this many reps
    tempo_share: float = 0.5  # Z3-Z4 share of the running time for a tempo run
    tempo_min_s: int = 900  # ... with one unbroken Z3-Z4 stretch at least this long
    long_easy_share: float = 0.7  # Z1-Z2 share of a long run (60 minutes or more)
    easy_share: float = 0.8  # Z1-Z2 share of an easy run
    aerobic_change: float = 0.02  # aerobic value this much above/below the recent median
    split_change: float = 0.02  # second half's GAP pace this much faster/slower


@dataclass(frozen=True)
class Config:
    reference_hr: int = 145
    physiology: tuple[Physiology, ...] = field(default_factory=tuple)
    run_walk: RunWalk = field(default_factory=RunWalk)
    aerobic: Aerobic = field(default_factory=Aerobic)
    load: Load = field(default_factory=Load)
    zones: Zones = field(default_factory=Zones)
    report: Report = field(default_factory=Report)


def data_dir() -> Path:
    """The data directory path. Not checked for existence."""
    value = os.environ.get(ENV_VAR)
    if value:
        return Path(value)
    home = os.environ.get("USERPROFILE") or str(Path.home())
    return Path(home) / "running-data"


def analysis_db_path(root: Path | None = None) -> Path:
    return (root or data_dir()) / "running.sqlite"


def load_config(root: Path | None = None) -> Config:
    """Read `config.toml` from the data directory, raising ConfigError with a
    message that says what to create when something is missing."""
    root = root or data_dir()
    if not root.is_dir():
        raise ConfigError(
            f"数据目录 {root} 不存在。请创建它，"
            f"或用 {ENV_VAR} 指向存放 config.toml、raw/、secrets/ 的目录。"
        )
    path = root / "config.toml"
    if not path.is_file():
        raise ConfigError(
            f"找不到配置文件 {path}。请在数据目录里创建 config.toml（格式见 README）。"
        )
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as err:
        raise ConfigError(f"配置文件 {path} 格式错误：{err}") from err
    try:
        physiology = tuple(
            Physiology(
                effective_from=p["effective_from"],
                hr_max=int(p["hr_max"]),
                hr_rest=int(p["hr_rest"]),
                lthr=int(p["lthr"]),
            )
            for p in raw.get("physiology", [])
        )
        aerobic = _aerobic(raw.get("aerobic", {}))
        run_walk = _run_walk(raw.get("run_walk", {}))
        load = Load(
            max_sample_gap_s=float(
                raw.get("load", {}).get("max_sample_gap_s", Load.max_sample_gap_s)
            )
        )
        zones = _zones(raw.get("zones", {}))
        report = _report(raw.get("report", {}))
    except (KeyError, TypeError, ValueError) as err:
        raise ConfigError(f"配置文件 {path} 缺少或写错了字段：{err}") from err
    return Config(
        reference_hr=aerobic.reference_hr,
        physiology=physiology,
        run_walk=run_walk,
        aerobic=aerobic,
        load=load,
        zones=zones,
        report=report,
    )


def _run_walk(raw: dict) -> RunWalk:
    d = RunWalk()
    return RunWalk(
        cadence_spm=float(raw.get("cadence_spm", d.cadence_spm)),
        smoothing_s=int(raw.get("smoothing_s", d.smoothing_s)),
        min_walk_s=int(raw.get("min_walk_s", d.min_walk_s)),
        pause_gap_s=int(raw.get("pause_gap_s", d.pause_gap_s)),
    )


def _aerobic(raw: dict) -> Aerobic:
    d = Aerobic()
    return Aerobic(
        **{
            name: type(getattr(d, name))(raw.get(name, getattr(d, name)))
            for name in Aerobic.__dataclass_fields__
        }
    )


def _zones(raw: dict) -> Zones:
    pct = tuple(float(v) for v in raw.get("lthr_pct", Zones.lthr_pct))
    if len(pct) != 4 or any(b <= a for a, b in zip(pct, pct[1:], strict=False)):
        raise ValueError("[zones] lthr_pct 要写 4 个递增的百分比，例如 [85, 90, 95, 100]")
    return Zones(lthr_pct=pct)


def _report(raw: dict) -> Report:
    d = Report()
    return Report(
        **{
            name: type(getattr(d, name))(raw.get(name, getattr(d, name)))
            for name in Report.__dataclass_fields__
        }
    )
