from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from reportkit.loaders import (
    count_xml_rows,
    dedupe_controls,
    find_period_files,
    load_period,
    load_range,
    normalize_names,
    read_file,
    to_local_timestamps,
    translate,
)
from reportkit.model import CONTROL, GROUP, PERIOD, RESULT, SOURCE, TIMESTAMP, UNIT
from reportkit.synthetic import RAW_HEADERS, SyntheticOptions, write_workbooks


@pytest.fixture(scope="module")
def raw_tree(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("raw")
    write_workbooks(root, ["2025-12", "2026-01", "2026-02"], SyntheticOptions(seed=11))
    return root


def _raw(rows: list[list], headers: list[str] = RAW_HEADERS) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=headers, dtype=object)


def _row(
    control="V1",
    group="Cafetería",
    element="CAFE-01",
    category="Higiene",
    item="Suelos limpios",
    result="Correcto",
    when=datetime(2026, 3, 5, 10),
    responsible="Cafés Lumen, S.L.",
    unit="Inspección",
):
    return [
        control,
        group,
        element,
        "Café 1",
        responsible,
        "Planta baja",
        category,
        item,
        result,
        None,
        when,
        unit,
    ]


# --- Locating files -------------------------------------------------------------------------------


def test_find_files_is_tolerant_and_skips_drafts(raw_tree: Path, schema) -> None:
    files, warnings = find_period_files(raw_tree, "2026-01", schema)
    names = [f.name for f in files]
    assert len(files) == 3
    assert not any("copia" in n for n in names)
    assert not any(n.startswith("~$") for n in names)
    assert any(w.kind == "draft-skipped" for w in warnings)


def test_find_files_matches_folder_without_leading_zero(tmp_path: Path, schema) -> None:
    (tmp_path / "2026" / "3. marzo").mkdir(parents=True)
    target = tmp_path / "2026" / "3. marzo" / "Registros marzo 2026.xlsx"
    target.write_bytes(b"")
    (tmp_path / "2026" / "03. Marzo").mkdir(parents=True)
    files, _ = find_period_files(tmp_path, "2026-03", schema)
    assert files == [target]


# --- Reading ---------------------------------------------------------------------------------------


def test_forbidden_sheet_is_never_read(raw_tree: Path, schema) -> None:
    main = next(raw_tree.rglob("Registros Enero 2026.xlsx"))
    sheets, warnings = read_file(main, schema)
    assert [s for s, _ in sheets] == ["Registros"]
    assert any(w.kind == "forbidden-sheet" for w in warnings)


def test_lying_dimension_is_counted_in_xml(raw_tree: Path, schema) -> None:
    second = next(raw_tree.rglob("Registros encuestas enero 2026.xlsx"))
    assert count_xml_rows(second, "Datos") > 20
    sheets, warnings = read_file(second, schema)
    frame = dict(sheets)["Datos"]
    assert len(frame) > 20
    assert any(w.kind == "dimension-mismatch" for w in warnings)


# --- Translating -----------------------------------------------------------------------------------


def test_blank_result_is_not_an_item(schema, groups, items) -> None:
    rows = [_row(control=f"V{i}") for i in range(8)] + [
        _row(control="V1", result=None),
        _row(control="V2", result=""),
    ]
    good, bad, warnings = translate(_raw(rows), schema, groups, items, "t.xlsx::Registros")
    assert len(good) == 8
    w = next(w for w in warnings if w.kind == "no-items")
    assert w.rows == 2 and set(w.controls) == {"V1", "V2"}


def test_wrong_month_label_row_is_ignored_and_period_comes_from_date(schema, groups, items) -> None:
    rows = [
        _row(control="V1"),
        ["ENERO 2025"] + [None] * (len(RAW_HEADERS) - 1),
        _row(control="V2"),
    ]
    good, _, warnings = translate(_raw(rows), schema, groups, items, "t")
    assert set(good[PERIOD]) == {"2026-03"}
    assert any(w.kind == "separator-row" and "ENERO 2025" in w.message for w in warnings)


def test_mixed_file_resolves_group_row_by_row(schema, groups, items) -> None:
    rows = [
        _row(control="V1", group="Cafetería"),
        _row(control="V2", group="Quiosco", element="KIOS-01"),
        _row(control="V3", group="Kioscos", element="KIOS-07"),
    ]
    good, bad, _ = translate(_raw(rows), schema, groups, items, "t")
    assert bad.empty
    assert good.set_index(CONTROL)[GROUP].to_dict() == {
        "V1": "CAFE",
        "V2": "KIOS",
        "V3": "CAFE",
    }  # KIOS-07 is reassigned


def test_unknown_group_and_result_are_quarantined_not_guessed(schema, groups, items) -> None:
    rows = [
        _row(control="V1"),
        _row(control="V2", group="Helipuerto"),
        _row(control="V3", result="Quizás"),
    ]
    good, bad, warnings = translate(_raw(rows), schema, groups, items, "t")
    assert good[CONTROL].tolist() == ["V1"]
    assert sorted(bad["_reason"]) == ["unknown-group", "unknown-result"]
    kinds = {w.kind for w in warnings}
    assert {"unknown-group", "unknown-result"} <= kinds


def test_category_normalisation_and_shifted_column(schema, groups, items) -> None:
    rows = [
        _row(control="V1", category="3. Higiene"),
        _row(control="V2", category="Senalizacion"),
        _row(control="V3", category="2026-03-05"),
        _row(control="V4", category="Pintura exterior"),
    ]
    good, bad, warnings = translate(_raw(rows), schema, groups, items, "t")
    assert good.set_index(CONTROL)["category"].to_dict() == {
        "V1": "Higiene",
        "V2": "Señalización",
        "V4": "Pintura exterior",
    }
    assert bad["_reason"].tolist() == ["shifted-column"]
    assert any(w.kind == "unknown-category" and "Pintura exterior" in w.message for w in warnings)


def test_utc_timestamp_moves_to_next_local_day(schema) -> None:
    ts = to_local_timestamps(pd.Series(["2026-03-01T23:30:00Z"]), schema)
    assert ts.iloc[0].day == 2 and str(ts.dt.tz) == "Europe/Madrid"


def test_naive_timestamp_declared_as_utc_is_converted(schema) -> None:
    from dataclasses import replace

    utc_schema = replace(schema, source_timezone="UTC")
    ts = to_local_timestamps(pd.Series([datetime(2026, 7, 31, 22, 30)]), utc_schema)
    assert (ts.iloc[0].month, ts.iloc[0].day, ts.iloc[0].hour) == (8, 1, 0)  # +2 h in summer


def test_period_is_derived_from_local_date(schema, groups, items) -> None:
    rows = [_row(control="V1", when="2026-03-31T23:30:00Z")]
    good, _, _ = translate(_raw(rows), schema, groups, items, "t")
    assert good[PERIOD].iloc[0] == "2026-04"


def test_name_merge_is_reported() -> None:
    s = pd.Series(["Cafés Lumen , S.L.", "Cafés Lumen, S.L.", "Cafés Lumen,  S.L.", "Otra, S.A."])
    norm, merges = normalize_names(s)
    assert norm.nunique() == 2
    assert merges == {
        "Cafés Lumen, S.L.": sorted(
            {"Cafés Lumen , S.L.", "Cafés Lumen, S.L.", "Cafés Lumen,  S.L."}
        )
    }


def test_different_names_are_never_merged() -> None:
    norm, merges = normalize_names(pd.Series(["Cafés Lumen, S.L.", "Cafés Lumen 2, S.L."]))
    assert norm.nunique() == 2 and merges == {}


def test_unit_column_separates_surveys(schema, groups, items) -> None:
    rows = [
        _row(control="V1"),
        _row(control="E1", group="Encuesta", element="ENCU-01", unit="Encuesta"),
    ]
    good, _, _ = translate(_raw(rows), schema, groups, items, "t")
    assert good.set_index(CONTROL)[UNIT].to_dict() == {"V1": "control", "E1": "survey"}


# --- Assembling --------------------------------------------------------------------------------------


def test_duplicate_control_keeps_copy_with_most_items() -> None:
    a = pd.DataFrame({CONTROL: ["V1"] * 5, SOURCE: "a", RESULT: "ok"})
    b = pd.DataFrame({CONTROL: ["V1"] * 3 + ["V2"], SOURCE: "b", RESULT: "ok"})
    out, warnings = dedupe_controls(pd.concat([a, b], ignore_index=True))
    assert out[out[CONTROL] == "V1"][SOURCE].unique().tolist() == ["a"]
    assert len(out) == 6
    w = next(w for w in warnings if w.kind == "duplicate-control")
    assert w.controls == ("V1",) and w.details["items"] == [5, 3]


def test_load_period_end_to_end(raw_tree: Path, schema, groups, items) -> None:
    period = load_period("2026-01", schema, groups, items, raw_tree, use_cache=False)
    df = period.data
    kinds = {w.kind for w in period.warnings}
    assert {
        "no-items",
        "separator-row",
        "forbidden-sheet",
        "duplicate-control",
        "dimension-mismatch",
        "draft-skipped",
        "name-merge",
    } <= kinds
    assert set(df[PERIOD]) == {"2026-01"}
    assert df[TIMESTAMP].dt.tz is not None
    assert set(df[GROUP]) == {"CAFE", "KIOS", "ASEO", "INFO", "LIMP", "ENCU"}
    # Every synthetic inspection control survives: 5 groups x 10 controls (+ surveys).
    assert df[df[UNIT] == "control"][CONTROL].nunique() == 50
    assert df[CONTROL].is_unique or df.groupby(CONTROL)[SOURCE].nunique().max() == 1
    # UTC CSV rows at 23:30Z the previous day land on the right local day of the right month.
    api_rows = df[df[SOURCE].str.startswith("registro_api")]
    assert not api_rows.empty and set(api_rows[PERIOD]) == {"2026-01"}


def test_load_period_uses_versioned_parquet_cache(
    raw_tree: Path, schema, groups, items, tmp_path: Path
) -> None:
    first = load_period("2026-02", schema, groups, items, raw_tree, cache_dir=tmp_path)
    cached = list(tmp_path.rglob("*.parquet"))
    assert len(cached) == 1 and cached[0].parent.name == f"v{schema.version}"
    second = load_period("2026-02", schema, groups, items, raw_tree, cache_dir=tmp_path)
    assert [w.kind for w in second.warnings] == ["cache-hit"]
    a = first.data.reset_index(drop=True).astype(object)
    b = second.data.reset_index(drop=True).astype(object)
    pd.testing.assert_frame_equal(
        a.where(a.notna(), None), b.where(b.notna(), None), check_dtype=False
    )


def test_load_range_crosses_the_year_boundary(raw_tree: Path, schema, groups, items) -> None:
    period = load_range("2025-12", "2026-02", schema, groups, items, raw_tree, use_cache=False)
    assert period.months == ["2025-12", "2026-01", "2026-02"]
    assert set(period.data[PERIOD]) == {"2025-12", "2026-01", "2026-02"}
    assert period.label == "2025-12 a 2026-02"
