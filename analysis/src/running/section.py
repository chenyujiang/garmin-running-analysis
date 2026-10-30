"""What every dashboard section shares: the `method` block of its API response
and the start of each read (which day is today, which data directory, which
config)."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TypedDict

from running.config import Config, ConfigError, data_dir, load_config


class Method(TypedDict):
    """The "how is this calculated" block every API response carries."""

    name: str
    description: str  # Chinese, shown in the "怎么算的" box
    params: dict


@dataclass(frozen=True)
class SectionInputs:
    today: date
    root: Path
    config: Config
    config_error: str | None  # set when config.toml is missing or malformed


def section_inputs(today: date | None = None, root: Path | None = None) -> SectionInputs:
    """`today` defaults to the real date, `root` to the data directory. A
    missing or malformed config falls back to the defaults and reports why."""
    root = root or data_dir()
    try:
        config, error = load_config(root), None
    except ConfigError as err:
        config, error = Config(), str(err)
    return SectionInputs(today=today or date.today(), root=root, config=config, config_error=error)
