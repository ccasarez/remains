# dregs

Triples-based knowledge graph CLI for LLM agents.

*The messy bits your agents remember.*

```
pip install dregs
```

Persistent knowledge graph storage backed by SQLite. Your agent extracts triples from unstructured text, dregs validates them against an OWL ontology + SHACL shapes, and stores what survives in a queryable graph. One file carries the schema, the constraints, and the data. No Java. No system deps. Pure Python.

## Quick Start

```bash
# Initialize with ontology + SHACL shapes
dregs init my.db --schema ontology.ttl --shacl shapes.ttl

# Load validated data (rejects invalid triples)
dregs load my.db extracted.ttl --graph emails

# Query with SPARQL
dregs query my.db "PREFIX ex: <http://example.com/ontology#>
  SELECT ?name WHERE { ?p a ex:Person ; ex:name ?name }"

# JSON output for agent consumption
dregs query my.db "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 5" --format json

# Export schema back to Turtle
dregs export my.db --type schema > ontology.ttl
```

## Commands

### `init`

Create a new store. Load ontology and/or SHACL shapes.

```
dregs init DB --schema ONTOLOGY [--shacl SHAPES]
```

### `load`

Load Turtle data. Validates against stored schema/SHACL by default. Rejects invalid data with clear violation messages.

```
dregs load DB DATA [--graph NAME] [--no-validate]
```

Exit code 1 on validation failure. Agent reads violations, fixes extraction, retries.

### `check`

Validate without loading. Two modes:

```
dregs check my.db data.ttl              # against DB's schema/SHACL
dregs check ontology.ttl data.ttl       # standalone, no DB
```

Runs OWL reasoning + SHACL validation + schema conformance checks.

### `query`

Execute SPARQL against the store. Queries the union of all graphs by default.

```
dregs query DB "SPARQL" [--format table|json|turtle] [--graph NAME]
```

### `export`

Export graphs as Turtle.

```
dregs export DB --type schema|shacl|data|all [--graph NAME]
```

### `prompt`

Generate LLM extraction prompt context from the ontology. Lists all classes, properties, and `skos:example` annotations.

```
dregs prompt my.db          # from DB's schema graph
dregs prompt ontology.ttl   # standalone from file
```

### `info`

Database statistics.

```
dregs info DB
```

### `graphs`

List named graphs.

```
dregs graphs DB
```

### `drop`

Delete a named graph and its triples.

```
dregs drop DB --graph NAME [-y]
```

## Agent Workflow

```bash
# 1. Setup (once)
dregs init project.db --schema ontology.ttl --shacl shapes.ttl

# 2. Generate extraction context
dregs prompt project.db > context.txt

# 3. LLM extracts triples from unstructured text using context.txt
#    (this step is yours -- dregs handles storage, not extraction)

# 4. Load with validation
dregs load project.db extracted.ttl --graph "source-doc"
# Exit 1? Read violations, re-extract, retry. Max 3 attempts.

# 5. Query the knowledge graph
dregs query project.db "PREFIX ex: <http://example.com/ontology#>
  SELECT ?person ?decision WHERE {
    ?d a ex:Decision ; ex:madeBy ?p ; ex:description ?decision .
    ?p ex:name ?person
  }"

# 6. Export for external tools
dregs export project.db --type schema > ontology.ttl
dregs export project.db --type data > all_data.ttl
```

## Python API

```python
from dregs import DregsStore
from dregs.sparql import execute_sparql
from dregs.prompt import prompt_from_store

# Initialize
db = DregsStore("project.db")
db.init(schema_path=Path("ontology.ttl"), shacl_path=Path("shapes.ttl"))

# Load with validation
result = db.load(Path("data.ttl"), graph_name="emails")
if not result["loaded"]:
    print(result["validation"].summary())

# Query
qr = execute_sparql(db, "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 10")
print(qr.to_table())

# Generate extraction prompt
context = prompt_from_store(db)

db.close()
```

## Connection Modes

dregs supports three connection modes, configured via environment variables:

### Local Only (default)

Pure local SQLite. No network required.

```bash
export DREGS_DSN=./my.db
dregs init --schema ontology.ttl
```

### Remote Only (Turso Cloud)

Every read and write goes over the network to a Turso database.

```bash
export DREGS_DSN=libsql://your-db-org.turso.io
export DREGS_AUTH_TOKEN=eyJ...
dregs info
```

### Embedded Replica (recommended for production)

A local SQLite file acts as a read cache that syncs with Turso Cloud. Reads hit the local file (fast, works offline), writes go through the cloud, and `sync()` pulls changes down on connect.

```bash
export DREGS_DSN="${XDG_DATA_HOME:-$HOME/.local/share}/dregs/dregs.db"
export DREGS_SYNC_URL=libsql://your-db-org.turso.io
export DREGS_AUTH_TOKEN=eyJ...
dregs info
```

```
┌─────────────────┐      sync()       ┌──────────────────┐
│ Local SQLite     │ ◄──────────────► │ Turso Cloud DB    │
│ (fast reads)     │                  │ (source of truth) │
│ ~/.local/share/  │                  │                   │
│   dregs/dregs.db │                  │                   │
└─────────────────┘                  └──────────────────┘
```

**How it works:**

- `libsql.connect()` is called with both a local `database` path and a `sync_url`
- On connect, `conn.sync()` pulls the latest state from the cloud into the local file
- All subsequent reads hit the local SQLite — typically **5-10x faster** than remote
- The local file is a full SQLite database you can inspect with standard tools

**Environment variables:**

| Variable | Required | Description |
|---|---|---|
| `DREGS_DSN` | Yes | Local file path (embedded replica) or `libsql://` URL (remote) |
| `DREGS_SYNC_URL` | No | Turso cloud URL to sync from. Activates embedded replica mode |
| `DREGS_AUTH_TOKEN` | For remote/sync | Turso auth token (rw or ro) |

**XDG compliance:** The recommended location for the local replica is `$XDG_DATA_HOME/dregs/dregs.db` (defaults to `~/.local/share/dregs/dregs.db`). This follows the [XDG Base Directory Specification](https://specifications.freedesktop.org/basedir-spec/latest/) — persistent user data goes in `XDG_DATA_HOME`.

### Switching modes

The mode is determined entirely by what environment variables are set:

```bash
# Local only — no DREGS_SYNC_URL, DSN is a file path
DREGS_DSN=./local.db

# Remote only — DSN is a libsql:// URL, no DREGS_SYNC_URL
DREGS_DSN=libsql://your-db.turso.io

# Embedded replica — DSN is a file path + DREGS_SYNC_URL is set
DREGS_DSN=~/.local/share/dregs/dregs.db
DREGS_SYNC_URL=libsql://your-db.turso.io
```

## Architecture

- **SQLite** owns persistence. Triples table with subject/predicate/object/graph columns. Indexed for common SPARQL access patterns.
- **rdflib** used at the boundary: parse Turtle in, serialize Turtle out, execute SPARQL by loading from SQLite into in-memory graphs.
- **Named graphs** with types: `schema`, `shacl`, `data`, `inferred`. SPARQL queries hit the union of all graphs by default.
- **Validation-on-load** extracts schema + SHACL from the DB, runs OWL-RL reasoning + SHACL validation + schema conformance checks. Only commits on PASS.

## Validation Pipeline

Three layers, run on every `dregs load`:

1. **SHACL Validation** -- structural constraints (required fields, cardinality, datatypes)
1. **OWL-RL Reasoning** -- infer missing triples, detect logical contradictions
1. **Schema Conformance** -- unknown types, abstract class misuse, provenance checks

## Dependencies

- `rdflib>=7.0.0` -- RDF parsing, SPARQL
- `owlrl>=6.0.2` -- OWL 2 RL reasoning (pure Python)
- `pyshacl>=0.26.0` -- SHACL validation
- `click>=8.0.0` -- CLI
- `libsql>=0.1.0` -- Turso/libSQL support

No Java. No system packages. Works in any Python 3.10+ environment.

## Examples

See `examples/` for complete working setups. Each has an OWL ontology, SHACL shapes, valid data, and intentionally broken data.

### Default (custom ontology)

- `examples/ontology.ttl` -- OWL ontology with abstract + leaf classes
- `examples/shapes.ttl` -- SHACL shapes for data quality
- `examples/data_good.ttl` -- valid data (passes validation, loads)
- `examples/data_bad.ttl` -- broken data (fails with clear errors)

### FOAF (Friend-of-a-Friend)

Application profile based on [FOAF 0.99](http://xmlns.com/foaf/0.1/) with Dublin Core terms. Extracts people, organizations, projects, and relationships from text.

```bash
dregs init foaf.db --schema examples/foaf/ontology.ttl --shacl examples/foaf/shapes.ttl
dregs load foaf.db examples/foaf/data_good.ttl --graph test
dregs check foaf.db examples/foaf/data_bad.ttl
```

### Schema.org (Events + Articles)

Application profile based on [Schema.org](https://schema.org/). Extracts events, articles, organizations, and people from web content.

```bash
dregs init schema.db --schema examples/schema-org/ontology.ttl --shacl examples/schema-org/shapes.ttl
dregs load schema.db examples/schema-org/data_good.ttl --graph test
dregs check schema.db examples/schema-org/data_bad.ttl
```

### DCAT (Data Catalog Vocabulary)

Application profile based on [DCAT 3](http://www.w3.org/ns/dcat#) and DCAT-AP. Extracts dataset metadata from data portals and API documentation.

```bash
dregs init dcat.db --schema examples/dcat/ontology.ttl --shacl examples/dcat/shapes.ttl
dregs load dcat.db examples/dcat/data_good.ttl --graph test
dregs check dcat.db examples/dcat/data_bad.ttl
```

## Testing

Install with test dependencies and run:

```bash
pip install -e ".[test]"
pytest
```

The core test suites (`test_examples.py`, `test_turso.py`) cover validation, SPARQL queries, store lifecycle, and local Turso-compatible storage. They require no external services.

Remote Turso tests (`test_turso_remote.py`) require a running Turso database:

```bash
export DREGS_TEST_DSN="libsql://your-db.turso.io"
export DREGS_TEST_AUTH_TOKEN="your-token"
pytest tests/test_turso_remote.py
```

## License

MIT
