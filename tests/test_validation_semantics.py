"""Validation-semantics tests for remains.

These tests specify the intended behavior of validation entry points:

1. ``store.load()`` validates ONLY the incoming subgraph, using the current
   DB contents (ontology + shapes + existing default-graph) as CONTEXT so
   references resolve. It does not re-validate existing data on every load.

2. ``remains check`` (via ``store`` API used by the CLI) also validates
   incoming against DB-as-context, not in isolation.

3. ``store.validate_store()`` is a separate entry point that re-validates
   the entire default graph against the current shapes (used for audits
   when shapes change).
"""
from __future__ import annotations

from pathlib import Path

from remains.store import RemainsStore

EXAMPLES_ROOT = Path(__file__).parent.parent / "examples"

PERMISSIVE_SHAPES = """\
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix ex: <http://example.com/ontology#> .

# Permissive: no property constraints at all.
ex:PersonShape a sh:NodeShape ;
    sh:targetClass ex:Person .
"""


# ---------------------------------------------------------------------------
# store.load() — validate incoming-only with DB as context
# ---------------------------------------------------------------------------


class TestLoadValidatesIncomingOnly:
    def test_existing_data_violating_current_shapes_does_not_block_unrelated_load(
        self, tmp_path
    ):
        """Existing data that would fail CURRENT shapes must not block a
        new, shape-compliant load of unrelated data. Old data is context,
        not a re-validation target.
        """
        db = RemainsStore(tmp_path / "t.db")
        db.init(ontology_path=EXAMPLES_ROOT / "ontology.ttl")
        db.update_shacl(PERMISSIVE_SHAPES)

        # Permissive PersonShape lets a name-less Person in.
        r = db.load(
            "@prefix ex: <http://example.com/ontology#> .\n"
            "ex:alice a ex:Person .\n"
        )
        assert r["loaded"], "permissive load should succeed"

        # Tighten shapes. Existing alice now violates the stricter PersonShape
        # (no ex:name), but update_shacl does not re-validate historical data.
        db.update_shacl(EXAMPLES_ROOT / "shapes.ttl")

        # Load unrelated new data. Only the incoming subgraph is validated.
        r = db.load(
            "@prefix ex: <http://example.com/ontology#> .\n"
            'ex:doc-x a ex:Document ; ex:title "X" .\n'
        )
        assert r["loaded"], (
            "load of valid incoming data must not be blocked by pre-existing "
            "data that violates current shapes; got: "
            + (r["validation"].summary() if "validation" in r else repr(r))
        )
        db.close()

    def test_incoming_references_existing_instance_resolves_sh_class(
        self, tmp_path
    ):
        """Incoming data may reference an instance already in the DB by URI
        alone (without restating its type). A sh:class constraint on that
        reference resolves via the DB context.
        """
        db = RemainsStore(tmp_path / "t.db")
        db.init(
            ontology_path=EXAMPLES_ROOT / "ontology.ttl",
            shacl_path=EXAMPLES_ROOT / "shapes.ttl",
        )
        r = db.load(EXAMPLES_ROOT / "data_good.ttl")
        assert r["loaded"]

        # A new Decision referencing the already-loaded ex:person-john.
        # The incoming subgraph does NOT restate `ex:person-john a ex:Person`.
        # DecisionShape requires ex:madeBy to be sh:class ex:Person; this
        # must resolve from DB context.
        incoming = (
            "@prefix ex: <http://example.com/ontology#> .\n"
            "ex:decision-new a ex:Decision ;\n"
            '    ex:description "new call" ;\n'
            "    ex:madeBy ex:person-john .\n"
        )
        r = db.load(incoming)
        assert r["loaded"], (
            "sh:class constraint on reference to pre-loaded individual must "
            "be satisfied by DB context; got: "
            + (r["validation"].summary() if "validation" in r else repr(r))
        )
        db.close()

    def test_incoming_itself_violates_shapes_is_still_rejected(self, tmp_path):
        """Incoming-only validation still catches violations in the
        incoming subgraph. This guards the existing rejection path."""
        db = RemainsStore(tmp_path / "t.db")
        db.init(
            ontology_path=EXAMPLES_ROOT / "ontology.ttl",
            shacl_path=EXAMPLES_ROOT / "shapes.ttl",
        )
        # Person with no name — violates PersonShape.
        r = db.load(
            "@prefix ex: <http://example.com/ontology#> .\n"
            "ex:bob a ex:Person .\n"
        )
        assert not r["loaded"], "incoming violation must still be rejected"
        db.close()


# ---------------------------------------------------------------------------
# `remains check` / store.check() — DB as context
# ---------------------------------------------------------------------------


class TestCheckUsesDbContext:
    def test_check_resolves_references_from_existing_db(self, tmp_path):
        """Checking an incoming subgraph that references a pre-loaded
        individual must succeed when the referenced individual satisfies
        the constraint via DB context.
        """
        db = RemainsStore(tmp_path / "t.db")
        db.init(
            ontology_path=EXAMPLES_ROOT / "ontology.ttl",
            shacl_path=EXAMPLES_ROOT / "shapes.ttl",
        )
        db.load(EXAMPLES_ROOT / "data_good.ttl")

        incoming = (
            "@prefix ex: <http://example.com/ontology#> .\n"
            "ex:decision-new a ex:Decision ;\n"
            '    ex:description "new call" ;\n'
            "    ex:madeBy ex:person-john .\n"
        )
        result = db.check(incoming)
        assert result.conforms, (
            "check should resolve sh:class via DB context; got: "
            + result.summary()
        )
        db.close()

    def test_check_does_not_mutate_store(self, tmp_path):
        """check validates without persisting any incoming triples."""
        db = RemainsStore(tmp_path / "t.db")
        db.init(
            ontology_path=EXAMPLES_ROOT / "ontology.ttl",
            shacl_path=EXAMPLES_ROOT / "shapes.ttl",
        )
        before = db.stats()["data_triples"]

        incoming = (
            "@prefix ex: <http://example.com/ontology#> .\n"
            'ex:doc-y a ex:Document ; ex:title "Y" .\n'
        )
        db.check(incoming)

        after = db.stats()["data_triples"]
        assert after == before, "check must not persist"
        db.close()


# ---------------------------------------------------------------------------
# store.validate_store() — re-validate the whole default graph
# ---------------------------------------------------------------------------


class TestValidateStore:
    def test_validate_store_flags_historical_violations(self, tmp_path):
        """When shapes tighten after data is already loaded,
        validate_store() surfaces the now-non-conforming historical data.
        """
        db = RemainsStore(tmp_path / "t.db")
        db.init(ontology_path=EXAMPLES_ROOT / "ontology.ttl")
        db.update_shacl(PERMISSIVE_SHAPES)

        db.load(
            "@prefix ex: <http://example.com/ontology#> .\n"
            "ex:alice a ex:Person .\n"
        )

        # Tighten shapes. Alice now violates PersonShape (no name).
        db.update_shacl(EXAMPLES_ROOT / "shapes.ttl")

        result = db.validate_store()
        assert not result.conforms, (
            "validate_store should surface historical violations under "
            "current shapes"
        )
        joined = "\n".join(result.shacl_violations or [])
        assert "alice" in joined, (
            "violation report should identify the offending node; got: "
            + joined
        )
        db.close()

    def test_validate_store_clean_db_conforms(self, tmp_path):
        """A fully-conformant DB produces a clean validate_store result."""
        db = RemainsStore(tmp_path / "t.db")
        db.init(
            ontology_path=EXAMPLES_ROOT / "ontology.ttl",
            shacl_path=EXAMPLES_ROOT / "shapes.ttl",
        )
        db.load(EXAMPLES_ROOT / "data_good.ttl")
        result = db.validate_store()
        assert result.conforms, (
            "clean data should conform under validate_store; got: "
            + result.summary()
        )
        db.close()
