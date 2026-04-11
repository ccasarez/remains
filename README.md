# dregs

SQLite-backed RDF triple store with SPARQL, OWL reasoning, and SHACL validation.

**Zero system deps. Pure Python. Deploys anywhere.**

```
pip install dregs
```

## What It Does

Persistent knowledge graph storage for LLM agents. Unstructured data goes through an extraction pipeline, gets validated against OWL ontology + SHACL shapes, and lands in a queryable SQLite store. Agents query via SPARQL.

The ontology and SHACL specs live inside the database. One file carries the schema, the constraints, and the data. Validation runs automatically on every load.

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

No Java. No system packages. Works in any Python 3.10+ environment.

## Examples

See `examples/` for a complete working setup:

- `ontology.ttl` -- OWL ontology with abstract + leaf classes
- `shapes.ttl` -- SHACL shapes for data quality
- `data_good.ttl` -- valid data (passes validation, loads)
- `data_bad.ttl` -- broken data (fails with clear errors)

## License

MIT
