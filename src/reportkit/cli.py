"""Command line: ``reportkit generate | comments | validate | md | demo``."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from . import __version__
from .brand import BrandKit
from .catalog import ReportCatalog
from .comments import CommentStore
from .loaders import load_range
from .model import month_range
from .report import ReportRequest, build_report
from .schema import DataSchema, GroupCatalog, ItemCatalog

app = typer.Typer(
    help="Periodic branded reports from tabular data.", no_args_is_help=True, add_completion=False
)

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PACKAGE_ROOT / "config"
DEFAULT_BRAND = PACKAGE_ROOT / "brands" / "nordal" / "brand.yaml"

ConfigOpt = Annotated[
    Path,
    typer.Option(
        "--config",
        help="Folder with data_schema.yaml, groups.yaml, items.yaml, report_catalog.yaml",
    ),
]
BrandOpt = Annotated[Path, typer.Option("--brand", help="brand.yaml of the brand kit")]
DataOpt = Annotated[Path, typer.Option("--data", help="Root folder of the raw files")]


def _config(config: Path) -> tuple[DataSchema, GroupCatalog, ItemCatalog, ReportCatalog]:
    return (
        DataSchema.load(config / "data_schema.yaml"),
        GroupCatalog.load(config / "groups.yaml"),
        ItemCatalog.load(config / "items.yaml"),
        ReportCatalog.load(config / "report_catalog.yaml"),
    )


def _echo_warnings(warnings, limit: int = 40) -> None:
    for w in warnings[:limit]:
        typer.echo(f"  - {w}")
    if len(warnings) > limit:
        typer.echo(f"  ... {len(warnings) - limit} more")


@app.callback(invoke_without_command=True)
def main(version: Annotated[bool, typer.Option("--version", is_eager=True)] = False) -> None:
    if version:
        typer.echo(f"reportkit {__version__}")
        raise typer.Exit()


@app.command()
def generate(
    report_type: Annotated[str, typer.Option("--type", help="monthly | semester | annual")],
    start: Annotated[str, typer.Option("--from", help="First month YYYY-MM")],
    end: Annotated[str, typer.Option("--to", help="Last month YYYY-MM (inclusive)")],
    out: Annotated[Path, typer.Option("--out", help="Output root; each run gets its own folder")],
    data: DataOpt,
    config: ConfigOpt = DEFAULT_CONFIG,
    brand: BrandOpt = DEFAULT_BRAND,
    pdf: Annotated[
        bool,
        typer.Option(
            "--pdf", help="Also render the PDF (a period counts as delivered only with it)"
        ),
    ] = False,
    recipient: Annotated[str, typer.Option(help="Recipient shown on the cover")] = "Cliente",
    reference: Annotated[str, typer.Option(help="Reference shown on the cover")] = "",
    comments: Annotated[
        Path | None, typer.Option(help="Folder with <period>.yaml comment files")
    ] = None,
    synthetic: Annotated[
        bool, typer.Option("--synthetic", help="Tag the output as synthetic data")
    ] = False,
    no_cache: Annotated[bool, typer.Option("--no-cache")] = False,
) -> None:
    """Generate a monthly / semester / annual report for an explicit month range."""
    schema, groups, items, catalog = _config(config)
    kit = BrandKit.load(brand)
    period = load_range(start, end, schema, groups, items, data, use_cache=not no_cache)
    store = CommentStore.load(
        f"{start}_{end}" if start != end else start, comments or (out / "comments")
    )
    request = ReportRequest(
        report_type,
        start,
        end,
        recipient=recipient,
        reference=reference,
        synthetic=synthetic,
        pdf=pdf,
    )
    result = build_report(period, request, kit, catalog, groups, store, out)
    typer.echo(f"docx: {result.docx}")
    if result.pdf:
        typer.echo(f"pdf:  {result.pdf}")
    typer.echo(
        f"version v{result.version:03d} · gaps: {result.gaps} · warnings: {len(result.warnings)}"
    )
    _echo_warnings(result.warnings)


@app.command()
def comments(
    period: Annotated[str, typer.Option("--period", help="Month YYYY-MM or range YYYY-MM_YYYY-MM")],
    data: DataOpt,
    out: Annotated[Path, typer.Option("--out", help="Folder where <period>.yaml is written")],
    config: ConfigOpt = DEFAULT_CONFIG,
) -> None:
    """Write (or refresh) the comment template of a period with the current hints."""
    from .report import _hints

    schema, groups, items, _catalog = _config(config)
    start, _, end = period.partition("_")
    end = end or start
    loaded = load_range(start, end, schema, groups, items, data)
    hints = {"summary": _hints(loaded.data)}
    for g in groups.groups:
        slice_ = loaded.data[loaded.data["group"] == g.code]
        if not slice_.empty:
            hints[f"group:{g.code}"] = _hints(slice_, g.unit)
    store = CommentStore.load(period, out)
    path = store.write_template(hints)
    typer.echo(f"template: {path}")


@app.command()
def validate(
    period: Annotated[str, typer.Option("--period", help="Month YYYY-MM or range YYYY-MM_YYYY-MM")],
    delivered: Annotated[Path, typer.Option("--delivered", help="Delivered .docx to contrast")],
    data: DataOpt,
    config: ConfigOpt = DEFAULT_CONFIG,
) -> None:
    """Contrast the model against a delivered document; exit 1 on any discrepancy."""
    from .validator import contrast

    schema, groups, items, _catalog = _config(config)
    start, _, end = period.partition("_")
    loaded = load_range(start, end or start, schema, groups, items, data)
    report = contrast(loaded, delivered, groups)
    for line in report.summary_lines():
        typer.echo(line)
    raise typer.Exit(code=report.exit_code)


@app.command()
def md(
    source: Annotated[Path, typer.Argument(help="Markdown file (--- separates slides)")],
    docx: Annotated[bool, typer.Option("--docx")] = False,
    pptx: Annotated[bool, typer.Option("--pptx")] = False,
    out: Annotated[
        Path | None, typer.Option("--out", help="Output folder (default: next to the .md)")
    ] = None,
    brand: BrandOpt = DEFAULT_BRAND,
) -> None:
    """Build a .docx and/or .pptx from a Markdown file with visual blocks."""
    from .render_md import md_to_docx, md_to_pptx

    if not (docx or pptx):
        docx = pptx = True
    kit = BrandKit.load(brand)
    folder = out or source.parent
    if docx:
        typer.echo(f"docx: {md_to_docx(source, kit, folder / source.with_suffix('.docx').name)}")
    if pptx:
        typer.echo(f"pptx: {md_to_pptx(source, kit, folder / source.with_suffix('.pptx').name)}")


@app.command()
def demo(
    out: Annotated[
        Path, typer.Option("--out", help="Folder for the synthetic data and the reports")
    ],
    pdf: Annotated[bool, typer.Option("--pdf/--no-pdf")] = True,
    months: Annotated[int, typer.Option(help="Months of synthetic data to generate")] = 6,
    config: ConfigOpt = DEFAULT_CONFIG,
    brand: BrandOpt = DEFAULT_BRAND,
) -> None:
    """Generate synthetic raw data and a monthly + semester report tagged as synthetic."""
    from .synthetic import SyntheticOptions, write_workbooks

    periods = month_range("2025-10", "2026-03")[-months:]
    data = out / "data"
    files = write_workbooks(data, periods, SyntheticOptions(seed=7))
    typer.echo(f"synthetic files: {len(files)} under {data}")
    schema, groups, items, catalog = _config(config)
    kit = BrandKit.load(brand)
    for report_type, start, end in (
        ("monthly", periods[-1], periods[-1]),
        ("semester", periods[0], periods[-1]),
    ):
        loaded = load_range(start, end, schema, groups, items, data)
        store = CommentStore.load(start if start == end else f"{start}_{end}", out / "comments")
        request = ReportRequest(
            report_type, start, end, recipient="Cliente de demostración", synthetic=True, pdf=pdf
        )
        result = build_report(loaded, request, kit, catalog, groups, store, out / "reports")
        typer.echo(
            f"{report_type}: {result.docx}" + (f" + {result.pdf.name}" if result.pdf else "")
        )


if __name__ == "__main__":  # pragma: no cover
    app()
