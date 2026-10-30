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
    pause_gap_s: int = 30  # a gap between samples longer than this is a pause, not time


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


@dataclass(frozen=True)
class Config:
    reference_hr: int = 145
    physiology: tuple[Physiology, ...] = field(default_factory=tuple)
    run_walk: RunWalk = field(default_factory=RunWalk)
    aerobic: Aerobic = field(default_factory=Aerobic)


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
    except (KeyError, TypeError, ValueError) as err:
        raise ConfigError(f"配置文件 {path} 缺少或写错了字段：{err}") from err
    return Config(
        reference_hr=aerobic.reference_hr,
        physiology=physiology,
        run_walk=run_walk,
        aerobic=aerobic,
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
