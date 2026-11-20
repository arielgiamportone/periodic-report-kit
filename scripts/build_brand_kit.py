"""Build the demo brand assets: ``template.docx`` and ``cover_background.png``.

Usage::

    python scripts/build_brand_kit.py brands/nordal/brand.yaml [--from-template]

By default the cover background is drawn with Pillow from the geometry declared in
``brand.yaml`` (deterministic, no office suite needed). With ``--from-template`` the template
body is emptied preserving its shapes, converted to PDF with LibreOffice and page 1 is
rasterised at the declared DPI, which is how a real letterhead becomes a full-bleed cover.
"""

from __future__ import annotations

import argparse
import copy
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls
from docx.shared import Cm, Pt, RGBColor
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from reportkit.brand import BrandKit, hex_to_rgb  # noqa: E402

A4_W_PX, A4_H_PX = 1241, 1754


def _rgb(value: str) -> RGBColor:
    return RGBColor(*hex_to_rgb(value))


def _textbox_xml(text: str, color: str, width_pt: int = 400, height_pt: int = 28) -> str:
    """A VML text box (the kind real letterheads carry in their headers)."""
    return (
        f'<w:r {nsdecls("w")} xmlns:v="urn:schemas-microsoft-com:vml"><w:pict>'
        f'<v:shape id="brand_header" type="#_x0000_t202" style="position:absolute;margin-left:0;margin-top:-6pt;width:{width_pt}pt;height:{height_pt}pt;z-index:1" filled="f" stroked="f">'
        f'<v:textbox inset="0,0,0,0"><w:txbxContent><w:p><w:pPr><w:spacing w:after="0"/></w:pPr>'
        f'<w:r><w:rPr><w:b/><w:color w:val="{color.lstrip("#")}"/><w:sz w:val="18"/></w:rPr><w:t xml:space="preserve">{text}</w:t></w:r>'
        f"</w:p></w:txbxContent></v:textbox></v:shape></w:pict></w:r>"
    )


def _field_run(instr: str) -> str:
    return (
        f'<w:r {nsdecls("w")}><w:fldChar w:fldCharType="begin"/></w:r>'
        f'<w:r {nsdecls("w")}><w:instrText xml:space="preserve"> {instr} </w:instrText></w:r>'
        f'<w:r {nsdecls("w")}><w:fldChar w:fldCharType="separate"/></w:r>'
        f"<w:r {nsdecls('w')}><w:t>1</w:t></w:r>"
        f'<w:r {nsdecls("w")}><w:fldChar w:fldCharType="end"/></w:r>'
    )


def build_template(brand: BrandKit, out: Path) -> Path:
    doc = Document()
    section = doc.sections[0]
    section.orientation = WD_ORIENT.PORTRAIT
    section.page_width, section.page_height = Cm(21.0), Cm(29.7)
    section.left_margin = section.right_margin = Cm(2.0)
    section.top_margin, section.bottom_margin = Cm(2.5), Cm(2.0)
    section.header_distance = section.footer_distance = Cm(1.0)
    # Real letterheads come with their own cover: "different first page" on, empty first header.
    section.different_first_page_header_footer = True

    body_font = brand.body().used
    heading_font = brand.heading().used

    styles = doc.styles
    normal = styles["Normal"]
    normal.font.name = body_font
    normal.font.size = Pt(10.5)
    normal.font.color.rgb = _rgb(brand.palette.ink)

    def named(
        name: str,
        base: str,
        size: float,
        color: str,
        bold: bool = True,
        font: str = heading_font,
        before: int = 12,
        after: int = 6,
    ) -> None:
        st = styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        st.base_style = styles[base]
        st.font.name = font
        st.font.size = Pt(size)
        st.font.bold = bold
        st.font.color.rgb = _rgb(color)
        st.paragraph_format.space_before = Pt(before)
        st.paragraph_format.space_after = Pt(after)
        st.quick_style = True

    named("Nordal Title", "Normal", 24, brand.palette.primary, before=0, after=12)
    named("Nordal Heading 1", "Normal", 16, brand.palette.primary, before=18, after=8)
    named("Nordal Heading 2", "Normal", 12.5, brand.palette.secondary, before=12, after=4)
    named(
        "Nordal Body",
        "Normal",
        10.5,
        brand.palette.ink,
        bold=False,
        font=body_font,
        before=0,
        after=6,
    )
    named(
        "Nordal Caption",
        "Normal",
        9,
        brand.palette.muted,
        bold=False,
        font=body_font,
        before=2,
        after=10,
    )
    styles["Nordal Caption"].font.italic = True

    # Header: brand name inside a text box (as real letterheads do) + a thin rule.
    header = section.header
    hp = header.paragraphs[0]
    hp._p.append(
        parse_xml(
            _textbox_xml(f"{brand.name} · Informe periódico de servicio", brand.palette.primary)
        )
    )
    hp.paragraph_format.space_after = Pt(0)
    rule = header.add_paragraph()
    rule.paragraph_format.space_after = Pt(0)
    pbdr = parse_xml(
        f'<w:pBdr {nsdecls("w")}><w:bottom w:val="single" w:sz="6" w:space="1" w:color="{brand.palette.secondary.lstrip("#")}"/></w:pBdr>'
    )
    rule._p.get_or_add_pPr().append(pbdr)

    footer = section.footer
    fp = footer.paragraphs[0]
    run = fp.add_run(brand.legal_footer)
    run.font.size = Pt(7.5)
    run.font.color.rgb = _rgb(brand.palette.muted)
    pn = footer.add_paragraph()
    pn.alignment = 2
    r = pn.add_run("Página ")
    r.font.size = Pt(8)
    for xml in (_field_run("PAGE"),):
        for el in parse_xml(f"<w:root {nsdecls('w')}>{xml}</w:root>"):
            pn._p.append(copy.deepcopy(el))
    r2 = pn.add_run(" de ")
    r2.font.size = Pt(8)
    for el in parse_xml(f"<w:root {nsdecls('w')}>{_field_run('NUMPAGES')}</w:root>"):
        pn._p.append(copy.deepcopy(el))

    doc.add_paragraph("Cuerpo de la plantilla: se vacía al generar.", style="Nordal Body")
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out)
    return out


def _font(brand: BrandKit, size: int, heading: bool = True) -> ImageFont.FreeTypeFont:
    res = brand.heading() if heading else brand.body()
    if res.path is None:
        raise RuntimeError("no scalable font found; the bitmap default is never acceptable")
    return ImageFont.truetype(str(res.path), size)


def draw_background(brand: BrandKit, out: Path) -> Path:
    """Draw the cover background from the declared geometry (fixed labels are baked in)."""
    geo = brand.cover
    img = Image.new("RGB", (geo.width_px, geo.height_px), hex_to_rgb(brand.palette.page_bg))
    d = ImageDraw.Draw(img)
    primary, secondary = hex_to_rgb(brand.palette.primary), hex_to_rgb(brand.palette.secondary)
    # Top band with the brand name and tagline (fixed labels live in the PNG).
    d.rectangle([0, 0, geo.width_px, 330], fill=primary)
    d.rectangle([0, 330, geo.width_px, 346], fill=secondary)
    d.text((110, 90), brand.name, font=_font(brand, 76), fill="white")
    if brand.tagline:
        d.text(
            (112, 190),
            brand.tagline,
            font=_font(brand, 34, heading=False),
            fill=hex_to_rgb(brand.palette.frame_bg),
        )
    d.text((110, 440), "Informe periódico de servicio", font=_font(brand, 44), fill=primary)
    # Bars where the variable text (Word paragraphs) will sit.
    for name, bar in geo.bars.items():
        colour = primary if name != "reference" else secondary
        d.rectangle([0, bar.top, geo.width_px, bar.top + bar.height], fill=colour)
    # Bottom band with legal text and a side accent.
    d.rectangle(
        [0, geo.height_px - 110, geo.width_px, geo.height_px],
        fill=hex_to_rgb(brand.palette.frame_bg),
    )
    d.rectangle([0, geo.height_px - 110, 18, geo.height_px], fill=hex_to_rgb(brand.palette.accent))
    d.text(
        (60, geo.height_px - 80),
        brand.legal_footer[:110],
        font=_font(brand, 18, heading=False),
        fill=hex_to_rgb(brand.palette.muted),
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, dpi=(geo.dpi, geo.dpi))
    return out


def rasterize_template_cover(template: Path, out: Path, dpi: int) -> Path:
    """Empty the template body (keeping shapes), convert to PDF with LibreOffice, rasterise page 1."""
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice is None:
        raise RuntimeError("LibreOffice (soffice) not found")
    import pypdfium2 as pdfium

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        doc = Document(template)
        body = doc.element.body
        for child in list(body):
            if child.tag.endswith("}sectPr"):
                continue
            body.remove(child)
        emptied = tmp_path / "cover_source.docx"
        doc.save(emptied)
        subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf", "--outdir", tmp, str(emptied)],
            check=True,
            capture_output=True,
        )
        pdf = pdfium.PdfDocument(str(tmp_path / "cover_source.pdf"))
        page = pdf[0]
        image = page.render(scale=dpi / 72).to_pil()
        image = image.resize((A4_W_PX, A4_H_PX))
        out.parent.mkdir(parents=True, exist_ok=True)
        image.save(out, dpi=(dpi, dpi))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("brand_yaml", type=Path)
    parser.add_argument(
        "--from-template",
        action="store_true",
        help="rasterise the emptied template with LibreOffice",
    )
    args = parser.parse_args(argv)
    brand = BrandKit.load(args.brand_yaml)
    template = brand.template or (brand.root / "template.docx")
    background = brand.cover_background or (brand.root / "cover_background.png")
    print("template  ->", build_template(brand, template))
    if args.from_template:
        print("background->", rasterize_template_cover(template, background, brand.cover.dpi))
    else:
        print("background->", draw_background(brand, background))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
