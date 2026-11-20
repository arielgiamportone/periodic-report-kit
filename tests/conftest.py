from pathlib import Path

import pytest

from reportkit.schema import DataSchema, GroupCatalog, ItemCatalog

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"


@pytest.fixture(scope="session")
def schema() -> DataSchema:
    return DataSchema.load(CONFIG / "data_schema.yaml")


@pytest.fixture(scope="session")
def groups() -> GroupCatalog:
    return GroupCatalog.load(CONFIG / "groups.yaml")


@pytest.fixture(scope="session")
def items() -> ItemCatalog:
    return ItemCatalog.load(CONFIG / "items.yaml")
