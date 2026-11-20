"""Canonical long model: the architectural boundary of the kit.

Above this module nobody knows which file a row came from. One row = one evaluated item.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any

import pandas as pd

# --- Canonical column names -------------------------------------------------------------

PERIOD = "period"  # "YYYY-MM", derived from the local timestamp, never from labels
GROUP = "group"  # report group code (see groups.yaml)
CONTROL = "control_id"  # one visit to one element; indivisible unit
ELEMENT = "element"  # inspected thing, identified by code
ELEMENT_NAME = "element_name"
CATEGORY = "category"  # checklist level 1 (6-12 values, for breakdowns)
ITEM = "item"  # checklist level 2 (10-50 values, for top-N rankings)
RESULT = "result"  # ok | fail | na
COMMENT = "comment"
TIMESTAMP = "timestamp"  # tz-aware, local zone declared in the schema
SOURCE = "source"  # file the row came from (loader-only provenance)
UNIT = "unit"  # "control" for inspections; other units count in volume only

CORE_COLUMNS: tuple[str, ...] = (
    PERIOD,
    GROUP,
    CONTROL,
    ELEMENT,
    ELEMENT_NAME,
    CATEGORY,
    ITEM,
    RESULT,
    COMMENT,
    TIMESTAMP,
    SOURCE,
    UNIT,
)

DEFAULT_UNIT = "control"


class Result(StrEnum):
    """Canonical outcome of an evaluated item."""

    OK = "ok"
    FAIL = "fail"
    NA = "na"


RESULT_VALUES: frozenset[str] = frozenset(r.value for r in Result)


# --- Warnings ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Warning:
    """A loader or validator notice: typed, counted and attributable to a file."""

    kind: str
    message: str
    file: str | None = None
    rows: int = 0
    controls: tuple[str, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        where = f" [{self.file}]" if self.file else ""
        count = f" ({self.rows} rows)" if self.rows else ""
        return f"{self.kind}: {self.message}{where}{count}"


# --- Period container --------------------------------------------------------------------


def month_key(d: date | pd.Timestamp) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def parse_month(text: str) -> date:
    """``"2026-03"`` -> ``date(2026, 3, 1)``. Raises ``ValueError`` on anything else."""
    parts = text.strip().split("-")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        raise ValueError(f"period must look like YYYY-MM, got {text!r}")
    year, month = int(parts[0]), int(parts[1])
    if not 1 <= month <= 12:
        raise ValueError(f"month out of range in {text!r}")
    return date(year, month, 1)


def month_range(start: str, end: str) -> list[str]:
    """Inclusive list of ``YYYY-MM`` keys between two months; may cross a year boundary."""
    a, b = parse_month(start), parse_month(end)
    if b < a:
        raise ValueError(f"range end {end} is before start {start}")
    out: list[str] = []
    y, m = a.year, a.month
    while (y, m) <= (b.year, b.month):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


@dataclass(slots=True)
class Period:
    """A loaded slice of the canonical model plus the notices produced while loading it."""

    data: pd.DataFrame
    warnings: list[Warning] = field(default_factory=list)
    start: str = ""
    end: str = ""
    quarantine: pd.DataFrame | None = None  # rows that were not recognised; never guessed

    @property
    def months(self) -> list[str]:
        if self.start and self.end:
            return month_range(self.start, self.end)
        if PERIOD in self.data:
            return sorted(self.data[PERIOD].dropna().unique().tolist())
        return []

    @property
    def label(self) -> str:
        return self.start if self.start == self.end else f"{self.start} a {self.end}"

    def warnings_of(self, kind: str) -> list[Warning]:
        return [w for w in self.warnings if w.kind == kind]


def empty_model() -> pd.DataFrame:
    """An empty DataFrame with every canonical column, for concatenation and tests."""
    return pd.DataFrame({c: pd.Series(dtype="object") for c in CORE_COLUMNS})


def ensure_model(df: pd.DataFrame) -> pd.DataFrame:
    """Add any missing canonical column (as missing values) and validate the result column."""
    out = df.copy()
    for col in CORE_COLUMNS:
        if col not in out.columns:
            out[col] = None
    if UNIT in out:
        out[UNIT] = out[UNIT].fillna(DEFAULT_UNIT)
    bad = set(out[RESULT].dropna().unique()) - RESULT_VALUES
    if bad:
        raise ValueError(f"non-canonical result values: {sorted(bad)}")
    return out
