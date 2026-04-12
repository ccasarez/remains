"""Tests for the graph visualizer and analytics engine."""
import json
import threading
import time
import urllib.request

import pytest

from dregs.store import DregsStore
from dregs.viz import _build_graph_data, serve_viz
from dregs.analytics import compute_analytics, HAS_NETWORKX


@pytest.fixture
def loaded_store(tmp_path):
    """Create a store with schema and sample data."""
    db = tmp_path / "test.db"
    store = DregsStore(str(db))

    schema = tmp_path / "schema.ttl"
    schema.write_text("""
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <http://example.com/ns#> .

ex:Person a owl:Class ; rdfs:label "Person" .
ex:Org a owl:Class ; rdfs:label "Org" .
ex:Project a owl:Class ; rdfs:label "Project" .
ex:worksAt a owl:ObjectProperty ; rdfs:domain ex:Person ; rdfs:range ex:Org .
ex:manages a owl:ObjectProperty ; rdfs:domain ex:Person ; rdfs:range ex:Project .
ex:fundedBy a owl:ObjectProperty ; rdfs:domain ex:Project ; rdfs:range ex:Org .
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

ex:alice a ex:Person ; ex:name "Alice"^^xsd:string ; ex:worksAt ex:acme ; ex:manages ex:projectX .
ex:bob a ex:Person ; ex:name "Bob"^^xsd:string ; ex:worksAt ex:acme ; ex:manages ex:projectY .
ex:carol a ex:Person ; ex:name "Carol"^^xsd:string ; ex:worksAt ex:globex ; ex:manages ex:projectZ .
ex:dave a ex:Person ; ex:name "Dave"^^xsd:string ; ex:worksAt ex:globex .
ex:acme a ex:Org ; ex:name "Acme Corp"^^xsd:string .
ex:globex a ex:Org ; ex:name "Globex Inc"^^xsd:string .
ex:projectX a ex:Project ; ex:name "Project X"^^xsd:string ; ex:fundedBy ex:acme .
ex:projectY a ex:Project ; ex:name "Project Y"^^xsd:string ; ex:fundedBy ex:acme .
ex:projectZ a ex:Project ; ex:name "Project Z"^^xsd:string ; ex:fundedBy ex:globex .
""")
    result = store.load(data, graph_name="test-data")
    assert result["loaded"]

    yield store
    store.close()


class TestBuildGraphData:
    def test_returns_nodes_edges_analytics(self, loaded_store):
        data = _build_graph_data(loaded_store)
        assert "nodes" in data
        assert "edges" in data
        assert "analytics" in data

    def test_nodes_have_required_fields(self, loaded_store):
        data = _build_graph_data(loaded_store)
        for node in data["nodes"]:
            assert "id" in node
            assert "label" in node
            assert "type" in node
            assert "color" in node
            assert "size" in node
            assert "community" in node
            assert "bc" in node
            assert "degree" in node

    def test_edges_have_required_fields(self, loaded_store):
        data = _build_graph_data(loaded_store)
        for edge in data["edges"]:
            assert "source" in edge
            assert "target" in edge
            assert "label" in edge

    def test_finds_entities(self, loaded_store):
        data = _build_graph_data(loaded_store)
        assert len(data["nodes"]) >= 9  # 4 people + 2 orgs + 3 projects

    def test_finds_relationships(self, loaded_store):
        data = _build_graph_data(loaded_store)
        edge_labels = {e["label"] for e in data["edges"]}
        assert "worksAt" in edge_labels
        assert "manages" in edge_labels
        assert "fundedBy" in edge_labels

    def test_no_schema_nodes(self, loaded_store):
        data = _build_graph_data(loaded_store)
        ids = {n["id"] for n in data["nodes"]}
        for nid in ids:
            assert "owl:" not in nid
            assert "rdfs:" not in nid
            assert "shacl" not in nid.lower()


class TestAnalytics:
    def test_community_detection(self, loaded_store):
        data = _build_graph_data(loaded_store)
        for node in data["nodes"]:
            assert "community" in node
            assert isinstance(node["community"], int)

    def test_betweenness_centrality(self, loaded_store):
        data = _build_graph_data(loaded_store)
        for node in data["nodes"]:
            assert "bc" in node
            assert 0 <= node["bc"] <= 1

    def test_analytics_metadata(self, loaded_store):
        data = _build_graph_data(loaded_store)
        a = data["analytics"]
        assert "modularity" in a
        assert "communities" in a
        assert "biasLabel" in a
        assert "density" in a
        assert "componentCount" in a
        assert "avgDegree" in a
        assert "topBCNodes" in a
        assert "gaps" in a

    def test_communities_have_structure(self, loaded_store):
        data = _build_graph_data(loaded_store)
        for comm in data["analytics"]["communities"]:
            assert "id" in comm
            assert "nodeCount" in comm
            assert "color" in comm
            assert "topNodes" in comm
            assert comm["nodeCount"] > 0

    def test_gap_detection(self, loaded_store):
        data = _build_graph_data(loaded_store)
        for gap in data["analytics"]["gaps"]:
            assert "communityA" in gap
            assert "communityB" in gap
            assert "crossEdges" in gap
            assert "question" in gap

    def test_node_sizing_varies(self, loaded_store):
        data = _build_graph_data(loaded_store)
        sizes = [n["size"] for n in data["nodes"]]
        if len(sizes) > 2:
            assert max(sizes) > min(sizes), "Node sizes should vary by centrality"

    def test_bias_label_valid(self, loaded_store):
        data = _build_graph_data(loaded_store)
        assert data["analytics"]["biasLabel"] in ("Dispersed", "Diversified", "Focused", "Biased", "Empty", "Unknown")

    def test_top_bc_nodes_have_fields(self, loaded_store):
        data = _build_graph_data(loaded_store)
        for n in data["analytics"]["topBCNodes"]:
            assert "id" in n
            assert "label" in n
            assert "bc" in n
            assert "community" in n
            assert "color" in n


class TestAnalyticsDirect:
    """Test compute_analytics directly with synthetic data."""

    def test_empty_graph(self):
        result = compute_analytics([], [])
        assert result["modularity"] == 0
        assert result["biasLabel"] in ("Empty", "Unknown")

    def test_single_node(self):
        nodes = [{"id": "a", "label": "A", "type": "X", "color": "#fff", "edges": 0, "size": 4}]
        result = compute_analytics(nodes, [])
        assert nodes[0]["community"] == 0
        assert nodes[0]["bc"] == 0

    @pytest.mark.skipif(not HAS_NETWORKX, reason="networkx required")
    def test_two_clusters(self):
        """Two disconnected cliques should produce 2 communities."""
        nodes = [{"id": f"n{i}", "label": f"N{i}", "type": "X", "color": "#fff", "edges": 0, "size": 4} for i in range(6)]
        # Clique 1: n0-n1-n2
        # Clique 2: n3-n4-n5
        edges = [
            {"source": "n0", "target": "n1", "label": "r"},
            {"source": "n1", "target": "n2", "label": "r"},
            {"source": "n0", "target": "n2", "label": "r"},
            {"source": "n3", "target": "n4", "label": "r"},
            {"source": "n4", "target": "n5", "label": "r"},
            {"source": "n3", "target": "n5", "label": "r"},
        ]
        result = compute_analytics(nodes, edges)
        assert len(result["communities"]) >= 2
        assert result["componentCount"] == 2

    @pytest.mark.skipif(not HAS_NETWORKX, reason="networkx required")
    def test_bridge_node_has_high_bc(self):
        """A bridge node connecting two groups should have highest BC."""
        nodes = [{"id": f"n{i}", "label": f"N{i}", "type": "X", "color": "#fff", "edges": 0, "size": 4} for i in range(5)]
        # n0-n1-n2(bridge)-n3-n4
        edges = [
            {"source": "n0", "target": "n1", "label": "r"},
            {"source": "n1", "target": "n2", "label": "r"},
            {"source": "n0", "target": "n2", "label": "r"},
            {"source": "n2", "target": "n3", "label": "r"},
            {"source": "n3", "target": "n4", "label": "r"},
            {"source": "n2", "target": "n4", "label": "r"},
        ]
        compute_analytics(nodes, edges)
        node_map = {n["id"]: n for n in nodes}
        # n2 is the bridge
        assert node_map["n2"]["bc"] >= node_map["n0"]["bc"]
        assert node_map["n2"]["bc"] >= node_map["n4"]["bc"]


class TestServeViz:
    def test_serves_html(self, loaded_store):
        port = 17171
        prebuilt = _build_graph_data(loaded_store)
        server_thread = threading.Thread(
            target=serve_viz, args=(loaded_store,),
            kwargs={"port": port, "open_browser": False, "_prebuilt_data": prebuilt},
            daemon=True,
        )
        server_thread.start()
        time.sleep(1)

        resp = urllib.request.urlopen(f"http://localhost:{port}/")
        html = resp.read().decode()
        assert "dregs" in html
        assert "analytics" in html  # JSON data contains analytics key
        assert "communities" in html
        assert resp.status == 200

    def test_serves_api_graph(self, loaded_store):
        port = 17172
        prebuilt = _build_graph_data(loaded_store)
        server_thread = threading.Thread(
            target=serve_viz, args=(loaded_store,),
            kwargs={"port": port, "open_browser": False, "_prebuilt_data": prebuilt},
            daemon=True,
        )
        server_thread.start()
        time.sleep(1)

        resp = urllib.request.urlopen(f"http://localhost:{port}/api/graph")
        data = json.loads(resp.read())
        assert "nodes" in data
        assert "edges" in data
        assert "analytics" in data
        assert len(data["nodes"]) > 0

    def test_post_annotate(self, loaded_store):
        """POST /api/annotate accepts annotations and returns ok."""
        port = 17174
        prebuilt = _build_graph_data(loaded_store)
        server_thread = threading.Thread(
            target=serve_viz, args=(loaded_store,),
            kwargs={"port": port, "open_browser": False, "_prebuilt_data": prebuilt},
            daemon=True,
        )
        server_thread.start()
        time.sleep(1)

        annotation = json.dumps({"type": "toast", "text": "Hello"}).encode()
        req = urllib.request.Request(
            f"http://localhost:{port}/api/annotate",
            data=annotation,
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req)
        result = json.loads(resp.read())
        assert result["ok"] is True

    def test_post_annotate_bad_json(self, loaded_store):
        """POST /api/annotate rejects invalid JSON."""
        port = 17175
        prebuilt = _build_graph_data(loaded_store)
        server_thread = threading.Thread(
            target=serve_viz, args=(loaded_store,),
            kwargs={"port": port, "open_browser": False, "_prebuilt_data": prebuilt},
            daemon=True,
        )
        server_thread.start()
        time.sleep(1)

        req = urllib.request.Request(
            f"http://localhost:{port}/api/annotate",
            data=b"not json",
            headers={"Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(req)
            assert False, "Should have raised"
        except urllib.error.HTTPError as e:
            assert e.code == 400

    def test_sse_endpoint_connects(self, loaded_store):
        """GET /api/events returns SSE stream."""
        port = 17176
        prebuilt = _build_graph_data(loaded_store)
        server_thread = threading.Thread(
            target=serve_viz, args=(loaded_store,),
            kwargs={"port": port, "open_browser": False, "_prebuilt_data": prebuilt},
            daemon=True,
        )
        server_thread.start()
        time.sleep(1)

        req = urllib.request.Request(f"http://localhost:{port}/api/events")
        resp = urllib.request.urlopen(req, timeout=2)
        assert resp.headers.get("Content-Type") == "text/event-stream"
        # Read the initial comment
        first_line = resp.readline().decode().strip()
        assert first_line == ": connected"

    def test_serves_api_analytics(self, loaded_store):
        port = 17173
        prebuilt = _build_graph_data(loaded_store)
        server_thread = threading.Thread(
            target=serve_viz, args=(loaded_store,),
            kwargs={"port": port, "open_browser": False, "_prebuilt_data": prebuilt},
            daemon=True,
        )
        server_thread.start()
        time.sleep(1)

        resp = urllib.request.urlopen(f"http://localhost:{port}/api/analytics")
        data = json.loads(resp.read())
        assert "communities" in data
        assert "modularity" in data
        assert "biasLabel" in data
