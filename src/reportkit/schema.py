"""Declared configuration: data schema, group catalogue and item catalogue (YAML)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .model import DEFAULT_UNIT


def fold(text: Any) -> str:
    """Accent-insensitive, case-insensitive, whitespace-collapsed key for matching labels."""
    if text is None:
        return ""
    s = unicodedata.normalize("NFKD", str(text))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"\s+", " ", s.replace(" ", " ")).strip().lower()
    return s


def load_yaml(path: Path | str) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top level must be a mapping")
    return data


# --- Data schema ---------------------------------------------------------------------------


@dataclass(slots=True)
class DataSchema:
    """What the raw spreadsheets look like. Loaders translate; they never interpret."""

    version: int
    timezone: str
    source_timezone: str | None
    file_patterns: list[str]
    skip_name_fragments: list[str]
    detail_sheets: list[str]
    forbidden_sheets: list[str]
    columns: dict[str, list[str]]  # canonical -> accepted raw headers
    dimensions: dict[str, list[str]]  # dimension name -> accepted raw headers
    result_values: dict[str, list[str]]  # ok/fail/na -> raw values
    default_unit: str = DEFAULT_UNIT
    unit_values: dict[str, list[str]] = field(default_factory=dict)
    separator_row_pattern: str | None = None
    io_retries: int = 3
    path: Path | None = None

    @classmethod
    def load(cls, path: Path | str) -> DataSchema:
        raw = load_yaml(path)
        required = ("columns", "result_values", "detail_sheets")
        missing = [k for k in required if k not in raw]
        if missing:
            raise ValueError(f"{path}: missing keys {missing}")
        return cls(
            version=int(raw.get("version", 1)),
            timezone=str(raw.get("timezone", "UTC")),
            source_timezone=raw.get("source_timezone"),
            file_patterns=list(raw.get("file_patterns", [])),
            skip_name_fragments=[fold(x) for x in raw.get("skip_name_fragments", [])],
            detail_sheets=list(raw["detail_sheets"]),
            forbidden_sheets=list(raw.get("forbidden_sheets", [])),
            columns={k: list(v) for k, v in raw["columns"].items()},
            dimensions={k: list(v) for k, v in (raw.get("dimensions") or {}).items()},
            result_values={k: list(v) for k, v in raw["result_values"].items()},
            default_unit=str(raw.get("default_unit", DEFAULT_UNIT)),
            unit_values={k: list(v) for k, v in (raw.get("unit_values") or {}).items()},
            separator_row_pattern=raw.get("separator_row_pattern"),
            io_retries=int(raw.get("io_retries", 3)),
            path=Path(path),
        )

    # -- lookups ------------------------------------------------------------------------

    def header_map(self) -> dict[str, str]:
        """Folded raw header -> canonical column (core columns and dimensions)."""
        out: dict[str, str] = {}
        for canonical, variants in {**self.columns, **self.dimensions}.items():
            for v in variants:
                out[fold(v)] = canonical
        return out

    def result_map(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for canonical, variants in self.result_values.items():
            for v in variants:
                out[fold(v)] = canonical
        return out

    def unit_map(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for canonical, variants in self.unit_values.items():
            for v in variants:
                out[fold(v)] = canonical
        return out

    def is_detail_sheet(self, name: str) -> bool:
        return fold(name) in {fold(s) for s in self.detail_sheets}

    def is_forbidden_sheet(self, name: str) -> bool:
        return fold(name) in {fold(s) for s in self.forbidden_sheets}


# --- Group catalogue -----------------------------------------------------------------------


@dataclass(slots=True)
class Group:
    code: str
    name: str
    labels: list[str] = field(default_factory=list)
    has_responsible: bool = False
    unit: str = DEFAULT_UNIT
    blocked_reason: str | None = None

    def matches(self, label: Any) -> bool:
        f = fold(label)
        return f == fold(self.code) or f == fold(self.name) or f in {fold(x) for x in self.labels}


@dataclass(slots=True)
class GroupCatalog:
    groups: list[Group]
    element_reassignments: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | str) -> GroupCatalog:
        raw = load_yaml(path)
        groups = [
            Group(
                code=str(g["code"]),
                name=str(g["name"]),
                labels=[str(x) for x in g.get("labels", [])],
                has_responsible=bool(g.get("has_responsible", False)),
                unit=str(g.get("unit", DEFAULT_UNIT)),
                blocked_reason=g.get("blocked_reason"),
            )
            for g in raw.get("groups", [])
        ]
        reassign = {str(k): str(v) for k, v in (raw.get("element_reassignments") or {}).items()}
        return cls(groups=groups, element_reassignments=reassign)

    @property
    def codes(self) -> list[str]:
        return [g.code for g in self.groups]

    def get(self, code: str) -> Group:
        for g in self.groups:
            if g.code == code:
                return g
        raise KeyError(code)

    def name_of(self, code: str) -> str:
        try:
            return self.get(code).name
        except KeyError:
            return code

    def resolve(self, label: Any, element: Any = None) -> str | None:
        """Group code for a raw label, honouring element reassignments. ``None`` if unknown."""
        if element is not None and str(element) in self.element_reassignments:
            return self.element_reassignments[str(element)]
        for g in self.groups:
            if g.matches(label):
                return g.code
        return None


# --- Item catalogue ------------------------------------------------------------------------

_NUMERIC_PREFIX = re.compile(r"^\s*\d+(?:[.)\-]\d+)*[.)\-]?\s+")


@dataclass(slots=True)
class ItemCatalog:
    categories: dict[str, list[str]]  # canonical -> aliases
    merges: dict[str, str]  # explicit raw -> canonical merges
    shifted_symptoms: list[re.Pattern[str]]
    fold_accents: bool = True
    strip_numeric_prefix: bool = True

    @classmethod
    def load(cls, path: Path | str) -> ItemCatalog:
        raw = load_yaml(path)
        norm = raw.get("normalization") or {}
        cats = {
            str(c["name"]): [str(a) for a in c.get("aliases", [])]
            for c in raw.get("categories", [])
        }
        merges = {str(k): str(v) for k, v in (raw.get("merges") or {}).items()}
        symptoms = [re.compile(p, re.IGNORECASE) for p in raw.get("shifted_column_symptoms", [])]
        return cls(
            categories=cats,
            merges=merges,
            shifted_symptoms=symptoms,
            fold_accents=bool(norm.get("fold_accents", True)),
            strip_numeric_prefix=bool(norm.get("strip_numeric_prefix", True)),
        )

    def _lookup(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for canonical, aliases in self.categories.items():
            out[fold(canonical)] = canonical
            for a in aliases:
                out[fold(a)] = canonical
        for raw, canonical in self.merges.items():
            out[fold(raw)] = canonical
        return out

    def clean_label(self, value: Any) -> str:
        text = "" if value is None else str(value)
        if self.strip_numeric_prefix:
            text = _NUMERIC_PREFIX.sub("", text)
        return re.sub(r"\s+", " ", text.replace(" ", " ")).strip()

    def looks_shifted(self, value: Any) -> bool:
        text = "" if value is None else str(value).strip()
        return any(p.search(text) for p in self.shifted_symptoms)

    def canonical_category(self, value: Any) -> tuple[str, bool]:
        """(canonical name, known?) for a raw category label."""
        cleaned = self.clean_label(value)
        hit = self._lookup().get(fold(cleaned))
        if hit is not None:
            return hit, True
        return cleaned, False
