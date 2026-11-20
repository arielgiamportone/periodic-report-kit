from pathlib import Path

import pandas as pd
import pytest
from PIL import Image

from reportkit.brand import BrandKit
from reportkit.catalog import ReportCatalog
from reportkit.charts import ChartSpec, draw, evaluate_condition
from reportkit.comments import CommentStore
from reportkit.metrics import CLEAN_RATE
from reportkit.model import RESULT
from reportkit.placeholders import COMMENT_TOKEN, PENDING_TOKEN
from reportkit.synthetic import generate_canonical, three_controls_fixture
from reportkit.tables import presentable, summary_by_group

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def brand() -> BrandKit:
    return BrandKit.load(ROOT / "brands" / "nordal" / "brand.yaml")


@pytest.fixture(scope="module")
def catalog() -> ReportCatalog:
    return ReportCatalog.load(ROOT / "config" / "report_catalog.yaml")


# --- conditions ----------------------------------------------------------------------------------


def test_condition_grammar() -> None:
    ctx = {"incidents": 3, "controls": 10, "periods": 1}
    assert evaluate_condition("incidents >= 3", ctx)
    assert not evaluate_condition("incidents > 3", ctx)
    assert evaluate_condition("incidents > 5 or controls == 10", ctx)
    assert not evaluate_condition("incidents > 5 and controls == 10", ctx)
    assert evaluate_condition(None, ctx) and evaluate_condition("", ctx)
    assert not evaluate_condition(
        "conformity_rate >= 0", {"conformity_rate": None}
    )  # None is not zero
    with pytest.raises(ValueError):
        evaluate_condition("__import__('os')", ctx)


def test_group_with_zero_incidents_gets_no_chart(catalog) -> None:
    df = three_controls_fixture().copy()
    df[RESULT] = "ok"
    assert not catalog.charts["incidents_by_category"].applies(df)
    assert not catalog.applicable_charts("monthly", df)
    many = generate_canonical("2026-03")
    names = {c.name for c in catalog.applicable_charts("monthly", many)}
    assert "incidents_by_category" in names and "conformity_by_period" not in names


def test_charts_are_drawn_at_170_dpi(brand, catalog, tmp_path: Path) -> None:
    df = pd.concat([generate_canonical("2026-02"), generate_canonical("2026-03")])
    for spec in catalog.applicable_charts("semester", df):
        fig = draw(spec, df, brand, tmp_path, slug="t")
        assert fig.path.is_file() and fig.path.name == f"t_{spec.name}.png"
        img = Image.open(fig.path)
        assert round(img.info["dpi"][0]) == 170
        assert not fig.data.empty


def test_chart_spec_validates_kind_and_level() -> None:
    with pytest.raises(ValueError):
        ChartSpec("x", "pie", "category", "incidents", "t")
    with pytest.raises(ValueError):
        ChartSpec("x", "bar", "galaxy", "incidents", "t")


# --- tables ------------------------------------------------------------------------------------------


def test_summary_marks_blocked_group_pending_and_total_ignores_it(groups) -> None:
    df = generate_canonical("2026-03")
    df = df[df["group"] != "ENCU"]  # the surveys have no source this month
    table = summary_by_group(df, groups)
    encu = table[table["group"] == "Encuestas de satisfacción"].iloc[0]
    assert encu["controls"] == PENDING_TOKEN and encu[CLEAN_RATE] == PENDING_TOKEN
    total = table.iloc[-1]
    assert total["group"] == "Total" and total["controls"] == 50
    shown = presentable(table)
    assert "Controles sin incidencias (controles sin fallo / controles)" in shown.columns
    assert shown.iloc[-1]["Conformidad de ítems (ítems correctos / (correctos + fallos))"].endswith(
        "%"
    )
    assert PENDING_TOKEN in shown.iloc[:-1]["Controles"].tolist()


def test_presentable_formats_rates_with_comma(groups) -> None:
    table = summary_by_group(three_controls_fixture(), groups)
    shown = presentable(table)
    cafe = shown.iloc[0]
    assert cafe["Controles"] == 3
    assert cafe[[c for c in shown.columns if c.startswith("Conformidad")][0]] == "66,7 %"


# --- comments --------------------------------------------------------------------------------------------


def test_comment_gap_when_nothing_stored(tmp_path: Path) -> None:
    store = CommentStore.load("2026-03", tmp_path)
    text, warnings = store.render("summary", {"controls": 50, "incidents": 12})
    assert text.startswith(COMMENT_TOKEN) and "controls=50" in text and not warnings


def test_stored_comment_is_published_and_drift_is_reported(tmp_path: Path) -> None:
    (tmp_path / "2026-03.yaml").write_text(
        "sections:\n  summary:\n    text: 'Buen mes.'\n    hints: {controls: 48, incidents: 12}\n    proposal: 'Borrador automático'\n",
        encoding="utf-8",
    )
    store = CommentStore.load("2026-03", tmp_path)
    text, warnings = store.render("summary", {"controls": 50, "incidents": 12})
    assert text == "Buen mes."
    assert [w.kind for w in warnings] == ["comment-stale"]
    text2, warnings2 = store.render("summary", {"controls": 48, "incidents": 12})
    assert text2 == "Buen mes." and not warnings2
    assert "Borrador" not in text and "Borrador" not in text2  # the proposal is never published


def test_write_template_keeps_existing_text(tmp_path: Path) -> None:
    store = CommentStore.load("2026-03", tmp_path)
    path = store.write_template({"summary": {"controls": 50}, "group:CAFE": {"incidents": 3}})
    assert path.is_file()
    (tmp_path / "2026-03.yaml").write_text(
        path.read_text(encoding="utf-8").replace("text: null", "text: Escrito", 1), encoding="utf-8"
    )
    store2 = CommentStore.load("2026-03", tmp_path)
    store2.write_template({"summary": {"controls": 51}, "group:CAFE": {"incidents": 4}})
    store3 = CommentStore.load("2026-03", tmp_path)
    assert store3.get("summary").text == "Escrito" and store3.get("summary").hints == {
        "controls": 51
    }


def test_catalog_types_and_texts(catalog) -> None:
    assert set(catalog.report_types) == {"monthly", "semester", "annual"}
    assert catalog.report_type("annual").periods_on_axis == 12
    assert catalog.text("no_chart_sentence", incidents=2).startswith("Con 2 incidencias")
    assert catalog.text("pending_token") == PENDING_TOKEN
    with pytest.raises(KeyError):
        catalog.report_type("weekly")
