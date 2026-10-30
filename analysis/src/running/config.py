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
class Config:
    reference_hr: int = 145
    physiology: tuple[Physiology, ...] = field(default_factory=tuple)


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
        reference_hr = int(raw.get("aerobic", {}).get("reference_hr", 145))
    except (KeyError, TypeError, ValueError) as err:
        raise ConfigError(f"配置文件 {path} 缺少或写错了字段：{err}") from err
    return Config(reference_hr=reference_hr, physiology=physiology)
