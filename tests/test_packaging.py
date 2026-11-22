"""The installed package must carry its defaults: 0.1.0 shipped only the code and
``reportkit demo`` failed outside the repository checkout."""

import os
import subprocess
import sys
from pathlib import Path

import reportkit
from reportkit.defaults import check_defaults, data_dir, default_brand_path, default_config_dir

ROOT = Path(__file__).resolve().parents[1]


def test_defaults_live_inside_the_package_not_the_repo_root() -> None:
    package_dir = Path(reportkit.__file__).resolve().parent
    for path in check_defaults():
        assert path.is_file(), path
        assert package_dir in path.resolve().parents, f"{path} is outside the package"
    assert (
        not (ROOT / "config").exists() and not (ROOT / "brands").exists()
    )  # single source of truth


def test_demo_brand_assets_are_complete() -> None:
    brand_dir = default_brand_path().parent
    assert {p.name for p in brand_dir.iterdir() if p.is_file()} >= {
        "brand.yaml",
        "template.docx",
        "cover_background.png",
    }
    assert {p.name for p in default_config_dir().glob("*.yaml")} == {
        "data_schema.yaml",
        "groups.yaml",
        "items.yaml",
        "report_catalog.yaml",
    }
    assert data_dir().name == "data"


def test_cli_demo_runs_from_a_directory_outside_the_repo(tmp_path: Path) -> None:
    """Reproduces the 0.1.0 failure: the CLI must not depend on the current directory."""
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    out = tmp_path / "out"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "reportkit.cli",
            "demo",
            "--out",
            str(out),
            "--months",
            "1",
            "--no-pdf",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert next((out / "reports").rglob("Informe_monthly_*.docx"), None) is not None
