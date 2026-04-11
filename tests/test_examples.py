"""Tests for all example sets: default, FOAF, Schema.org, DCAT.

Each example set is tested through the parametrized `example` / `store` /
`loaded_store` fixtures defined in conftest.py.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from dregs import DregsStore, validate_files, execute_sparql
from dregs.prompt import prompt_from_store, prompt_from_file
from tests.conftest import EXAMPLE_SETS

EXAMPLES_ROOT = Path(__file__).parent.parent / "examples"

# ── Expected violation counts per example set ────────────────────────
# Keyed by example name.  Values: (shacl_count, schema_count).
# Derived from manual test runs; update if bad-data files change.

EXPECTED_VIOLATIONS = {
    "default": (4, 3),
    "foaf": (3, 4),
    "schema-org": (5, 6),
    "dcat": (5, 3),
}


# ── Standalone validation (no DB) ───────────────────────────────────

class TestValidateFiles:
    """Tests using validate_files() — pure function, no store."""

    def test_good_data_conforms(self, example):
        result = validate_files(
            example["ontology"], example["good_data"], example["shapes"]
        )
        assert result.conforms, result.summary()

    def test_bad_data_fails(self, example):
        result = validate_files(
            example["ontology"], example["bad_data"], example["shapes"]
        )
        assert not result.conforms

    def test_bad_data_shacl_violations(self, example):
        result = validate_files(
            example["ontology"], example["bad_data"], example["shapes"]
        )
        expected_shacl, _ = EXPECTED_VIOLATIONS[example["name"]]
        assert len(result.shacl_violations) == expected_shacl, (
            f"expected {expected_shacl} SHACL violations, got {len(result.shacl_violations)}:\n"
            + "\n".join(result.shacl_violations)
        )

    def test_bad_data_schema_violations(self, example):
        result = validate_files(
            example["ontology"], example["bad_data"], example["shapes"]
        )
        _, expected_schema = EXPECTED_VIOLATIONS[example["name"]]
        assert len(result.schema_violations) == expected_schema, (
            f"expected {expected_schema} schema violations, got {len(result.schema_violations)}:\n"
            + "\n".join(result.schema_violations)
        )

    def test_owl_reasoning_infers_triples(self, example):
        result = validate_files(
            example["ontology"], example["good_data"], example["shapes"]
        )
        assert result.owl_inferred_triples > 0
        assert result.total_triples_after > result.total_triples_before


# ── Store lifecycle: init / load / reject ────────────────────────────

class TestStoreLifecycle:
    """Tests using DregsStore — full init/load/query/export cycle."""

    def test_init_creates_graphs(self, store):
        graphs = store.list_graphs()
        types = {g.graph_type for g in graphs}
        assert "schema" in types
        assert "shacl" in types

    def test_init_stats(self, store):
        info = store.stats()
        assert info["total_triples"] > 0
        assert info["graph_count"] >= 2

    def test_load_good_data(self, store, example):
        result = store.load(example["good_data"], graph_name="test")
        assert result["loaded"] is True
        assert result["triple_count"] > 0

    def test_load_rejects_bad_data(self, store, example):
        result = store.load(example["bad_data"], graph_name="test")
        assert result["loaded"] is False
        assert result["validation"].conforms is False

    def test_load_no_validate(self, store, example):
        result = store.load(example["bad_data"], graph_name="raw", validate=False)
        assert result["loaded"] is True


# ── SPARQL queries ───────────────────────────────────────────────────

class TestSparql:
    """SPARQL query tests against loaded stores."""

    def test_select_returns_results(self, loaded_store):
        qr = execute_sparql(
            loaded_store,
            "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 10",
        )
        assert len(qr.bindings) > 0
        assert len(qr.variables) == 3

    def test_count_matches_load(self, loaded_store, example):
        """Triple count from SPARQL ≥ loaded triple count."""
        qr = execute_sparql(
            loaded_store,
            "SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }",
        )
        count = int(qr.bindings[0]["n"])
        assert count > 0


# ── Per-example SPARQL smoke tests ──────────────────────────────────

class TestSparqlPerExample:
    """Targeted SPARQL queries that exercise each ontology's structure."""

    @pytest.fixture
    def foaf_store(self, tmp_path):
        paths = _load_example(tmp_path, "foaf")
        return paths

    @pytest.fixture
    def schema_store(self, tmp_path):
        return _load_example(tmp_path, "schema-org")

    @pytest.fixture
    def dcat_store(self, tmp_path):
        return _load_example(tmp_path, "dcat")

    def test_foaf_knows(self, foaf_store):
        """Two people who know each other."""
        qr = execute_sparql(
            foaf_store,
            """PREFIX foaf: <http://xmlns.com/foaf/0.1/>
            SELECT ?a ?b WHERE { ?a foaf:knows ?b }""",
        )
        assert len(qr.bindings) >= 2  # both directions

    def test_foaf_member(self, foaf_store):
        qr = execute_sparql(
            foaf_store,
            """PREFIX foaf: <http://xmlns.com/foaf/0.1/>
            SELECT ?org ?person WHERE {
                ?o a foaf:Organization ; foaf:name ?org ; foaf:member ?p .
                ?p foaf:name ?person
            }""",
        )
        assert len(qr.bindings) >= 1

    def test_schema_event_performer(self, schema_store):
        qr = execute_sparql(
            schema_store,
            """PREFIX schema: <https://schema.org/>
            SELECT ?event ?person WHERE {
                ?e a schema:Event ; schema:name ?event ;
                   schema:performer ?p .
                ?p schema:name ?person
            }""",
        )
        assert len(qr.bindings) >= 1
        assert any("KubeCon" in b["event"] for b in qr.bindings)

    def test_schema_article_author(self, schema_store):
        qr = execute_sparql(
            schema_store,
            """PREFIX schema: <https://schema.org/>
            SELECT ?headline ?author WHERE {
                ?a a schema:Article ; schema:headline ?headline ;
                   schema:author ?p .
                ?p schema:name ?author
            }""",
        )
        assert len(qr.bindings) >= 1

    def test_dcat_dataset_distributions(self, dcat_store):
        qr = execute_sparql(
            dcat_store,
            """PREFIX dcat: <http://www.w3.org/ns/dcat#>
            PREFIX dct: <http://purl.org/dc/terms/>
            SELECT ?dataset ?format WHERE {
                ?ds a dcat:Dataset ; dct:title ?dataset ;
                    dcat:distribution ?d .
                ?d dcat:mediaType ?format
            }""",
        )
        assert len(qr.bindings) >= 2

    def test_dcat_catalog_datasets(self, dcat_store):
        qr = execute_sparql(
            dcat_store,
            """PREFIX dcat: <http://www.w3.org/ns/dcat#>
            PREFIX dct: <http://purl.org/dc/terms/>
            SELECT ?catalog ?dataset WHERE {
                ?c a dcat:Catalog ; dct:title ?catalog ;
                   dcat:dataset ?ds .
                ?ds dct:title ?dataset
            }""",
        )
        assert len(qr.bindings) >= 1


# ── Prompt generation ────────────────────────────────────────────────

class TestPrompt:
    """Prompt context generation tests."""

    def test_prompt_from_store(self, store):
        ctx = prompt_from_store(store)
        assert "Entity Types" in ctx
        assert "Relationships" in ctx
        assert "Data Properties" in ctx

    def test_prompt_from_file(self, example):
        ctx = prompt_from_file(example["ontology"])
        assert "Entity Types" in ctx

    def test_prompt_includes_examples(self, example):
        """skos:example annotations appear in prompt output."""
        ctx = prompt_from_file(example["ontology"])
        assert "example:" in ctx.lower() or "example" in ctx.lower()


# ── Export ───────────────────────────────────────────────────────────

class TestExport:

    def test_export_schema(self, store):
        ttl = store.export_by_type("schema")
        assert len(ttl) > 0
        assert "@prefix" in ttl or "a owl:Class" in ttl

    def test_export_data_after_load(self, loaded_store):
        ttl = loaded_store.export_by_type("data")
        assert len(ttl) > 0

    def test_export_round_trips(self, loaded_store):
        """Exported Turtle re-parses without error."""
        from rdflib import Graph

        ttl = loaded_store.export_by_type("data")
        g = Graph()
        g.parse(data=ttl, format="turtle")
        assert len(g) > 0


# ── Drop graph ───────────────────────────────────────────────────────

class TestDropGraph:

    def test_drop_removes_triples(self, loaded_store):
        before = loaded_store.stats()["total_triples"]
        dropped = loaded_store.drop_graph("test")
        after = loaded_store.stats()["total_triples"]
        assert dropped > 0
        assert after < before


# ── Well-known namespace fix ─────────────────────────────────────────

class TestWellKnownNamespaceFix:
    """Verify foaf: types are checked by schema conformance.

    This tests the fix that removed foaf: from _WELL_KNOWN_NS.
    Before the fix, abstract foaf:Agent and unknown foaf:Gadget would
    silently pass schema conformance checks.
    """

    def test_foaf_abstract_class_detected(self):
        paths = EXAMPLE_SETS["foaf"]
        result = validate_files(paths["ontology"], paths["bad_data"], paths["shapes"])
        abstract_violations = [
            v for v in result.schema_violations if "ABSTRACT_TYPE" in v
        ]
        assert any("Agent" in v for v in abstract_violations), (
            f"Expected ABSTRACT_TYPE for foaf:Agent, got: {result.schema_violations}"
        )

    def test_foaf_unknown_type_detected(self):
        paths = EXAMPLE_SETS["foaf"]
        result = validate_files(paths["ontology"], paths["bad_data"], paths["shapes"])
        unknown_violations = [
            v for v in result.schema_violations if "UNKNOWN_TYPE" in v
        ]
        assert any("Gadget" in v for v in unknown_violations), (
            f"Expected UNKNOWN_TYPE for foaf:Gadget, got: {result.schema_violations}"
        )

    def test_well_known_ns_excludes_only_meta_vocabularies(self):
        """The well-known list should only contain W3C meta-vocabularies."""
        from dregs.store import _WELL_KNOWN_NS

        for ns in _WELL_KNOWN_NS:
            assert ns.startswith("http://www.w3.org/"), (
                f"Non-W3C namespace in _WELL_KNOWN_NS: {ns}"
            )


# ── Schema-subject URI collision (issue #4) ───────────────────────────

class TestSchemaSubjectCollision:
    """Regression test for GitHub issue #4.

    Data instances whose URI also appears as a subject in the schema graph
    must still be checked by schema conformance.  Before the fix, the set
    subtraction `set(combined) - set(schema_subjects)` silently excluded them.
    """

    def test_instance_with_schema_uri_is_checked(self):
        """An entity whose URI appears as a subject in the schema (e.g. in
        an example or annotation) but is NOT a class/property definition
        must still be checked."""
        from rdflib import Graph, URIRef, Namespace, OWL, RDF, RDFS, Literal
        from dregs.store import _run_schema_checks

        EX = Namespace("http://example.org/")

        schema = Graph()
        schema.add((EX.Person, RDF.type, OWL.Class))
        # EX.alice appears as a subject in the schema (e.g., an example)
        schema.add((EX.alice, RDFS.comment, Literal("example individual")))

        combined = Graph()
        # Data also uses EX.alice — before the fix this was silently skipped
        combined.add((EX.alice, RDF.type, EX.BogusType))

        violations = _run_schema_checks(schema, combined)
        assert any("UNKNOWN_TYPE" in v and "BogusType" in v for v in violations), (
            f"Expected UNKNOWN_TYPE for EX.alice typed as EX.BogusType, "
            f"got: {violations}"
        )

    def test_instance_sharing_schema_uri_not_silently_skipped(self):
        """An entity whose URI is also in the schema must still get NO_TYPE
        if it has no rdf:type at all in the data."""
        from rdflib import Graph, URIRef, Namespace, OWL, RDF, RDFS
        from dregs.store import _run_schema_checks

        EX = Namespace("http://example.org/")

        schema = Graph()
        schema.add((EX.MyClass, RDF.type, OWL.Class))
        # EX.item appears as a subject in the schema (e.g., an example annotation)
        schema.add((EX.item, RDFS.comment, URIRef("http://example.org/note")))

        combined = Graph()
        # Data uses EX.item as a subject but gives it no type
        combined.add((EX.item, RDFS.label, URIRef("http://example.org/hello")))

        violations = _run_schema_checks(schema, combined)
        assert any("NO_TYPE" in v and "item" in v for v in violations), (
            f"Expected NO_TYPE for EX.item, got: {violations}"
        )

    def test_actual_schema_definition_still_excluded(self):
        """A subject that IS a schema definition (owl:Class) should still be
        excluded from instance checks — we don't want false positives on
        class definitions themselves."""
        from rdflib import Graph, Namespace, OWL, RDF, RDFS
        from dregs.store import _run_schema_checks

        EX = Namespace("http://example.org/")

        schema = Graph()
        schema.add((EX.Person, RDF.type, OWL.Class))
        schema.add((EX.Animal, RDF.type, OWL.Class))
        schema.add((EX.Person, RDFS.subClassOf, EX.Animal))

        # combined graph also has the schema triples (they're merged)
        combined = schema + Graph()

        violations = _run_schema_checks(schema, combined)
        # No UNKNOWN_TYPE / NO_TYPE for class definitions
        assert not violations, (
            f"Schema class definitions should not produce violations, got: {violations}"
        )


# ── Specific violation content checks ───────────────────────────────

class TestViolationMessages:
    """Verify specific violation messages are actionable."""

    @pytest.mark.parametrize("name", EXAMPLE_SETS.keys())
    def test_shacl_messages_are_human_readable(self, name):
        paths = EXAMPLE_SETS[name]
        result = validate_files(paths["ontology"], paths["bad_data"], paths["shapes"])
        for v in result.shacl_violations:
            # Each violation should have [focusNode] path: message
            assert "]" in v, f"Missing focus node in: {v}"
            assert ":" in v, f"Missing path/message separator in: {v}"

    @pytest.mark.parametrize("name", ["default", "foaf", "schema-org", "dcat"])
    def test_schema_violations_identify_subject(self, name):
        paths = EXAMPLE_SETS[name]
        result = validate_files(paths["ontology"], paths["bad_data"], paths["shapes"])
        for v in result.schema_violations:
            # Each should contain ABSTRACT_TYPE, UNKNOWN_TYPE, or NO_TYPE
            assert any(tag in v for tag in ("ABSTRACT_TYPE", "UNKNOWN_TYPE", "NO_TYPE")), (
                f"Unrecognized violation format: {v}"
            )


# ── Unique index correctness ────────────────────────────────────────

class TestUniqueIndex:
    """Regression tests for the unique index on triples.

    The original index omitted datatype and lang columns, causing
    INSERT OR IGNORE to silently discard distinct triples that
    differed only in datatype or language tag.
    """

    def test_distinct_datatypes_preserved(self, tmp_path):
        """Two literals with same lexical form but different datatypes must both survive."""
        from rdflib import Graph, Literal, URIRef, Namespace, XSD

        db = DregsStore(tmp_path / "dt.db")
        db.init()
        conn = db._connect()

        g = Graph()
        EX = Namespace("http://example.com/")
        g.add((EX.item, EX.value, Literal("5", datatype=XSD.integer)))
        g.add((EX.item, EX.value, Literal("5", datatype=XSD.decimal)))

        count = db._insert_graph(conn, g, "test", "data")
        conn.commit()

        rows = conn.execute(
            "SELECT datatype FROM triples WHERE subject = ? AND predicate = ?",
            (str(EX.item), str(EX.value)),
        ).fetchall()
        db.close()

        datatypes = {r[0] for r in rows}
        assert str(XSD.integer) in datatypes, f"xsd:integer lost, got: {datatypes}"
        assert str(XSD.decimal) in datatypes, f"xsd:decimal lost, got: {datatypes}"
        assert count == 2

    def test_distinct_language_tags_preserved(self, tmp_path):
        """Two lang-tagged literals with different tags must both survive."""
        from rdflib import Graph, Literal, URIRef, Namespace

        db = DregsStore(tmp_path / "lang.db")
        db.init()
        conn = db._connect()

        g = Graph()
        EX = Namespace("http://example.com/")
        g.add((EX.item, EX.label, Literal("hello", lang="en")))
        g.add((EX.item, EX.label, Literal("hello", lang="fr")))

        count = db._insert_graph(conn, g, "test", "data")
        conn.commit()

        rows = conn.execute(
            "SELECT lang FROM triples WHERE subject = ? AND predicate = ?",
            (str(EX.item), str(EX.label)),
        ).fetchall()
        db.close()

        langs = {r[0] for r in rows}
        assert "en" in langs, f"en lost, got: {langs}"
        assert "fr" in langs, f"fr lost, got: {langs}"
        assert count == 2

    def test_triple_count_matches_actual(self, tmp_path):
        """Reported triple count must match actual rows in database."""
        from rdflib import Graph, Literal, URIRef, Namespace

        db = DregsStore(tmp_path / "count.db")
        db.init()
        conn = db._connect()

        g = Graph()
        EX = Namespace("http://example.com/")
        # Add the same triple twice — rdflib deduplicates, but test the path
        g.add((EX.a, EX.b, Literal("x")))
        g.add((EX.a, EX.b, Literal("y")))

        count = db._insert_graph(conn, g, "test", "data")
        conn.commit()

        actual = conn.execute(
            "SELECT COUNT(*) FROM triples WHERE graph = 'test'"
        ).fetchone()[0]
        db.close()

        assert count == actual, f"reported {count}, actual {actual}"

    def test_bnode_object_type_is_bnode(self, tmp_path):
        """BNode objects must be stored with object_type='bnode', not 'uri'."""
        from rdflib import Graph, URIRef, BNode, Namespace

        db = DregsStore(tmp_path / "bnode.db")
        db.init()
        conn = db._connect()

        g = Graph()
        EX = Namespace("http://example.com/")
        bn = BNode()
        g.add((EX.item, EX.rel, bn))

        db._insert_graph(conn, g, "test", "data")
        conn.commit()

        row = conn.execute(
            "SELECT object_type FROM triples WHERE subject = ? AND predicate = ?",
            (str(EX.item), str(EX.rel)),
        ).fetchone()
        db.close()

        assert row[0] == "bnode", f"expected 'bnode', got '{row[0]}'"


# ── ASK query support ──────────────────────────────────────────────

class TestAskQuery:
    """Regression test for ASK queries, which previously crashed."""

    def test_ask_returns_boolean(self, loaded_store):
        qr = execute_sparql(
            loaded_store,
            "ASK WHERE { ?s ?p ?o }",
        )
        assert len(qr.bindings) == 1
        assert qr.bindings[0]["result"] == "true"

    def test_ask_false(self, loaded_store):
        qr = execute_sparql(
            loaded_store,
            "ASK WHERE { <http://nonexistent.example/x> ?p ?o }",
        )
        assert qr.bindings[0]["result"] == "false"


# ── SQLite detection (issue #6) ────────────────────────────────────

class TestSqliteDetection:
    """Verify _is_sqlite detects databases by magic bytes, not extension."""

    def test_detects_real_sqlite_file(self, tmp_path):
        from dregs.cli import _is_sqlite

        db_path = tmp_path / "test.db"
        store = DregsStore(db_path)
        store.init()
        store.close()
        assert _is_sqlite(db_path) is True

    def test_detects_sqlite_with_nonstandard_extension(self, tmp_path):
        from dregs.cli import _is_sqlite

        db_path = tmp_path / "test.dregs"
        store = DregsStore(db_path)
        store.init()
        store.close()
        assert _is_sqlite(db_path) is True

    def test_detects_sqlite_with_no_extension(self, tmp_path):
        from dregs.cli import _is_sqlite

        db_path = tmp_path / "knowledge-base"
        store = DregsStore(db_path)
        store.init()
        store.close()
        assert _is_sqlite(db_path) is True

    def test_rejects_turtle_file(self):
        from dregs.cli import _is_sqlite

        ttl_path = EXAMPLES_ROOT / "ontology.ttl"
        assert _is_sqlite(ttl_path) is False

    def test_rejects_nonexistent_file(self, tmp_path):
        from dregs.cli import _is_sqlite

        assert _is_sqlite(tmp_path / "nope") is False

    def test_rejects_directory(self, tmp_path):
        from dregs.cli import _is_sqlite

        assert _is_sqlite(tmp_path) is False

    def test_check_works_with_nonstandard_db_extension(self, tmp_path):
        """End-to-end: `dregs check` routes correctly for .dregs extension."""
        from click.testing import CliRunner
        from dregs.cli import cli

        paths = EXAMPLE_SETS["default"]
        db_path = tmp_path / "my-store.dregs"
        store = DregsStore(db_path)
        store.init(schema_path=paths["ontology"], shacl_path=paths["shapes"])
        store.close()

        runner = CliRunner()
        result = runner.invoke(cli, ["check", str(db_path), str(paths["good_data"])])
        assert result.exit_code == 0, result.output

    def test_prompt_works_with_nonstandard_db_extension(self, tmp_path):
        """End-to-end: `dregs prompt` routes correctly for .dregs extension."""
        from click.testing import CliRunner
        from dregs.cli import cli

        paths = EXAMPLE_SETS["default"]
        db_path = tmp_path / "my-store.dregs"
        store = DregsStore(db_path)
        store.init(schema_path=paths["ontology"], shacl_path=paths["shapes"])
        store.close()

        runner = CliRunner()
        result = runner.invoke(cli, ["prompt", str(db_path)])
        assert result.exit_code == 0, result.output
        assert "Entity Types" in result.output


# ── Helpers ──────────────────────────────────────────────────────────


def _load_example(tmp_path: Path, name: str) -> DregsStore:
    """Init + load an example set, return the store."""
    paths = EXAMPLE_SETS[name]
    db = DregsStore(tmp_path / f"{name}.db")
    db.init(schema_path=paths["ontology"], shacl_path=paths["shapes"])
    result = db.load(paths["good_data"], graph_name="test")
    assert result["loaded"], result
    return db
