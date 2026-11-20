from pathlib import Path

from typer.testing import CliRunner

from reportkit.cli import app

ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0 and "reportkit 0.1.0" in result.output


def test_demo_then_comments_validate_and_md(tmp_path: Path) -> None:
    out = tmp_path / "demo"
    result = runner.invoke(app, ["demo", "--out", str(out), "--months", "2", "--no-pdf"])
    assert result.exit_code == 0, result.output
    assert "monthly:" in result.output and "semester:" in result.output
    docx = next((out / "reports").rglob("Informe_monthly_*.docx"))
    assert "SINTÉTICO" in docx.name

    result = runner.invoke(
        app,
        [
            "comments",
            "--period",
            "2026-03",
            "--data",
            str(out / "data"),
            "--out",
            str(tmp_path / "c"),
        ],
    )
    assert result.exit_code == 0 and (tmp_path / "c" / "2026-03.yaml").is_file()

    result = runner.invoke(
        app,
        ["validate", "--period", "2026-03", "--delivered", str(docx), "--data", str(out / "data")],
    )
    assert result.exit_code == 0, result.output
    assert "OK: sin discrepancias" in result.output

    result = runner.invoke(
        app, ["md", str(ROOT / "examples" / "demo_deck.md"), "--out", str(tmp_path / "md")]
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "md" / "demo_deck.docx").is_file() and (
        tmp_path / "md" / "demo_deck.pptx"
    ).is_file()


def test_generate_requires_explicit_range(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["generate", "--type", "monthly", "--out", str(tmp_path), "--data", str(tmp_path)]
    )
    assert result.exit_code != 0
