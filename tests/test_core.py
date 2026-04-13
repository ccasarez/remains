"""Tests for dregs: 3 fixed graphs, system/user split, topics, domains."""
from __future__ import annotations

from pathlib import Path

import pytest
from rdflib import Graph, Literal, URIRef, Namespace, RDF, RDFS, OWL, XSD

from dregs.store import DregsStore

EXAMPLES_ROOT = Path(__file__).parent.parent / "examples"
SYSTEM_DIR = Path(__file__).parent.parent / "src" / "dregs" / "system"

DREGS = Namespace("urn:dregs:system#")
DREGS_SH = Namespace("urn:dregs:shapes#")
EX = Namespace("http://example.com/ontology#")


# ---------------------------------------------------------------------------
# Phase 1: Core DB restructure - 3 fixed graphs
# ---------------------------------------------------------------------------


class TestInit:
    """dregs init creates 3-graph structure with system + user ontology/shapes."""

    def test_init_creates_three_graphs(self, tmp_path):
        """Init should create exactly 3 graphs: default, urn:ontology, urn:shacl."""
        db = DregsStore(tmp_path / "test.db")
        db.init(
            ontology_path=EXAMPLES_ROOT / "ontology.ttl",
            shacl_path=EXAMPLES_ROOT / "shapes.ttl",
        )

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
        """System ontology (dregs:Topic, dregs:Domain, etc.) must be in urn:ontology."""
        db = DregsStore(tmp_path / "test.db")
        db.init(
            ontology_path=EXAMPLES_ROOT / "ontology.ttl",
            shacl_path=EXAMPLES_ROOT / "shapes.ttl",
        )

        conn = db._connect()
        # Check dregs:Topic class exists
        topic_exists = conn.execute(
            "SELECT COUNT(*) FROM triples WHERE subject = ? AND predicate = ? AND graph = ?",
            (str(DREGS.Topic), str(RDF.type), "urn:ontology"),
        ).fetchone()[0]
        assert topic_exists > 0

        # Check dregs:Domain class exists
        domain_exists = conn.execute(
            "SELECT COUNT(*) FROM triples WHERE subject = ? AND predicate = ? AND graph = ?",
            (str(DREGS.Domain), str(RDF.type), "urn:ontology"),
        ).fetchone()[0]
        assert domain_exists > 0
        db.close()

    def test_init_loads_user_ontology(self, tmp_path):
        """User ontology classes must also be in urn:ontology."""
        db = DregsStore(tmp_path / "test.db")
        db.init(
            ontology_path=EXAMPLES_ROOT / "ontology.ttl",
            shacl_path=EXAMPLES_ROOT / "shapes.ttl",
        )

        conn = db._connect()
        # Check user class ex:Person exists in urn:ontology
        person_exists = conn.execute(
            "SELECT COUNT(*) FROM triples WHERE subject = ? AND predicate = ? AND graph = ?",
            (str(EX.Person), str(RDF.type), "urn:ontology"),
        ).fetchone()[0]
        assert person_exists > 0
        db.close()

    def test_init_loads_system_shapes(self, tmp_path):
        """System shapes (dregs-sh:TopicShape, etc.) must be in urn:shacl."""
        db = DregsStore(tmp_path / "test.db")
        db.init(
            ontology_path=EXAMPLES_ROOT / "ontology.ttl",
            shacl_path=EXAMPLES_ROOT / "shapes.ttl",
        )

        conn = db._connect()
        topic_shape = conn.execute(
            "SELECT COUNT(*) FROM triples WHERE subject = ? AND graph = ?",
            (str(DREGS_SH.TopicShape), "urn:shacl"),
        ).fetchone()[0]
        assert topic_shape > 0
        db.close()

    def test_init_loads_user_shapes(self, tmp_path):
        """User shapes must also be in urn:shacl."""
        db = DregsStore(tmp_path / "test.db")
        db.init(
            ontology_path=EXAMPLES_ROOT / "ontology.ttl",
            shacl_path=EXAMPLES_ROOT / "shapes.ttl",
        )

        conn = db._connect()
        # The examples/shapes.ttl has shapes — check any user shape exists
        user_shapes = conn.execute(
            "SELECT COUNT(*) FROM triples WHERE graph = ? AND subject NOT LIKE 'urn:dregs:%'",
            ("urn:shacl",),
        ).fetchone()[0]
        assert user_shapes > 0
        db.close()


class TestLoad:
    """Loading data goes into default graph only."""

    @pytest.fixture
    def store(self, tmp_path):
        db = DregsStore(tmp_path / "test.db")
        db.init(
            ontology_path=EXAMPLES_ROOT / "ontology.ttl",
            shacl_path=EXAMPLES_ROOT / "shapes.ttl",
        )
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
    ``dregs load`` should only police the user's data, not the ontology.
    """

    GIST_ROOT = EXAMPLES_ROOT / "gist"

    @pytest.fixture
    def store(self, tmp_path):
        db = DregsStore(tmp_path / "test.db")
        db.init(
            ontology_path=self.GIST_ROOT / "ontology.ttl",
            shacl_path=self.GIST_ROOT / "shapes.ttl",
        )
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

        from dregs.store import run_validation

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
    """dregs prompt generates from urn:ontology graph."""

    @pytest.fixture
    def store(self, tmp_path):
        db = DregsStore(tmp_path / "test.db")
        db.init(
            ontology_path=EXAMPLES_ROOT / "ontology.ttl",
            shacl_path=EXAMPLES_ROOT / "shapes.ttl",
        )
        yield db
        db.close()

    def test_prompt_includes_user_classes(self, store):
        """Prompt should include user ontology classes."""
        from dregs.prompt import prompt_from_store

        output = prompt_from_store(store)
        assert "Person" in output
        assert "Organization" in output
        assert "Meeting" in output

    def test_prompt_excludes_system_classes(self, store):
        """Prompt should NOT include system classes (Topic, Domain)."""
        from dregs.prompt import prompt_from_store

        output = prompt_from_store(store)
        assert "Topic" not in output
        assert "Domain" not in output


class TestPromptDomain:
    """dregs prompt --domain filters to domain classes only."""

    @pytest.fixture
    def store_with_domain(self, tmp_path):
        db = DregsStore(tmp_path / "test.db")
        db.init(
            ontology_path=EXAMPLES_ROOT / "ontology.ttl",
            shacl_path=EXAMPLES_ROOT / "shapes.ttl",
        )
        # Add a domain to urn:ontology
        conn = db._connect()
        domain_uri = "urn:dregs:domain#people"
        triples = [
            (domain_uri, str(RDF.type), str(DREGS.Domain), "uri", "", "", "urn:ontology"),
            (domain_uri, str(RDFS.label), "People", "typed_literal", str(XSD.string), "", "urn:ontology"),
            (domain_uri, str(DREGS.includesClass), str(EX.Person), "uri", "", "", "urn:ontology"),
            (domain_uri, str(DREGS.includesClass), str(EX.Organization), "uri", "", "", "urn:ontology"),
        ]
        conn.executemany(
            """INSERT OR IGNORE INTO triples
               (subject, predicate, object, object_type, datatype, lang, graph)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            triples,
        )
        conn.commit()
        yield db
        db.close()

    def test_prompt_domain_filters_classes(self, store_with_domain):
        """Prompt with domain should only include domain classes as entity types."""
        from dregs.prompt import prompt_from_store

        output = prompt_from_store(store_with_domain, domain="people")
        # Classes in domain appear as headers
        assert "### Person" in output
        assert "### Organization" in output
        # Classes NOT in domain should not appear as headers
        assert "### Meeting" not in output
        assert "### Document" not in output

    def test_prompt_domain_includes_properties(self, store_with_domain):
        """Prompt with domain should include properties relevant to domain classes."""
        from dregs.prompt import prompt_from_store

        output = prompt_from_store(store_with_domain, domain="people")
        assert "worksAt" in output  # Person -> Organization


class TestNamespaceProtection:
    """System namespaces are protected from user modification."""

    @pytest.fixture
    def store(self, tmp_path):
        db = DregsStore(tmp_path / "test.db")
        db.init(
            ontology_path=EXAMPLES_ROOT / "ontology.ttl",
            shacl_path=EXAMPLES_ROOT / "shapes.ttl",
        )
        yield db
        db.close()

    def test_update_ontology_rejects_system_namespace(self, store, tmp_path):
        """Updating ontology with system namespace triples should fail."""
        evil = tmp_path / "evil.ttl"
        evil.write_text("""
@prefix dregs: <urn:dregs:system#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

dregs:Topic rdfs:label "Hacked" .
dregs:EvilClass a owl:Class .
""")
        with pytest.raises(ValueError, match="system namespace"):
            store.update_ontology(evil)

    def test_update_shacl_rejects_system_namespace(self, store, tmp_path):
        """Updating shapes with system namespace triples should fail."""
        evil = tmp_path / "evil-shapes.ttl"
        evil.write_text("""
@prefix dregs-sh: <urn:dregs:shapes#> .
@prefix sh: <http://www.w3.org/ns/shacl#> .

dregs-sh:TopicShape sh:deactivated true .
""")
        with pytest.raises(ValueError, match="system namespace"):
            store.update_shacl(evil)


class TestExport:
    """Export with new flags."""

    @pytest.fixture
    def store(self, tmp_path):
        db = DregsStore(tmp_path / "test.db")
        db.init(
            ontology_path=EXAMPLES_ROOT / "ontology.ttl",
            shacl_path=EXAMPLES_ROOT / "shapes.ttl",
        )
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
        assert "dregs:system" not in ttl.lower() or "urn:dregs:system" not in ttl

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
        db = DregsStore(tmp_path / "test.db")
        db.init(
            ontology_path=EXAMPLES_ROOT / "ontology.ttl",
            shacl_path=EXAMPLES_ROOT / "shapes.ttl",
        )
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
# Phase 2: Domains
# ---------------------------------------------------------------------------


class TestDomains:
    """Domain management commands."""

    @pytest.fixture
    def store(self, tmp_path):
        db = DregsStore(tmp_path / "test.db")
        db.init(
            ontology_path=EXAMPLES_ROOT / "ontology.ttl",
            shacl_path=EXAMPLES_ROOT / "shapes.ttl",
        )
        yield db
        db.close()

    def test_create_domain(self, store):
        """Create a domain and verify it exists."""
        store.create_domain("people", "People", [str(EX.Person), str(EX.Organization)])

        domains = store.list_domains()
        assert len(domains) == 1
        assert domains[0]["name"] == "People"
        assert len(domains[0]["classes"]) == 2

    def test_add_to_domain(self, store):
        """Add a class to existing domain."""
        store.create_domain("people", "People", [str(EX.Person)])
        store.add_to_domain("people", [str(EX.Organization)])

        domains = store.list_domains()
        assert len(domains[0]["classes"]) == 2

    def test_list_domains_empty(self, store):
        """List domains when none exist."""
        domains = store.list_domains()
        assert domains == []


# ---------------------------------------------------------------------------
# Phase 3: Topics (data graph)
# ---------------------------------------------------------------------------


class TestTopics:
    """Topic management."""

    @pytest.fixture
    def store(self, tmp_path):
        db = DregsStore(tmp_path / "test.db")
        db.init(
            ontology_path=EXAMPLES_ROOT / "ontology.ttl",
            shacl_path=EXAMPLES_ROOT / "shapes.ttl",
        )
        db.load(EXAMPLES_ROOT / "data_good.ttl")
        yield db
        db.close()

    def test_create_topic(self, store):
        """Create a topic with members."""
        store.create_topic("research", "Research", ["http://example.com/ontology#alice"])

        topics = store.list_topics()
        assert len(topics) == 1
        assert topics[0]["name"] == "Research"

    def test_topic_stored_in_default_graph(self, store):
        """Topics must be stored in default data graph."""
        store.create_topic("research", "Research", ["http://example.com/ontology#alice"])

        conn = store._connect()
        topic_triples = conn.execute(
            "SELECT COUNT(*) FROM triples WHERE graph = '' AND subject LIKE 'urn:dregs:topic%'"
        ).fetchone()[0]
        assert topic_triples > 0

    def test_list_topics_empty(self, store):
        """List topics when none exist."""
        topics = store.list_topics()
        assert topics == []


# ---------------------------------------------------------------------------
# Phase 4: Display names
# ---------------------------------------------------------------------------


class TestDisplayNames:
    """Display name resolution using standard property fallback."""

    @pytest.fixture
    def store(self, tmp_path):
        db = DregsStore(tmp_path / "test.db")
        db.init(
            ontology_path=EXAMPLES_ROOT / "ontology.ttl",
            shacl_path=EXAMPLES_ROOT / "shapes.ttl",
        )
        db.load(EXAMPLES_ROOT / "data_good.ttl")
        yield db
        db.close()

    def test_display_name_from_rdfs_label(self, store):
        """Should find rdfs:label."""
        from dregs.display import get_display_name

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
        from dregs.display import get_display_name

        name = get_display_name("http://example.com/test#SomeEntity", store)
        assert name == "SomeEntity"

    def test_display_name_uri_path_fallback(self, store):
        """Should fall back to last path segment when no fragment."""
        from dregs.display import get_display_name

        name = get_display_name("http://example.com/things/my-thing", store)
        assert name == "my-thing"
