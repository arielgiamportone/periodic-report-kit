from pathlib import Path

import pytest
from docx import Document
from pptx import Presentation

from reportkit.brand import BrandKit
from reportkit.render_md import (
    VISUAL_BLOCKS,
    chip_colour,
    md_to_docx,
    md_to_pptx,
    parse_markdown,
    parse_visual,
    shape_count,
)

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "demo_deck.md"


@pytest.fixture(scope="module")
def brand() -> BrandKit:
    return BrandKit.load(ROOT / "brands" / "nordal" / "brand.yaml")


def test_parser_splits_slides_and_attaches_lead_and_foot() -> None:
    doc = parse_markdown(DEMO.read_text(encoding="utf-8"))
    assert doc.title.startswith("Plan de modernización")
    assert len(doc.slides) == 10
    kinds = [b.text for b in doc.blocks if b.kind == "visual"]
    assert kinds == list(VISUAL_BLOCKS)
    kpi = next(b for b in doc.blocks if b.text == "kpi")
    assert kpi.lead.startswith("Cada mes") and kpi.foot == "Las cifras son ilustrativas."
    assert kpi.items == [
        ("7 h", "horas por informe"),
        ("3", "versiones por entrega"),
        ("12", "cifras contradictorias detectadas"),
    ]
    table = next(b for b in doc.blocks if b.kind == "table")
    assert table.headers == ["Bloque", "Word", "PowerPoint"] and len(table.rows) == 2


def test_visual_grammar() -> None:
    assert parse_visual("flow", ["A → B", "C"]) == ["A", "B", "C"]
    assert parse_visual("quad", ["H | a ;; b"]) == [("H", ["a", "b"])]
    road = parse_visual("roadmap", ["Lane | T: 2026-Q1-2026-Q3"])
    assert road == [("Lane", [("T", (2026, 1), (2026, 3))])]
    bcg = parse_visual("bcgmatrix", ["X :: 0.1 :: 0.9 :: 0.5 :: 0.5"])
    assert bcg == [("X", 0.1, 0.9, (0.5, 0.5))]
    with pytest.raises(ValueError):
        parse_visual("bcgmatrix", ["X :: 2 :: 0.5"])
    with pytest.raises(ValueError):
        parse_visual("roadmap", ["Lane | sin rango"])


def test_chip_colours_by_keyword(brand) -> None:
    assert chip_colour(brand, "En producción") == brand.semantic.ok
    assert chip_colour(brand, "En curso") == brand.semantic.warn
    assert chip_colour(brand, "Crítico") == brand.semantic.fail
    assert chip_colour(brand, "Pendiente") == brand.palette.muted


def test_md_to_docx_and_pptx_render_all_nine_blocks(brand, tmp_path: Path) -> None:
    docx_path = md_to_docx(DEMO, brand, tmp_path / "deck.docx")
    pptx_path = md_to_pptx(DEMO, brand, tmp_path / "deck.pptx")
    doc = Document(docx_path)
    assert len(doc.tables) >= 9  # every block but decisions/flow-text lands as a table in Word
    texts = "\n".join(p.text for p in doc.paragraphs)
    assert "Cargar → Normalizar" in texts and "1. Reglas en YAML" in texts
    prs = Presentation(str(pptx_path))
    assert len(prs.slides) == 11  # title slide + intro slide + 9 visual slides
    counts = shape_count(pptx_path)
    # title slide: band + background + 2 labels; each visual slide carries its shapes
    assert counts[0] == 4
    expected_min = {
        "kpi": 3 * 4,
        "cards": 4 * 3,
        "quad": 8,
        "flow": 9,
        "beforeafter": 12,
        "decisions": 9,
        "roadmap": 10,
        "bcgmatrix": 4 + 3 * 2 + 1,
        "porter": 5 + 4,
    }
    for slide, kind in zip(list(prs.slides)[2:], VISUAL_BLOCKS, strict=True):
        assert len(slide.shapes) >= expected_min[kind] + 2, kind  # + band + title
    porter_slide = prs.slides[10]
    assert any(sh.has_table for sh in porter_slide.shapes)
    bcg = prs.slides[9]
    assert (
        sum(1 for sh in bcg.shapes if sh.shape_type is not None and "LINE" in str(sh.shape_type))
        == 1
    )
