from dataclasses import replace
from pathlib import Path

import pytest

from reportkit.brand import BrandKit
from reportkit.defaults import default_brand_path
from reportkit.placeholders import SYNTHETIC_TAG
from reportkit.render_pdf import PdfCover, compose_pdf, page_count, page_texts

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def brand() -> BrandKit:
    return BrandKit.load(default_brand_path())


def _three_pages() -> list[str]:
    return [
        f"<h1>Capítulo {i}</h1><p>Texto con acentos: canción, señal.</p><pdf:nextpage/>"
        for i in (1, 2)
    ] + ["<h1>Capítulo 3</h1><table><tr><th>A</th></tr><tr><td class='num'>1</td></tr></table>"]


def test_cover_plus_three_pages_numbered_only_in_content(brand) -> None:
    pdf = compose_pdf(
        _three_pages(),
        brand,
        cover=PdfCover("Informe mensual", "Cliente demo", "Ref. 1", synthetic=True),
    )
    assert page_count(pdf) == 4
    texts = page_texts(pdf)
    assert "1 / 3" not in texts[0] and SYNTHETIC_TAG in texts[0]
    assert "Cliente demo" in texts[0]
    assert "1 / 3" in texts[1] and "3 / 3" in texts[3]
    assert "canción" in texts[1]


def test_without_png_single_pass_css_cover(brand) -> None:
    no_png = replace(brand, cover_background=None)
    pdf = compose_pdf(
        _three_pages(), no_png, cover=PdfCover("Informe mensual", "Cliente demo", "Ref. 1")
    )
    texts = page_texts(pdf)
    assert page_count(pdf) == 4
    assert "Cliente demo" in texts[0] and brand.name in texts[0]
    assert "1 / 4" in texts[0]  # single pass: the cover is page 1 of the content


def test_landscape_annex_is_a_third_pass(brand) -> None:
    pdf = compose_pdf(
        _three_pages(), brand, cover=PdfCover("A", "B", "C"), landscape_sections=["<h1>Anexo</h1>"]
    )
    assert page_count(pdf) == 5
    from io import BytesIO

    from pypdf import PdfReader

    last = PdfReader(BytesIO(pdf)).pages[-1]
    assert float(last.mediabox.width) > float(last.mediabox.height)
