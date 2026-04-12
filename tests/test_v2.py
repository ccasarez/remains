"""Tests for dregs v2: 3 fixed graphs, system/user split, topics, domains."""
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


class TestInitV2:
    """dregs init creates 3-graph structure with system + user ontology/shapes."""

    def test_init_creates_three_graphs(self, tmp_path):
        """Init should create exactly 3 graphs: default, urn:ontology, urn:shacl."""
        db = DregsStore(tmp_path / "test.db")
        db.init_v2(
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
        db.init_v2(
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
        db.init_v2(
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
        db.init_v2(
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
        db.init_v2(
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


class TestLoadV2:
    """Loading data goes into default graph only."""

    @pytest.fixture
    def v2_store(self, tmp_path):
        db = DregsStore(tmp_path / "test.db")
        db.init_v2(
            ontology_path=EXAMPLES_ROOT / "ontology.ttl",
            shacl_path=EXAMPLES_ROOT / "shapes.ttl",
        )
        yield db
        db.close()

    def test_load_into_default_graph(self, v2_store):
        """Data loads into default (empty string) graph."""
        result = v2_store.load_v2(EXAMPLES_ROOT / "data_good.ttl")
        assert result["loaded"] is True
        assert result["triple_count"] > 0

        conn = v2_store._connect()
        data_triples = conn.execute(
            "SELECT COUNT(*) FROM triples WHERE graph = ''",
        ).fetchone()[0]
        assert data_triples > 0

    def test_load_rejects_bad_data(self, v2_store):
        """Bad data should still fail validation."""
        result = v2_store.load_v2(EXAMPLES_ROOT / "data_bad.ttl")
        assert result["loaded"] is False

    def test_no_named_graphs_created(self, v2_store):
        """Loading data should not create any named data graphs."""
        v2_store.load_v2(EXAMPLES_ROOT / "data_good.ttl")

        conn = v2_store._connect()
        graphs = conn.execute(
            "SELECT DISTINCT graph FROM triples"
        ).fetchall()
        graph_names = {r[0] for r in graphs}
        assert graph_names <= {"", "urn:ontology", "urn:shacl"}


class TestPromptV2:
    """dregs prompt generates from urn:ontology graph."""

    @pytest.fixture
    def v2_store(self, tmp_path):
        db = DregsStore(tmp_path / "test.db")
        db.init_v2(
            ontology_path=EXAMPLES_ROOT / "ontology.ttl",
            shacl_path=EXAMPLES_ROOT / "shapes.ttl",
        )
        yield db
        db.close()

    def test_prompt_includes_user_classes(self, v2_store):
        """Prompt should include user ontology classes."""
        from dregs.prompt import prompt_from_store_v2

        output = prompt_from_store_v2(v2_store)
        assert "Person" in output
        assert "Organization" in output
        assert "Meeting" in output

    def test_prompt_excludes_system_classes(self, v2_store):
        """Prompt should NOT include system classes (Topic, Domain)."""
        from dregs.prompt import prompt_from_store_v2

        output = prompt_from_store_v2(v2_store)
        assert "Topic" not in output
        assert "Domain" not in output


class TestPromptDomain:
    """dregs prompt --domain filters to domain classes only."""

    @pytest.fixture
    def v2_store_with_domain(self, tmp_path):
        db = DregsStore(tmp_path / "test.db")
        db.init_v2(
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

    def test_prompt_domain_filters_classes(self, v2_store_with_domain):
        """Prompt with domain should only include domain classes as entity types."""
        from dregs.prompt import prompt_from_store_v2

        output = prompt_from_store_v2(v2_store_with_domain, domain="people")
        # Classes in domain appear as headers
        assert "### Person" in output
        assert "### Organization" in output
        # Classes NOT in domain should not appear as headers
        assert "### Meeting" not in output
        assert "### Document" not in output

    def test_prompt_domain_includes_properties(self, v2_store_with_domain):
        """Prompt with domain should include properties relevant to domain classes."""
        from dregs.prompt import prompt_from_store_v2

        output = prompt_from_store_v2(v2_store_with_domain, domain="people")
        assert "worksAt" in output  # Person -> Organization


class TestNamespaceProtection:
    """System namespaces are protected from user modification."""

    @pytest.fixture
    def v2_store(self, tmp_path):
        db = DregsStore(tmp_path / "test.db")
        db.init_v2(
            ontology_path=EXAMPLES_ROOT / "ontology.ttl",
            shacl_path=EXAMPLES_ROOT / "shapes.ttl",
        )
        yield db
        db.close()

    def test_update_ontology_rejects_system_namespace(self, v2_store, tmp_path):
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
            v2_store.update_ontology(evil)

    def test_update_shacl_rejects_system_namespace(self, v2_store, tmp_path):
        """Updating shapes with system namespace triples should fail."""
        evil = tmp_path / "evil-shapes.ttl"
        evil.write_text("""
@prefix dregs-sh: <urn:dregs:shapes#> .
@prefix sh: <http://www.w3.org/ns/shacl#> .

dregs-sh:TopicShape sh:deactivated true .
""")
        with pytest.raises(ValueError, match="system namespace"):
            v2_store.update_shacl(evil)


class TestExportV2:
    """Export with new flags."""

    @pytest.fixture
    def v2_store(self, tmp_path):
        db = DregsStore(tmp_path / "test.db")
        db.init_v2(
            ontology_path=EXAMPLES_ROOT / "ontology.ttl",
            shacl_path=EXAMPLES_ROOT / "shapes.ttl",
        )
        db.load_v2(EXAMPLES_ROOT / "data_good.ttl")
        yield db
        db.close()

    def test_export_data_only(self, v2_store):
        """Export default graph data only."""
        ttl = v2_store.export_v2("data")
        assert len(ttl) > 0
        # Parse it to verify it's valid turtle
        g = Graph()
        g.parse(data=ttl, format="turtle")
        assert len(g) > 0

    def test_export_ontology_user_only(self, v2_store):
        """Export user ontology triples only (no system)."""
        ttl = v2_store.export_v2("ontology")
        assert len(ttl) > 0
        assert "dregs:system" not in ttl.lower() or "urn:dregs:system" not in ttl

    def test_export_all(self, v2_store):
        """Export everything."""
        ttl = v2_store.export_v2("all")
        g = Graph()
        g.parse(data=ttl, format="turtle")
        assert len(g) > 0


class TestInfoV2:
    """Info command shows system/user split."""

    @pytest.fixture
    def v2_store(self, tmp_path):
        db = DregsStore(tmp_path / "test.db")
        db.init_v2(
            ontology_path=EXAMPLES_ROOT / "ontology.ttl",
            shacl_path=EXAMPLES_ROOT / "shapes.ttl",
        )
        db.load_v2(EXAMPLES_ROOT / "data_good.ttl")
        yield db
        db.close()

    def test_stats_v2_structure(self, v2_store):
        """Stats should show data, ontology, shacl counts."""
        stats = v2_store.stats_v2()
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
    def v2_store(self, tmp_path):
        db = DregsStore(tmp_path / "test.db")
        db.init_v2(
            ontology_path=EXAMPLES_ROOT / "ontology.ttl",
            shacl_path=EXAMPLES_ROOT / "shapes.ttl",
        )
        yield db
        db.close()

    def test_create_domain(self, v2_store):
        """Create a domain and verify it exists."""
        v2_store.create_domain("people", "People", [str(EX.Person), str(EX.Organization)])

        domains = v2_store.list_domains()
        assert len(domains) == 1
        assert domains[0]["name"] == "People"
        assert len(domains[0]["classes"]) == 2

    def test_add_to_domain(self, v2_store):
        """Add a class to existing domain."""
        v2_store.create_domain("people", "People", [str(EX.Person)])
        v2_store.add_to_domain("people", [str(EX.Organization)])

        domains = v2_store.list_domains()
        assert len(domains[0]["classes"]) == 2

    def test_list_domains_empty(self, v2_store):
        """List domains when none exist."""
        domains = v2_store.list_domains()
        assert domains == []


# ---------------------------------------------------------------------------
# Phase 3: Topics (data graph)
# ---------------------------------------------------------------------------


class TestTopics:
    """Topic management."""

    @pytest.fixture
    def v2_store(self, tmp_path):
        db = DregsStore(tmp_path / "test.db")
        db.init_v2(
            ontology_path=EXAMPLES_ROOT / "ontology.ttl",
            shacl_path=EXAMPLES_ROOT / "shapes.ttl",
        )
        db.load_v2(EXAMPLES_ROOT / "data_good.ttl")
        yield db
        db.close()

    def test_create_topic(self, v2_store):
        """Create a topic with members."""
        v2_store.create_topic("research", "Research", ["http://example.com/ontology#alice"])

        topics = v2_store.list_topics()
        assert len(topics) == 1
        assert topics[0]["name"] == "Research"

    def test_topic_stored_in_default_graph(self, v2_store):
        """Topics must be stored in default data graph."""
        v2_store.create_topic("research", "Research", ["http://example.com/ontology#alice"])

        conn = v2_store._connect()
        topic_triples = conn.execute(
            "SELECT COUNT(*) FROM triples WHERE graph = '' AND subject LIKE 'urn:dregs:topic%'"
        ).fetchone()[0]
        assert topic_triples > 0

    def test_list_topics_empty(self, v2_store):
        """List topics when none exist."""
        topics = v2_store.list_topics()
        assert topics == []


# ---------------------------------------------------------------------------
# Phase 4: Display names
# ---------------------------------------------------------------------------


class TestDisplayNames:
    """Display name resolution using standard property fallback."""

    @pytest.fixture
    def v2_store(self, tmp_path):
        db = DregsStore(tmp_path / "test.db")
        db.init_v2(
            ontology_path=EXAMPLES_ROOT / "ontology.ttl",
            shacl_path=EXAMPLES_ROOT / "shapes.ttl",
        )
        db.load_v2(EXAMPLES_ROOT / "data_good.ttl")
        yield db
        db.close()

    def test_display_name_from_rdfs_label(self, v2_store):
        """Should find rdfs:label."""
        from dregs.display import get_display_name

        # Add rdfs:label to an entity
        conn = v2_store._connect()
        conn.execute(
            """INSERT OR IGNORE INTO triples
               (subject, predicate, object, object_type, datatype, lang, graph)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("http://example.com/test#x", str(RDFS.label), "Test Entity", "literal", "", "", ""),
        )
        conn.commit()

        name = get_display_name("http://example.com/test#x", v2_store)
        assert name == "Test Entity"

    def test_display_name_fallback_to_uri(self, v2_store):
        """Should fall back to URI fragment when no display property exists."""
        from dregs.display import get_display_name

        name = get_display_name("http://example.com/test#SomeEntity", v2_store)
        assert name == "SomeEntity"

    def test_display_name_uri_path_fallback(self, v2_store):
        """Should fall back to last path segment when no fragment."""
        from dregs.display import get_display_name

        name = get_display_name("http://example.com/things/my-thing", v2_store)
        assert name == "my-thing"
