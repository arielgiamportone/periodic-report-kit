"""Chart catalogue (matplotlib). Every chart declares its axis, its level and the condition
under which it is generated; a chart that does not apply is replaced by a table and a sentence
by the composer, never by an empty figure."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib import font_manager  # noqa: E402

from .brand import BrandKit  # noqa: E402
from .metrics import CLEAN_RATE, CONFORMITY_RATE, failures_by, summarize, summarize_by  # noqa: E402
from .model import CATEGORY, ITEM, PERIOD, RESULT  # noqa: E402

LEVELS = {"category", "item", "group", "period", "responsible", "site"}
KINDS = {"bar", "hbar", "line", "stacked"}

_COND_TOKEN = re.compile(r"^\s*([a-z_]+)\s*(>=|<=|==|!=|>|<)\s*(-?\d+(?:\.\d+)?)\s*$")


def evaluate_condition(condition: str | None, context: dict[str, Any]) -> bool:
    """``"incidents >= 3 and controls > 0"``. Only names, comparisons, ``and`` / ``or``.

    A missing or ``None`` value makes its comparison false: nothing is ever read as zero.
    """
    if not condition or not condition.strip():
        return True
    for or_part in re.split(r"\s+or\s+", condition.strip()):
        ok = True
        for and_part in re.split(r"\s+and\s+", or_part):
            m = _COND_TOKEN.match(and_part)
            if not m:
                raise ValueError(f"cannot parse condition fragment {and_part!r}")
            name, op, number = m.group(1), m.group(2), float(m.group(3))
            value = context.get(name)
            if value is None:
                ok = False
                break
            ok = {
                ">=": value >= number,
                "<=": value <= number,
                "==": value == number,
                "!=": value != number,
                ">": value > number,
                "<": value < number,
            }[op]
            if not ok:
                break
        if ok:
            return True
    return False


@dataclass(frozen=True, slots=True)
class ChartSpec:
    name: str
    kind: str
    level: str  # what the x axis (or the bars) enumerate
    metric: str  # incidents | controls | conformity_rate | clean_rate | results
    title: str
    condition: str | None = None
    top_n: int | None = None
    periods: int | None = None  # how many periods the axis shows (period charts)
    caption: str = ""

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"chart {self.name}: unknown kind {self.kind}")
        if self.level not in LEVELS:
            raise ValueError(f"chart {self.name}: unknown level {self.level}")

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ChartSpec:
        return cls(
            name=str(raw["name"]),
            kind=str(raw.get("kind", "bar")),
            level=str(raw.get("level", "category")),
            metric=str(raw.get("metric", "incidents")),
            title=str(raw.get("title", raw["name"])),
            condition=raw.get("if"),
            top_n=int(raw["top_n"]) if raw.get("top_n") else None,
            periods=int(raw["periods"]) if raw.get("periods") else None,
            caption=str(raw.get("caption", "")),
        )

    def applies(self, df: pd.DataFrame) -> bool:
        ctx = summarize(df).as_dict()
        ctx["periods"] = int(df[PERIOD].nunique()) if PERIOD in df.columns else 0
        return evaluate_condition(self.condition, ctx)


@dataclass(slots=True)
class Figure:
    spec: ChartSpec
    path: Path
    caption: str
    data: pd.DataFrame = field(default_factory=pd.DataFrame)


def _style(brand: BrandKit) -> dict[str, Any]:
    body = brand.body()
    if body.path is not None:
        font_manager.fontManager.addfont(str(body.path))
        family = font_manager.FontProperties(fname=str(body.path)).get_name()
    else:  # pragma: no cover
        family = "DejaVu Sans"
    return {
        "font.family": family,
        "font.size": 9,
        "axes.edgecolor": brand.palette.border,
        "axes.labelcolor": brand.palette.ink,
        "axes.titlecolor": brand.palette.ink,
        "axes.titlesize": 10.5,
        "axes.titleweight": "bold",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.color": brand.palette.border,
        "grid.linewidth": 0.6,
        "axes.axisbelow": True,
        "xtick.color": brand.palette.muted,
        "ytick.color": brand.palette.muted,
        "figure.facecolor": brand.palette.page_bg,
        "axes.facecolor": brand.palette.page_bg,
        "legend.frameon": False,
    }


def _level_column(level: str) -> str:
    return {"category": CATEGORY, "item": ITEM, "group": "group", "period": PERIOD}.get(
        level, level
    )


def _series(spec: ChartSpec, df: pd.DataFrame) -> pd.DataFrame:
    col = _level_column(spec.level)
    if spec.metric == "incidents":
        table = failures_by(df, col, qualify=(spec.level == "item")).rename(
            columns={col: "label", "incidents": "value"}
        )
    elif spec.metric == "results":
        counts = df.groupby([col, RESULT]).size().unstack(fill_value=0)
        table = (
            counts.reindex(columns=["ok", "fail", "na"], fill_value=0)
            .reset_index()
            .rename(columns={col: "label"})
        )
    else:
        by = summarize_by(df, col)
        metric = spec.metric if spec.metric in by.columns else "controls"
        table = by[[col, metric]].rename(columns={col: "label", metric: "value"})
    if spec.level == "period":
        table = table.sort_values("label")
        if spec.periods:
            table = table.tail(spec.periods)
    elif "value" in table.columns:
        table = table.sort_values("value", ascending=False)
    if spec.top_n and "value" in table.columns:
        table = table.head(spec.top_n)
    return table.reset_index(drop=True)


def draw(
    spec: ChartSpec, df: pd.DataFrame, brand: BrandKit, out_dir: Path, slug: str = ""
) -> Figure:
    """Render the chart to a PNG at 170 dpi and return the figure with its data."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    table = _series(spec, df)
    name = f"{slug + '_' if slug else ''}{spec.name}.png"
    path = out_dir / name
    width = 6.3
    with plt.rc_context(_style(brand)):
        fig, ax = plt.subplots(
            figsize=(width, 3.2 if spec.kind != "hbar" else max(2.4, 0.32 * len(table) + 1.0))
        )
        labels = table["label"].astype(str).tolist()
        is_rate = spec.metric in (CONFORMITY_RATE, CLEAN_RATE)
        if spec.metric == "results":
            left = [0.0] * len(table)
            for key, colour, text in (
                ("ok", brand.semantic.ok, "Correcto"),
                ("fail", brand.semantic.fail, "Fallo"),
                ("na", brand.semantic.na, "No procede"),
            ):
                vals = table[key].tolist()
                ax.barh(
                    labels,
                    vals,
                    left=left,
                    color=colour,
                    label=text,
                    height=0.62,
                    edgecolor=brand.palette.page_bg,
                    linewidth=1.5,
                )
                for i, (lft, v) in enumerate(zip(left, vals, strict=True)):
                    if v and v / max(1, sum(table.loc[i, ["ok", "fail", "na"]])) > 0.12:
                        ax.text(
                            lft + v / 2,
                            i,
                            str(v),
                            ha="center",
                            va="center",
                            color="white",
                            fontsize=8,
                        )
                left = [a + b for a, b in zip(left, vals, strict=True)]
            ax.invert_yaxis()
            ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=3, fontsize=8)
            ax.grid(axis="y", visible=False)
        elif spec.kind == "hbar":
            values = table["value"].tolist()
            ax.barh(labels, values, color=brand.palette.secondary, height=0.62)
            ax.invert_yaxis()
            for i, v in enumerate(values):
                ax.text(
                    v,
                    i,
                    f" {v:.0%}" if is_rate else f" {v:g}",
                    va="center",
                    fontsize=8,
                    color=brand.palette.ink,
                )
            ax.grid(axis="y", visible=False)
            if is_rate:
                ax.set_xlim(0, 1.05)
                ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
        elif spec.kind == "line":
            values = table["value"].tolist()
            ax.plot(
                labels, values, color=brand.palette.secondary, linewidth=2, marker="o", markersize=5
            )
            if values:
                ax.annotate(
                    f"{values[-1]:.1%}" if is_rate else f"{values[-1]:g}",
                    (labels[-1], values[-1]),
                    textcoords="offset points",
                    xytext=(0, 7),
                    ha="center",
                    fontsize=8,
                    color=brand.palette.ink,
                )
            ax.grid(axis="x", visible=False)
            if is_rate:
                ax.set_ylim(0, 1.05)
                ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
        else:
            values = table["value"].tolist()
            ax.bar(labels, values, color=brand.palette.secondary, width=0.62)
            for i, v in enumerate(values):
                ax.text(
                    i,
                    v,
                    f"{v:.0%}" if is_rate else f"{v:g}",
                    ha="center",
                    va="bottom",
                    fontsize=8,
                    color=brand.palette.ink,
                )
            ax.grid(axis="x", visible=False)
            if len(labels) > 5:
                plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
            if is_rate:
                ax.set_ylim(0, 1.05)
                ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
        ax.set_title(spec.title, loc="left")
        fig.tight_layout()
        fig.savefig(path, dpi=170)
        plt.close(fig)
    return Figure(spec=spec, path=path, caption=spec.caption or spec.title, data=table)
