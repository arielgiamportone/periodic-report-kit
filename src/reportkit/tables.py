"""Tables ready to be dumped into a document. Every percentage column is labelled with its
base; what cannot be computed is ``[[PENDIENTE]]``, never zero."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .metrics import (
    CLEAN_RATE,
    CONFORMITY_RATE,
    RATE_LABELS,
    failures_by,
    format_rate,
    summarize,
    summarize_by,
    with_total,
)
from .model import GROUP, ITEM, PERIOD
from .placeholders import PENDING_TOKEN
from .schema import GroupCatalog

SUMMARY_HEADERS: dict[str, str] = {
    GROUP: "Grupo",
    "volume": "Actuaciones",
    "controls": "Controles",
    "clean": "Sin incidencias",
    "incidents": "Incidencias",
    CLEAN_RATE: f"{RATE_LABELS[CLEAN_RATE][0]} ({RATE_LABELS[CLEAN_RATE][1]})",
    CONFORMITY_RATE: f"{RATE_LABELS[CONFORMITY_RATE][0]} ({RATE_LABELS[CONFORMITY_RATE][1]})",
}


def summary_by_group(
    df: pd.DataFrame, groups: GroupCatalog, with_rates: bool = True
) -> pd.DataFrame:
    """Chapter-1 summary: one row per catalogue group in catalogue order, plus total.

    Groups without data get ``[[PENDIENTE]]`` in every figure (the blocked reason is reported
    by the composer); the total row ignores them.
    """
    rows: list[dict[str, Any]] = []
    for g in groups.groups:
        slice_ = df[df[GROUP] == g.code]
        if slice_.empty:
            rows.append(
                {
                    GROUP: g.name,
                    "volume": PENDING_TOKEN,
                    "controls": PENDING_TOKEN,
                    "clean": PENDING_TOKEN,
                    "incidents": PENDING_TOKEN,
                    "ok": PENDING_TOKEN,
                    "fails": PENDING_TOKEN,
                    CLEAN_RATE: PENDING_TOKEN,
                    CONFORMITY_RATE: PENDING_TOKEN,
                }
            )
            continue
        s = summarize(slice_, unit=g.unit)
        rows.append(
            {
                GROUP: g.name,
                "volume": s.volume,
                "controls": s.controls,
                "clean": s.clean,
                "incidents": s.fails,
                "ok": s.ok,
                "fails": s.fails,
                CLEAN_RATE: s.clean_rate,
                CONFORMITY_RATE: s.conformity_rate,
            }
        )
    table = pd.DataFrame(rows)
    if not with_rates:
        table = table.drop(columns=[CLEAN_RATE, CONFORMITY_RATE])
    return with_total(table, label="Total")


def summary_by_period(df: pd.DataFrame, group: str | None = None) -> pd.DataFrame:
    slice_ = df if group is None else df[df[GROUP] == group]
    table = summarize_by(slice_, PERIOD)[
        [PERIOD, "volume", "controls", "clean", "incidents", CLEAN_RATE, CONFORMITY_RATE]
    ]
    return table.rename(columns={PERIOD: "Periodo"})


def incidents_by_category(df: pd.DataFrame) -> pd.DataFrame:
    table = failures_by(df, "category").rename(
        columns={"category": "Categoría", "incidents": "Incidencias", "share": "Peso"}
    )
    return with_total(table, label="Total")


def top_items(df: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    return (
        failures_by(df, ITEM)
        .head(n)
        .rename(columns={ITEM: "Ítem", "incidents": "Incidencias", "share": "Peso"})
    )


def by_dimension(df: pd.DataFrame, dim: str, label: str) -> pd.DataFrame:
    table = summarize_by(df, dim)[
        [dim, "controls", "clean", "incidents", "ok", "fails", CLEAN_RATE, CONFORMITY_RATE]
    ]
    table = table.sort_values("incidents", ascending=False).rename(columns={dim: label})
    return with_total(table, label="Total")


def presentable(table: pd.DataFrame) -> pd.DataFrame:
    """Human headers and formatted rates/shares; the frame that goes into a document."""
    out = table.drop(columns=[c for c in ("ok", "fails", "na") if c in table.columns])
    for col in list(out.columns):
        if col in (CLEAN_RATE, CONFORMITY_RATE):
            out[col] = out[col].map(
                lambda v: v if isinstance(v, str) else format_rate(None if pd.isna(v) else float(v))
            )
        elif col in ("Peso", "share"):
            out[col] = out[col].map(
                lambda v: (
                    v
                    if isinstance(v, str)
                    else ("" if pd.isna(v) else f"{float(v) * 100:.1f} %".replace(".", ","))
                )
            )
        elif col == "incidents_per_control":
            out[col] = out[col].map(
                lambda v: (
                    v
                    if isinstance(v, str)
                    else ("" if pd.isna(v) else f"{float(v):.2f}".replace(".", ","))
                )
            )
    return out.rename(columns=SUMMARY_HEADERS)
