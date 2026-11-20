"""Word renderer on top of a letterhead template.

* The template is opened, its body emptied keeping the final ``sectPr`` (which references
  the letterhead header and footer) and written with its named styles. Without a template
  the renderer refuses: a report without letterhead is not issued.
* The cover is a section of its own (margins zero, no header/footer references) with the
  background PNG anchored *behind* the text at page position 0,0, and the variable blocks as
  real Word paragraphs with exact line spacing computed from the bar geometry (72 / dpi).
* The table of contents is a TOC field by outline level (``\\o "1-2"``) with ``updateFields``
  on, and the level is set on the paragraph, not on the style, so the "Contents" title stays
  out of its own index.
"""

from __future__ import annotations

import contextlib
import copy
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_COLOR_INDEX, WD_LINE_SPACING
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Cm, Emu, Pt, RGBColor
from docx.text.paragraph import Paragraph

from .brand import BrandKit, hex_to_rgb
from .placeholders import SYNTHETIC_TAG

_PLACEHOLDER_SPLIT = re.compile(r"(\[\[[^\]]+\]\])")
_NUMBER = re.compile(r"^\s*[-+]?[\d.,]+\s*%?\s*$")


@dataclass(frozen=True, slots=True)
class CoverData:
    report_type: str
    recipient: str
    reference: str
    synthetic: bool = False

    def bar_text(self, bar: str) -> str:
        return {
            "report_type": self.report_type,
            "recipient": self.recipient,
            "reference": self.reference,
        }.get(bar, "")


def _rgb(value: str) -> RGBColor:
    return RGBColor(*hex_to_rgb(value))


def _set_spacing_exact(paragraph: Paragraph, points: float) -> None:
    fmt = paragraph.paragraph_format
    fmt.space_before = Pt(0)
    fmt.space_after = Pt(0)
    fmt.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    fmt.line_spacing = Pt(max(points, 1.0))


def _shade(cell: Any, colour: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = parse_xml(
        f'<w:shd {nsdecls("w")} w:val="clear" w:color="auto" w:fill="{colour.lstrip("#")}"/>'
    )
    tc_pr.append(shd)


def _table_borders(table: Any, colour: str) -> None:
    tbl_pr = table._tbl.tblPr
    borders = parse_xml(
        f"<w:tblBorders {nsdecls('w')}>"
        + "".join(
            f'<w:{side} w:val="single" w:sz="4" w:space="0" w:color="{colour.lstrip("#")}"/>'
            for side in ("top", "left", "bottom", "right", "insideH", "insideV")
        )
        + "</w:tblBorders>"
    )
    for old in tbl_pr.findall(qn("w:tblBorders")):
        tbl_pr.remove(old)
    tbl_pr.append(borders)


class BrandDocument:
    """A branded Word document being written section by section."""

    def __init__(
        self, brand: BrandKit, cover: CoverData | None = None, contents_title: str = "Contenidos"
    ) -> None:
        if brand.template is None or not Path(brand.template).is_file():
            raise FileNotFoundError(
                "brand template not found: a report without letterhead is not issued"
            )
        self.brand = brand
        self.contents_title = contents_title
        self.doc = Document(str(brand.template))
        self._empty_body()
        self._apply_fonts()
        self._body_section_setup()
        self._picture_id = 100
        if cover is not None:
            self._build_cover(cover)

    # -- template handling --------------------------------------------------------------------

    def _empty_body(self) -> None:
        body = self.doc.element.body
        for child in list(body):
            if child.tag != qn("w:sectPr"):
                body.remove(child)

    def _style(self, role: str) -> str:
        name = self.brand.styles.get(role, role)
        try:
            self.doc.styles[name]
        except KeyError as exc:
            raise KeyError(f"template has no style {name!r} for role {role!r}") from exc
        return name

    def _apply_fonts(self) -> None:
        """Set each role style to the font that actually resolves on this machine."""
        heading, body = self.brand.heading().used, self.brand.body().used
        for role, font in (
            ("title", heading),
            ("heading1", heading),
            ("heading2", heading),
            ("body", body),
            ("caption", body),
        ):
            with contextlib.suppress(KeyError):
                self.doc.styles[self._style(role)].font.name = font

    def _body_section_setup(self) -> None:
        """The body keeps the letterhead on page 1 and starts numbering at 1."""
        sect_pr = self.doc.element.body.find(qn("w:sectPr"))
        for title_pg in sect_pr.findall(qn("w:titlePg")):
            sect_pr.remove(title_pg)
        for old in sect_pr.findall(qn("w:pgNumType")):
            sect_pr.remove(old)
        pg = OxmlElement("w:pgNumType")
        pg.set(qn("w:start"), "1")
        # schema order: pgNumType goes after pgMar/paperSrc/pgBorders/lnNumType... before cols.
        cols = sect_pr.find(qn("w:cols"))
        if cols is not None:
            cols.addprevious(pg)
        else:
            sect_pr.append(pg)

    @property
    def usable_width(self) -> Emu:
        section = self.doc.sections[-1]
        return Emu(section.page_width - section.left_margin - section.right_margin)

    # -- cover -----------------------------------------------------------------------------------

    def _anchor_xml(self, rid: str, cx: int, cy: int, name: str) -> str:
        self._picture_id += 1
        return (
            f'<wp:anchor {nsdecls("wp", "a", "pic", "r")} distT="0" distB="0" distL="0" distR="0" simplePos="0" '
            f'relativeHeight="0" behindDoc="1" locked="0" layoutInCell="1" allowOverlap="1">'
            f'<wp:simplePos x="0" y="0"/>'
            f'<wp:positionH relativeFrom="page"><wp:posOffset>0</wp:posOffset></wp:positionH>'
            f'<wp:positionV relativeFrom="page"><wp:posOffset>0</wp:posOffset></wp:positionV>'
            f'<wp:extent cx="{cx}" cy="{cy}"/><wp:effectExtent l="0" t="0" r="0" b="0"/><wp:wrapNone/>'
            f'<wp:docPr id="{self._picture_id}" name="{name}"/><wp:cNvGraphicFramePr/>'
            f'<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            f'<pic:pic><pic:nvPicPr><pic:cNvPr id="{self._picture_id}" name="{name}"/><pic:cNvPicPr/></pic:nvPicPr>'
            f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
            f"</pic:pic></a:graphicData></a:graphic></wp:anchor>"
        )

    def _build_cover(self, cover: CoverData) -> None:
        brand = self.brand
        geo = brand.cover
        body = self.doc.element.body
        body_sect = body.find(qn("w:sectPr"))
        page_w, page_h = self.doc.sections[-1].page_width, self.doc.sections[-1].page_height

        # Background anchored behind the text, at 0,0 of the page.
        first = self.doc.add_paragraph()
        _set_spacing_exact(first, 1)
        if brand.cover_background is not None and Path(brand.cover_background).is_file():
            run = first.add_run()
            rid, _image = self.doc.part.get_or_add_image(str(brand.cover_background))
            anchor = parse_xml(self._anchor_xml(rid, int(page_w), int(page_h), "cover_background"))
            drawing = OxmlElement("w:drawing")
            drawing.append(anchor)
            run._r.append(drawing)

        # Variable blocks as paragraphs with exact spacing computed from the bar geometry.
        y = 1.0  # points already consumed by the anchor paragraph
        heading_font = brand.heading().used
        if cover.synthetic:
            badge = self.doc.add_paragraph()
            _set_spacing_exact(badge, 18)
            badge.paragraph_format.left_indent = Pt(
                geo.left_pt("report_type") if "report_type" in geo.bars else 60
            )
            r = badge.add_run(SYNTHETIC_TAG)
            r.font.name = heading_font
            r.font.bold = True
            r.font.size = Pt(12)
            r.font.color.rgb = _rgb(brand.synthetic_badge_color)
            y += 18
        for name, bar in sorted(geo.bars.items(), key=lambda kv: kv[1].top):
            top_pt, height_pt = geo.top_pt(name), geo.height_pt(name)
            gap = top_pt - y
            if gap > 1:
                spacer = self.doc.add_paragraph()
                _set_spacing_exact(spacer, gap)
                spacer.add_run(" ").font.size = Pt(1)
                y += gap
            text = cover.bar_text(name)
            lines = text.split("\n")[: bar.lines] if bar.lines > 1 else [text]
            line_pt = height_pt / max(1, bar.lines)
            for line in lines:
                p = self.doc.add_paragraph()
                _set_spacing_exact(p, line_pt)
                p.paragraph_format.left_indent = Pt(geo.left_pt(name))
                r = p.add_run(line)
                r.font.name = heading_font
                r.font.bold = name != "recipient"
                r.font.size = Pt(max(8, round(line_pt * 0.55)))
                r.font.color.rgb = _rgb(geo.text_color)
                y += line_pt

        # Close the cover section: a clone of the body sectPr without header/footer references,
        # margins zero, no title page. Stored on the last cover paragraph.
        closer = self.doc.add_paragraph()
        _set_spacing_exact(closer, 1)
        cover_sect = copy.deepcopy(body_sect)
        for tag in ("w:headerReference", "w:footerReference", "w:titlePg", "w:pgNumType"):
            for el in cover_sect.findall(qn(tag)):
                cover_sect.remove(el)
        pg_mar = cover_sect.find(qn("w:pgMar"))
        if pg_mar is None:
            pg_mar = OxmlElement("w:pgMar")
            cover_sect.append(pg_mar)
        for attr in ("top", "right", "bottom", "left", "header", "footer", "gutter"):
            pg_mar.set(qn(f"w:{attr}"), "0")
        closer._p.get_or_add_pPr().append(cover_sect)

    # -- content -------------------------------------------------------------------------------------

    def _add_text_runs(self, paragraph: Paragraph, text: str, size: float | None = None) -> None:
        for piece in _PLACEHOLDER_SPLIT.split(text):
            if not piece:
                continue
            run = paragraph.add_run(piece)
            if size:
                run.font.size = Pt(size)
            if _PLACEHOLDER_SPLIT.fullmatch(piece):
                run.font.highlight_color = WD_COLOR_INDEX.YELLOW
                run.font.bold = True

    def title(self, text: str) -> Paragraph:
        p = self.doc.add_paragraph(style=self._style("title"))
        self._add_text_runs(p, text)
        return p

    def heading(self, text: str, level: int = 1, in_toc: bool = True) -> Paragraph:
        """A heading with its outline level on the paragraph. ``in_toc=False`` sends it to a
        level the TOC field excludes."""
        role = "heading1" if level == 1 else "heading2"
        p = self.doc.add_paragraph(style=self._style(role))
        self._add_text_runs(p, text)
        outline = OxmlElement("w:outlineLvl")
        outline.set(qn("w:val"), str(level - 1 if in_toc else 8))
        p._p.get_or_add_pPr().append(outline)
        return p

    def text(self, text: str, style_role: str = "body", italic: bool = False) -> Paragraph:
        p = self.doc.add_paragraph(style=self._style(style_role))
        self._add_text_runs(p, text)
        if italic:
            for r in p.runs:
                r.font.italic = True
        return p

    def caption(self, text: str) -> Paragraph:
        p = self.doc.add_paragraph(style=self._style("caption"))
        r = p.add_run(text)
        r.font.italic = True
        r.font.color.rgb = _rgb(self.brand.palette.muted)
        return p

    def bullets(self, items: list[str]) -> None:
        for item in items:
            p = self.doc.add_paragraph(style=self._style("body"))
            p.paragraph_format.left_indent = Cm(0.6)
            self._add_text_runs(p, f"• {item}")

    def page_break(self) -> None:
        self.doc.add_page_break()

    def toc(self, levels: str = "1-2") -> Paragraph:
        """Contents title (outside the index) + TOC field by outline level; updates on open."""
        self.heading(self.contents_title, level=1, in_toc=False)
        p = self.doc.add_paragraph(style=self._style("body"))
        instr = f'TOC \\o "{levels}" \\h \\z \\u'
        for tag, attrs, text in (
            ("w:fldChar", {"w:fldCharType": "begin"}, None),
            ("w:instrText", {"xml:space": "preserve"}, f" {instr} "),
            ("w:fldChar", {"w:fldCharType": "separate"}, None),
            (None, {}, "Índice: pulse F9 o abra el documento para actualizar."),
            ("w:fldChar", {"w:fldCharType": "end"}, None),
        ):
            run = p.add_run()
            if tag is None:
                run.text = text or ""
                continue
            el = OxmlElement(tag)
            for k, v in attrs.items():
                el.set(qn(k), v)
            if text:
                el.text = text
            run._r.append(el)
        self._enable_update_fields()
        return p

    def _enable_update_fields(self) -> None:
        settings = self.doc.settings.element
        for old in settings.findall(qn("w:updateFields")):
            settings.remove(old)
        uf = OxmlElement("w:updateFields")
        uf.set(qn("w:val"), "true")
        settings.append(uf)

    def table(
        self, frame: pd.DataFrame, caption: str | None = None, col_widths: list[float] | None = None
    ) -> Any:
        """Header in secondary with white text, alternate rows, soft borders, numbers right."""
        brand = self.brand
        table = self.doc.add_table(rows=1, cols=len(frame.columns))
        _table_borders(table, brand.palette.border)
        table.autofit = True
        for i, col in enumerate(frame.columns):
            cell = table.rows[0].cells[i]
            cell.text = ""
            run = cell.paragraphs[0].add_run(str(col))
            run.font.bold = True
            run.font.size = Pt(8.5)
            run.font.color.rgb = RGBColor(255, 255, 255)
            _shade(cell, brand.palette.secondary)
        for r_idx, row in enumerate(frame.itertuples(index=False)):
            cells = table.add_row().cells
            for c_idx, value in enumerate(row):
                text = (
                    ""
                    if value is None or (isinstance(value, float) and pd.isna(value))
                    else str(value)
                )
                cell = cells[c_idx]
                cell.text = ""
                para = cell.paragraphs[0]
                self._add_text_runs(para, text, size=8.5)
                if _NUMBER.match(text):
                    para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                if r_idx % 2 == 1:
                    _shade(cell, brand.palette.frame_bg)
            if r_idx == len(frame) - 1 and str(row[0]).lower().startswith("total"):
                for cell in cells:
                    for run in cell.paragraphs[0].runs:
                        run.font.bold = True
        if col_widths:
            for i, w in enumerate(col_widths):
                for cell in table.columns[i].cells:
                    cell.width = Cm(w)
        if caption:
            self.caption(caption)
        else:
            self.doc.add_paragraph(style=self._style("body"))
        return table

    def chart(self, path: Path, caption: str | None = None, max_width_cm: float = 16.0) -> None:
        width = min(int(self.usable_width), int(Cm(max_width_cm)))
        self.doc.add_picture(str(path), width=Emu(width))
        self.doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
        if caption:
            self.caption(caption)

    def kpi_row(self, kpis: list[tuple[str, str]]) -> None:
        """A row of big figures with their labels (borderless table, value in accent)."""
        table = self.doc.add_table(rows=2, cols=len(kpis))
        for i, (value, label) in enumerate(kpis):
            top, bottom = table.rows[0].cells[i], table.rows[1].cells[i]
            top.text, bottom.text = "", ""
            r = top.paragraphs[0].add_run(value)
            r.font.size = Pt(18)
            r.font.bold = True
            r.font.color.rgb = _rgb(self.brand.palette.accent)
            top.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
            r2 = bottom.paragraphs[0].add_run(label)
            r2.font.size = Pt(8)
            r2.font.color.rgb = _rgb(self.brand.palette.muted)
            bottom.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
            _shade(top, self.brand.palette.frame_bg)
            _shade(bottom, self.brand.palette.frame_bg)
        self.doc.add_paragraph(style=self._style("body"))

    def replace_header_text(self, mapping: dict[str, str]) -> int:
        """Replace fixed texts of the template header by walking its ``w:t`` (text boxes too)."""
        count = 0
        for section in self.doc.sections:
            for part in (section.header, section.first_page_header, section.footer):
                for t in part._element.iter(qn("w:t")):
                    for old, new in mapping.items():
                        if t.text and old in t.text:
                            t.text = t.text.replace(old, new)
                            count += 1
        return count

    def save(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.doc.save(str(path))
        return path
