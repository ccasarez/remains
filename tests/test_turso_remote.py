"""Integration tests against a live Turso database.

Gated behind DREGS_TEST_DSN and DREGS_TEST_AUTH_TOKEN — separate from the
production env vars so tests never accidentally run against a real database.

Skipped automatically when these are not set.  Run with:

    export DREGS_TEST_DSN=libsql://dregs-pirxthedev.aws-us-west-2.turso.io
    export DREGS_TEST_AUTH_TOKEN=eyJ...
    pytest tests/test_turso_remote.py -v

These tests exercise the full dregs lifecycle over a real remote connection:
init, load, query, export, list, drop, stats, and CLI commands.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

EXAMPLES_ROOT = Path(__file__).parent.parent / "examples"

_test_dsn = os.environ.get("DREGS_TEST_DSN", "")
_test_token = os.environ.get("DREGS_TEST_AUTH_TOKEN", "")

_has_turso = bool(
    _test_dsn.startswith(("libsql://", "https://", "http://"))
    and _test_token
)

pytestmark = pytest.mark.skipif(
    not _has_turso,
    reason="DREGS_TEST_DSN (remote URL) and DREGS_TEST_AUTH_TOKEN not set",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TABLES = ["triples", "graphs", "prefixes", "metadata"]


@pytest.fixture(autouse=True)
def _turso_env(monkeypatch):
    """Inject test credentials into DREGS_DSN / DREGS_AUTH_TOKEN for every test."""
    monkeypatch.setenv("DREGS_DSN", _test_dsn)
    monkeypatch.setenv("DREGS_AUTH_TOKEN", _test_token)


def _wipe_remote():
    """Drop all dregs tables from the remote database so each test starts clean."""
    from dregs.store import DregsStore

    store = DregsStore(_test_dsn)
    conn = store._connect()
    for table in _TABLES:
        try:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        except Exception:
            pass
    conn.commit()
    store.close()


@pytest.fixture(autouse=True)
def clean_remote():
    """Wipe remote DB before and after every test."""
    _wipe_remote()
    yield
    _wipe_remote()


# ---------------------------------------------------------------------------
# Store: init
# ---------------------------------------------------------------------------


class TestRemoteInit:
    """DregsStore.init() should create tables and store metadata remotely."""

    def test_init_bare(self):
        from dregs.store import DregsStore

        store = DregsStore()
        result = store.init()
        assert result["schema_triples"] == 0
        assert result["shacl_triples"] == 0
        store.close()

    def test_init_with_schema_and_shacl(self):
        from dregs.store import DregsStore

        store = DregsStore()
        result = store.init(
            schema_path=EXAMPLES_ROOT / "ontology.ttl",
            shacl_path=EXAMPLES_ROOT / "shapes.ttl",
        )
        assert result["schema_triples"] > 0
        assert result["shacl_triples"] > 0
        store.close()

    def test_stats_after_init(self):
        from dregs.store import DregsStore

        store = DregsStore()
        store.init(schema_path=EXAMPLES_ROOT / "ontology.ttl")
        stats = store.stats()
        assert stats["version"] == "0.1.0"
        assert stats["total_triples"] > 0
        assert stats["graph_count"] >= 1
        assert "schema" in stats["by_type"]
        store.close()

    def test_prefixes_stored(self):
        from dregs.store import DregsStore

        store = DregsStore()
        store.init(schema_path=EXAMPLES_ROOT / "ontology.ttl")
        prefixes = store.get_prefixes()
        assert "owl" in prefixes
        assert "rdf" in prefixes
        assert prefixes["owl"] == "http://www.w3.org/2002/07/owl#"
        store.close()


# ---------------------------------------------------------------------------
# Store: load + validation
# ---------------------------------------------------------------------------


class TestRemoteLoad:
    """Loading data into a remote Turso DB should work identically to local."""

    @pytest.fixture(autouse=True)
    def _init_store(self):
        from dregs.store import DregsStore

        store = DregsStore()
        store.init(
            schema_path=EXAMPLES_ROOT / "ontology.ttl",
            shacl_path=EXAMPLES_ROOT / "shapes.ttl",
        )
        store.close()

    def test_load_good_data(self):
        from dregs.store import DregsStore

        store = DregsStore()
        result = store.load(
            EXAMPLES_ROOT / "data_good.ttl",
            graph_name="test-good",
        )
        assert result["loaded"] is True
        assert result["triple_count"] > 0
        assert result["graph"] == "test-good"
        store.close()

    def test_load_bad_data_rejected(self):
        from dregs.store import DregsStore

        store = DregsStore()
        result = store.load(EXAMPLES_ROOT / "data_bad.ttl")
        assert result["loaded"] is False
        assert result["validation"].conforms is False
        assert len(result["validation"].shacl_violations) > 0
        store.close()

    def test_load_no_validate(self):
        from dregs.store import DregsStore

        store = DregsStore()
        result = store.load(
            EXAMPLES_ROOT / "data_bad.ttl",
            graph_name="forced",
            validate=False,
        )
        assert result["loaded"] is True
        assert result["triple_count"] > 0
        store.close()


# ---------------------------------------------------------------------------
# Store: query (SPARQL)
# ---------------------------------------------------------------------------


class TestRemoteQuery:
    """SPARQL queries against a remote Turso-backed store."""

    @pytest.fixture(autouse=True)
    def _load_data(self):
        from dregs.store import DregsStore

        store = DregsStore()
        store.init(
            schema_path=EXAMPLES_ROOT / "ontology.ttl",
            shacl_path=EXAMPLES_ROOT / "shapes.ttl",
        )
        store.load(
            EXAMPLES_ROOT / "data_good.ttl",
            graph_name="query-test",
        )
        store.close()

    def test_select_query(self):
        from dregs.sparql import execute_sparql
        from dregs.store import DregsStore

        store = DregsStore()
        result = execute_sparql(
            store,
            "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 5",
        )
        assert len(result.bindings) > 0
        assert len(result.bindings) <= 5
        store.close()

    def test_count_query(self):
        from dregs.sparql import execute_sparql
        from dregs.store import DregsStore

        store = DregsStore()
        result = execute_sparql(
            store,
            "SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }",
        )
        count = int(result.bindings[0]["n"])
        assert count > 0
        store.close()

    def test_ask_query(self):
        from dregs.sparql import execute_sparql
        from dregs.store import DregsStore

        store = DregsStore()
        result = execute_sparql(
            store,
            "ASK WHERE { ?s ?p ?o }",
        )
        assert result.bindings[0]["result"] is True
        store.close()


# ---------------------------------------------------------------------------
# Store: graphs lifecycle (list, drop)
# ---------------------------------------------------------------------------


class TestRemoteGraphs:
    """Graph management operations on a remote Turso DB."""

    @pytest.fixture(autouse=True)
    def _load_data(self):
        from dregs.store import DregsStore

        store = DregsStore()
        store.init(
            schema_path=EXAMPLES_ROOT / "ontology.ttl",
            shacl_path=EXAMPLES_ROOT / "shapes.ttl",
        )
        store.load(
            EXAMPLES_ROOT / "data_good.ttl",
            graph_name="graph-lifecycle",
        )
        store.close()

    def test_list_graphs(self):
        from dregs.store import DregsStore

        store = DregsStore()
        graph_list = store.list_graphs()
        uris = [g.uri for g in graph_list]
        assert "graph-lifecycle" in uris
        # schema and shacl graphs should also be present
        types = {g.graph_type for g in graph_list}
        assert "schema" in types
        assert "shacl" in types
        assert "data" in types
        store.close()

    def test_load_graph(self):
        from dregs.store import DregsStore

        store = DregsStore()
        g = store.load_graph("graph-lifecycle")
        assert len(g) > 0
        store.close()

    def test_load_all_graphs(self):
        from dregs.store import DregsStore

        store = DregsStore()
        g = store.load_all_graphs()
        assert len(g) > 0
        store.close()

    def test_drop_graph(self):
        from dregs.store import DregsStore

        store = DregsStore()
        before = store.stats()["total_triples"]
        count = store.drop_graph("graph-lifecycle")
        assert count > 0
        after = store.stats()["total_triples"]
        assert after < before

        # graph should no longer appear in list
        uris = [g.uri for g in store.list_graphs()]
        assert "graph-lifecycle" not in uris
        store.close()


# ---------------------------------------------------------------------------
# Store: export
# ---------------------------------------------------------------------------


class TestRemoteExport:
    """Export operations on a remote Turso DB."""

    @pytest.fixture(autouse=True)
    def _load_data(self):
        from dregs.store import DregsStore

        store = DregsStore()
        store.init(
            schema_path=EXAMPLES_ROOT / "ontology.ttl",
            shacl_path=EXAMPLES_ROOT / "shapes.ttl",
        )
        store.load(
            EXAMPLES_ROOT / "data_good.ttl",
            graph_name="export-test",
        )
        store.close()

    def test_export_schema(self):
        from dregs.store import DregsStore

        store = DregsStore()
        turtle = store.export_by_type("schema")
        assert len(turtle) > 0
        assert "owl" in turtle.lower() or "@prefix" in turtle
        store.close()

    def test_export_data(self):
        from dregs.store import DregsStore

        store = DregsStore()
        turtle = store.export_by_type("data")
        assert len(turtle) > 0
        store.close()

    def test_export_named_graph(self):
        from dregs.store import DregsStore

        store = DregsStore()
        turtle = store.export_graph("export-test")
        assert len(turtle) > 0
        store.close()

    def test_export_round_trip(self):
        """Exported Turtle should be parseable by rdflib."""
        from rdflib import Graph
        from dregs.store import DregsStore

        store = DregsStore()
        turtle = store.export_by_type("schema")
        g = Graph()
        g.parse(data=turtle, format="turtle")
        assert len(g) > 0
        store.close()


# ---------------------------------------------------------------------------
# CLI commands over remote
# ---------------------------------------------------------------------------


class TestRemoteCLI:
    """CLI commands using DREGS_DSN env var against live Turso."""

    def test_cli_init(self):
        from click.testing import CliRunner
        from dregs.cli import cli

        runner = CliRunner()
        schema = str(EXAMPLES_ROOT / "ontology.ttl")
        shapes = str(EXAMPLES_ROOT / "shapes.ttl")
        result = runner.invoke(cli, ["init", "--schema", schema, "--shacl", shapes])
        assert result.exit_code == 0, result.output
        assert "Initialized" in result.output

    def test_cli_init_then_info(self):
        from click.testing import CliRunner
        from dregs.cli import cli

        runner = CliRunner()
        schema = str(EXAMPLES_ROOT / "ontology.ttl")
        result = runner.invoke(cli, ["init", "--schema", schema])
        assert result.exit_code == 0, result.output

        result = runner.invoke(cli, ["info", "--json"])
        assert result.exit_code == 0, result.output
        import json
        data = json.loads(result.output)
        assert data["total_triples"] > 0
        assert data["version"] == "0.1.0"

    def test_cli_init_load_query(self):
        from click.testing import CliRunner
        from dregs.cli import cli

        runner = CliRunner()
        schema = str(EXAMPLES_ROOT / "ontology.ttl")
        shapes = str(EXAMPLES_ROOT / "shapes.ttl")
        good = str(EXAMPLES_ROOT / "data_good.ttl")

        # init
        result = runner.invoke(cli, ["init", "--schema", schema, "--shacl", shapes])
        assert result.exit_code == 0, result.output

        # load
        result = runner.invoke(cli, ["load", good, "--graph", "cli-remote"])
        assert result.exit_code == 0, result.output
        assert "Loaded" in result.output

        # query
        result = runner.invoke(
            cli, ["query", "SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }"]
        )
        assert result.exit_code == 0, result.output

    def test_cli_graphs(self):
        from click.testing import CliRunner
        from dregs.cli import cli

        runner = CliRunner()
        schema = str(EXAMPLES_ROOT / "ontology.ttl")
        runner.invoke(cli, ["init", "--schema", schema])

        result = runner.invoke(cli, ["graphs", "--json"])
        assert result.exit_code == 0, result.output
        import json
        data = json.loads(result.output)
        assert len(data) >= 1

    def test_cli_export(self):
        from click.testing import CliRunner
        from dregs.cli import cli

        runner = CliRunner()
        schema = str(EXAMPLES_ROOT / "ontology.ttl")
        runner.invoke(cli, ["init", "--schema", schema])

        result = runner.invoke(cli, ["export", "--type", "schema"])
        assert result.exit_code == 0, result.output
        assert "@prefix" in result.output

    def test_cli_drop(self):
        from click.testing import CliRunner
        from dregs.cli import cli

        runner = CliRunner()
        schema = str(EXAMPLES_ROOT / "ontology.ttl")
        shapes = str(EXAMPLES_ROOT / "shapes.ttl")
        good = str(EXAMPLES_ROOT / "data_good.ttl")

        runner.invoke(cli, ["init", "--schema", schema, "--shacl", shapes])
        runner.invoke(cli, ["load", good, "--graph", "to-drop"])

        result = runner.invoke(cli, ["drop", "--graph", "to-drop", "--yes", "--json"])
        assert result.exit_code == 0, result.output
        import json
        data = json.loads(result.output)
        assert data["dropped"] == "to-drop"
        assert data["triples_deleted"] > 0

    def test_cli_load_bad_data_rejected(self):
        from click.testing import CliRunner
        from dregs.cli import cli

        runner = CliRunner()
        schema = str(EXAMPLES_ROOT / "ontology.ttl")
        shapes = str(EXAMPLES_ROOT / "shapes.ttl")
        bad = str(EXAMPLES_ROOT / "data_bad.ttl")

        runner.invoke(cli, ["init", "--schema", schema, "--shacl", shapes])

        result = runner.invoke(cli, ["load", bad])
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Data integrity: round-trip fidelity
# ---------------------------------------------------------------------------


class TestRemoteDataFidelity:
    """Verify that data stored remotely is identical when read back."""

    def test_triple_count_matches(self):
        """Triple count from stats() should match what was loaded."""
        from rdflib import Graph
        from dregs.store import DregsStore

        # Parse locally to get expected count
        local = Graph()
        local.parse(str(EXAMPLES_ROOT / "data_good.ttl"), format="turtle")
        expected = len(local)

        store = DregsStore()
        store.init(
            schema_path=EXAMPLES_ROOT / "ontology.ttl",
            shacl_path=EXAMPLES_ROOT / "shapes.ttl",
        )
        result = store.load(
            EXAMPLES_ROOT / "data_good.ttl",
            graph_name="fidelity",
        )
        assert result["triple_count"] == expected

        # Read back and verify count
        g = store.load_graph("fidelity")
        assert len(g) == expected
        store.close()

    def test_triples_survive_close_and_reopen(self):
        """Data persists across store close/reopen (the whole point of Turso)."""
        from dregs.store import DregsStore

        store = DregsStore()
        store.init(
            schema_path=EXAMPLES_ROOT / "ontology.ttl",
            shacl_path=EXAMPLES_ROOT / "shapes.ttl",
        )
        store.load(
            EXAMPLES_ROOT / "data_good.ttl",
            graph_name="persist-test",
        )
        count_before = store.stats()["total_triples"]
        store.close()

        # Reopen — fresh connection, no local state
        store2 = DregsStore()
        count_after = store2.stats()["total_triples"]
        assert count_after == count_before

        graphs = [g.uri for g in store2.list_graphs()]
        assert "persist-test" in graphs
        store2.close()
