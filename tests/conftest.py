"""Shared fixtures for dregs tests."""
from __future__ import annotations

import pytest
from pathlib import Path

from dregs import DregsStore

EXAMPLES_ROOT = Path(__file__).parent.parent / "examples"


@pytest.fixture
def store(tmp_path):
    """Initialized DregsStore with example ontology and shapes."""
    db = DregsStore(tmp_path / "test.db")
    db.init(
        ontology_path=EXAMPLES_ROOT / "ontology.ttl",
        shacl_path=EXAMPLES_ROOT / "shapes.ttl",
    )
    yield db
    db.close()


@pytest.fixture
def loaded_store(store):
    """DregsStore with good data already loaded."""
    result = store.load(EXAMPLES_ROOT / "data_good.ttl")
    assert result["loaded"], f"good data failed to load: {result}"
    return store
