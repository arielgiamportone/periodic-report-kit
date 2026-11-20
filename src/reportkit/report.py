"""Composition: a report type + a loaded period -> elements -> Word (+ PDF).

The composer writes only the mechanical part (figures, methodology, tables, charts). Human
judgement enters through the comment store as a gap with hints. Nothing is ever overwritten:
every run gets its own versioned folder, and a period counts as delivered only with a PDF.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from .brand import BrandKit
from .catalog import ReportCatalog, Section
from .charts import Figure, draw
from .comments import CommentStore
from .loaders import warnings_summary
from .metrics import CLEAN_RATE, CONFORMITY_RATE, RATE_LABELS, format_rate, summarize
from .model import GROUP, PERIOD, Period, Warning
from .placeholders import PENDING_TOKEN, SYNTHETIC_TAG, find_placeholders
from .render_docx import BrandDocument, CoverData
from .render_pdf import PdfCover, compose_pdf
from .schema import GroupCatalog
from .tables import (
    by_dimension,
    incidents_by_category,
    presentable,
    summary_by_group,
    summary_by_period,
    top_items,
)

MONTHS_ES = [
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
]


def period_label(start: str, end: str) -> str:
    def one(p: str) -> str:
        y, m = p.split("-")
        return f"{MONTHS_ES[int(m) - 1]} {y}"

    return one(start) if start == end else f"{one(start)} – {one(end)}"


@dataclass(frozen=True, slots=True)
class ReportRequest:
    report_type: str
    start: str
    end: str
    recipient: str = "Cliente"
    reference: str = ""
    synthetic: bool = False
    pdf: bool = False


@dataclass(slots=True)
class Element:
    kind: str  # heading | text | table | chart | kpis | bullets
    text: str = ""
    level: int = 1
    in_toc: bool = True
    frame: pd.DataFrame | None = None
    caption: str | None = None
    path: Path | None = None
    kpis: list[tuple[str, str]] = field(default_factory=list)
    italic: bool = False


@dataclass(slots=True)
class ReportResult:
    out_dir: Path
    docx: Path
    pdf: Path | None
    warnings: list[Warning]
    hints: dict[str, dict[str, Any]]
    elements: list[Element]
    version: int

    @property
    def delivered(self) -> bool:
        return self.pdf is not None and self.pdf.is_file()

    @property
    def gaps(self) -> int:
        return sum(len(find_placeholders(e.text)) for e in self.elements if e.kind == "text")


def next_version_dir(out_root: Path, name: str) -> tuple[Path, int]:
    """``out_root/name/vNNN``: a fresh folder every run; existing deliverables are never touched."""
    base = Path(out_root) / name
    base.mkdir(parents=True, exist_ok=True)
    existing = [
        int(p.name[1:]) for p in base.iterdir() if p.is_dir() and re.fullmatch(r"v\d{3}", p.name)
    ]
    n = (max(existing) + 1) if existing else 1
    out = base / f"v{n:03d}"
    out.mkdir()
    return out, n


def _hints(df: pd.DataFrame, unit: str = "control") -> dict[str, Any]:
    s = summarize(df, unit)
    return {
        "controls": s.controls,
        "clean": s.clean,
        "incidents": s.fails,
        CONFORMITY_RATE: None if s.conformity_rate is None else round(s.conformity_rate, 4),
        CLEAN_RATE: None if s.clean_rate is None else round(s.clean_rate, 4),
    }


class Composer:
    def __init__(
        self,
        period: Period,
        request: ReportRequest,
        brand: BrandKit,
        catalog: ReportCatalog,
        groups: GroupCatalog,
        comments: CommentStore,
        out_dir: Path,
    ) -> None:
        self.period, self.request, self.brand, self.catalog, self.groups, self.comments = (
            period,
            request,
            brand,
            catalog,
            groups,
            comments,
        )
        self.out_dir = out_dir
        self.elements: list[Element] = []
        self.warnings: list[Warning] = list(period.warnings)
        self.hints: dict[str, dict[str, Any]] = {}
        self.chapter = 0
        self.figure_no = 0
        self.table_no = 0

    # -- helpers -------------------------------------------------------------------------------

    def heading(self, text: str, level: int = 1, in_toc: bool = True) -> None:
        if level == 1 and in_toc:
            self.chapter += 1
            text = f"{self.chapter}. {text}"
        self.elements.append(Element("heading", text, level=level, in_toc=in_toc))

    def text(self, text: str, italic: bool = False) -> None:
        self.elements.append(Element("text", text, italic=italic))

    def table(self, frame: pd.DataFrame, caption: str) -> None:
        self.table_no += 1
        self.elements.append(
            Element("table", frame=frame, caption=f"Tabla {self.table_no}. {caption}")
        )

    def chart(self, figure: Figure) -> None:
        self.figure_no += 1
        self.elements.append(
            Element("chart", path=figure.path, caption=f"Figura {self.figure_no}. {figure.caption}")
        )

    def comment(self, section: str, hints: dict[str, Any]) -> None:
        self.hints[section] = hints
        text, warnings = self.comments.render(section, hints)
        self.warnings.extend(warnings)
        self.text(text)

    # -- blocks ----------------------------------------------------------------------------------

    def _chart_block(self, name: str, df: pd.DataFrame, slug: str) -> bool:
        spec = self.catalog.charts[name]
        if spec.applies(df):
            self.chart(draw(spec, df, self.brand, self.out_dir / "charts", slug=slug))
            return True
        if spec.on_skip:
            self.text(self.catalog.text(spec.on_skip, **_hints(df)), italic=True)
        return False

    def block(
        self, name: str, df: pd.DataFrame, section: Section, group_code: str | None = None
    ) -> None:
        slug = group_code or section.id
        if name == "summary_table":
            self.table(
                presentable(summary_by_group(df, self.groups)),
                "Resumen por grupo. Las tasas declaran su base en la cabecera.",
            )
            for g in self.groups.groups:
                if df[df[GROUP] == g.code].empty and g.blocked_reason:
                    self.text(
                        f"{g.name}: {PENDING_TOKEN} {self.catalog.text('blocked_group_sentence', reason=g.blocked_reason)}",
                        italic=True,
                    )
        elif name == "summary_by_period_table":
            self.table(
                presentable(summary_by_period(df)), "Evolución mensual del conjunto del servicio."
            )
        elif name == "summary_comment":
            self.comment("summary", _hints(df))
        elif name == "methodology_text":
            for para in self.catalog.text("methodology").split("\n\n"):
                self.text(" ".join(para.split()))
            self.text(
                f"Tasas publicadas: {RATE_LABELS[CONFORMITY_RATE][0]} = {RATE_LABELS[CONFORMITY_RATE][1]}; {RATE_LABELS[CLEAN_RATE][0]} = {RATE_LABELS[CLEAN_RATE][1]}."
            )
        elif name == "group_kpis":
            assert group_code is not None
            g = self.groups.get(group_code)
            if df.empty:
                reason = g.blocked_reason or "sin registros en el periodo"
                self.text(
                    f"{PENDING_TOKEN} {self.catalog.text('blocked_group_sentence', reason=reason)}"
                )
                return
            s = summarize(df, g.unit)
            self.elements.append(
                Element(
                    "kpis",
                    kpis=[
                        (str(s.volume), "actuaciones"),
                        (str(s.controls), "controles"),
                        (str(s.fails), "incidencias"),
                        (format_rate(s.conformity_rate), RATE_LABELS[CONFORMITY_RATE][0]),
                        (format_rate(s.clean_rate), RATE_LABELS[CLEAN_RATE][0]),
                    ],
                )
            )
            self.text(
                f"En el periodo se realizaron {s.controls} controles sobre {s.elements} elementos ({s.items} ítems evaluados), con {s.fails} incidencias; {s.clean} controles sin incidencias."
            )
        elif name == "group_comment":
            assert group_code is not None
            if not df.empty:
                self.comment(f"group:{group_code}", _hints(df))
        elif name in self.catalog.charts:
            if not df.empty:
                self._chart_block(name, df, slug)
        elif name == "incidents_by_category_table":
            if not df.empty:
                self.table(presentable(incidents_by_category(df)), "Incidencias por categoría.")
        elif name == "top_items_table":
            if not df.empty and (df["result"] == "fail").any():
                self.table(presentable(top_items(df)), "Ítems con más incidencias.")
        elif name == "by_responsible_table":
            if (
                group_code
                and self.groups.get(group_code).has_responsible
                and not df.empty
                and "responsible" in df.columns
            ):
                self.table(
                    presentable(by_dimension(df, "responsible", "Responsable")),
                    "Resultados por responsable.",
                )
        elif name == "warnings_table":
            table = warnings_summary(self.warnings)
            if table.empty:
                self.text("Sin avisos de carga.")
            else:
                self.table(
                    table.rename(
                        columns={
                            "kind": "Tipo",
                            "file": "Fichero",
                            "rows": "Filas",
                            "controls": "Controles",
                            "message": "Mensaje",
                        }
                    ),
                    "Avisos emitidos durante la carga y la composición.",
                )
        else:
            raise KeyError(f"unknown block {name!r} in section {section.id!r}")

    def compose(self) -> list[Element]:
        rt = self.catalog.report_type(self.request.report_type)
        df = self.period.data
        for section in rt.sections:
            if section.per_group:
                for g in self.groups.groups:
                    slice_ = df[df[GROUP] == g.code]
                    self.heading(section.title.format(group=g.name), level=section.toc_level)
                    for block in section.blocks:
                        self.block(block, slice_, section, g.code)
            else:
                self.heading(section.title, level=section.toc_level, in_toc=section.toc_level <= 2)
                for block in section.blocks:
                    self.block(block, df, section)
        return self.elements


# --- Rendering of elements -------------------------------------------------------------------------


def elements_to_docx(
    elements: list[Element],
    brand: BrandKit,
    cover: CoverData,
    title: str,
    contents_title: str,
    out: Path,
) -> Path:
    doc = BrandDocument(brand, cover=cover, contents_title=contents_title)
    doc.replace_header_text({"Informe periódico de servicio": title})
    doc.title(title)
    doc.toc()
    for e in elements:
        if e.kind == "heading":
            doc.heading(e.text, level=e.level, in_toc=e.in_toc)
        elif e.kind == "text":
            doc.text(e.text, italic=e.italic)
        elif e.kind == "table" and e.frame is not None:
            doc.table(e.frame, caption=e.caption)
        elif e.kind == "chart" and e.path is not None:
            doc.chart(e.path, caption=e.caption)
        elif e.kind == "kpis":
            doc.kpi_row(e.kpis)
    return doc.save(out)


def _frame_html(frame: pd.DataFrame) -> str:
    head = "".join(f"<th>{html.escape(str(c))}</th>" for c in frame.columns)
    rows = []
    for i, row in enumerate(frame.itertuples(index=False)):
        cells = []
        for v in row:
            text = "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)
            cls = ' class="num"' if re.match(r"^\s*[-+]?[\d.,]+\s*%?\s*$", text) else ""
            cells.append(f"<td{cls}>{_gap_html(text)}</td>")
        alt = ' class="alt"' if i % 2 else ""
        rows.append(f"<tr{alt}>{''.join(cells)}</tr>")
    return f"<table><tr>{head}</tr>{''.join(rows)}</table>"


def _gap_html(text: str) -> str:
    return re.sub(r"(\[\[[^\]]+\]\])", r'<span class="gap">\1</span>', html.escape(text))


def elements_to_html(elements: list[Element], title: str) -> list[str]:
    parts = [f"<h1>{html.escape(title)}</h1>"]
    for e in elements:
        if e.kind == "heading":
            tag = "h1" if e.level == 1 else "h2"
            parts.append(f"<{tag}>{html.escape(e.text)}</{tag}>")
        elif e.kind == "text":
            style = ' style="font-style: italic;"' if e.italic else ""
            parts.append(f"<p{style}>{_gap_html(e.text)}</p>")
        elif e.kind == "table" and e.frame is not None:
            parts.append(
                _frame_html(e.frame) + f'<p class="caption">{html.escape(e.caption or "")}</p>'
            )
        elif e.kind == "chart" and e.path is not None:
            from .render_pdf import data_uri

            parts.append(
                f'<p style="text-align:center;"><img src="{data_uri(e.path)}" style="width: 150mm;"/></p><p class="caption">{html.escape(e.caption or "")}</p>'
            )
        elif e.kind == "kpis":
            cells = "".join(
                f'<td class="kpi"><div class="value">{html.escape(v)}</div><div class="label">{html.escape(lbl)}</div></td>'
                for v, lbl in e.kpis
            )
            parts.append(f"<table><tr>{cells}</tr></table>")
    return parts


def build_report(
    period: Period,
    request: ReportRequest,
    brand: BrandKit,
    catalog: ReportCatalog,
    groups: GroupCatalog,
    comments: CommentStore,
    out_root: Path,
) -> ReportResult:
    """Compose and render a report into a fresh versioned folder under ``out_root``."""
    rt = catalog.report_type(request.report_type)
    tag = f"_{SYNTHETIC_TAG.replace(' ', '-')}" if request.synthetic else ""
    name = f"{request.report_type}_{request.start}_{request.end}{tag}"
    out_dir, version = next_version_dir(out_root, name)
    composer = Composer(period, request, brand, catalog, groups, comments, out_dir)
    elements = composer.compose()
    label = period_label(request.start, request.end)
    title = f"{rt.title} · {label}"
    reference = request.reference or f"Ref. {request.start}" + (
        "" if request.start == request.end else f"–{request.end}"
    )
    cover = CoverData(
        rt.title, request.recipient, f"{reference}\n{label}", synthetic=request.synthetic
    )
    docx = elements_to_docx(
        elements,
        brand,
        cover,
        title,
        catalog.text("contents_title") or "Contenidos",
        out_dir / f"Informe_{name}.docx",
    )
    pdf: Path | None = None
    if request.pdf:
        pdf_cover = PdfCover(
            rt.title, request.recipient, f"{reference}\n{label}", synthetic=request.synthetic
        )
        pdf_bytes = compose_pdf(
            elements_to_html(elements, title), brand, cover=pdf_cover, header_text=title
        )
        pdf = out_dir / f"Informe_{name}.pdf"
        pdf.write_bytes(pdf_bytes)
    periods = (
        sorted(period.data[PERIOD].dropna().unique().tolist()) if not period.data.empty else []
    )
    composer.warnings.append(
        Warning(
            "report-built",
            f"{name} v{version}: {len(periods)} periods, {composer.chapter} chapters, {composer.figure_no} figures",
            details={"version": version},
        )
    )
    return ReportResult(
        out_dir=out_dir,
        docx=docx,
        pdf=pdf,
        warnings=composer.warnings,
        hints=composer.hints,
        elements=elements,
        version=version,
    )
