"""Report catalogue: which sections, tables and charts each report type carries."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from .charts import ChartSpec
from .schema import load_yaml


@dataclass(frozen=True, slots=True)
class Section:
    id: str
    title: str
    blocks: tuple[str, ...]
    per_group: bool = False
    toc_level: int = 1


@dataclass(frozen=True, slots=True)
class ReportType:
    name: str
    title: str
    periods_on_axis: int
    sections: tuple[Section, ...]


@dataclass(slots=True)
class ReportCatalog:
    version: int
    texts: dict[str, str]
    charts: dict[str, ChartSpec]
    report_types: dict[str, ReportType]
    path: Path | None = None
    _chart_order: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path | str) -> ReportCatalog:
        raw = load_yaml(path)
        charts = {c["name"]: ChartSpec.from_dict(c) for c in raw.get("charts", [])}
        types: dict[str, ReportType] = {}
        for name, body in (raw.get("report_types") or {}).items():
            sections = tuple(
                Section(
                    id=str(s["id"]),
                    title=str(s.get("title", s["id"])),
                    blocks=tuple(str(b) for b in s.get("blocks", [])),
                    per_group=bool(s.get("per_group", False)),
                    toc_level=int(s.get("toc_level", 1)),
                )
                for s in body.get("sections", [])
            )
            types[str(name)] = ReportType(
                str(name),
                str(body.get("title", name)),
                int(body.get("periods_on_axis", 1)),
                sections,
            )
        return cls(
            version=int(raw.get("version", 1)),
            texts={str(k): str(v) for k, v in (raw.get("texts") or {}).items()},
            charts=charts,
            report_types=types,
            path=Path(path),
            _chart_order=list(charts),
        )

    def report_type(self, name: str) -> ReportType:
        try:
            return self.report_types[name]
        except KeyError as exc:
            raise KeyError(
                f"unknown report type {name!r}; known: {sorted(self.report_types)}"
            ) from exc

    def applicable_charts(self, report_type: str, df: pd.DataFrame) -> list[ChartSpec]:
        """Charts referenced by the report type's sections whose condition holds for ``df``."""
        rt = self.report_type(report_type)
        wanted: list[str] = []
        for section in rt.sections:
            for block in section.blocks:
                if block in self.charts and block not in wanted:
                    wanted.append(block)
        return [self.charts[name] for name in wanted if self.charts[name].applies(df)]

    def text(self, key: str, **kwargs: Any) -> str:
        return self.texts.get(key, "").format(**kwargs) if kwargs else self.texts.get(key, "")
