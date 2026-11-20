"""PDF renderer: HTML -> PDF in two passes joined with pypdf.

The target engine (xhtml2pdf) ignores named ``@page`` rules, so a zero-margin cover and a
content body with margins and a footer cannot live in one HTML. The cover is rendered from a
minimal HTML with ``@page { margin: 0 }`` and no footer, the content from the brand CSS, and
the two PDFs are concatenated. The same pattern serves landscape annexes.

The cover canvas is 1241 x 1754 px saved at 150 dpi: the engine scales images by their DPI
and ignores point heights, so that canvas measures exactly A4 and bleeds without strips.
Only the content pass carries ``page / total``; the cover does not count.
"""

from __future__ import annotations

import base64
import html
import io
import logging
import mimetypes
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from xhtml2pdf import pisa

from .brand import BrandKit
from .placeholders import SYNTHETIC_TAG


@dataclass(frozen=True, slots=True)
class PdfCover:
    report_type: str
    recipient: str
    reference: str
    synthetic: bool = False


def data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    return f"data:{mime};base64,{base64.b64encode(Path(path).read_bytes()).decode('ascii')}"


def _font_face(brand: BrandKit) -> tuple[str, str]:
    """``@font-face`` for the body font if a TTF resolves; otherwise the PDF standard font."""
    body = brand.body()
    if body.path is not None and body.path.suffix.lower() == ".ttf":
        return (
            f"@font-face {{ font-family: 'BrandBody'; src: url('{body.path.as_posix()}'); }}",
            "'BrandBody'",
        )
    return "", "Helvetica"


def brand_css(brand: BrandKit, with_page: bool = True) -> str:
    face, family = _font_face(brand)
    p = brand.palette
    page = (
        "@page { size: a4 portrait; margin: 22mm 18mm 20mm 18mm; "
        "@frame footer { -pdf-frame-content: footer; bottom: 8mm; margin-left: 18mm; margin-right: 18mm; height: 8mm; } "
        "@frame header { -pdf-frame-content: header; top: 8mm; margin-left: 18mm; margin-right: 18mm; height: 8mm; } }"
        if with_page
        else ""
    )
    return f"""
    {face}
    {page}
    body {{ font-family: {family}; font-size: 10pt; color: {p.ink}; }}
    h1 {{ color: {p.primary}; font-size: 18pt; margin: 14pt 0 6pt 0; }}
    h2 {{ color: {p.secondary}; font-size: 13pt; margin: 12pt 0 4pt 0; }}
    p {{ margin: 0 0 6pt 0; line-height: 1.35; }}
    table {{ border-collapse: collapse; width: 100%; margin: 4pt 0 8pt 0; font-size: 9pt; }}
    th {{ background-color: {p.secondary}; color: #FFFFFF; padding: 3pt 5pt; text-align: left; }}
    td {{ border: 0.5pt solid {p.border}; padding: 3pt 5pt; }}
    tr.alt td {{ background-color: {p.frame_bg}; }}
    td.num {{ text-align: right; }}
    .caption {{ color: {p.muted}; font-style: italic; font-size: 8.5pt; margin-bottom: 10pt; }}
    .gap {{ background-color: #FFFF00; font-weight: bold; }}
    .kpi {{ background-color: {p.frame_bg}; text-align: center; padding: 6pt; }}
    .kpi .value {{ color: {p.accent}; font-size: 18pt; font-weight: bold; }}
    .kpi .label {{ color: {p.muted}; font-size: 8pt; }}
    #header {{ color: {p.muted}; font-size: 8pt; border-bottom: 0.5pt solid {p.secondary}; }}
    #footer {{ color: {p.muted}; font-size: 7.5pt; text-align: right; }}
    .legal {{ color: {p.muted}; font-size: 7pt; text-align: left; }}
    .synthetic {{ color: {brand.synthetic_badge_color}; font-weight: bold; }}
    """


def cover_html(brand: BrandKit, cover: PdfCover) -> str:
    """Minimal full-bleed page: background image + text frames at the bar geometry."""
    assert brand.cover_background is not None
    geo = brand.cover
    mm_per_px = 297.0 / geo.height_px
    face, family = _font_face(brand)
    frames, blocks = [], []
    bars = {
        "report_type": cover.report_type,
        "recipient": cover.recipient,
        "reference": cover.reference,
    }
    for name, bar in geo.bars.items():
        top_mm = bar.top * mm_per_px
        height_mm = bar.height * mm_per_px
        left_mm = bar.left * mm_per_px
        frames.append(
            f"@frame f_{name} {{ -pdf-frame-content: c_{name}; left: {left_mm:.1f}mm; top: {top_mm:.1f}mm; "
            f"width: {210 - left_mm - 10:.1f}mm; height: {height_mm:.1f}mm; }}"
        )
        size = max(10, round(height_mm * 1.2 / max(1, bar.lines)))
        lines = "<br/>".join(html.escape(x) for x in bars.get(name, "").split("\n"))
        blocks.append(
            f'<div id="c_{name}" style="color:{geo.text_color}; font-size:{size}pt; font-weight:bold; margin-top:{height_mm * 0.12:.1f}mm;">{lines}</div>'
        )
    badge = ""
    if cover.synthetic:
        frames.append(
            "@frame f_badge { -pdf-frame-content: c_badge; left: 18mm; top: 2mm; width: 120mm; height: 8mm; }"
        )
        badge = f'<div id="c_badge" style="color:{brand.synthetic_badge_color}; font-size:11pt; font-weight:bold;">{SYNTHETIC_TAG}</div>'
    # The background goes in a static frame declared FIRST, so the text frames paint over it.
    bg_frame = (
        "@frame bg { -pdf-frame-content: c_bg; left: 0; top: 0; width: 210mm; height: 297mm; }"
    )
    return f"""<html><head><style>
    {face}
    @page {{ size: a4 portrait; margin: 0; {bg_frame} {" ".join(frames)} }}
    body {{ margin: 0; padding: 0; font-family: {family}; }}
    </style></head><body>
    <div id="c_bg"><img src="{data_uri(brand.cover_background)}" /></div>
    {badge}
    {"".join(blocks)}
    <p>&nbsp;</p>
    </body></html>"""


def css_cover_block(brand: BrandKit, cover: PdfCover) -> str:
    """Fallback cover built inline with CSS when there is no background PNG (single pass)."""
    p = brand.palette
    badge = f'<p class="synthetic">{SYNTHETIC_TAG}</p>' if cover.synthetic else ""
    return f"""
    <div style="background-color:{p.primary}; color:#FFFFFF; padding: 24pt;">
      <p style="font-size:26pt; font-weight:bold; margin:0;">{html.escape(brand.name)}</p>
      <p style="font-size:11pt; margin:0;">{html.escape(brand.tagline)}</p>
    </div>
    <div style="border: 1pt solid {p.border}; padding: 16pt; margin-top: 60pt;">
      {badge}
      <p style="font-size:20pt; color:{p.primary}; font-weight:bold;">{html.escape(cover.report_type)}</p>
      <p style="font-size:13pt;">{html.escape(cover.recipient)}</p>
      <p style="font-size:11pt; color:{p.muted};">{html.escape(cover.reference).replace(chr(10), "<br/>")}</p>
    </div>
    <p class="legal" style="margin-top: 200pt;">{html.escape(brand.legal_footer)}</p>
    <pdf:nextpage />
    """


def content_html(
    brand: BrandKit,
    sections_html: list[str],
    header_text: str = "",
    landscape: bool = False,
    prefix_html: str = "",
) -> str:
    css = brand_css(brand)
    if landscape:
        css = css.replace("size: a4 portrait", "size: a4 landscape")
    footer = f'<div id="footer">{html.escape(brand.legal_footer)} &nbsp;·&nbsp; <pdf:pagenumber></pdf:pagenumber> / <pdf:pagecount></pdf:pagecount></div>'
    header = f'<div id="header">{html.escape(header_text or brand.name)}</div>'
    body = "".join(sections_html)
    return f"<html><head><style>{css}</style></head><body>{header}{footer}{prefix_html}{body}</body></html>"


def render_html(html_text: str) -> bytes:
    logging.getLogger("xhtml2pdf").setLevel(logging.ERROR)
    buf = io.BytesIO()
    result = pisa.CreatePDF(io.BytesIO(html_text.encode("utf-8")), dest=buf, encoding="utf-8")
    if result.err:
        raise RuntimeError(f"HTML to PDF failed with {result.err} error(s)")
    return buf.getvalue()


def merge_pdfs(parts: list[bytes]) -> bytes:
    writer = PdfWriter()
    for part in parts:
        reader = PdfReader(io.BytesIO(part))
        for page in reader.pages:
            writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def compose_pdf(
    sections_html: list[str],
    brand: BrandKit,
    cover: PdfCover | None = None,
    header_text: str = "",
    landscape_sections: list[str] | None = None,
) -> bytes:
    """Two passes + merge (cover, content, optional landscape annex). One pass without PNG."""
    has_png = (
        cover is not None
        and brand.cover_background is not None
        and Path(brand.cover_background).is_file()
    )
    parts: list[bytes] = []
    if cover is not None and has_png:
        parts.append(render_html(cover_html(brand, cover)))
        parts.append(render_html(content_html(brand, sections_html, header_text)))
    elif cover is not None:
        parts.append(
            render_html(
                content_html(
                    brand, sections_html, header_text, prefix_html=css_cover_block(brand, cover)
                )
            )
        )
    else:
        parts.append(render_html(content_html(brand, sections_html, header_text)))
    if landscape_sections:
        parts.append(
            render_html(content_html(brand, landscape_sections, header_text, landscape=True))
        )
    return merge_pdfs(parts) if len(parts) > 1 else parts[0]


def page_count(pdf: bytes) -> int:
    return len(PdfReader(io.BytesIO(pdf)).pages)


def page_texts(pdf: bytes) -> list[str]:
    return [page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf)).pages]
