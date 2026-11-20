from pathlib import Path

import pandas as pd
from openpyxl import load_workbook

from reportkit.model import CONTROL, CORE_COLUMNS, RESULT, UNIT
from reportkit.synthetic import (
    SyntheticOptions,
    aggregated_visits_fixture,
    generate_canonical,
    three_controls_fixture,
    write_workbooks,
)


def test_canonical_month_is_deterministic_and_well_formed() -> None:
    a = generate_canonical("2026-03", SyntheticOptions(seed=3))
    b = generate_canonical("2026-03", SyntheticOptions(seed=3))
    pd.testing.assert_frame_equal(a, b)
    assert set(CORE_COLUMNS) <= set(a.columns)
    assert set(a[RESULT].unique()) <= {"ok", "fail", "na"}
    assert (a["period"] == "2026-03").all()
    assert a["timestamp"].dt.tz is not None
    assert {"control", "survey"} == set(a[UNIT].unique())


def test_three_controls_fixture_shape() -> None:
    df = three_controls_fixture()
    assert df[CONTROL].nunique() == 3
    assert len(df) == 10
    assert df[RESULT].value_counts().to_dict() == {"ok": 6, "fail": 3, "na": 1}


def test_aggregated_fixture_columns() -> None:
    df = aggregated_visits_fixture()
    assert list(df.columns) == ["element", "period", "visits", "incidents"]


def test_write_workbooks_creates_quirky_tree(tmp_path: Path) -> None:
    files = write_workbooks(tmp_path, ["2026-02", "2026-03"], SyntheticOptions(seed=1))
    assert len(files) == 6
    year = tmp_path / "2026"
    assert year.is_dir()
    main = [f for f in files if f.name.startswith("Registros ") and "encuestas" not in f.name]
    assert len(main) == 2
    wb = load_workbook(main[0], read_only=True)
    assert "Resumen" in wb.sheetnames and "Registros" in wb.sheetnames
    # Drafts and lock files exist so that the loader has something to skip.
    drafts = list(year.rglob("* - copia.xlsx"))
    locks = list(year.rglob("~$*"))
    assert len(drafts) == 2 and len(locks) == 2
    # The second workbook lies about its size.
    second = [f for f in files if "encuestas" in f.name][0]
    import zipfile

    with zipfile.ZipFile(second) as zf:
        assert b'<dimension ref="A1:A1"' in zf.read("xl/worksheets/sheet2.xml")
