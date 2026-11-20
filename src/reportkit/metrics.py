"""Metrics: five definitions and two rates with fixed names.

Every percentage declares its base. Volume is summed across every unit (that is what gets
certified); rates and densities are computed only over controls of the default unit.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

from .model import CATEGORY, CONTROL, DEFAULT_UNIT, ELEMENT, ITEM, RESULT, UNIT
from .placeholders import PENDING_TOKEN, is_placeholder

# Fixed names of the two confusable rates. They are always published with their base.
CONFORMITY_RATE = "conformity_rate"  # ok / (ok + fail)        — items
CLEAN_RATE = "clean_rate"  # clean controls / controls — controls

RATE_LABELS: dict[str, tuple[str, str]] = {
    CONFORMITY_RATE: ("Conformidad de ítems", "ítems correctos / (correctos + fallos)"),
    CLEAN_RATE: ("Controles sin incidencias", "controles sin fallo / controles"),
}

COUNT_COLUMNS = ("controls", "clean", "elements", "items", "ok", "fails", "na", "volume")


@dataclass(frozen=True, slots=True)
class Summary:
    controls: int
    clean: int
    elements: int
    items: int
    ok: int
    fails: int
    na: int
    conformity_rate: float | None  # None when the base is empty, never 0
    clean_rate: float | None
    volume: int  # every unit: controls + surveys + ...
    unit: str = DEFAULT_UNIT

    @property
    def incidents(self) -> int:
        return self.fails

    @property
    def incidents_per_control(self) -> float | None:
        return None if self.controls == 0 else self.fails / self.controls

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["incidents"] = self.incidents
        d["incidents_per_control"] = self.incidents_per_control
        return d


def _rate(num: int, den: int) -> float | None:
    return None if den == 0 else num / den


def _controls_only(df: pd.DataFrame, unit: str) -> pd.DataFrame:
    if UNIT in df.columns:
        return df[df[UNIT].fillna(DEFAULT_UNIT) == unit]
    return df


def summarize(df: pd.DataFrame, unit: str = DEFAULT_UNIT) -> Summary:
    """The five definitions on a slice of the model. Rates only over ``unit``; volume over all."""
    volume = int(df[CONTROL].nunique()) if not df.empty else 0
    c = _controls_only(df, unit)
    if c.empty:
        return Summary(0, 0, 0, 0, 0, 0, 0, None, None, volume, unit)
    counts = c[RESULT].value_counts()
    ok, fails, na = int(counts.get("ok", 0)), int(counts.get("fail", 0)), int(counts.get("na", 0))
    per_control = c.groupby(CONTROL)[RESULT].apply(lambda s: (s == "fail").sum())
    controls = int(len(per_control))
    clean = int((per_control == 0).sum())
    return Summary(
        controls=controls,
        clean=clean,
        elements=int(c[ELEMENT].nunique()),
        items=int(len(c)),
        ok=ok,
        fails=fails,
        na=na,
        conformity_rate=_rate(ok, ok + fails),
        clean_rate=_rate(clean, controls),
        volume=volume,
        unit=unit,
    )


def summarize_by(df: pd.DataFrame, *dims: str, unit: str = DEFAULT_UNIT) -> pd.DataFrame:
    """One summary row per combination of ``dims`` (any canonical column or dimension)."""
    if not dims:
        return pd.DataFrame([summarize(df, unit).as_dict()])
    rows = []
    for key, grp in df.groupby(list(dims), dropna=False, sort=True):
        key_t = key if isinstance(key, tuple) else (key,)
        rows.append({**dict(zip(dims, key_t, strict=True)), **summarize(grp, unit).as_dict()})
    cols = [
        *dims,
        *COUNT_COLUMNS,
        CONFORMITY_RATE,
        CLEAN_RATE,
        "incidents",
        "incidents_per_control",
        "unit",
    ]
    return pd.DataFrame(rows, columns=cols)


def failures_by(
    df: pd.DataFrame, dim: str, qualify: bool = True, unit: str = DEFAULT_UNIT
) -> pd.DataFrame:
    """Incidents per value of ``dim``, descending. Items are qualified ``item (category)`` when
    the same item name lives in several categories, so two levels never get mixed up."""
    c = _controls_only(df, unit)
    fails = c[c[RESULT] == "fail"].copy()
    label_col = dim
    if dim == ITEM and qualify and CATEGORY in c.columns:
        ambiguous = c.groupby(ITEM)[CATEGORY].nunique()
        ambiguous = set(ambiguous[ambiguous > 1].index)
        fails["_label"] = [
            f"{i} ({cat})" if i in ambiguous else i
            for i, cat in zip(fails[ITEM], fails[CATEGORY], strict=True)
        ]
        label_col = "_label"
    if fails.empty:
        return pd.DataFrame(columns=[dim, "incidents", "share"])
    out = fails.groupby(label_col, dropna=False).size().reset_index(name="incidents")
    out = out.rename(columns={label_col: dim}).sort_values(
        ["incidents", dim], ascending=[False, True]
    )
    total = int(out["incidents"].sum())
    out["share"] = out["incidents"] / total if total else None
    return out.reset_index(drop=True)


def with_total(
    table: pd.DataFrame, label: str = "Total", label_col: str | None = None
) -> pd.DataFrame:
    """Append a total row. Counts are summed, rates recomputed from the summed counts when the
    columns exist, and ``[[PENDIENTE]]`` cells are ignored (never read as zero)."""
    if table.empty:
        return table
    label_col = label_col or table.columns[0]
    total: dict[str, Any] = {label_col: label}
    numeric = {}
    for col in table.columns:
        if col == label_col:
            continue
        values = table[col]
        if (
            values.map(is_placeholder).any()
            and values.map(lambda v: is_placeholder(v) or pd.isna(v)).all()
        ):
            total[col] = PENDING_TOKEN
            continue
        clean = pd.to_numeric(
            values.map(lambda v: None if is_placeholder(v) else v), errors="coerce"
        )
        if clean.notna().any() and col not in (
            CONFORMITY_RATE,
            CLEAN_RATE,
            "share",
            "incidents_per_control",
        ):
            numeric[col] = clean.sum()
            total[col] = (
                int(numeric[col]) if float(numeric[col]).is_integer() else float(numeric[col])
            )
        else:
            total[col] = None
    if CONFORMITY_RATE in table.columns and {"ok", "fails"} <= numeric.keys():
        total[CONFORMITY_RATE] = _rate(int(numeric["ok"]), int(numeric["ok"] + numeric["fails"]))
    if CLEAN_RATE in table.columns and {"clean", "controls"} <= numeric.keys():
        total[CLEAN_RATE] = _rate(int(numeric["clean"]), int(numeric["controls"]))
    if "share" in table.columns:
        total["share"] = 1.0 if numeric else None
    if "incidents_per_control" in table.columns and {"incidents", "controls"} <= numeric.keys():
        total["incidents_per_control"] = _rate(int(numeric["incidents"]), int(numeric["controls"]))
    return pd.concat([table, pd.DataFrame([total], columns=table.columns)], ignore_index=True)


@dataclass(frozen=True, slots=True)
class RateWithBase:
    """A rate that cannot be published without its base."""

    name: str
    value: float | None
    numerator: int
    base: int
    basis: str

    def label(self) -> str:
        pct = "—" if self.value is None else f"{self.value * 100:.1f} %"
        return f"{pct} ({self.numerator}/{self.base}, {self.basis})"


def clean_rate_lower_bound(
    agg: pd.DataFrame, visits: str = "visits", incidents: str = "incidents"
) -> RateWithBase:
    """Clean-case rate when the source is aggregated (visits and incidents per element-month).

    Every visit of an element-month without incidents counts as clean; an element-month with
    incidents contributes zero clean visits. The base is the total number of visits, so the
    figure is a lower bound that exists in the client's own files. The restricted variant
    (elements with exactly one visit) is deliberately not offered: it fabricates a trend on a
    base nobody can audit.
    """
    v = pd.to_numeric(agg[visits], errors="coerce").fillna(0).astype(int)
    i = pd.to_numeric(agg[incidents], errors="coerce").fillna(0).astype(int)
    base = int(v.sum())
    clean = int(v[i == 0].sum())
    return RateWithBase(
        CLEAN_RATE, _rate(clean, base), clean, base, "cota inferior sobre el total de visitas"
    )


def format_rate(value: float | None, decimals: int = 1) -> str:
    return PENDING_TOKEN if value is None else f"{value * 100:.{decimals}f} %".replace(".", ",")
