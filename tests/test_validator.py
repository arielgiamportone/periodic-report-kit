import zipfile
from pathlib import Path

import pytest

from reportkit.brand import BrandKit
from reportkit.catalog import ReportCatalog
from reportkit.comments import CommentStore
from reportkit.defaults import default_brand_path, default_config_dir
from reportkit.loaders import load_range
from reportkit.report import ReportRequest, build_report
from reportkit.synthetic import SyntheticOptions, write_workbooks
from reportkit.validator import contrast, read_prose_figures, read_summary_table

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def delivered(tmp_path_factory, schema, groups, items):
    root = tmp_path_factory.mktemp("val")
    write_workbooks(root / "data", ["2026-03"], SyntheticOptions(seed=9))
    brand = BrandKit.load(default_brand_path())
    catalog = ReportCatalog.load(default_config_dir() / "report_catalog.yaml")
    period = load_range("2026-03", "2026-03", schema, groups, items, root / "data", use_cache=False)
    store = CommentStore.load("2026-03", root / "comments")
    result = build_report(
        period,
        ReportRequest("monthly", "2026-03", "2026-03", pdf=True),
        brand,
        catalog,
        groups,
        store,
        root / "out",
    )
    return period, result.docx


def _tamper(src: Path, dst: Path, old: str, new: str) -> Path:
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == "word/document.xml":
                text = data.decode("utf-8")
                assert old in text, old
                data = text.replace(old, new, 1).encode("utf-8")
            zout.writestr(info, data)
    return dst


def test_our_own_report_contrasts_clean(delivered, groups) -> None:
    period, docx = delivered
    report = contrast(period, docx, groups)
    assert report.discrepancies == []
    assert (
        report.exit_code == 0
        and report.has_pdf
        and report.version == "001"
        and len(report.short_hash) == 8
    )
    table = read_summary_table(docx)
    assert table is not None and "Cafeterías" in table["group"].tolist()
    prose = read_prose_figures(docx, {g.name: g.code for g in groups.groups})
    assert (
        prose["CAFE"]["controls"]
        == period.data[period.data["group"] == "CAFE"]["control_id"].nunique()
    )


def test_prose_differing_from_table_is_flagged(delivered, groups, tmp_path: Path) -> None:
    period, docx = delivered
    prose = read_prose_figures(docx, {g.name: g.code for g in groups.groups})
    n = prose["CAFE"]["incidents"]
    tampered = _tamper(
        docx, tmp_path / "entregado.docx", f"con {n} incidencias", f"con {n + 1} incidencias"
    )
    report = contrast(period, tampered, groups)
    sources = sorted(d.source for d in report.discrepancies)
    assert sources == ["prose", "prose-vs-table"]
    assert report.exit_code == 1
    assert any("incoherencia interna" in d.message for d in report.discrepancies)


def test_mapping_is_explicit_not_substring(delivered, groups) -> None:
    period, docx = delivered
    prose = read_prose_figures(docx, {"Cafés": "CAFE"})  # not the chapter title: nothing matches
    assert prose == {}
