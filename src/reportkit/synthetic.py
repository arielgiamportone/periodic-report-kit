"""Synthetic data generators.

Everything the tests, the demo and the documentation use comes from here: invented groups,
invented responsibles, invented checklists. The raw writer deliberately reproduces the quirks
that the loader rules exist for (drafts, separator rows, blank results, mixed files, duplicated
controls, a lying sheet dimension, UTC exports), so that every rule has an end-to-end fixture.
"""

from __future__ import annotations

import calendar
import csv
import random
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl import Workbook

from .model import (
    CATEGORY,
    COMMENT,
    CONTROL,
    ELEMENT,
    ELEMENT_NAME,
    GROUP,
    ITEM,
    PERIOD,
    RESULT,
    SOURCE,
    TIMESTAMP,
    UNIT,
    Result,
    ensure_model,
    parse_month,
)

MONTH_NAMES_ES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]  # fmt: skip

CHECKLIST: dict[str, list[str]] = {
    "Higiene": ["Suelos limpios", "Superficies desinfectadas", "Papeleras vaciadas", "Uniformidad"],
    "Señalización": ["Cartel de horario visible", "Rótulo iluminado", "Pictogramas"],
    "Documentación": ["Hoja de reclamaciones", "Registro de temperaturas", "Licencia visible"],
    "Atención al cliente": ["Saludo inicial", "Tiempo de espera", "Resolución de dudas"],
    "Seguridad": ["Extintor accesible", "Salida despejada", "Botiquín completo"],
    "Instalaciones": ["Mobiliario íntegro", "Iluminación correcta", "Climatización"],
    "Precios": ["Lista de precios expuesta", "Ticket entregado"],
    "Horario": ["Apertura puntual", "Cierre puntual"],
}

GROUP_LABELS: dict[str, list[str]] = {
    "CAFE": ["Cafetería", "CAFETERIAS", "Cafés"],
    "KIOS": ["Quiosco", "Kioscos"],
    "ASEO": ["Aseos", "ASEO"],
    "INFO": ["Punto de información", "Información"],
    "LIMP": ["Limpieza", "Zonas comunes"],
}

RESPONSIBLES: dict[str, list[str]] = {
    "CAFE": ["Cafés Lumen, S.L.", "Hostelería Brisa, S.A.", "Grupo Tamariz, S.L."],
    "KIOS": ["Prensa Delta, S.L.", "Quioscos Orión, S.A."],
}

SITES = ["Planta baja", "Planta 1", "Planta 2", "Exterior"]

RAW_RESULTS = {
    Result.OK: ["Correcto", "OK"],
    Result.FAIL: ["Incorrecto", "KO"],
    Result.NA: ["No procede", "N/A"],
}


@dataclass(slots=True)
class SyntheticOptions:
    seed: int = 7
    controls_per_group: int = 10
    fail_rate: float = 0.08
    na_rate: float = 0.05
    surveys: int = 25
    quirks: bool = True


def _rng(period: str, options: SyntheticOptions) -> random.Random:
    return random.Random(f"{options.seed}:{period}")


def _month_days(period: str) -> int:
    d = parse_month(period)
    return calendar.monthrange(d.year, d.month)[1]


def generate_canonical(period: str, options: SyntheticOptions | None = None) -> pd.DataFrame:
    """A clean canonical month, directly in the long model (no loader involved)."""
    options = options or SyntheticOptions()
    rng = _rng(period, options)
    first = parse_month(period)
    rows: list[dict[str, Any]] = []
    control_no = 0
    for group, labels in GROUP_LABELS.items():
        del labels
        for n in range(options.controls_per_group):
            control_no += 1
            control_id = f"V{first.year % 100:02d}{first.month:02d}-{control_no:04d}"
            element = f"{group}-{(n % 8) + 1:02d}"
            responsible = (
                rng.choice(RESPONSIBLES.get(group, ["—"])) if group in RESPONSIBLES else None
            )
            day = rng.randint(1, _month_days(period))
            stamp = datetime(
                first.year, first.month, day, rng.randint(7, 20), rng.choice([0, 15, 30, 45])
            )
            ts = pd.Timestamp(stamp, tz="Europe/Madrid")
            for category, items in CHECKLIST.items():
                for item in items:
                    r = rng.random()
                    result = (
                        Result.FAIL
                        if r < options.fail_rate
                        else Result.NA
                        if r < options.fail_rate + options.na_rate
                        else Result.OK
                    )
                    rows.append(
                        {
                            PERIOD: period,
                            GROUP: group,
                            CONTROL: control_id,
                            ELEMENT: element,
                            ELEMENT_NAME: f"{group} {element[-2:]}",
                            "responsible": responsible,
                            "site": rng.choice(SITES),
                            CATEGORY: category,
                            ITEM: item,
                            RESULT: result.value,
                            COMMENT: "Revisar" if result is Result.FAIL else None,
                            TIMESTAMP: ts,
                            SOURCE: "synthetic",
                            UNIT: "control",
                        }
                    )
    # Surveys: volume only. One row each, no checklist.
    for k in range(options.surveys):
        day = rng.randint(1, _month_days(period))
        rows.append(
            {
                PERIOD: period,
                GROUP: "ENCU",
                CONTROL: f"E{first.year % 100:02d}{first.month:02d}-{k + 1:04d}",
                ELEMENT: f"ENCU-{rng.randint(1, 4):02d}",
                ELEMENT_NAME: None,
                "responsible": None,
                "site": rng.choice(SITES),
                CATEGORY: "Encuesta",
                ITEM: "Cuestionario entregado",
                RESULT: Result.OK.value,
                COMMENT: None,
                TIMESTAMP: pd.Timestamp(
                    datetime(first.year, first.month, day, 12), tz="Europe/Madrid"
                ),
                SOURCE: "synthetic",
                UNIT: "survey",
            }
        )
    return ensure_model(pd.DataFrame(rows))


def three_controls_fixture() -> pd.DataFrame:
    """The minimal fixture that pins the five metric definitions.

    * V-1: clean (3 ok)
    * V-2: one incident (2 ok, 1 fail)
    * V-3: two incidents and one not-applicable (1 ok, 2 fail, 1 na)
    """
    ts = pd.Timestamp("2026-03-10 10:00", tz="Europe/Madrid")
    spec = [
        ("V-1", "E-1", ["ok", "ok", "ok"]),
        ("V-2", "E-2", ["ok", "ok", "fail"]),
        ("V-3", "E-3", ["ok", "fail", "fail", "na"]),
    ]
    items = [
        "Suelos limpios",
        "Cartel de horario visible",
        "Extintor accesible",
        "Ticket entregado",
    ]
    cats = ["Higiene", "Señalización", "Seguridad", "Precios"]
    rows = []
    for control, element, results in spec:
        for i, res in enumerate(results):
            rows.append(
                {
                    PERIOD: "2026-03",
                    GROUP: "CAFE",
                    CONTROL: control,
                    ELEMENT: element,
                    ELEMENT_NAME: element,
                    "responsible": "Cafés Lumen, S.L.",
                    "site": "Planta baja",
                    CATEGORY: cats[i],
                    ITEM: items[i],
                    RESULT: res,
                    COMMENT: None,
                    TIMESTAMP: ts,
                    SOURCE: "fixture",
                    UNIT: "control",
                }
            )
    return ensure_model(pd.DataFrame(rows))


def aggregated_visits_fixture() -> pd.DataFrame:
    """An aggregated source: visits and incidents per element and month (no item detail)."""
    return pd.DataFrame(
        {
            ELEMENT: ["E-1", "E-2", "E-3", "E-4"],
            PERIOD: ["2026-03"] * 4,
            "visits": [1, 3, 2, 4],
            "incidents": [0, 0, 1, 2],
        }
    )


# --- Raw writer ---------------------------------------------------------------------------

RAW_HEADERS = [
    "Id visita", "Línea", "Código elemento", "Nombre elemento", "Responsable", "Zona",
    "Apartado", "Punto de control", "Valoración", "Observaciones", "Fecha visita", "Tipo de registro",
]  # fmt: skip


def _none_if_missing(value: Any) -> Any:
    return None if value is None or (isinstance(value, float) and pd.isna(value)) else value


def _raw_rows_from_canonical(df: pd.DataFrame, rng: random.Random, quirks: bool) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for rec in df.itertuples(index=False):
        d = {k: _none_if_missing(v) for k, v in rec._asdict().items()}
        label = rng.choice(GROUP_LABELS.get(d[GROUP], [d[GROUP]]))
        category = d[CATEGORY]
        if quirks and rng.random() < 0.15:
            category = f"{rng.randint(1, 9)}. {category}"
        if quirks and category == "Señalización" and rng.random() < 0.3:
            category = "Senalizacion"
        responsible = d["responsible"]
        if quirks and responsible and rng.random() < 0.2:
            responsible = responsible.replace(", ", " , ")  # space before comma: same company
        result = rng.choice(RAW_RESULTS[Result(d[RESULT])])
        stamp = d[TIMESTAMP]
        naive = stamp.tz_localize(None) if getattr(stamp, "tzinfo", None) else stamp
        rows.append(
            [
                d[CONTROL],
                label,
                d[ELEMENT],
                d[ELEMENT_NAME],
                responsible,
                d["site"],
                category,
                d[ITEM],
                result,
                d[COMMENT],
                naive.to_pydatetime(),
                "Encuesta" if d[UNIT] == "survey" else "Inspección",
            ]
        )
    return rows


def _write_xlsx(path: Path, sheets: dict[str, list[list[Any]]]) -> None:
    wb = Workbook()
    first = True
    for name, rows in sheets.items():
        ws = wb.active if first else wb.create_sheet()
        ws.title = name
        first = False
        for row in rows:
            ws.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def corrupt_sheet_dimension(path: Path, sheet_index: int = 1, ref: str = "A1:A1") -> None:
    """Rewrite the declared ``<dimension>`` of a worksheet so that it lies about its size."""
    tmp = path.with_suffix(".tmp")
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as dst:
        target = f"xl/worksheets/sheet{sheet_index}.xml"
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename == target:
                data = re.sub(
                    rb'<dimension ref="[^"]*"', f'<dimension ref="{ref}"'.encode(), data, count=1
                )
            dst.writestr(info, data)
    tmp.replace(path)


def write_workbooks(
    root: Path, periods: list[str], options: SyntheticOptions | None = None
) -> list[Path]:
    """Write a raw folder tree for ``periods`` under ``root`` and return the files created.

    Layout (tolerant on purpose): ``{yyyy}/{mm}. {Month}/Registros {Month} {yyyy}.xlsx`` plus a
    second workbook, a UTC CSV export, a draft copy and a lock file. With ``quirks`` the main
    sheet carries a wrong month label row, two photo rows without result and a control that
    is duplicated in the second workbook with fewer items.
    """
    options = options or SyntheticOptions()
    written: list[Path] = []
    for period in periods:
        rng = _rng(f"raw-{period}", options)
        df = generate_canonical(period, options)
        first = parse_month(period)
        month_name = MONTH_NAMES_ES[first.month - 1]
        folder_name = (
            f"{first.month:02d}. {month_name}"
            if rng.random() < 0.5
            else f"{first.month}. {month_name.lower()}"
        )
        folder = root / str(first.year) / folder_name

        inspections = df[df[UNIT] == "control"]
        surveys = df[df[UNIT] == "survey"]
        controls = inspections[CONTROL].unique().tolist()

        # Main workbook: every inspection except the ones moved to the second file.
        moved = set(controls[-2:]) if options.quirks else set()
        duplicated = controls[0] if options.quirks else None
        main_rows = _raw_rows_from_canonical(
            inspections[~inspections[CONTROL].isin(moved)], rng, options.quirks
        )
        if options.quirks:
            # A hand-written month label inside the data, with the WRONG year.
            main_rows.insert(
                len(main_rows) // 2,
                [f"{month_name.upper()} {first.year - 1}"] + [None] * (len(RAW_HEADERS) - 1),
            )
            # Two photo rows: informative, no result.
            photo = list(main_rows[3])
            photo[8] = None
            photo[9] = "Foto adjunta"
            main_rows.insert(4, photo)
            main_rows.insert(10, list(photo))
        summary_rows = [
            ["Línea", "Controles"],
            ["Cafetería", 999],
            ["Quiosco", 999],
        ]  # a hand pivot
        main_path = folder / f"Registros {month_name} {first.year}.xlsx"
        _write_xlsx(main_path, {"Registros": [RAW_HEADERS, *main_rows], "Resumen": summary_rows})
        written.append(main_path)

        # Second workbook: the moved controls + the surveys (a mixed file) + a short duplicate.
        second = inspections[inspections[CONTROL].isin(moved)]
        second_rows = _raw_rows_from_canonical(second, rng, options.quirks)
        second_rows += _raw_rows_from_canonical(surveys, rng, options.quirks)
        if duplicated is not None:
            dup = inspections[inspections[CONTROL] == duplicated].head(5)
            second_rows += _raw_rows_from_canonical(dup, rng, options.quirks)
        second_path = folder / f"Registros encuestas {month_name.lower()} {first.year}.xlsx"
        _write_xlsx(
            second_path, {"Portada": [["Exportación"]], "Datos": [RAW_HEADERS, *second_rows]}
        )
        if options.quirks:
            corrupt_sheet_dimension(second_path, sheet_index=2)
        written.append(second_path)

        # A UTC export from an API: ISO timestamps with "Z". Two controls at 23:30Z (next day locally).
        api = inspections[inspections[CONTROL].isin(controls[2:4])].copy()
        api_rows = _raw_rows_from_canonical(api, rng, False)
        api_path = folder / f"registro_api_{period}.csv"
        with api_path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(RAW_HEADERS)
            for r in api_rows:
                r = list(r)
                stamp: datetime = r[10]
                r[10] = (stamp.replace(hour=23, minute=30) - timedelta(days=1)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
                w.writerow(r)
        written.append(api_path)

        if options.quirks:
            draft = folder / f"Registros {month_name} {first.year} - copia.xlsx"
            _write_xlsx(draft, {"Registros": [RAW_HEADERS, *main_rows[:3]]})
            lock = folder / f"~$Registros {month_name} {first.year}.xlsx"
            lock.write_bytes(b"")
    return written
