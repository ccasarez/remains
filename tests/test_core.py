"""Tests for remains: 3 fixed graphs, system/user split."""
from __future__ import annotations

from pathlib import Path

import pytest
from rdflib import Graph, Namespace, RDF, RDFS

from remains.store import RemainsStore

EXAMPLES_ROOT = Path(__file__).parent.parent / "examples"
SYSTEM_DIR = Path(__file__).parent.parent / "src" / "remains" / "system"

REMAINS = Namespace("urn:remains:system#")
REMAINS_SH = Namespace("urn:remains:shapes#")
EX = Namespace("http://example.com/ontology#")


# ---------------------------------------------------------------------------
# Phase 1: Core DB restructure - 3 fixed graphs
# ---------------------------------------------------------------------------


class TestInit:
    """remains init creates 3-graph structure with system + user ontology/shapes."""

    def test_init_creates_three_graphs(self, tmp_path):
        """Init should create exactly 3 graphs: default, urn:ontology, urn:shacl."""
        db = RemainsStore(tmp_path / "test.db")
        db.init()
        db.update_ontology(EXAMPLES_ROOT / "ontology.ttl")
        db.update_shacl(EXAMPLES_ROOT / "shapes.ttl")

        conn = db._connect()
        graphs = conn.execute(
            "SELECT DISTINCT graph FROM triples ORDER BY graph"
        ).fetchall()
        graph_names = {r[0] for r in graphs}

        assert "" in graph_names or graph_names  # default graph may have no data yet
        assert "urn:ontology" in graph_names
        assert "urn:shacl" in graph_names
        # No other graphs
        assert graph_names <= {"", "urn:ontology", "urn:shacl"}
        db.close()

    def test_init_loads_system_ontology(self, tmp_path):
        """System ontology (remains:RequiresDisplayName, etc.) must be in urn:ontology."""
        db = RemainsStore(tmp_path / "test.db")
        db.init()
        db.update_ontology(EXAMPLES_ROOT / "ontology.ttl")
        db.update_shacl(EXAMPLES_ROOT / "shapes.ttl")

        conn = db._connect()
        marker_exists = conn.execute(
            "SELECT COUNT(*) FROM triples WHERE subject = ? AND predicate = ? AND graph = ?",
            (str(REMAINS.RequiresDisplayName), str(RDF.type), "urn:ontology"),
        ).fetchone()[0]
        assert marker_exists > 0
        db.close()

    def test_init_loads_user_ontology(self, tmp_path):
        """User ontology classes must also be in urn:ontology."""
        db = RemainsStore(tmp_path / "test.db")
        db.init()
        db.update_ontology(EXAMPLES_ROOT / "ontology.ttl")
        db.update_shacl(EXAMPLES_ROOT / "shapes.ttl")

        conn = db._connect()
        # Check user class ex:Person exists in urn:ontology
        person_exists = conn.execute(
            "SELECT COUNT(*) FROM triples WHERE subject = ? AND predicate = ? AND graph = ?",
            (str(EX.Person), str(RDF.type), "urn:ontology"),
        ).fetchone()[0]
        assert person_exists > 0
        db.close()

    def test_init_loads_system_shapes(self, tmp_path):
        """System shapes (remains-sh:DisplayNameShape, etc.) must be in urn:shacl."""
        db = RemainsStore(tmp_path / "test.db")
        db.init()
        db.update_ontology(EXAMPLES_ROOT / "ontology.ttl")
        db.update_shacl(EXAMPLES_ROOT / "shapes.ttl")

        conn = db._connect()
        display_shape = conn.execute(
            "SELECT COUNT(*) FROM triples WHERE subject = ? AND graph = ?",
            (str(REMAINS_SH.DisplayNameShape), "urn:shacl"),
        ).fetchone()[0]
        assert display_shape > 0
        db.close()

    def test_init_loads_user_shapes(self, tmp_path):
        """User shapes must also be in urn:shacl."""
        db = RemainsStore(tmp_path / "test.db")
        db.init()
        db.update_ontology(EXAMPLES_ROOT / "ontology.ttl")
        db.update_shacl(EXAMPLES_ROOT / "shapes.ttl")

        conn = db._connect()
        # The examples/shapes.ttl has shapes — check any user shape exists
        user_shapes = conn.execute(
            "SELECT COUNT(*) FROM triples WHERE graph = ? AND subject NOT LIKE 'urn:remains:%'",
            ("urn:shacl",),
        ).fetchone()[0]
        assert user_shapes > 0
        db.close()


class TestLoad:
    """Loading data goes into default graph only."""

    @pytest.fixture
    def store(self, tmp_path):
        db = RemainsStore(tmp_path / "test.db")
        db.init()
        db.update_ontology(EXAMPLES_ROOT / "ontology.ttl")
        db.update_shacl(EXAMPLES_ROOT / "shapes.ttl")
        yield db
        db.close()

    def test_load_into_default_graph(self, store):
        """Data loads into default (empty string) graph."""
        result = store.load(EXAMPLES_ROOT / "data_good.ttl")
        assert result["loaded"] is True
        assert result["triple_count"] > 0

        conn = store._connect()
        data_triples = conn.execute(
            "SELECT COUNT(*) FROM triples WHERE graph = ''",
        ).fetchone()[0]
        assert data_triples > 0

    def test_load_rejects_bad_data(self, store):
        """Bad data should still fail validation."""
        result = store.load(EXAMPLES_ROOT / "data_bad.ttl")
        assert result["loaded"] is False

    def test_no_named_graphs_created(self, store):
        """Loading data should not create any named data graphs."""
        store.load(EXAMPLES_ROOT / "data_good.ttl")

        conn = store._connect()
        graphs = conn.execute(
            "SELECT DISTINCT graph FROM triples"
        ).fetchall()
        graph_names = {r[0] for r in graphs}
        assert graph_names <= {"", "urn:ontology", "urn:shacl"}


class TestOntologyShapesAreNotDataTargets:
    """Ontology-policing SHACL shapes must not fire against ontology nodes.

    Regression test: gist's shapes use SPARQL-based targets that select all
    ``owl:Class`` and ``owl:ObjectProperty`` nodes in the gist namespace and
    require each to have a ``skos:definition`` and a conforming label. With
    ``advanced=True``, pyshacl merges the ontology into the data graph for
    target evaluation, which used to produce hundreds of spurious violations
    against the gist ontology itself whenever a user loaded *any* data file.
    ``remains load`` should only police the user's data, not the ontology.
    """

    GIST_ROOT = EXAMPLES_ROOT / "gist"

    @pytest.fixture
    def store(self, tmp_path):
        db = RemainsStore(tmp_path / "test.db")
        db.init()
        db.update_ontology(self.GIST_ROOT / "ontology.ttl")
        db.update_shacl(self.GIST_ROOT / "shapes.ttl")
        yield db
        db.close()

    def test_clean_user_data_loads_with_gist_shapes(self, store, tmp_path):
        """Minimal user data should load cleanly despite gist shapes being present."""
        data = tmp_path / "user_data.ttl"
        data.write_text(
            """
@prefix gist: <https://w3id.org/semanticarts/ns/ontology/gist/> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex:   <http://example.com/data#> .

ex:alice a gist:Person ;
    skos:prefLabel "Alice" .
"""
        )
        result = store.load(data)
        assert result["loaded"] is True, (
            f"clean user data rejected by ontology-policing shapes: "
            f"{getattr(result.get('validation'), 'shacl_violations', None)}"
        )

    def test_run_validation_filters_ontology_only_violations(self):
        """run_validation drops violations whose focus node is only in the ontology."""
        from rdflib import Graph

        from remains.store import run_validation

        ontology = Graph()
        ontology.parse(
            data="""
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix ex:  <http://example.com/ontology#> .

ex:Person a owl:Class .
ex:UnusedClass a owl:Class .
""",
            format="turtle",
        )

        shapes = Graph()
        shapes.parse(
            data="""
@prefix sh:   <http://www.w3.org/ns/shacl#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex:   <http://example.com/shapes#> .

ex:ClassDefinitionShape a sh:NodeShape ;
    sh:targetClass owl:Class ;
    sh:property [
        sh:path rdfs:comment ;
        sh:minCount 1 ;
        sh:message "Classes must have an rdfs:comment" ;
    ] .
""",
            format="turtle",
        )

        data = Graph()
        data.parse(
            data="""
@prefix ex:   <http://example.com/data#> .
@prefix cls:  <http://example.com/ontology#> .

ex:alice a cls:Person .
""",
            format="turtle",
        )

        result = run_validation(
            schema_graph=ontology,
            data_graph=data,
            shacl_graph=shapes,
        )

        # Without the fix, ex:Person and ex:UnusedClass (from the ontology)
        # would trigger violations because pyshacl merges ont_graph into the
        # data graph for target evaluation. With the fix, those are filtered
        # out because their focus nodes only live in the ontology.
        assert result.conforms, (
            f"ontology-only violations leaked through: {result.shacl_violations}"
        )


class TestPrompt:
    """remains prompt generates from urn:ontology graph."""

    @pytest.fixture
    def store(self, tmp_path):
        db = RemainsStore(tmp_path / "test.db")
        db.init()
        db.update_ontology(EXAMPLES_ROOT / "ontology.ttl")
        db.update_shacl(EXAMPLES_ROOT / "shapes.ttl")
        yield db
        db.close()

    def test_prompt_includes_user_classes(self, store):
        """Prompt should include user ontology classes."""
        from remains.prompt import prompt_from_store

        output = prompt_from_store(store)
        assert "Person" in output
        assert "Organization" in output
        assert "Meeting" in output

    def test_prompt_excludes_system_classes(self, store):
        """Prompt should NOT include system classes."""
        from remains.prompt import prompt_from_store

        output = prompt_from_store(store)
        assert "RequiresDisplayName" not in output


class TestNamespaceProtection:
    """System namespaces are protected from user modification."""

    @pytest.fixture
    def store(self, tmp_path):
        db = RemainsStore(tmp_path / "test.db")
        db.init()
        db.update_ontology(EXAMPLES_ROOT / "ontology.ttl")
        db.update_shacl(EXAMPLES_ROOT / "shapes.ttl")
        yield db
        db.close()

    def test_update_ontology_rejects_system_namespace(self, store, tmp_path):
        """Updating ontology with system namespace triples should fail."""
        evil = tmp_path / "evil.ttl"
        evil.write_text("""
@prefix remains: <urn:remains:system#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

remains:RequiresDisplayName rdfs:label "Hacked" .
remains:EvilClass a owl:Class .
""")
        with pytest.raises(ValueError, match="system namespace"):
            store.update_ontology(evil)

    def test_update_shacl_rejects_system_namespace(self, store, tmp_path):
        """Updating shapes with system namespace triples should fail."""
        evil = tmp_path / "evil-shapes.ttl"
        evil.write_text("""
@prefix remains-sh: <urn:remains:shapes#> .
@prefix sh: <http://www.w3.org/ns/shacl#> .

remains-sh:DisplayNameShape sh:deactivated true .
""")
        with pytest.raises(ValueError, match="system namespace"):
            store.update_shacl(evil)


class TestExport:
    """Export with new flags."""

    @pytest.fixture
    def store(self, tmp_path):
        db = RemainsStore(tmp_path / "test.db")
        db.init()
        db.update_ontology(EXAMPLES_ROOT / "ontology.ttl")
        db.update_shacl(EXAMPLES_ROOT / "shapes.ttl")
        db.load(EXAMPLES_ROOT / "data_good.ttl")
        yield db
        db.close()

    def test_export_data_only(self, store):
        """Export default graph data only."""
        ttl = store.export("data")
        assert len(ttl) > 0
        # Parse it to verify it's valid turtle
        g = Graph()
        g.parse(data=ttl, format="turtle")
        assert len(g) > 0

    def test_export_ontology_user_only(self, store):
        """Export user ontology triples only (no system)."""
        ttl = store.export("ontology")
        assert len(ttl) > 0
        assert "remains:system" not in ttl.lower() or "urn:remains:system" not in ttl

    def test_export_all(self, store):
        """Export everything."""
        ttl = store.export("all")
        g = Graph()
        g.parse(data=ttl, format="turtle")
        assert len(g) > 0


class TestInfo:
    """Info command shows system/user split."""

    @pytest.fixture
    def store(self, tmp_path):
        db = RemainsStore(tmp_path / "test.db")
        db.init()
        db.update_ontology(EXAMPLES_ROOT / "ontology.ttl")
        db.update_shacl(EXAMPLES_ROOT / "shapes.ttl")
        db.load(EXAMPLES_ROOT / "data_good.ttl")
        yield db
        db.close()

    def test_stats_structure(self, store):
        """Stats should show data, ontology, shacl counts."""
        stats = store.stats()
        assert "data_triples" in stats
        assert "ontology_triples" in stats
        assert "shacl_triples" in stats
        assert stats["data_triples"] > 0
        assert stats["ontology_triples"] > 0
        assert stats["shacl_triples"] > 0


# ---------------------------------------------------------------------------
# Display names
# ---------------------------------------------------------------------------


class TestDisplayNames:
    """Display name resolution using standard property fallback."""

    @pytest.fixture
    def store(self, tmp_path):
        db = RemainsStore(tmp_path / "test.db")
        db.init()
        db.update_ontology(EXAMPLES_ROOT / "ontology.ttl")
        db.update_shacl(EXAMPLES_ROOT / "shapes.ttl")
        db.load(EXAMPLES_ROOT / "data_good.ttl")
        yield db
        db.close()

    def test_display_name_from_rdfs_label(self, store):
        """Should find rdfs:label."""
        from remains.display import get_display_name

        # Add rdfs:label to an entity
        conn = store._connect()
        conn.execute(
            """INSERT OR IGNORE INTO triples
               (subject, predicate, object, object_type, datatype, lang, graph)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("http://example.com/test#x", str(RDFS.label), "Test Entity", "literal", "", "", ""),
        )
        conn.commit()

        name = get_display_name("http://example.com/test#x", store)
        assert name == "Test Entity"

    def test_display_name_fallback_to_uri(self, store):
        """Should fall back to URI fragment when no display property exists."""
        from remains.display import get_display_name

        name = get_display_name("http://example.com/test#SomeEntity", store)
        assert name == "SomeEntity"

    def test_display_name_uri_path_fallback(self, store):
        """Should fall back to last path segment when no fragment."""
        from remains.display import get_display_name

        name = get_display_name("http://example.com/things/my-thing", store)
        assert name == "my-thing"


class TestStdinInput:
    """Store methods accept TTL strings in addition to file paths."""

    @pytest.fixture
    def store(self, tmp_path):
        db = RemainsStore(tmp_path / "test.db")
        db.init()
        db.update_ontology(EXAMPLES_ROOT / "ontology.ttl")
        db.update_shacl(EXAMPLES_ROOT / "shapes.ttl")
        yield db
        db.close()

    def test_load_from_string(self, store):
        data_ttl = (EXAMPLES_ROOT / "data_good.ttl").read_text()
        result = store.load(data_ttl)
        assert result["loaded"] is True
        assert result["triple_count"] > 0

    def test_load_rejects_bad_string(self, store):
        bad_ttl = (EXAMPLES_ROOT / "data_bad.ttl").read_text()
        result = store.load(bad_ttl)
        assert result["loaded"] is False

    def test_update_ontology_from_string(self, store):
        ont_ttl = (EXAMPLES_ROOT / "ontology.ttl").read_text()
        count = store.update_ontology(ont_ttl)
        assert count > 0

    def test_update_shacl_from_string(self, store):
        shapes_ttl = (EXAMPLES_ROOT / "shapes.ttl").read_text()
        count = store.update_shacl(shapes_ttl)
        assert count > 0

    def test_update_ontology_string_rejects_system_ns(self, store):
        evil_ttl = """
@prefix remains: <urn:remains:system#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
remains:EvilClass a owl:Class .
"""
        with pytest.raises(ValueError, match="system namespace"):
            store.update_ontology(evil_ttl)


class TestCLIStdin:
    """CLI commands accept '-' for stdin."""

    def test_load_from_stdin(self, tmp_path):
        from click.testing import CliRunner
        from remains.cli import cli

        db_path = tmp_path / "test.db"
        runner = CliRunner()
        runner.invoke(cli, ["init", "-d", str(db_path)])

        ont_ttl = (EXAMPLES_ROOT / "ontology.ttl").read_text()
        runner.invoke(cli, ["load-ontology", "-", "-d", str(db_path)], input=ont_ttl)
        shapes_ttl = (EXAMPLES_ROOT / "shapes.ttl").read_text()
        runner.invoke(cli, ["load-shacl", "-", "-d", str(db_path)], input=shapes_ttl)

        data_ttl = (EXAMPLES_ROOT / "data_good.ttl").read_text()
        result = runner.invoke(cli, ["load", "-", "-d", str(db_path)], input=data_ttl)
        assert result.exit_code == 0
        assert "Loaded" in result.output

    def test_check_from_stdin(self, tmp_path):
        from click.testing import CliRunner
        from remains.cli import cli

        db_path = tmp_path / "test.db"
        runner = CliRunner()
        runner.invoke(cli, ["init", "-d", str(db_path)])

        ont_ttl = (EXAMPLES_ROOT / "ontology.ttl").read_text()
        runner.invoke(cli, ["load-ontology", "-", "-d", str(db_path)], input=ont_ttl)
        shapes_ttl = (EXAMPLES_ROOT / "shapes.ttl").read_text()
        runner.invoke(cli, ["load-shacl", "-", "-d", str(db_path)], input=shapes_ttl)

        data_ttl = (EXAMPLES_ROOT / "data_good.ttl").read_text()
        result = runner.invoke(cli, ["check", "-", "-d", str(db_path)], input=data_ttl)
        assert result.exit_code == 0

    def test_load_ontology_from_file(self, tmp_path):
        from click.testing import CliRunner
        from remains.cli import cli

        db_path = tmp_path / "test.db"
        runner = CliRunner()
        runner.invoke(cli, ["init", "-d", str(db_path)])
        result = runner.invoke(cli, ["load-ontology", str(EXAMPLES_ROOT / "ontology.ttl"), "-d", str(db_path)])
        assert result.exit_code == 0
        assert "ontology" in result.output.lower()

    def test_load_shacl_from_file(self, tmp_path):
        from click.testing import CliRunner
        from remains.cli import cli

        db_path = tmp_path / "test.db"
        runner = CliRunner()
        runner.invoke(cli, ["init", "-d", str(db_path)])
        result = runner.invoke(cli, ["load-shacl", str(EXAMPLES_ROOT / "shapes.ttl"), "-d", str(db_path)])
        assert result.exit_code == 0
        assert "shape" in result.output.lower()


class TestPromptStdin:
    """Prompt command accepts '-' for stdin."""

    def test_prompt_from_stdin(self, tmp_path):
        from click.testing import CliRunner
        from remains.cli import cli

        ont_ttl = (EXAMPLES_ROOT / "ontology.ttl").read_text()
        runner = CliRunner()
        result = runner.invoke(cli, ["prompt", "-"], input=ont_ttl)
        assert result.exit_code == 0
        assert "Person" in result.output
