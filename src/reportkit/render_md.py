"""Markdown -> .docx / .pptx with brand and visual blocks.

The ``.md`` is the source: ``---`` separates slides, the first ``#`` is the title, and visual
blocks are fenced with a tag (``kpi``, ``cards``, ``quad``, ``flow``, ``beforeafter``,
``decisions``, ``roadmap``, ``bcgmatrix``, ``porter``). One line per element; ``::`` separates
fields, ``|`` separates columns, ``;;`` separates items. The paragraph right before a block is
its lead, the one right after is its foot. Output is always regenerated; never edit it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn as pqn
from pptx.util import Inches, Pt

from .brand import BrandKit, hex_to_rgb, mix
from .render_docx import BrandDocument, CoverData, _shade

VISUAL_BLOCKS = (
    "kpi",
    "cards",
    "quad",
    "flow",
    "beforeafter",
    "decisions",
    "roadmap",
    "bcgmatrix",
    "porter",
)

# --- Parsing ----------------------------------------------------------------------------------------


@dataclass(slots=True)
class Block:
    kind: str
    text: str = ""
    level: int = 0
    items: list[Any] = field(default_factory=list)
    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    lead: str | None = None
    foot: str | None = None
    lang: str = ""


@dataclass(slots=True)
class Slide:
    title: str | None
    blocks: list[Block]


@dataclass(slots=True)
class MarkdownDoc:
    title: str
    slides: list[Slide]

    @property
    def blocks(self) -> list[Block]:
        return [b for s in self.slides for b in s.blocks]


_FENCE = re.compile(r"^```\s*([A-Za-z0-9_-]*)\s*$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_NUMBERED = re.compile(r"^(\s*)\d+[.)]\s+(.*)$")
_TABLE_SEP = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?$")


def _split_fields(line: str, sep: str) -> list[str]:
    return [p.strip() for p in line.split(sep)]


def _parse_table_row(line: str) -> list[str]:
    cells = line.strip().strip("|").split("|")
    return [c.strip() for c in cells]


def parse_visual(kind: str, lines: list[str]) -> list[Any]:
    lines = [ln.strip() for ln in lines if ln.strip()]
    if kind == "kpi":
        return [tuple(_split_fields(ln, "::")[:2]) for ln in lines]
    if kind in ("cards", "decisions", "porter"):
        return [tuple((_split_fields(ln, "::") + ["", ""])[:3]) for ln in lines]
    if kind == "quad":
        out = []
        for ln in lines:
            head, _, rest = ln.partition("|")
            out.append((head.strip(), [i.strip() for i in rest.split(";;") if i.strip()]))
        return out
    if kind == "flow":
        joined = " → ".join(lines)
        return [s.strip() for s in re.split(r"→|->", joined) if s.strip()]
    if kind == "beforeafter":
        return [tuple((_split_fields(ln, "|") + ["", ""])[:3]) for ln in lines]
    if kind == "roadmap":
        out = []
        for ln in lines:
            parts = _split_fields(ln, "|")
            lane, tasks = parts[0], []
            for task in parts[1:]:
                name, _, span = task.rpartition(":")
                m = re.match(r"\s*(\d{4})-Q([1-4])\s*-\s*(\d{4})-Q([1-4])\s*$", span)
                if not m or not name.strip():
                    raise ValueError(f"roadmap task must be 'name: YYYY-Qn-YYYY-Qn', got {task!r}")
                tasks.append(
                    (
                        name.strip(),
                        (int(m.group(1)), int(m.group(2))),
                        (int(m.group(3)), int(m.group(4))),
                    )
                )
            out.append((lane, tasks))
        return out
    if kind == "bcgmatrix":
        out = []
        for ln in lines:
            parts = _split_fields(ln, "::")
            label, nums = parts[0], [float(x) for x in parts[1:]]
            if len(nums) not in (2, 4) or not all(0 <= n <= 1 for n in nums):
                raise ValueError(
                    f"bcgmatrix needs 'label :: x :: y [:: x2 :: y2]' in 0-1, got {ln!r}"
                )
            out.append((label, nums[0], nums[1], (nums[2], nums[3]) if len(nums) == 4 else None))
        return out
    raise ValueError(f"unknown visual block {kind!r}")


def parse_markdown(text: str) -> MarkdownDoc:
    lines = text.splitlines()
    title = ""
    slides: list[Slide] = []
    current: list[Block] = []
    slide_title: str | None = None
    i = 0
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            current.append(Block("paragraph", " ".join(s.strip() for s in paragraph)))
            paragraph.clear()

    def close_slide() -> None:
        nonlocal current, slide_title
        flush_paragraph()
        if current or slide_title:
            slides.append(Slide(slide_title, current))
        current, slide_title = [], None

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        fence = _FENCE.match(stripped)
        if fence:
            flush_paragraph()
            lang = fence.group(1).lower()
            body: list[str] = []
            i += 1
            while i < len(lines) and not _FENCE.match(lines[i].strip()):
                body.append(lines[i])
                i += 1
            i += 1
            if lang in VISUAL_BLOCKS:
                current.append(Block("visual", lang, items=parse_visual(lang, body)))
            else:
                current.append(Block("code", "\n".join(body), lang=lang))
            continue
        if stripped == "---":
            close_slide()
            i += 1
            continue
        heading = _HEADING.match(stripped)
        if heading:
            flush_paragraph()
            level, text_ = len(heading.group(1)), heading.group(2).strip()
            if level == 1 and not title:
                title = text_
            if slide_title is None and level <= 2:
                slide_title = text_
            current.append(Block("heading", text_, level=level))
            i += 1
            continue
        if stripped.startswith(">"):
            flush_paragraph()
            quote: list[str] = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip().lstrip(">").strip())
                i += 1
            current.append(Block("quote", " ".join(quote)))
            continue
        if _BULLET.match(line) or _NUMBERED.match(line):
            flush_paragraph()
            numbered = bool(_NUMBERED.match(line))
            items: list[tuple[int, str]] = []
            while i < len(lines):
                m = (_NUMBERED if numbered else _BULLET).match(lines[i])
                if not m:
                    break
                items.append((len(m.group(1).replace("\t", "  ")) // 2, m.group(2).strip()))
                i += 1
            current.append(Block("numbered" if numbered else "bullets", items=items))
            continue
        if (
            stripped.startswith("|")
            and i + 1 < len(lines)
            and _TABLE_SEP.match(lines[i + 1].strip())
        ):
            flush_paragraph()
            headers = _parse_table_row(stripped)
            i += 2
            rows: list[list[str]] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(_parse_table_row(lines[i]))
                i += 1
            current.append(Block("table", headers=headers, rows=rows))
            continue
        if not stripped:
            flush_paragraph()
            i += 1
            continue
        paragraph.append(line)
        i += 1
    close_slide()

    # Lead / foot: the paragraph right before a visual block, the one right after.
    for slide in slides:
        blocks = slide.blocks
        keep: list[Block] = []
        k = 0
        while k < len(blocks):
            b = blocks[k]
            if b.kind == "visual":
                if keep and keep[-1].kind == "paragraph":
                    b.lead = keep.pop().text
                if k + 1 < len(blocks) and blocks[k + 1].kind == "paragraph":
                    b.foot = blocks[k + 1].text
                    k += 1
            keep.append(b)
            k += 1
        slide.blocks = keep
    return MarkdownDoc(
        title=title or (slides[0].title if slides and slides[0].title else "Documento"),
        slides=slides,
    )


# --- Word ---------------------------------------------------------------------------------------------

_CHIP_KEYWORDS = (
    ("producci", "ok"),
    ("hecho", "ok"),
    ("listo", "ok"),
    ("curso", "warn"),
    ("progreso", "warn"),
    ("crític", "fail"),
    ("bloquead", "fail"),
    ("riesgo", "fail"),
)


def chip_colour(brand: BrandKit, chip: str) -> str:
    low = chip.lower()
    for key, role in _CHIP_KEYWORDS:
        if key in low:
            return getattr(brand.semantic, role)
    return brand.palette.muted


def _quarters(items: list[Any]) -> list[tuple[int, int]]:
    starts = [t[1] for _, tasks in items for t in tasks]
    ends = [t[2] for _, tasks in items for t in tasks]
    if not starts:
        return []
    (y0, q0), (y1, q1) = min(starts), max(ends)
    out, y, q = [], y0, q0
    while (y, q) <= (y1, q1):
        out.append((y, q))
        q += 1
        if q == 5:
            y, q = y + 1, 1
    return out


def _docx_visual(doc: BrandDocument, block: Block) -> None:
    kind, items = block.text, block.items
    if block.lead:
        doc.text(block.lead)
    if kind == "kpi":
        doc.kpi_row([(v, lbl) for v, lbl in items])
    elif kind == "cards":
        cols = 3 if len(items) > 4 else 2
        rows = [items[i : i + cols] for i in range(0, len(items), cols)]
        frame = pd.DataFrame(
            [
                [f"{t}\n{s}\n[{c}]" if c else f"{t}\n{s}" for t, s, c in r] + [""] * (cols - len(r))
                for r in rows
            ],
            columns=[f"Tarjeta {i + 1}" for i in range(cols)],
        )
        doc.table(frame)
    elif kind == "quad":
        cells = [f"{h}\n" + "\n".join(f"• {x}" for x in lst) for h, lst in items[:4]]
        cells += [""] * (4 - len(cells))
        doc.table(
            pd.DataFrame(
                [cells[:2], cells[2:]],
                columns=[items[0][0] if items else "", items[1][0] if len(items) > 1 else ""],
            )
        )
    elif kind == "flow":
        doc.table(pd.DataFrame([items], columns=[f"Paso {i + 1}" for i in range(len(items))]))
        doc.text(" → ".join(items), italic=True)
    elif kind == "beforeafter":
        table = doc.table(pd.DataFrame(items, columns=["Dimensión", "ANTES", "DESPUÉS"]))
        sem, page = doc.brand.semantic, doc.brand.palette.page_bg
        for row in list(table.rows)[1:]:
            _shade(row.cells[1], mix(sem.fail, page, 0.8))
            _shade(row.cells[2], mix(sem.ok, page, 0.8))
    elif kind == "decisions":
        for n, (t, d, _c) in enumerate(items, 1):
            doc.text(f"{n}. {t} — {d}")
    elif kind == "roadmap":
        quarters = _quarters(items)
        headers = ["Carril"] + [f"{y}-Q{q}" for y, q in quarters]
        rows = []
        for lane, tasks in items:
            row = [lane]
            for yq in quarters:
                row.append(", ".join(t[0] for t in tasks if t[1] <= yq <= t[2]))
            rows.append(row)
        doc.table(pd.DataFrame(rows, columns=headers))
    elif kind == "bcgmatrix":
        quad = {("hi", "lo"): [], ("hi", "hi"): [], ("lo", "lo"): [], ("lo", "hi"): []}
        for label, x, y, traj in items:
            key = ("hi" if y >= 0.5 else "lo", "hi" if x >= 0.5 else "lo")
            quad[key].append(label + (f" → ({traj[0]:.1f}, {traj[1]:.1f})" if traj else ""))
        doc.table(
            pd.DataFrame(
                [
                    [", ".join(quad[("hi", "lo")]), ", ".join(quad[("hi", "hi")])],
                    [", ".join(quad[("lo", "lo")]), ", ".join(quad[("lo", "hi")])],
                ],
                columns=["x bajo", "x alto"],
            )
        )
    elif kind == "porter":
        pos = {p.lower(): f"{t}\n{d}" for p, t, d in items}
        grid = [
            ["", pos.get("arriba", ""), ""],
            [pos.get("izquierda", ""), pos.get("centro", ""), pos.get("derecha", "")],
            ["", pos.get("abajo", ""), ""],
        ]
        doc.table(pd.DataFrame(grid, columns=["", " ", "  "]))
    if block.foot:
        doc.caption(block.foot)


def md_to_docx(md_path: Path, brand: BrandKit, out: Path, cover: CoverData | None = None) -> Path:
    doc_md = parse_markdown(Path(md_path).read_text(encoding="utf-8"))
    doc = BrandDocument(brand, cover=cover)
    doc.title(doc_md.title)
    first = True
    for slide in doc_md.slides:
        for block in slide.blocks:
            if block.kind == "heading":
                if block.level == 1 and first:
                    first = False
                    continue
                doc.heading(block.text, level=1 if block.level <= 2 else 2)
            elif block.kind == "paragraph":
                doc.text(block.text)
            elif block.kind == "bullets":
                doc.bullets([("    " * lvl) + t for lvl, t in block.items])
            elif block.kind == "numbered":
                doc.bullets([f"{n}. {t}" for n, (_lvl, t) in enumerate(block.items, 1)])
            elif block.kind == "quote":
                doc.text(f"«{block.text}»", italic=True)
            elif block.kind == "table":
                doc.table(pd.DataFrame(block.rows, columns=block.headers))
            elif block.kind == "code":
                p = doc.text(block.text)
                for r in p.runs:
                    r.font.name = "Courier New"
            elif block.kind == "visual":
                _docx_visual(doc, block)
        first = False
    return doc.save(out)


# --- PowerPoint ---------------------------------------------------------------------------------------

SLIDE_W, SLIDE_H = Inches(13.333), Inches(7.5)
MARGIN = Inches(0.6)


def _rgb(value: str) -> RGBColor:
    return RGBColor(*hex_to_rgb(value))


class _Deck:
    def __init__(self, brand: BrandKit) -> None:
        self.brand = brand
        self.prs = Presentation()
        self.prs.slide_width, self.prs.slide_height = SLIDE_W, SLIDE_H
        self.blank = self.prs.slide_layouts[6]
        self.heading_font = brand.heading().used
        self.body_font = brand.body().used
        self.accents = [brand.palette.primary, brand.palette.secondary, brand.palette.accent]

    def new_slide(self, title: str | None) -> Any:
        slide = self.prs.slides.add_slide(self.blank)
        band = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, SLIDE_W, Inches(0.18))
        self._fill(band, self.brand.palette.primary)
        if title:
            tb = slide.shapes.add_textbox(MARGIN, Inches(0.35), SLIDE_W - 2 * MARGIN, Inches(0.8))
            self._text(tb, title, 28, self.brand.palette.primary, bold=True, font=self.heading_font)
        return slide

    def _fill(self, shape: Any, colour: str, line: str | None = None) -> None:
        shape.fill.solid()
        shape.fill.fore_color.rgb = _rgb(colour)
        if line is None:
            shape.line.fill.background()
        else:
            shape.line.color.rgb = _rgb(line)
            shape.line.width = Pt(0.75)
        shape.shadow.inherit = False

    def _text(
        self,
        shape: Any,
        text: str,
        size: float,
        colour: str,
        bold: bool = False,
        font: str | None = None,
        align: PP_ALIGN = PP_ALIGN.LEFT,
        anchor: MSO_ANCHOR | None = None,
    ) -> None:
        tf = shape.text_frame
        tf.word_wrap = True
        if anchor is not None:
            tf.vertical_anchor = anchor
        lines = text.split("\n")
        for n, line in enumerate(lines):
            p = tf.paragraphs[0] if n == 0 else tf.add_paragraph()
            p.alignment = align
            run = p.add_run()
            run.text = line
            run.font.size = Pt(size)
            run.font.bold = bold
            run.font.name = font or self.body_font
            run.font.color.rgb = _rgb(colour)

    def box(
        self,
        slide: Any,
        x: int,
        y: int,
        w: int,
        h: int,
        fill: str,
        text: str = "",
        size: float = 12,
        colour: str = "#FFFFFF",
        bold: bool = False,
        shape: MSO_SHAPE = MSO_SHAPE.ROUNDED_RECTANGLE,
        align: PP_ALIGN = PP_ALIGN.CENTER,
        line: str | None = None,
    ) -> Any:
        s = slide.shapes.add_shape(shape, x, y, w, h)
        self._fill(s, fill, line)
        if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
            s.adjustments[0] = 0.08
        if text:
            self._text(s, text, size, colour, bold=bold, align=align, anchor=MSO_ANCHOR.MIDDLE)
        return s

    def label(
        self,
        slide: Any,
        x: int,
        y: int,
        w: int,
        h: int,
        text: str,
        size: float = 12,
        colour: str | None = None,
        bold: bool = False,
        align: PP_ALIGN = PP_ALIGN.LEFT,
    ) -> Any:
        tb = slide.shapes.add_textbox(x, y, w, h)
        self._text(tb, text, size, colour or self.brand.palette.ink, bold=bold, align=align)
        return tb

    def arrow(
        self, slide: Any, x1: int, y1: int, x2: int, y2: int, colour: str | None = None
    ) -> Any:
        c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, x1, y1, x2, y2)
        c.line.color.rgb = _rgb(colour or self.brand.palette.muted)
        c.line.width = Pt(1.75)
        ln = c.line._get_or_add_ln()
        tail = ln.makeelement(pqn("a:tailEnd"), {"type": "triangle", "w": "med", "len": "med"})
        ln.append(tail)
        return c

    def table(self, slide: Any, headers: list[str], rows: list[list[str]], y: int) -> Any:
        n_rows, n_cols = len(rows) + 1, len(headers)
        shape = slide.shapes.add_table(
            n_rows, n_cols, MARGIN, y, SLIDE_W - 2 * MARGIN, Inches(0.4) * n_rows
        )
        table = shape.table
        for c, h in enumerate(headers):
            cell = table.cell(0, c)
            cell.text = ""
            cell.fill.solid()
            cell.fill.fore_color.rgb = _rgb(self.brand.palette.secondary)
            self._text(cell, h, 12, "#FFFFFF", bold=True)
        for r, row in enumerate(rows, 1):
            for c in range(n_cols):
                cell = table.cell(r, c)
                cell.text = ""
                cell.fill.solid()
                cell.fill.fore_color.rgb = _rgb(
                    self.brand.palette.frame_bg if r % 2 == 0 else self.brand.palette.page_bg
                )
                self._text(cell, row[c] if c < len(row) else "", 11, self.brand.palette.ink)
        return shape

    def save(self, out: Path) -> Path:
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        self.prs.save(str(out))
        return out


def _pptx_visual(deck: _Deck, slide: Any, block: Block, y: int) -> int:
    """Draw a visual block starting at ``y``; return the y after it."""
    b, p, sem = deck.brand, deck.brand.palette, deck.brand.semantic
    kind, items = block.text, block.items
    width = SLIDE_W - 2 * MARGIN
    if block.lead:
        deck.label(slide, MARGIN, y, width, Inches(0.5), block.lead, 13, p.muted)
        y += Inches(0.55)
    if kind == "kpi":
        n = max(1, len(items))
        gap = Inches(0.25)
        w = int((width - gap * (n - 1)) / n)
        for i, (value, lbl) in enumerate(items):
            x = MARGIN + i * (w + gap)
            card = deck.box(slide, x, y, w, Inches(1.6), p.frame_bg)
            deck.box(
                slide,
                x,
                y,
                Inches(0.12),
                Inches(1.6),
                deck.accents[i % 3],
                shape=MSO_SHAPE.RECTANGLE,
            )
            deck.label(
                slide,
                x + Inches(0.25),
                y + Inches(0.15),
                w - Inches(0.3),
                Inches(0.9),
                value,
                30,
                p.accent,
                bold=True,
            )
            deck.label(
                slide,
                x + Inches(0.25),
                y + Inches(1.0),
                w - Inches(0.3),
                Inches(0.5),
                lbl,
                12,
                p.muted,
            )
            del card
        y += Inches(1.8)
    elif kind == "cards":
        cols = 3 if len(items) > 4 else max(1, min(2, len(items)))
        gap = Inches(0.25)
        w = int((width - gap * (cols - 1)) / cols)
        h = Inches(1.5)
        for i, (title, subtitle, chip) in enumerate(items):
            r, c = divmod(i, cols)
            x, yy = MARGIN + c * (w + gap), y + r * (h + gap)
            deck.box(slide, x, yy, w, h, p.frame_bg)
            deck.label(
                slide,
                x + Inches(0.2),
                yy + Inches(0.1),
                w - Inches(0.4),
                Inches(0.5),
                title,
                15,
                p.primary,
                bold=True,
            )
            deck.label(
                slide,
                x + Inches(0.2),
                yy + Inches(0.55),
                w - Inches(0.4),
                Inches(0.5),
                subtitle,
                11,
                p.ink,
            )
            if chip:
                deck.box(
                    slide,
                    x + Inches(0.2),
                    yy + h - Inches(0.45),
                    Inches(1.6),
                    Inches(0.3),
                    chip_colour(b, chip),
                    chip,
                    9,
                    bold=True,
                )
        y += (len(items) + cols - 1) // cols * (h + gap)
    elif kind == "quad":
        gap = Inches(0.2)
        w, h = int((width - gap) / 2), Inches(2.3)
        for i, (head, lst) in enumerate(items[:4]):
            r, c = divmod(i, 2)
            x, yy = MARGIN + c * (w + gap), y + r * (h + gap)
            deck.box(
                slide,
                x,
                yy,
                w,
                Inches(0.45),
                deck.accents[i % 3],
                head,
                13,
                bold=True,
                shape=MSO_SHAPE.RECTANGLE,
            )
            deck.box(
                slide,
                x,
                yy + Inches(0.45),
                w,
                h - Inches(0.45),
                p.frame_bg,
                "\n".join(f"• {t}" for t in lst),
                11,
                p.ink,
                shape=MSO_SHAPE.RECTANGLE,
                align=PP_ALIGN.LEFT,
            )
        y += 2 * (h + gap)
    elif kind == "flow":
        n = max(1, len(items))
        arrow_w = Inches(0.45)
        w = int((width - arrow_w * (n - 1)) / n)
        for i, step in enumerate(items):
            x = MARGIN + i * (w + arrow_w)
            deck.box(slide, x, y, w, Inches(1.1), deck.accents[i % 3], step, 12, bold=True)
            if i < n - 1:
                deck.box(
                    slide,
                    x + w + Inches(0.05),
                    y + Inches(0.35),
                    arrow_w - Inches(0.1),
                    Inches(0.4),
                    p.muted,
                    shape=MSO_SHAPE.RIGHT_ARROW,
                )
        y += Inches(1.3)
    elif kind == "beforeafter":
        col_w = int(width / 3)
        for i, (dim, before, after) in enumerate(items):
            yy = y + i * Inches(0.75)
            deck.box(
                slide,
                MARGIN,
                yy,
                col_w - Inches(0.1),
                Inches(0.65),
                p.frame_bg,
                dim,
                12,
                p.ink,
                bold=True,
                shape=MSO_SHAPE.RECTANGLE,
            )
            deck.box(
                slide,
                MARGIN + col_w,
                yy,
                col_w - Inches(0.5),
                Inches(0.65),
                mix(sem.fail, p.page_bg, 0.8),
                before,
                11,
                p.ink,
                shape=MSO_SHAPE.RECTANGLE,
            )
            deck.box(
                slide,
                MARGIN + col_w * 2 - Inches(0.45),
                yy + Inches(0.17),
                Inches(0.4),
                Inches(0.3),
                p.muted,
                shape=MSO_SHAPE.RIGHT_ARROW,
            )
            deck.box(
                slide,
                MARGIN + col_w * 2,
                yy,
                col_w - Inches(0.1),
                Inches(0.65),
                mix(sem.ok, p.page_bg, 0.8),
                after,
                11,
                p.ink,
                shape=MSO_SHAPE.RECTANGLE,
            )
        y += len(items) * Inches(0.75)
    elif kind == "decisions":
        for i, (title, desc, _c) in enumerate(items):
            yy = y + i * Inches(0.95)
            deck.box(slide, MARGIN, yy, width, Inches(0.85), p.frame_bg)
            deck.box(
                slide,
                MARGIN + Inches(0.15),
                yy + Inches(0.17),
                Inches(0.5),
                Inches(0.5),
                deck.accents[i % 3],
                str(i + 1),
                14,
                bold=True,
                shape=MSO_SHAPE.OVAL,
            )
            deck.label(
                slide,
                MARGIN + Inches(0.8),
                yy + Inches(0.05),
                width - Inches(1),
                Inches(0.4),
                title,
                14,
                p.primary,
                bold=True,
            )
            deck.label(
                slide,
                MARGIN + Inches(0.8),
                yy + Inches(0.4),
                width - Inches(1),
                Inches(0.4),
                desc,
                11,
                p.ink,
            )
        y += len(items) * Inches(0.95)
    elif kind == "roadmap":
        quarters = _quarters(items)
        lane_w = Inches(2.0)
        grid_w = width - lane_w
        qw = int(grid_w / max(1, len(quarters)))
        years = sorted({yq[0] for yq in quarters})
        for yr in years:
            idx = [i for i, yq in enumerate(quarters) if yq[0] == yr]
            deck.box(
                slide,
                MARGIN + lane_w + idx[0] * qw,
                y,
                qw * len(idx) - Inches(0.03),
                Inches(0.35),
                p.primary,
                str(yr),
                11,
                bold=True,
                shape=MSO_SHAPE.RECTANGLE,
            )
        for i, (_yr, q) in enumerate(quarters):
            deck.box(
                slide,
                MARGIN + lane_w + i * qw,
                y + Inches(0.38),
                qw - Inches(0.03),
                Inches(0.3),
                p.secondary,
                f"Q{q}",
                10,
                shape=MSO_SHAPE.RECTANGLE,
            )
        yy = y + Inches(0.8)
        for li, (lane, tasks) in enumerate(items):
            deck.box(
                slide,
                MARGIN,
                yy,
                lane_w - Inches(0.1),
                Inches(0.5),
                p.frame_bg,
                lane,
                11,
                p.ink,
                bold=True,
                shape=MSO_SHAPE.RECTANGLE,
            )
            for ti, (name, start, end) in enumerate(tasks):
                s_idx, e_idx = quarters.index(start), quarters.index(end)
                deck.box(
                    slide,
                    MARGIN + lane_w + s_idx * qw,
                    yy + Inches(0.08),
                    qw * (e_idx - s_idx + 1) - Inches(0.05),
                    Inches(0.34),
                    deck.accents[(li + ti) % 3],
                    name,
                    9,
                    bold=True,
                )
            yy += Inches(0.6)
        y = yy
    elif kind == "bcgmatrix":
        size = Inches(4.2)
        x0 = int((SLIDE_W - size) / 2)
        half = int(size / 2)
        tints = [
            mix(p.secondary, p.page_bg, 0.85),
            mix(p.primary, p.page_bg, 0.85),
            mix(p.muted, p.page_bg, 0.85),
            mix(p.accent, p.page_bg, 0.85),
        ]
        for i, (r, c) in enumerate(((0, 0), (0, 1), (1, 0), (1, 1))):
            deck.box(
                slide,
                x0 + c * half,
                y + r * half,
                half - Inches(0.03),
                half - Inches(0.03),
                tints[i],
                shape=MSO_SHAPE.RECTANGLE,
                line=p.border,
            )
        for label, x, yv, traj in items:
            px, py = x0 + int(x * size), y + int((1 - yv) * size)
            deck.box(
                slide,
                px - Inches(0.12),
                py - Inches(0.12),
                Inches(0.24),
                Inches(0.24),
                p.accent,
                shape=MSO_SHAPE.OVAL,
            )
            deck.label(
                slide,
                px + Inches(0.1),
                py - Inches(0.2),
                Inches(2.0),
                Inches(0.4),
                label,
                10,
                p.ink,
                bold=True,
            )
            if traj:
                tx, ty = x0 + int(traj[0] * size), y + int((1 - traj[1]) * size)
                deck.arrow(slide, px, py, tx, ty, p.secondary)
        y += size + Inches(0.2)
    elif kind == "porter":
        pos = {p_.lower(): (t, d) for p_, t, d in items}
        bw, bh = Inches(3.2), Inches(1.3)
        cx = int((SLIDE_W - bw) / 2)
        coords = {
            "arriba": (cx, y),
            "izquierda": (cx - bw - Inches(0.6), y + bh + Inches(0.4)),
            "centro": (cx, y + bh + Inches(0.4)),
            "derecha": (cx + bw + Inches(0.6), y + bh + Inches(0.4)),
            "abajo": (cx, y + 2 * (bh + Inches(0.4))),
        }
        for key, (x, yy) in coords.items():
            t, d = pos.get(key, ("", ""))
            fill = p.primary if key == "centro" else p.frame_bg
            colour = "#FFFFFF" if key == "centro" else p.ink
            deck.box(slide, x, yy, bw, bh, fill, f"{t}\n{d}", 11, colour, bold=key == "centro")
        c = coords["centro"]
        ccx, ccy = c[0] + int(bw / 2), c[1] + int(bh / 2)
        for key in ("arriba", "izquierda", "derecha", "abajo"):
            x, yy = coords[key]
            deck.arrow(slide, x + int(bw / 2), yy + int(bh / 2), ccx, ccy)
        y += 3 * (bh + Inches(0.4))
    if block.foot:
        deck.label(slide, MARGIN, y, width, Inches(0.4), block.foot, 10, p.muted)
        y += Inches(0.45)
    return y


def md_to_pptx(md_path: Path, brand: BrandKit, out: Path) -> Path:
    doc_md = parse_markdown(Path(md_path).read_text(encoding="utf-8"))
    deck = _Deck(brand)
    p = brand.palette
    # Title slide.
    title_slide = deck.new_slide(None)
    deck.box(title_slide, 0, 0, SLIDE_W, SLIDE_H, p.primary, shape=MSO_SHAPE.RECTANGLE)
    deck.label(
        title_slide,
        MARGIN,
        Inches(2.6),
        SLIDE_W - 2 * MARGIN,
        Inches(1.4),
        doc_md.title,
        40,
        "#FFFFFF",
        bold=True,
    )
    deck.label(
        title_slide,
        MARGIN,
        Inches(4.0),
        SLIDE_W - 2 * MARGIN,
        Inches(0.6),
        brand.name,
        18,
        p.frame_bg,
    )
    for slide_md in doc_md.slides:
        blocks = [
            b for b in slide_md.blocks if not (b.kind == "heading" and b.text == slide_md.title)
        ]
        if not blocks and slide_md.title == doc_md.title:
            continue
        slide = deck.new_slide(slide_md.title)
        y = Inches(1.3)
        width = SLIDE_W - 2 * MARGIN
        for block in blocks:
            if block.kind == "heading":
                deck.label(
                    slide, MARGIN, y, width, Inches(0.5), block.text, 18, p.secondary, bold=True
                )
                y += Inches(0.55)
            elif block.kind == "paragraph":
                deck.label(slide, MARGIN, y, width, Inches(0.8), block.text, 14)
                y += Inches(0.3) + Inches(0.3) * max(1, len(block.text) // 110 + 1)
            elif block.kind in ("bullets", "numbered"):
                lines = [
                    ("    " * lvl) + (f"{n}. {t}" if block.kind == "numbered" else f"• {t}")
                    for n, (lvl, t) in enumerate(block.items, 1)
                ]
                deck.label(slide, MARGIN, y, width, Inches(0.35) * len(lines), "\n".join(lines), 14)
                y += Inches(0.35) * len(lines) + Inches(0.1)
            elif block.kind == "quote":
                deck.box(
                    slide,
                    MARGIN,
                    y,
                    width,
                    Inches(0.9),
                    p.frame_bg,
                    f"«{block.text}»",
                    14,
                    p.ink,
                    shape=MSO_SHAPE.RECTANGLE,
                    align=PP_ALIGN.LEFT,
                )
                y += Inches(1.0)
            elif block.kind == "table":
                deck.table(slide, block.headers, block.rows, y)
                y += Inches(0.4) * (len(block.rows) + 1) + Inches(0.2)
            elif block.kind == "code":
                tb = deck.label(slide, MARGIN, y, width, Inches(1.5), block.text, 11, p.ink)
                for para in tb.text_frame.paragraphs:
                    for run in para.runs:
                        run.font.name = "Courier New"
                y += Inches(1.6)
            elif block.kind == "visual":
                y = _pptx_visual(deck, slide, block, y)
    return deck.save(out)


def shape_count(pptx_path: Path) -> list[int]:
    prs = Presentation(str(pptx_path))
    return [len(s.shapes) for s in prs.slides]
