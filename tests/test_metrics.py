import pandas as pd
import pytest

from reportkit.metrics import (
    CLEAN_RATE,
    CONFORMITY_RATE,
    RATE_LABELS,
    clean_rate_lower_bound,
    failures_by,
    format_rate,
    summarize,
    summarize_by,
    with_total,
)
from reportkit.model import CATEGORY, CONTROL, ITEM, RESULT, UNIT
from reportkit.placeholders import PENDING_TOKEN
from reportkit.synthetic import (
    aggregated_visits_fixture,
    generate_canonical,
    three_controls_fixture,
)


def test_clean_control_only_if_every_item_is_clean() -> None:
    s = summarize(three_controls_fixture())
    assert s.controls == 3
    assert s.clean == 1
    assert s.elements == 3
    assert s.items == 10
    assert (s.ok, s.fails, s.na) == (6, 3, 1)


def test_conformity_excludes_not_applicable() -> None:
    rows = [{CONTROL: "V", RESULT: r} for r in ["ok"] * 5 + ["fail"] * 3 + ["na"]]
    df = pd.DataFrame(rows)
    df["element"] = "E"
    s = summarize(df)
    assert s.conformity_rate == pytest.approx(0.625)  # 5 / 8, base 8
    assert s.ok + s.fails == 8
    assert s.clean_rate == 0.0


def test_rates_are_none_on_empty_base_never_zero() -> None:
    s = summarize(three_controls_fixture().iloc[0:0])
    assert s.conformity_rate is None and s.clean_rate is None
    assert format_rate(s.conformity_rate) == PENDING_TOKEN


def test_rates_have_fixed_names_and_declared_bases() -> None:
    assert CONFORMITY_RATE in RATE_LABELS and CLEAN_RATE in RATE_LABELS
    for _name, (label, base) in RATE_LABELS.items():
        assert label and "/" in base


def test_volume_sums_every_unit_but_rates_only_controls() -> None:
    df = generate_canonical("2026-03")
    s = summarize(df)
    controls_only = df[df[UNIT] == "control"]
    assert s.volume == df[CONTROL].nunique()
    assert s.controls == controls_only[CONTROL].nunique()
    assert s.volume > s.controls  # surveys add to volume...
    assert s.items == len(controls_only)  # ...but never to the rate bases
    assert s.incidents_per_control == pytest.approx(s.fails / s.controls)


def test_summarize_by_group_and_period() -> None:
    df = pd.concat([generate_canonical("2026-02"), generate_canonical("2026-03")])
    table = summarize_by(df, "group", "period")
    assert set(table.columns) >= {"group", "period", "controls", CONFORMITY_RATE, CLEAN_RATE}
    assert len(table) == df.groupby(["group", "period"]).ngroups
    cafe = table[(table["group"] == "CAFE") & (table["period"] == "2026-03")].iloc[0]
    assert cafe["controls"] == 10


def test_failures_by_item_qualifies_ambiguous_names() -> None:
    df = three_controls_fixture().copy()
    # The same item name in two categories must be told apart.
    df.loc[df.index[-1], [CATEGORY, ITEM, RESULT]] = ["Instalaciones", "Suelos limpios", "fail"]
    df.loc[df.index[0], RESULT] = "fail"
    table = failures_by(df, ITEM)
    labels = table[ITEM].tolist()
    assert "Suelos limpios (Higiene)" in labels and "Suelos limpios (Instalaciones)" in labels
    assert table["incidents"].is_monotonic_decreasing
    assert table["share"].sum() == pytest.approx(1.0)


def test_with_total_sums_counts_recomputes_rates_and_ignores_pending() -> None:
    table = pd.DataFrame(
        {
            "group": ["A", "B", "C"],
            "controls": [10, 20, PENDING_TOKEN],
            "clean": [8, 10, PENDING_TOKEN],
            "ok": [90, 150, PENDING_TOKEN],
            "fails": [10, 50, PENDING_TOKEN],
            CONFORMITY_RATE: [0.9, 0.75, PENDING_TOKEN],
            CLEAN_RATE: [0.8, 0.5, PENDING_TOKEN],
        }
    )
    out = with_total(table)
    total = out.iloc[-1]
    assert total["group"] == "Total"
    assert total["controls"] == 30 and total["clean"] == 18
    assert total[CONFORMITY_RATE] == pytest.approx(240 / 300)
    assert total[CLEAN_RATE] == pytest.approx(18 / 30)
    assert out.iloc[2]["controls"] == PENDING_TOKEN  # the pending cell survives untouched


def test_with_total_keeps_pending_when_whole_column_is_pending() -> None:
    table = pd.DataFrame({"group": ["A"], "controls": [PENDING_TOKEN]})
    assert with_total(table).iloc[-1]["controls"] == PENDING_TOKEN


def test_clean_rate_lower_bound_uses_total_visits_as_base() -> None:
    rate = clean_rate_lower_bound(aggregated_visits_fixture())
    # elements with 0 incidents: E-1 (1 visit) + E-2 (3 visits) = 4 clean out of 10 visits
    assert rate.numerator == 4 and rate.base == 10
    assert rate.value == pytest.approx(0.4)
    assert "4/10" in rate.label() and "cota inferior" in rate.label()
