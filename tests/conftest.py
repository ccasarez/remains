"""Shared fixtures for dregs example tests."""
from __future__ import annotations

import pytest
from pathlib import Path

from dregs import DregsStore

EXAMPLES_ROOT = Path(__file__).parent.parent / "examples"


def _paths(subdir: str | None = None) -> dict[str, Path]:
    base = EXAMPLES_ROOT / subdir if subdir else EXAMPLES_ROOT
    return {
        "ontology": base / "ontology.ttl",
        "shapes": base / "shapes.ttl",
        "good_data": base / "data_good.ttl",
        "bad_data": base / "data_bad.ttl",
    }


EXAMPLE_SETS = {
    "default": _paths(),
    "foaf": _paths("foaf"),
    "schema-org": _paths("schema-org"),
    "dcat": _paths("dcat"),
}


@pytest.fixture(params=EXAMPLE_SETS.keys())
def example(request):
    """Parametrized fixture yielding paths for each example set."""
    return {**EXAMPLE_SETS[request.param], "name": request.param}


@pytest.fixture
def store(tmp_path, example):
    """Initialized DregsStore for the current example set."""
    db = DregsStore(tmp_path / "test.db")
    db.init(schema_path=example["ontology"], shacl_path=example["shapes"])
    yield db
    db.close()


@pytest.fixture
def loaded_store(store, example):
    """DregsStore with good data already loaded."""
    result = store.load(example["good_data"], graph_name="test")
    assert result["loaded"], f"good data failed to load: {result}"
    return store
