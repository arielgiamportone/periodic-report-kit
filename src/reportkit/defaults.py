"""Default configuration and demo brand shipped inside the package.

The package carries its own ``data/`` folder (``config/*.yaml`` and the fictional brand
``brands/nordal``), resolved with :mod:`importlib.resources` so that an installed wheel works
from any directory. Users with their own rules point ``--config`` / ``--brand`` elsewhere;
``reportkit paths`` prints where the defaults live so they can be copied and edited.
"""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

DEMO_BRAND = "nordal"


def data_dir() -> Path:
    """Root of the packaged data (``reportkit/data``)."""
    return Path(str(files("reportkit") / "data"))


def default_config_dir() -> Path:
    """Folder with ``data_schema.yaml``, ``groups.yaml``, ``items.yaml``, ``report_catalog.yaml``."""
    return data_dir() / "config"


def default_brand_path(brand: str = DEMO_BRAND) -> Path:
    """``brand.yaml`` of a packaged brand kit (only the fictional demo brand ships)."""
    return data_dir() / "brands" / brand / "brand.yaml"


def check_defaults() -> list[Path]:
    """Return the packaged files the CLI depends on; raises if any is missing."""
    required = [
        default_config_dir() / "data_schema.yaml",
        default_config_dir() / "groups.yaml",
        default_config_dir() / "items.yaml",
        default_config_dir() / "report_catalog.yaml",
        default_brand_path(),
        default_brand_path().parent / "template.docx",
        default_brand_path().parent / "cover_background.png",
    ]
    missing = [p for p in required if not p.is_file()]
    if missing:
        raise FileNotFoundError(f"packaged defaults missing: {[str(m) for m in missing]}")
    return required
