# CLAUDE.md

## Visualizing the knowledge graph

`remains viz` has two modes:

```
remains viz -d my.db                    # live server on localhost:7171
remains viz -d my.db -o graph.html      # write a self-contained static HTML file and exit
```

The static export is the right choice in headless environments (CI, remote
servers, agent sandboxes) where there is no browser to connect to the
server. The exported HTML is identical to what the server serves, minus the
SSE-based live annotation channel (which needs a running server).

### Scoping the visualization

Large graphs become a hairball. Two flags let you narrow to a subgraph:

```
# Visualize only triples returned by a CONSTRUCT query
remains viz -d my.db --query "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o ; a ex:Event }"

# Focus on a node and its N-hop neighborhood (sugar for a common CONSTRUCT)
remains viz -d my.db --focus http://example.com/ns#alice --hops 2

# Combine with --output for a static export of the focused subgraph
remains viz -d my.db -o alice.html --focus http://example.com/ns#alice --hops 2
```

`--query` and `--focus` are mutually exclusive.

## Running Tests

Install the project with test dependencies:

```
pip install -e ".[test]"
```

Run all tests:

```
python -m pytest tests/ -v
```

Run only local tests (no remote database required):

```
python -m pytest tests/ -v --ignore=tests/test_turso_remote.py
```

Note: `test_turso_remote.py` requires a live Turso database connection and will fail without network access.
