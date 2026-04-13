# remains — 3 Fixed Graphs Architecture

*2026-04-12T21:49:54Z by Showboat 0.6.1*
<!-- showboat-id: a14a3ade-cf2a-4028-8a95-1943b3035bcc -->

One SQLite database. 3 fixed graphs: default (data), urn:ontology (system + user vocabulary), urn:shacl (system + user shapes). System ontology ships remains:RequiresDisplayName.

## Tests

```bash
/usr/bin/python3 -m pytest tests/ -v --tb=short 2>&1 | tail -60
```

```output
============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-9.0.3, pluggy-1.6.0 -- /usr/bin/python3
cachedir: .pytest_cache
rootdir: /tmp/remains
configfile: pyproject.toml
collecting ... collected 51 items

tests/test_core.py::TestInit::test_init_creates_three_graphs PASSED      [  1%]
tests/test_core.py::TestInit::test_init_loads_system_ontology PASSED     [  3%]
tests/test_core.py::TestInit::test_init_loads_user_ontology PASSED       [  5%]
tests/test_core.py::TestInit::test_init_loads_system_shapes PASSED       [  7%]
tests/test_core.py::TestInit::test_init_loads_user_shapes PASSED         [  9%]
tests/test_core.py::TestLoad::test_load_into_default_graph PASSED        [ 11%]
tests/test_core.py::TestLoad::test_load_rejects_bad_data PASSED          [ 13%]
tests/test_core.py::TestLoad::test_no_named_graphs_created PASSED        [ 15%]
tests/test_core.py::TestPrompt::test_prompt_includes_user_classes PASSED [ 17%]
tests/test_core.py::TestPrompt::test_prompt_excludes_system_classes PASSED [ 19%]
tests/test_core.py::TestNamespaceProtection::test_update_ontology_rejects_system_namespace PASSED [ 25%]
tests/test_core.py::TestNamespaceProtection::test_update_shacl_rejects_system_namespace PASSED [ 27%]
tests/test_core.py::TestExport::test_export_data_only PASSED             [ 29%]
tests/test_core.py::TestExport::test_export_ontology_user_only PASSED    [ 31%]
tests/test_core.py::TestExport::test_export_all PASSED                   [ 33%]
tests/test_core.py::TestInfo::test_stats_structure PASSED                [ 35%]
tests/test_core.py::TestDisplayNames::test_display_name_from_rdfs_label PASSED [ 49%]
tests/test_core.py::TestDisplayNames::test_display_name_fallback_to_uri PASSED [ 50%]
tests/test_core.py::TestDisplayNames::test_display_name_uri_path_fallback PASSED [ 52%]
tests/test_viz.py::TestBuildGraphData::test_returns_nodes_edges_analytics PASSED [ 54%]
tests/test_viz.py::TestBuildGraphData::test_nodes_have_required_fields PASSED [ 56%]
tests/test_viz.py::TestBuildGraphData::test_edges_have_required_fields PASSED [ 58%]
tests/test_viz.py::TestBuildGraphData::test_finds_entities PASSED        [ 60%]
tests/test_viz.py::TestBuildGraphData::test_finds_relationships PASSED   [ 62%]
tests/test_viz.py::TestBuildGraphData::test_no_schema_nodes PASSED       [ 64%]
tests/test_viz.py::TestAnalytics::test_community_detection PASSED        [ 66%]
tests/test_viz.py::TestAnalytics::test_betweenness_centrality PASSED     [ 68%]
tests/test_viz.py::TestAnalytics::test_analytics_metadata PASSED         [ 70%]
tests/test_viz.py::TestAnalytics::test_communities_have_structure PASSED [ 72%]
tests/test_viz.py::TestAnalytics::test_gap_detection PASSED              [ 74%]
tests/test_viz.py::TestAnalytics::test_node_sizing_varies PASSED         [ 76%]
tests/test_viz.py::TestAnalytics::test_bias_label_valid PASSED           [ 78%]
tests/test_viz.py::TestAnalytics::test_top_bc_nodes_have_fields PASSED   [ 80%]
tests/test_viz.py::TestAnalyticsDirect::test_empty_graph PASSED          [ 82%]
tests/test_viz.py::TestAnalyticsDirect::test_single_node PASSED          [ 84%]
tests/test_viz.py::TestAnalyticsDirect::test_two_clusters PASSED         [ 86%]
tests/test_viz.py::TestAnalyticsDirect::test_bridge_node_has_high_bc PASSED [ 88%]
tests/test_viz.py::TestServeViz::test_serves_html PASSED                 [ 90%]
tests/test_viz.py::TestServeViz::test_serves_api_graph PASSED            [ 92%]
tests/test_viz.py::TestServeViz::test_post_annotate PASSED               [ 94%]
tests/test_viz.py::TestServeViz::test_post_annotate_bad_json PASSED      [ 96%]
tests/test_viz.py::TestServeViz::test_sse_endpoint_connects PASSED       [ 98%]
tests/test_viz.py::TestServeViz::test_serves_api_analytics PASSED        [100%]

============================= 51 passed in 13.43s ==============================
```

## Initialize

```bash
export PATH=$HOME/.local/bin:$PATH && REMAINS_DSN=/tmp/demo.db remains init --ontology examples/ontology.ttl --shacl examples/shapes.ttl 2>/dev/null
```

```output
Initialized /tmp/demo.db
  System ontology: 35 triples
  User ontology:   116 triples
  System shapes:   48 triples
  User shapes:     48 triples
```

## Load Data

```bash
export PATH=$HOME/.local/bin:$PATH && REMAINS_DSN=/tmp/demo.db remains load examples/data_good.ttl 2>/dev/null
```

```output
Loaded 23 triples
```

## Info

```bash
export PATH=$HOME/.local/bin:$PATH && REMAINS_DSN=/tmp/demo.db remains info 2>/dev/null
```

```output
Database:  /tmp/demo.db
Version:   0.2.0
Created:   2026-04-12T21:50:29.270950+00:00
Data:      23 triples
Ontology:  151 triples
SHACL:     96 triples
```

## Prompt — Full Ontology

```bash
export PATH=$HOME/.local/bin:$PATH && REMAINS_DSN=/tmp/demo.db remains prompt 2>/dev/null | head -30
```

```output
# Ontology Schema for Extraction

Extract ONLY the following entity types and relationships.
Do NOT invent new types. Output as Turtle (TTL) format.

## Entity Types
### Activity
  Definition: Abstract: something that happens. Not used directly.

### Agent
  Definition: Abstract: an entity that acts. Not used directly.

### Artifact
  Definition: Abstract: a thing produced or referenced. Not used directly.

### Decision (subclass of Artifact)
  Definition: A Decision is an Artifact representing a formal choice with rationale.
  example: Approved migration to Kubernetes

### Document (subclass of Artifact)
  Definition: A Document is an Artifact representing a written work (report, memo, spec).
  example: Q3 Architecture Review document

### Meeting (subclass of Activity)
  Definition: A Meeting is an Activity where agents convene to discuss topics.
  example: Weekly standup on 2026-04-01
```

## Namespace Protection

```bash
export PATH=$HOME/.local/bin:$PATH
cat > /tmp/evil.ttl << 'EOF'
@prefix remains: <urn:remains:system#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
remains:EvilClass a owl:Class .
EOF
REMAINS_DSN=/tmp/demo.db remains update-ontology /tmp/evil.ttl 2>&1 | grep -o 'ValueError:.*'
```

```output
ValueError: Cannot modify system namespace (urn:remains:system#). Subject urn:remains:system#EvilClass is protected.
```

## Query

```bash
export PATH=$HOME/.local/bin:$PATH && REMAINS_DSN=/tmp/demo.db remains query 'SELECT ?person ?org WHERE { ?person a ex:Person . ?person ex:worksAt ?org }' 2>/dev/null
```

```output
person         | org        
---------------+------------
ex:person-john | ex:org-acme

(1 results)
```

## Export

```bash
export PATH=$HOME/.local/bin:$PATH && REMAINS_DSN=/tmp/demo.db remains export --what data 2>/dev/null | head -20
```

```output
@prefix ex: <http://example.com/ontology#> .
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

ex:decision-k8s a ex:Decision ;
    ex:date "2026-04-01" ;
    ex:description "Approved migration to Kubernetes for production workloads" ;
    ex:madeBy ex:person-john ;
    ex:producedAt ex:meeting-standup-apr1 ;
    ex:rationale "Better scaling, team familiarity, cost reduction vs current VMs" ;
    prov:wasDerivedFrom <http://example.com/docs/standup-2026-04-01.md> .

ex:doc-arch-review a ex:Document ;
    ex:authored ex:person-john ;
    ex:title "Q3 Architecture Review" ;
    prov:wasDerivedFrom <http://example.com/docs/standup-2026-04-01.md> .
```
