"""Tests for the graph visualizer."""
import json
import threading
import time
import urllib.request

import pytest

from dregs.store import DregsStore
from dregs.viz import _build_graph_data, serve_viz


@pytest.fixture
def loaded_store(tmp_path):
    """Create a store with schema and sample data."""
    db = tmp_path / "test.db"
    store = DregsStore(str(db))

    # Minimal schema
    schema = tmp_path / "schema.ttl"
    schema.write_text("""
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <http://example.com/ns#> .

ex:Person a owl:Class ; rdfs:label "Person" .
ex:Org a owl:Class ; rdfs:label "Org" .
ex:worksAt a owl:ObjectProperty ; rdfs:domain ex:Person ; rdfs:range ex:Org .
ex:name a owl:DatatypeProperty .
""")

    shacl = tmp_path / "shapes.ttl"
    shacl.write_text("""
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix ex: <http://example.com/ns#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

ex:PersonShape a sh:NodeShape ;
    sh:targetClass ex:Person ;
    sh:property [ sh:path ex:name ; sh:minCount 1 ; sh:datatype xsd:string ] .
""")

    store.init(schema_path=schema, shacl_path=shacl)

    data = tmp_path / "data.ttl"
    data.write_text("""
@prefix ex: <http://example.com/ns#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

ex:alice a ex:Person ; ex:name "Alice"^^xsd:string ; ex:worksAt ex:acme .
ex:bob a ex:Person ; ex:name "Bob"^^xsd:string ; ex:worksAt ex:acme .
ex:acme a ex:Org ; ex:name "Acme Corp"^^xsd:string .
""")
    result = store.load(data, graph_name="test-data")
    assert result["loaded"]

    yield store
    store.close()


class TestBuildGraphData:
    def test_returns_nodes_and_edges(self, loaded_store):
        data = _build_graph_data(loaded_store)
        assert "nodes" in data
        assert "edges" in data
        assert "types" in data

    def test_nodes_have_required_fields(self, loaded_store):
        data = _build_graph_data(loaded_store)
        for node in data["nodes"]:
            assert "id" in node
            assert "label" in node
            assert "type" in node
            assert "color" in node
            assert "size" in node

    def test_edges_have_required_fields(self, loaded_store):
        data = _build_graph_data(loaded_store)
        for edge in data["edges"]:
            assert "source" in edge
            assert "target" in edge
            assert "label" in edge

    def test_finds_entities(self, loaded_store):
        data = _build_graph_data(loaded_store)
        ids = {n["id"] for n in data["nodes"]}
        # Should find alice, bob, and acme
        assert len(data["nodes"]) >= 3

    def test_finds_relationships(self, loaded_store):
        data = _build_graph_data(loaded_store)
        edge_labels = {e["label"] for e in data["edges"]}
        assert "worksAt" in edge_labels

    def test_no_schema_nodes(self, loaded_store):
        data = _build_graph_data(loaded_store)
        ids = {n["id"] for n in data["nodes"]}
        # Schema class URIs should not appear as nodes
        for nid in ids:
            assert "owl:" not in nid
            assert "rdfs:" not in nid
            assert "shacl" not in nid.lower()


class TestServeViz:
    def test_serves_html(self, loaded_store):
        """Server responds with HTML on /."""
        port = 17171
        # Build data in main thread (SQLite thread safety)
        prebuilt = _build_graph_data(loaded_store)
        server_thread = threading.Thread(
            target=serve_viz,
            args=(loaded_store,),
            kwargs={"port": port, "open_browser": False, "_prebuilt_data": prebuilt},
            daemon=True,
        )
        server_thread.start()
        time.sleep(1)

        resp = urllib.request.urlopen(f"http://localhost:{port}/")
        html = resp.read().decode()
        assert "dregs" in html
        assert "GRAPH_DATA" in html
        assert resp.status == 200

    def test_serves_api_json(self, loaded_store):
        """Server responds with JSON on /api/graph."""
        port = 17172
        prebuilt = _build_graph_data(loaded_store)
        server_thread = threading.Thread(
            target=serve_viz,
            args=(loaded_store,),
            kwargs={"port": port, "open_browser": False, "_prebuilt_data": prebuilt},
            daemon=True,
        )
        server_thread.start()
        time.sleep(1)

        resp = urllib.request.urlopen(f"http://localhost:{port}/api/graph")
        data = json.loads(resp.read())
        assert "nodes" in data
        assert "edges" in data
        assert len(data["nodes"]) > 0
