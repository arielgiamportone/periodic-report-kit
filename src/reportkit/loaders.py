"""Loaders: locate, read and translate raw files into the canonical model.

They translate, they never interpret. Anything unknown is quarantined with a typed warning
(kind, file, row count, affected controls). Above this module nobody knows where a row came
from.
"""

from __future__ import annotations

import fnmatch
import re
import time
import zipfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import numpy as np
import pandas as pd
from openpyxl import load_workbook

from .model import (
    CATEGORY,
    COMMENT,
    CONTROL,
    CORE_COLUMNS,
    ELEMENT,
    ELEMENT_NAME,
    GROUP,
    ITEM,
    PERIOD,
    RESULT,
    SOURCE,
    TIMESTAMP,
    UNIT,
    Period,
    Warning,
    empty_model,
    ensure_model,
    month_range,
    parse_month,
)
from .schema import DataSchema, GroupCatalog, ItemCatalog, fold

REQUIRED_COLUMNS = (CONTROL, GROUP, ELEMENT, CATEGORY, ITEM, RESULT, TIMESTAMP)
CACHE_DIRNAME = ".reportkit-cache"

# --- 1. Locate files ---------------------------------------------------------------------------


def _expand_patterns(pattern: str, period: str) -> list[str]:
    """``{mm}`` matches both ``03`` and ``3`` folders: the history is never renamed."""
    d = parse_month(period)
    base = pattern.replace("{yyyy}", f"{d.year:04d}")
    return sorted({base.replace("{mm}", f"{d.month:02d}"), base.replace("{mm}", str(d.month))})


def _fold_path(path: Path, root: Path) -> str:
    rel = path.relative_to(root).as_posix()
    return fold(rel)


def find_period_files(
    root: Path, period: str, schema: DataSchema
) -> tuple[list[Path], list[Warning]]:
    """Files of a month, matched with accent/case-insensitive globs; drafts and lock files skipped."""
    root = Path(root)
    warnings: list[Warning] = []
    if not root.is_dir():
        return [], [Warning("missing-root", f"data root not found: {root}")]
    patterns = [fold(x) for p in schema.file_patterns for x in _expand_patterns(p, period)]
    seen: set[Path] = set()
    found: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        name = path.name
        if name.startswith("~$") or name.startswith("."):
            continue
        folded_name = fold(name)
        if any(frag in folded_name for frag in schema.skip_name_fragments):
            warnings.append(Warning("draft-skipped", f"draft or copy ignored: {name}", file=name))
            continue
        folded = _fold_path(path, root)
        if not any(fnmatch.fnmatchcase(folded, pat) for pat in patterns):
            continue
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        found.append(path)
    if not found:
        warnings.append(Warning("no-files", f"no files matched for {period} under {root}"))
    return found, warnings


# --- 2. Read sheets --------------------------------------------------------------------------------


def _with_retries(fn, retries: int, *args: Any, **kwargs: Any) -> Any:
    last: Exception | None = None
    for attempt in range(max(1, retries)):
        try:
            return fn(*args, **kwargs)
        except OSError as exc:  # cloud-synced folders fail transiently
            last = exc
            time.sleep(0.05 * (attempt + 1))
    assert last is not None
    raise last


def _sheet_xml_name(zf: zipfile.ZipFile, sheet_name: str) -> str | None:
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    wb = ET.fromstring(zf.read("xl/workbook.xml"))
    rid_attr = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    rid = None
    for sheet in wb.findall(".//m:sheets/m:sheet", ns):
        if sheet.get("name") == sheet_name:
            rid = sheet.get(rid_attr)
            break
    if rid is None:
        return None
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    for rel in rels:
        if rel.get("Id") == rid:
            target = rel.get("Target", "")
            return target.lstrip("/") if target.startswith("/") else f"xl/{target}"
    return None


def count_xml_rows(path: Path, sheet_name: str) -> int | None:
    """Count ``<row>`` elements in the sheet XML, ignoring the declared ``<dimension>``."""
    with zipfile.ZipFile(path) as zf:
        part = _sheet_xml_name(zf, sheet_name)
        if part is None or part not in zf.namelist():
            return None
        count = 0
        with zf.open(part) as fh:
            for _event, el in ET.iterparse(fh, events=("end",)):
                if el.tag.endswith("}row"):
                    count += 1
                el.clear()
        return count


def declared_dimension(path: Path, sheet_name: str) -> str | None:
    with zipfile.ZipFile(path) as zf:
        part = _sheet_xml_name(zf, sheet_name)
        if part is None:
            return None
        m = re.search(rb'<dimension ref="([^"]*)"', zf.read(part))
        return m.group(1).decode() if m else None


def read_sheet(
    path: Path, sheet_name: str, schema: DataSchema
) -> tuple[list[list[Any]], list[Warning]]:
    """All rows of a sheet as lists. Does not trust the declared dimension."""
    warnings: list[Warning] = []

    def _read() -> list[list[Any]]:
        wb = load_workbook(path, read_only=True, data_only=True)
        try:
            ws = wb[sheet_name]
            ws.reset_dimensions()
            return [list(r) for r in ws.iter_rows(values_only=True)]
        finally:
            wb.close()

    rows = _with_retries(_read, schema.io_retries)
    xml_rows = _with_retries(count_xml_rows, schema.io_retries, path, sheet_name)
    if xml_rows is not None and xml_rows != len(rows):
        warnings.append(
            Warning(
                "row-count-mismatch",
                f"sheet {sheet_name!r}: {len(rows)} rows read, {xml_rows} in XML",
                file=path.name,
            )
        )
    dim = declared_dimension(path, sheet_name)
    if dim and xml_rows and ":" in dim:
        last = re.sub(r"[A-Z]+", "", dim.split(":")[1])
        if last.isdigit() and int(last) < xml_rows:
            warnings.append(
                Warning(
                    "dimension-mismatch",
                    f"sheet {sheet_name!r} declares {dim} but holds {xml_rows} rows; counted in XML",
                    file=path.name,
                    rows=xml_rows,
                )
            )
    return rows, warnings


def _find_header_row(rows: list[list[Any]], schema: DataSchema, limit: int = 15) -> int | None:
    known = set(schema.header_map())
    best, best_hits = None, 0
    for i, row in enumerate(rows[:limit]):
        hits = sum(1 for cell in row if fold(cell) in known)
        if hits > best_hits:
            best, best_hits = i, hits
    return best if best_hits >= 3 else None


def _rows_to_frame(rows: list[list[Any]], schema: DataSchema) -> pd.DataFrame | None:
    header_idx = _find_header_row(rows, schema)
    if header_idx is None:
        return None
    header = [str(c) if c is not None else f"col{i}" for i, c in enumerate(rows[header_idx])]
    body = rows[header_idx + 1 :]
    width = len(header)
    body = [list(r)[:width] + [None] * (width - len(r)) for r in body]
    return pd.DataFrame(body, columns=header, dtype=object)


def read_file(
    path: Path, schema: DataSchema
) -> tuple[list[tuple[str, pd.DataFrame]], list[Warning]]:
    """Every detail sheet of a workbook (or a CSV) as raw DataFrames: (sheet, frame)."""
    warnings: list[Warning] = []
    out: list[tuple[str, pd.DataFrame]] = []
    suffix = path.suffix.lower()
    if suffix == ".csv":
        df = _with_retries(
            pd.read_csv,
            schema.io_retries,
            path,
            dtype=object,
            sep=None,
            engine="python",
            encoding="utf-8",
        )
        out.append(("csv", df))
        return out, warnings
    if suffix not in {".xlsx", ".xlsm"}:
        return out, [Warning("unsupported-file", f"unsupported extension {suffix}", file=path.name)]

    def _names() -> list[str]:
        wb = load_workbook(path, read_only=True)
        try:
            return list(wb.sheetnames)
        finally:
            wb.close()

    names = _with_retries(_names, schema.io_retries)
    for name in names:
        if schema.is_forbidden_sheet(name):
            warnings.append(
                Warning("forbidden-sheet", f"hand-made sheet ignored: {name!r}", file=path.name)
            )
            continue
        if not schema.is_detail_sheet(name):
            continue
        rows, w = read_sheet(path, name, schema)
        warnings.extend(w)
        frame = _rows_to_frame(rows, schema)
        if frame is None:
            warnings.append(
                Warning("no-header", f"no recognisable header in sheet {name!r}", file=path.name)
            )
            continue
        out.append((name, frame))
    if not out:
        warnings.append(Warning("no-detail-sheet", "no detail sheet found", file=path.name))
    return out, warnings


# --- 3. Translate ------------------------------------------------------------------------------------

_SPACE_BEFORE_COMMA = re.compile(r"\s+,")
_MULTI_SPACE = re.compile(r"\s+")


def normalize_name(value: Any) -> Any:
    """Collapse repeated/hard spaces and remove space before a comma. Nothing else."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    text = str(value).replace(" ", " ")
    text = _MULTI_SPACE.sub(" ", text)
    text = _SPACE_BEFORE_COMMA.sub(",", text)
    return text.strip()


def normalize_names(series: pd.Series) -> tuple[pd.Series, dict[str, list[str]]]:
    """Normalise a dimension and report which raw variants were merged into each value."""
    normalized = series.map(normalize_name)
    merges: dict[str, list[str]] = {}
    pairs = pd.DataFrame({"raw": series, "norm": normalized}).dropna()
    for norm, grp in pairs.groupby("norm"):
        variants = sorted({str(v) for v in grp["raw"].unique()})
        if len(variants) > 1:
            merges[str(norm)] = variants
    return normalized, merges


def to_local_timestamps(series: pd.Series, schema: DataSchema) -> pd.Series:
    """Parse timestamps and express them in the declared local zone. Period comes after."""
    values = series.map(lambda v: None if (isinstance(v, float) and np.isnan(v)) else v)
    try:
        ts = pd.to_datetime(values, errors="coerce", format="mixed")
    except (ValueError, TypeError):
        ts = pd.to_datetime(values, errors="coerce", format="mixed", utc=True)
    if not isinstance(ts, pd.Series):
        ts = pd.Series(ts, index=series.index)
    if ts.dt.tz is None:
        source = schema.source_timezone or schema.timezone
        ts = ts.dt.tz_localize(
            source, ambiguous=np.ones(len(ts), dtype=bool), nonexistent="shift_forward"
        )
    return ts.dt.tz_convert(schema.timezone)


def translate(
    raw: pd.DataFrame,
    schema: DataSchema,
    groups: GroupCatalog,
    items: ItemCatalog,
    source: str,
) -> tuple[pd.DataFrame, pd.DataFrame, list[Warning]]:
    """Raw sheet -> (canonical rows, quarantined rows, warnings)."""
    warnings: list[Warning] = []
    header_map = schema.header_map()
    rename = {col: header_map[fold(col)] for col in raw.columns if fold(col) in header_map}
    df = raw.rename(columns=rename)
    df = df.loc[:, ~df.columns.duplicated()]
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        warnings.append(
            Warning(
                "missing-columns",
                f"required columns not found: {missing}",
                file=source,
                rows=len(df),
            )
        )
        return empty_model(), raw.assign(_reason="missing-columns"), warnings

    df = df.copy()
    df["_reason"] = None

    # Separator rows: a hand-written month label with everything else empty.
    if schema.separator_row_pattern:
        pat = re.compile(schema.separator_row_pattern, re.IGNORECASE)
        first_col = raw.columns[0]
        others = [c for c in raw.columns if c != first_col]
        is_sep = raw[first_col].map(
            lambda v: bool(pat.match(str(v).strip())) if v is not None else False
        )
        is_sep &= raw[others].isna().all(axis=1)
        if is_sep.any():
            labels = sorted({str(v).strip() for v in raw.loc[is_sep, first_col]})
            warnings.append(
                Warning(
                    "separator-row",
                    f"month label rows ignored; period comes from the date, not from {labels}",
                    file=source,
                    rows=int(is_sep.sum()),
                    details={"labels": labels},
                )
            )
            df = df.loc[~is_sep.values]

    # Fully empty rows are noise, not items.
    df = df.dropna(how="all", subset=[c for c in df.columns if c != "_reason"])

    # Result: empty -> not an item (photo, note). Unknown -> quarantine.
    result_map = schema.result_map()
    raw_result = df[RESULT]
    blank = raw_result.isna() | (raw_result.map(lambda v: fold(v) == ""))
    if blank.any():
        controls = tuple(sorted({str(c) for c in df.loc[blank, CONTROL].dropna().unique()}))
        warnings.append(
            Warning(
                "no-items",
                "rows without result are not evaluated items",
                file=source,
                rows=int(blank.sum()),
                controls=controls,
            )
        )
    df = df.loc[~blank].copy()
    df[RESULT] = df[RESULT].map(lambda v: result_map.get(fold(v)))
    unknown_result = df[RESULT].isna()
    df.loc[unknown_result, "_reason"] = "unknown-result"

    # Group: resolved row by row (a file may mix groups), honouring element reassignments.
    df[GROUP] = [
        groups.resolve(label, element)
        for label, element in zip(df[GROUP], df[ELEMENT], strict=True)
    ]
    unknown_group = df[GROUP].isna() & df["_reason"].isna()
    df.loc[unknown_group, "_reason"] = "unknown-group"

    # Category / item: two levels; shifted columns are quarantined, unknown labels kept with a warning.
    shifted = df[CATEGORY].map(items.looks_shifted) & df["_reason"].isna()
    df.loc[shifted, "_reason"] = "shifted-column"
    canon = df[CATEGORY].map(items.canonical_category)
    df[CATEGORY] = canon.map(lambda t: t[0])
    unknown_cat = sorted({c for c, known in canon if not known and c})
    if unknown_cat:
        warnings.append(
            Warning(
                "unknown-category",
                f"categories not in catalogue kept as-is: {unknown_cat}",
                file=source,
                details={"labels": unknown_cat},
            )
        )
    df[ITEM] = df[ITEM].map(items.clean_label)

    # Timestamps -> local zone -> period. Never from labels.
    df[TIMESTAMP] = to_local_timestamps(df[TIMESTAMP], schema)
    bad_ts = df[TIMESTAMP].isna() & df["_reason"].isna()
    df.loc[bad_ts, "_reason"] = "bad-timestamp"
    df[PERIOD] = df[TIMESTAMP].map(lambda t: None if pd.isna(t) else f"{t.year:04d}-{t.month:02d}")

    # Unit: declared column or default.
    unit_map = schema.unit_map()
    if UNIT in df.columns:
        df[UNIT] = df[UNIT].map(
            lambda v: (
                unit_map.get(fold(v), schema.default_unit) if v is not None else schema.default_unit
            )
        )
    else:
        df[UNIT] = schema.default_unit

    # Dimensions: whitespace-only normalisation, every merge is reported.
    for dim in schema.dimensions:
        if dim in df.columns:
            df[dim], merges = normalize_names(df[dim])
            if merges:
                warnings.append(
                    Warning(
                        "name-merge",
                        f"variants merged in {dim}: {merges}",
                        file=source,
                        details={"dimension": dim, "merges": merges},
                    )
                )
        else:
            df[dim] = None

    for col in (ELEMENT_NAME, COMMENT):
        if col not in df.columns:
            df[col] = None
    df[SOURCE] = source
    df[CONTROL] = df[CONTROL].map(lambda v: None if v is None else str(v).strip())
    df[ELEMENT] = df[ELEMENT].map(lambda v: None if v is None else str(v).strip())

    quarantined = df[df["_reason"].notna()]
    for reason, grp in quarantined.groupby("_reason"):
        controls = tuple(sorted({str(c) for c in grp[CONTROL].dropna().unique()}))
        warnings.append(
            Warning(
                str(reason),
                f"{len(grp)} rows quarantined ({reason})",
                file=source,
                rows=len(grp),
                controls=controls,
            )
        )
    good = df[df["_reason"].isna()].drop(columns=["_reason"])
    keep = list(CORE_COLUMNS) + list(schema.dimensions)
    good = ensure_model(good)[keep]
    return good.reset_index(drop=True), quarantined.reset_index(drop=True), warnings


# --- 4. Assemble a period ------------------------------------------------------------------------------


def dedupe_controls(df: pd.DataFrame) -> tuple[pd.DataFrame, list[Warning]]:
    """If a control appears in several sources keep the copy with most items; warn if they differ."""
    warnings: list[Warning] = []
    if df.empty:
        return df, warnings
    sizes = df.groupby([CONTROL, SOURCE], dropna=False).size().reset_index(name="n")
    multi = sizes.groupby(CONTROL).filter(lambda g: len(g) > 1)
    if multi.empty:
        return df, warnings
    keep_pairs: set[tuple[str, str]] = set()
    for control, grp in multi.groupby(CONTROL):
        grp = grp.sort_values(["n", SOURCE], ascending=[False, True])
        winner = grp.iloc[0]
        keep_pairs.add((control, winner[SOURCE]))
        if grp["n"].nunique() > 1:
            warnings.append(
                Warning(
                    "duplicate-control",
                    f"control {control} found in {len(grp)} sources with {grp['n'].tolist()} items; kept {winner[SOURCE]}",
                    file=str(winner[SOURCE]),
                    controls=(str(control),),
                    details={"sources": grp[SOURCE].tolist(), "items": grp["n"].tolist()},
                )
            )
    dup_controls = set(multi[CONTROL])
    mask = ~df[CONTROL].isin(dup_controls) | pd.Series(
        [(c, s) in keep_pairs for c, s in zip(df[CONTROL], df[SOURCE], strict=True)], index=df.index
    )
    return df[mask].reset_index(drop=True), warnings


def _cache_path(cache_dir: Path, schema: DataSchema, period: str) -> Path:
    return cache_dir / f"v{schema.version}" / f"{period}.parquet"


def load_period(
    period: str,
    schema: DataSchema,
    groups: GroupCatalog,
    items: ItemCatalog,
    root: Path,
    use_cache: bool = True,
    cache_dir: Path | None = None,
) -> Period:
    """Load one month into the canonical model. Cached in parquet (versioned, no warnings)."""
    parse_month(period)
    root = Path(root)
    cache_dir = Path(cache_dir) if cache_dir else root / CACHE_DIRNAME
    cache = _cache_path(cache_dir, schema, period)
    if use_cache and cache.is_file():
        df = pd.read_parquet(cache)
        return Period(
            data=df,
            warnings=[Warning("cache-hit", f"model loaded from cache {cache.name}")],
            start=period,
            end=period,
        )

    files, warnings = find_period_files(root, period, schema)
    frames: list[pd.DataFrame] = []
    quarantined: list[pd.DataFrame] = []
    for path in files:
        sheets, w = read_file(path, schema)
        warnings.extend(w)
        for sheet, raw in sheets:
            source = f"{path.name}::{sheet}"
            good, bad, w2 = translate(raw, schema, groups, items, source)
            warnings.extend(w2)
            frames.append(good)
            if not bad.empty:
                quarantined.append(bad)
    df = pd.concat(frames, ignore_index=True) if frames else empty_model()
    if not df.empty:
        outside = df[PERIOD] != period
        if outside.any():
            others = sorted(df.loc[outside, PERIOD].dropna().unique().tolist())
            warnings.append(
                Warning(
                    "out-of-period",
                    f"rows dated outside {period} set aside: {others}",
                    rows=int(outside.sum()),
                    details={"periods": others},
                )
            )
            quarantined.append(df[outside].assign(_reason="out-of-period"))
            df = df[~outside].reset_index(drop=True)
        df, w3 = dedupe_controls(df)
        warnings.extend(w3)
    quarantine = pd.concat(quarantined, ignore_index=True) if quarantined else None
    if use_cache and not df.empty:
        cache.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(cache, index=False)
    return Period(data=df, warnings=warnings, start=period, end=period, quarantine=quarantine)


def load_range(
    start: str,
    end: str,
    schema: DataSchema,
    groups: GroupCatalog,
    items: ItemCatalog,
    root: Path,
    use_cache: bool = True,
    cache_dir: Path | None = None,
) -> Period:
    """Half-year / year = concatenation of monthly models. The range is explicit, never deduced."""
    months = month_range(start, end)
    parts = [load_period(m, schema, groups, items, root, use_cache, cache_dir) for m in months]
    data = pd.concat([p.data for p in parts], ignore_index=True) if parts else empty_model()
    warnings = [w for p in parts for w in p.warnings]
    quarantines = [p.quarantine for p in parts if p.quarantine is not None]
    quarantine = pd.concat(quarantines, ignore_index=True) if quarantines else None
    return Period(data=data, warnings=warnings, start=start, end=end, quarantine=quarantine)


def warnings_summary(warnings: Iterable[Warning]) -> pd.DataFrame:
    rows = [
        {
            "kind": w.kind,
            "file": w.file,
            "rows": w.rows,
            "controls": len(w.controls),
            "message": w.message,
        }
        for w in warnings
    ]
    return pd.DataFrame(rows, columns=["kind", "file", "rows", "controls", "message"])
