# CLAUDE.md

`remains --help` and `remains <command> --help` are the authoritative CLI
reference — prefer them over anything restated in this file. The notes below
only cover things that are easy to get wrong or that `--help` cannot convey.

## Visualizing the knowledge graph

`remains viz` runs two modes: a live server on `localhost:7171` (default) and
a self-contained static HTML export (`-o graph.html`). The static export is
the right choice in headless environments (CI, remote servers, agent
sandboxes) where there is no browser to connect to the server. The exported
HTML is identical to what the server serves, minus the SSE-based live
annotation channel (which needs a running server).

### Scoping the visualization

Large graphs become a hairball. `--query` (a SPARQL `CONSTRUCT`) and
`--focus <uri> [--hops N]` both narrow the view to a subgraph, and both
combine with `-o` for a static export of the narrowed view. The two flags
are mutually exclusive. Example:

```
remains viz -d my.db -o alice.html --focus http://example.com/ns#alice --hops 2
```

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
