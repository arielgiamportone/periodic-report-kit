"""Contrast a loaded period against a delivered ``.docx``.

Two references are read from the delivered file: the chapter-1 summary table (strong, it was
computed) and the figures the prose of each chapter declares (weak). The mapping from chapter
title to group is explicit, never by substring: "Cafés" would match "Bares y cafés".
Controls are compared against the table, incidents against the prose, and prose != table is
flagged as an internal inconsistency of the delivered file. Any discrepancy is a non-zero exit:
our bug or their typo, both must be known.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
from docx import Document

from .metrics import summarize
from .model import GROUP, Period, Warning
from .schema import GroupCatalog, fold

_CONTROLS = re.compile(r"(\d[\d.]*)\s+controles", re.IGNORECASE)
_INCIDENTS = re.compile(r"(\d[\d.]*)\s+incidencias", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Discrepancy:
    group: str
    field: str  # controls | incidents
    expected: int | None  # from the model (None for prose vs table)
    found: int | None
    source: str  # table | prose | prose-vs-table
    message: str


@dataclass(slots=True)
class ContrastReport:
    delivered: Path
    version: str
    short_hash: str
    has_pdf: bool
    discrepancies: list[Discrepancy] = field(default_factory=list)
    warnings: list[Warning] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        return 1 if self.discrepancies else 0

    def summary_lines(self) -> list[str]:
        lines = [
            f"delivered: {self.delivered.name}  version: {self.version}  hash: {self.short_hash}  pdf: {'yes' if self.has_pdf else 'no'}"
        ]
        for d in self.discrepancies:
            lines.append(f"  [{d.source}] {d.group} {d.field}: {d.message}")
        for w in self.warnings:
            lines.append(f"  (aviso) {w.kind}: {w.message}")
        lines.append(
            "OK: sin discrepancias"
            if not self.discrepancies
            else f"{len(self.discrepancies)} discrepancia(s)"
        )
        return lines


def _to_int(text: str) -> int | None:
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def read_summary_table(docx_path: Path, group_header: str = "Grupo") -> pd.DataFrame | None:
    """The first table whose header starts with the group column: group, controls, incidents."""
    doc = Document(str(docx_path))
    for table in doc.tables:
        headers = [fold(c.text) for c in table.rows[0].cells]
        if not headers or headers[0] != fold(group_header):
            continue
        try:
            ctrl_idx = next(i for i, h in enumerate(headers) if h.startswith("control"))
            inc_idx = next(i for i, h in enumerate(headers) if h.startswith("incidencia"))
        except StopIteration:
            continue
        rows = []
        for row in list(table.rows)[1:]:
            cells = [c.text for c in row.cells]
            rows.append(
                {
                    "group": cells[0].strip(),
                    "controls": _to_int(cells[ctrl_idx]),
                    "incidents": _to_int(cells[inc_idx]),
                }
            )
        return pd.DataFrame(rows)
    return None


def read_prose_figures(
    docx_path: Path, title_to_group: dict[str, str]
) -> dict[str, dict[str, int | None]]:
    """Figures declared by the prose under each chapter heading, by group code.

    ``title_to_group`` maps the exact (folded) chapter title to a group code. Headings are
    matched after stripping a leading chapter number; never by substring.
    """
    doc = Document(str(docx_path))
    folded_map = {fold(re.sub(r"^\d+\.\s*", "", k)): v for k, v in title_to_group.items()}
    out: dict[str, dict[str, int | None]] = {}
    current: str | None = None
    for p in doc.paragraphs:
        key = fold(re.sub(r"^\d+\.\s*", "", p.text))
        if (
            key in folded_map
            and p.style is not None
            and ("heading" in p.style.name.lower() or "title" in p.style.name.lower())
        ):
            current = folded_map[key]
            out.setdefault(current, {"controls": None, "incidents": None})
            continue
        if current is None:
            continue
        m = _CONTROLS.search(p.text)
        if m and out[current]["controls"] is None:
            out[current]["controls"] = _to_int(m.group(1))
        m = _INCIDENTS.search(p.text)
        if m and out[current]["incidents"] is None:
            out[current]["incidents"] = _to_int(m.group(1))
    return out


def _version_of(path: Path) -> str:
    m = re.search(r"v(\d{3})", path.parent.name) or re.search(r"v(\d{3})", path.name)
    return m.group(1) if m else "?"


def contrast(
    period: Period,
    delivered: Path,
    groups: GroupCatalog,
    title_to_group: dict[str, str] | None = None,
) -> ContrastReport:
    delivered = Path(delivered)
    digest = hashlib.sha256(delivered.read_bytes()).hexdigest()[:8]
    report = ContrastReport(
        delivered=delivered,
        version=_version_of(delivered),
        short_hash=digest,
        has_pdf=delivered.with_suffix(".pdf").is_file(),
    )
    title_to_group = title_to_group or {g.name: g.code for g in groups.groups}
    df = period.data

    table = read_summary_table(delivered)
    if table is None:
        report.warnings.append(
            Warning("no-summary-table", "no summary table found in the delivered file")
        )
    prose = read_prose_figures(delivered, title_to_group)

    for g in groups.groups:
        slice_ = df[df[GROUP] == g.code]
        s = summarize(slice_, g.unit)
        expected_controls = s.controls if not slice_.empty else None
        expected_incidents = s.fails if not slice_.empty else None

        table_controls = table_incidents = None
        if table is not None:
            hit = table[table["group"].map(fold) == fold(g.name)]
            if not hit.empty:
                table_controls, table_incidents = hit.iloc[0]["controls"], hit.iloc[0]["incidents"]
                if expected_controls is not None and table_controls != expected_controls:
                    report.discrepancies.append(
                        Discrepancy(
                            g.code,
                            "controls",
                            expected_controls,
                            table_controls,
                            "table",
                            f"model {expected_controls} vs table {table_controls}",
                        )
                    )
        p = prose.get(g.code, {})
        prose_incidents = p.get("incidents")
        if (
            prose_incidents is not None
            and expected_incidents is not None
            and prose_incidents != expected_incidents
        ):
            report.discrepancies.append(
                Discrepancy(
                    g.code,
                    "incidents",
                    expected_incidents,
                    prose_incidents,
                    "prose",
                    f"model {expected_incidents} vs prose {prose_incidents}",
                )
            )
        if (
            prose_incidents is not None
            and table_incidents is not None
            and prose_incidents != table_incidents
        ):
            report.discrepancies.append(
                Discrepancy(
                    g.code,
                    "incidents",
                    None,
                    None,
                    "prose-vs-table",
                    f"prosa {prose_incidents} ≠ tabla {table_incidents}: incoherencia interna del entregado",
                )
            )
        if expected_controls is not None and table_controls is None and prose.get(g.code) is None:
            report.warnings.append(
                Warning("group-not-found", f"group {g.name!r} not found in the delivered file")
            )
    return report


def describe(report: ContrastReport) -> dict[str, Any]:
    return {
        "delivered": str(report.delivered),
        "version": report.version,
        "hash": report.short_hash,
        "has_pdf": report.has_pdf,
        "discrepancies": [d.__dict__ for d in report.discrepancies],
        "exit_code": report.exit_code,
    }
