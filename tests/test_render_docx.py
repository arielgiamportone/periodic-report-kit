import zipfile
from pathlib import Path

import pandas as pd
import pytest
from docx import Document
from docx.oxml.ns import qn

from reportkit.brand import BrandKit
from reportkit.placeholders import COMMENT_TOKEN, SYNTHETIC_TAG
from reportkit.render_docx import BrandDocument, CoverData

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def brand() -> BrandKit:
    return BrandKit.load(ROOT / "brands" / "nordal" / "brand.yaml")


@pytest.fixture(scope="module")
def generated(brand, tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("docx") / "informe.docx"
    cover = CoverData(
        "Informe mensual de servicio",
        "Cliente de demostración",
        "Ref. NA-2026-03 · Marzo 2026",
        synthetic=True,
    )
    doc = BrandDocument(brand, cover=cover)
    doc.title("Informe mensual · Marzo 2026")
    doc.toc()
    doc.heading("Resumen del periodo")
    doc.text(f"{COMMENT_TOKEN} controles=50; incidencias=12")
    doc.heading("Metodología")
    doc.heading("Cafeterías")
    doc.heading("Incidencias por categoría", level=2)
    doc.table(
        pd.DataFrame(
            {
                "Categoría": ["Higiene", "Total"],
                "Incidencias": [3, 3],
                "Peso": ["100,0 %", "100,0 %"],
            }
        ),
        caption="Tabla 1",
    )
    doc.heading("Anexo: avisos de carga", level=2, in_toc=False)
    doc.chart(ROOT / "brands" / "nordal" / "cover_background.png", caption="Figura 1")
    doc.kpi_row([("50", "controles"), ("12", "incidencias")])
    return doc.save(out)


def _xml(path: Path, part: str = "word/document.xml") -> str:
    with zipfile.ZipFile(path) as zf:
        return zf.read(part).decode("utf-8")


def test_refuses_to_render_without_template(brand) -> None:
    from dataclasses import replace

    with pytest.raises(FileNotFoundError):
        BrandDocument(replace(brand, template=None))


def test_cover_is_selectable_text_with_accents(generated: Path) -> None:
    doc = Document(generated)
    texts = [p.text for p in doc.paragraphs[:12]]
    assert "Cliente de demostración" in texts
    assert any("Marzo 2026" in t for t in texts)
    assert SYNTHETIC_TAG in texts


def test_background_is_anchored_behind_text_at_page_origin(generated: Path) -> None:
    xml = _xml(generated)
    assert 'behindDoc="1"' in xml
    assert '<wp:positionH relativeFrom="page"><wp:posOffset>0</wp:posOffset></wp:positionH>' in xml
    assert '<wp:positionV relativeFrom="page"><wp:posOffset>0</wp:posOffset></wp:positionV>' in xml
    assert "<wp:inline" not in xml.split("Resumen del periodo")[0]


def test_cover_section_has_zero_margins_and_body_keeps_letterhead(generated: Path) -> None:
    doc = Document(generated)
    assert len(doc.sections) == 2
    cover, body = doc.sections[0]._sectPr, doc.sections[1]._sectPr
    mar = cover.find(qn("w:pgMar"))
    assert all(mar.get(qn(f"w:{a}")) == "0" for a in ("top", "right", "bottom", "left"))
    assert (
        cover.find(qn("w:headerReference")) is None and cover.find(qn("w:footerReference")) is None
    )
    assert body.find(qn("w:headerReference")) is not None
    assert body.find(qn("w:titlePg")) is None
    assert body.find(qn("w:pgNumType")).get(qn("w:start")) == "1"


def test_cover_paragraphs_use_exact_spacing_from_geometry(generated: Path, brand) -> None:
    doc = Document(generated)
    exact = [
        p
        for p in doc.paragraphs[:12]
        if p.paragraph_format.line_spacing_rule is not None
        and p.paragraph_format.line_spacing_rule.name == "EXACTLY"
    ]
    assert len(exact) >= 4
    bar = brand.cover.bars["report_type"]
    expected = round(bar.height * 72 / brand.cover.dpi)
    assert any(abs(p.paragraph_format.line_spacing.pt - expected) < 1 for p in exact)


def test_toc_is_a_field_by_outline_level_and_excludes_its_title(generated: Path) -> None:
    xml = _xml(generated)
    assert 'TOC \\o "1-2"' in xml
    assert 'w:updateFields w:val="true"' in _xml(generated, "word/settings.xml")
    doc = Document(generated)
    contents = next(p for p in doc.paragraphs if p.text == "Contenidos")
    assert contents._p.pPr.find(qn("w:outlineLvl")).get(qn("w:val")) == "8"
    levels = [
        (p.text, p._p.pPr.find(qn("w:outlineLvl")).get(qn("w:val")))
        for p in doc.paragraphs
        if p._p.pPr is not None and p._p.pPr.find(qn("w:outlineLvl")) is not None
    ]
    in_toc = [t for t, lvl in levels if lvl in ("0", "1")]
    assert in_toc == [
        "Resumen del periodo",
        "Metodología",
        "Cafeterías",
        "Incidencias por categoría",
    ]
    assert ("Anexo: avisos de carga", "8") in levels


def test_gaps_are_highlighted_and_charts_inserted(generated: Path) -> None:
    doc = Document(generated)
    gap = next(p for p in doc.paragraphs if COMMENT_TOKEN in p.text)
    run = next(r for r in gap.runs if COMMENT_TOKEN in r.text)
    assert run.font.highlight_color is not None and run.font.highlight_color.name == "YELLOW"
    assert len(doc.inline_shapes) == 1  # the chart; the cover background is anchored, not inline
    table = doc.tables[0]
    assert table.rows[0].cells[0].text == "Categoría"
    assert table.rows[1].cells[1].paragraphs[0].alignment is not None  # numbers right-aligned


def test_header_text_boxes_can_be_replaced(brand, tmp_path: Path) -> None:
    doc = BrandDocument(brand)
    n = doc.replace_header_text({"Informe periódico de servicio": "Informe mensual · Marzo 2026"})
    assert n >= 1
    path = doc.save(tmp_path / "h.docx")
    assert "Informe mensual · Marzo 2026" in _xml(
        path, "word/header2.xml"
    ) or "Informe mensual · Marzo 2026" in _xml(path, "word/header1.xml")
