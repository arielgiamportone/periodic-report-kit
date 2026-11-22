from pathlib import Path

import pytest
from docx import Document

from reportkit.brand import BrandKit
from reportkit.catalog import ReportCatalog
from reportkit.comments import CommentStore
from reportkit.defaults import default_brand_path, default_config_dir
from reportkit.loaders import load_range
from reportkit.model import GROUP
from reportkit.placeholders import COMMENT_TOKEN, PENDING_TOKEN, SYNTHETIC_TAG
from reportkit.render_pdf import page_count, page_texts
from reportkit.report import ReportRequest, build_report, next_version_dir, period_label
from reportkit.synthetic import SyntheticOptions, write_workbooks

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def env(tmp_path_factory, schema, groups, items):
    root = tmp_path_factory.mktemp("env")
    write_workbooks(root / "data", ["2026-02", "2026-03"], SyntheticOptions(seed=5))
    brand = BrandKit.load(default_brand_path())
    catalog = ReportCatalog.load(default_config_dir() / "report_catalog.yaml")
    period = load_range("2026-02", "2026-03", schema, groups, items, root / "data", use_cache=False)
    return root, brand, catalog, period


def test_period_label() -> None:
    assert period_label("2026-03", "2026-03") == "marzo 2026"
    assert period_label("2025-12", "2026-05") == "diciembre 2025 – mayo 2026"


def test_versioned_output_never_overwrites(tmp_path: Path) -> None:
    a, n1 = next_version_dir(tmp_path, "x")
    b, n2 = next_version_dir(tmp_path, "x")
    assert (n1, n2) == (1, 2) and a != b and a.is_dir() and b.is_dir()


def test_monthly_report_structure(env, groups) -> None:
    root, brand, catalog, period = env
    month = period.data[period.data["period"] == "2026-03"]
    month = month[month[GROUP] != "ENCU"]  # surveys have no source this month -> pending
    from reportkit.model import Period

    p = Period(month, warnings=period.warnings, start="2026-03", end="2026-03")
    store = CommentStore.load("2026-03", root / "comments")
    request = ReportRequest(
        "monthly", "2026-03", "2026-03", recipient="Cliente demo", synthetic=True, pdf=True
    )
    result = build_report(p, request, brand, catalog, groups, store, root / "out")
    assert SYNTHETIC_TAG.replace(" ", "-") in result.docx.name and "SINTÉTICO" in result.docx.name
    assert result.delivered and result.version == 1
    doc = Document(result.docx)
    texts = [p.text for p in doc.paragraphs]
    assert SYNTHETIC_TAG in texts[:6]  # on the cover
    headings = [t for t in texts if t[:2].rstrip(".").isdigit() and t[1:3] in (". ", "0.")]
    assert headings[:3] == ["1. Resumen del periodo", "2. Metodología", "3. Cafeterías"]
    assert headings[-1].endswith("Encuestas de satisfacción")
    assert len(headings) == 2 + len(groups.groups)
    assert any(COMMENT_TOKEN in t for t in texts)
    assert result.gaps >= 1 + 5
    pending = [t for t in texts if PENDING_TOKEN in t]
    assert pending and any("Sin fuente de datos" in t for t in pending)
    summary = doc.tables[0]
    rows = {r.cells[0].text: r.cells[2].text for r in summary.rows[1:]}
    assert rows["Encuestas de satisfacción"] == PENDING_TOKEN and rows["Total"].isdigit()
    assert len(doc.inline_shapes) >= 3  # charts inserted
    assert any(w.kind == "report-built" for w in result.warnings)
    pdf = result.pdf.read_bytes()
    assert page_count(pdf) > 4 and SYNTHETIC_TAG in page_texts(pdf)[0]


def test_semester_concatenates_months_and_draws_period_charts(env, groups) -> None:
    root, brand, catalog, period = env
    store = CommentStore.load("2026-02_2026-03", root / "comments")
    request = ReportRequest("semester", "2026-02", "2026-03", pdf=False)
    result = build_report(period, request, brand, catalog, groups, store, root / "out")
    charts = [e for e in result.elements if e.kind == "chart"]
    assert any("conformity_by_period" in str(e.path) for e in charts)
    assert result.pdf is None and not result.delivered
    assert "summary" in result.hints and result.hints["summary"]["controls"] == 100


def test_group_without_incidents_gets_sentence_instead_of_chart(env, groups) -> None:
    root, brand, catalog, period = env
    from reportkit.model import Period

    df = period.data[period.data["period"] == "2026-03"].copy()
    df.loc[df[GROUP] == "ASEO", "result"] = "ok"
    p = Period(df, start="2026-03", end="2026-03")
    store = CommentStore.load("2026-03", root / "comments")
    result = build_report(
        p,
        ReportRequest("monthly", "2026-03", "2026-03"),
        brand,
        catalog,
        groups,
        store,
        root / "out",
    )
    texts = [e.text for e in result.elements if e.kind == "text"]
    assert any(t.startswith("Con 0 incidencias") for t in texts)
    assert not any(
        "ASEO_incidents_by_category" in str(e.path) for e in result.elements if e.kind == "chart"
    )
