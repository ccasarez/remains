# remains

What remains is what’s true.

```
pip install remains
```

Most agent memory is a junk drawer. Vectors stuffed into a database, no schema, no validation, no way to know if what your agent “remembers” is consistent or even real. Ask it what it knows and you get vibes, not facts.

Remains gives your agent structured memory with teeth. You define the shape of your domain — the types of things that exist, how they relate, what fields are required — and remains enforces it. Every fact your agent extracts gets validated against your schema before it’s stored. Bad extractions get rejected with specific errors. The agent reads the errors, fixes its output, and tries again.

The schema is the backpressure. Without it, agents hallucinate structure. With it, they converge on yours.

One SQLite file. No Java. No infrastructure. Pure Python.

## You define the world. Remains holds the line.

The core loop has two parts: a schema you write once, and a validation gate your agent hits every time it tries to remember something.

### 1. Define your domain

You describe your world in two files:

**An ontology** defines what exists. People, decisions, documents, meetings — whatever your domain cares about. You specify the classes, their properties, and how they connect. This is written in OWL (via Turtle syntax), but you don’t need to be an ontologist. It reads like a declaration:

```turtle
# ontology.ttl — "here's what exists in my world"
ex:Person a owl:Class ;
    skos:example "ex:jane-doe a ex:Person ; ex:name 'Jane Doe'" .

ex:Decision a owl:Class ;
    skos:example "ex:dec-001 a ex:Decision ; ex:description 'Approved budget'" .

ex:madeBy a owl:ObjectProperty ;
    rdfs:domain ex:Decision ;
    rdfs:range ex:Person .
```

**SHACL shapes** define the rules. Required fields, valid value types, cardinality constraints. This is where you say “every Decision must have a description and a person who made it”:

```turtle
# shapes.ttl — "here's what makes a fact valid"
ex:DecisionShape a sh:NodeShape ;
    sh:targetClass ex:Decision ;
    sh:property [
        sh:path ex:description ;
        sh:minCount 1 ;
        sh:datatype xsd:string
    ] ;
    sh:property [
        sh:path ex:madeBy ;
        sh:minCount 1 ;
        sh:class ex:Person
    ] .
```

These two files are your agent’s contract with reality. Everything downstream flows from them.

### 2. Remains provides the backpressure

```bash
# Point remains at a database (local file or libsql:// URL)
export REMAINS_DSN=project.db

# Initialize the store with your schema
remains init --ontology ontology.ttl --shacl shapes.ttl

# Generate extraction context — feed this to your LLM
remains prompt > context.txt

# Your agent extracts triples from unstructured text using context.txt
# (this step is yours — remains handles validation, not extraction)

# Load with validation
remains load extracted.ttl
```

If the extraction is clean, it loads. If not, remains rejects it:

```
SHACL violation: ex:dec-042 missing required property ex:madeBy
Schema violation: ex:Meetng is not a known class (did you mean ex:Meeting?)
```

Exit code 1. The agent reads the violations, fixes its extraction, retries. After a few rounds, the agent’s output conforms to your schema — not because you prompted harder, but because the system won’t accept anything else.

## Why not just use a vector store?

Vector search finds things that feel similar. Remains stores things that are true — validated against a schema you define, with relationships your agent can traverse. You get “Alice reported to Bob during Q3” instead of “here are 5 chunks that mention Alice.”

**Why not a property graph?** Neo4j is powerful but heavy. Remains is a pip package that stores everything in a single file. Your agent doesn’t need a graph database server. It needs a world model it can carry.

**Why not just dump JSON into SQLite?** Because without a schema, your agent will contradict itself within 20 extractions. Remains enforces structure. The schema is what keeps the world model from rotting.

**Why OWL/SHACL instead of JSON Schema or SQL?** Because agent memory operates under open-world assumptions. A SQL schema or JSON Schema is closed-world — if a column or field isn’t defined, the data is rejected. That works when you control the inputs. But agents extract knowledge from messy, incomplete text. They’ll encounter things your schema didn’t anticipate. OWL assumes the world is bigger than what you’ve described so far. Your agent can store a fact about a Person even if it only extracted a name and not an email — the absence of data isn’t an error, it’s incomplete knowledge. SHACL then lets you draw the lines that matter: “a Decision without a madeBy is an error, but a Person without a phone number is fine.” You get the flexibility to grow the world model without rewriting migrations, and the strictness to reject garbage where it counts.

## Commands

The CLI is the source of truth. `remains --help` lists every command, and
`remains <command> --help` documents its flags. A whirlwind tour:

```
remains init         # create a new store, load ontology + shapes
remains load DATA    # validate Turtle and load it into the data graph
remains check DATA   # same validation as load, without committing
remains query SPARQL # SELECT / CONSTRUCT / ASK across the union graph
remains prompt       # render the ontology as LLM extraction context
remains export       # dump data / ontology / shapes as Turtle
remains info         # database statistics
remains viz          # interactive or static knowledge-graph visualizer
```

The store has three fixed graphs — data (default), `urn:ontology`, and
`urn:shacl` — and a pair of grouping primitives layered on top:

- **Domains** scope the ontology: `remains create-domain`, `remains domains`,
  and `remains prompt --domain <slug>` emit extraction context for a subset
  of classes.
- **Topics** scope the data: `remains create-topic`, `remains topics` group
  related entities for recall and visualization.

For multi-domain setups, use one database per domain and point `REMAINS_DSN`
at whichever one you need:

```
REMAINS_DSN=meetings.db remains init --ontology meetings.ttl --shacl meetings-shapes.ttl
REMAINS_DSN=finance.db  remains init --ontology finance.ttl  --shacl finance-shapes.ttl
```

On a failed load, `remains load` exits with code 1 and prints SHACL
violations the agent can read and retry against.

## Python API

The CLI is a thin wrapper around `remains.RemainsStore` and a couple of
helpers. The full surface lives in `src/remains/`; a typical flow:

```python
from pathlib import Path
from remains import RemainsStore, execute_sparql, prompt_from_store

db = RemainsStore("project.db")
db.init(ontology_path=Path("ontology.ttl"), shacl_path=Path("shapes.ttl"))

result = db.load(Path("data.ttl"))
if not result["loaded"]:
    print(result["validation"].summary())

qr = execute_sparql(db, "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 10")
print(qr.to_table())

context = prompt_from_store(db)
db.close()
```

## Connection Modes

### Local Only (default)

Pure local SQLite. No network required.

```bash
export REMAINS_DSN=./my.db
remains init --ontology ontology.ttl
```

### Remote Only (Turso Cloud)

Every read and write goes over the network.

```bash
export REMAINS_DSN=libsql://your-db-org.turso.io
export REMAINS_AUTH_TOKEN=eyJ...
```

### Embedded Replica (recommended for production)

Local SQLite read cache that syncs with Turso Cloud. Reads are local and fast, writes go through the cloud.

```bash
export REMAINS_DSN="${XDG_DATA_HOME:-$HOME/.local/share}/remains/remains.db"
export REMAINS_SYNC_URL=libsql://your-db-org.turso.io
export REMAINS_AUTH_TOKEN=eyJ...
```

```
┌─────────────────┐      sync()       ┌──────────────────┐
│ Local SQLite     │ ◄──────────────► │ Turso Cloud DB    │
│ (fast reads)     │                  │ (source of truth) │
└─────────────────┘                  └──────────────────┘
```

|Variable            |Required       |Description                                     |
|--------------------|---------------|------------------------------------------------|
|`REMAINS_DSN`       |Yes            |Local file path or `libsql://` URL              |
|`REMAINS_SYNC_URL`  |No             |Turso cloud URL. Activates embedded replica mode|
|`REMAINS_AUTH_TOKEN`|For remote/sync|Turso auth token                                |

## Validation Pipeline

Every `remains load` runs the data through [pyshacl](https://github.com/RDFLib/pySHACL),
which enforces the SHACL shapes against the user data while using the ontology
as `ont_graph` so subclass relationships and `sh:class` constraints resolve
correctly. `remains check` exposes the same pipeline without a load and adds
an optional `--regime` flag (`none | rdfs | owlrl | both`) that tells pyshacl
which inference to apply before checking.

If validation fails, nothing gets committed. Your agent gets violation
messages it can use to fix the extraction and retry. This is the
backpressure — the schema doesn’t just document your domain, it defends it.

## Examples

See `examples/` for complete working setups with ontologies, SHACL shapes, valid data, and intentionally broken data covering FOAF, Schema.org, and DCAT vocabularies.

## Dependencies

- `rdflib` — RDF parsing, SPARQL
- `owlrl` — OWL 2 RL reasoning (pure Python)
- `pyshacl` — SHACL validation
- `click` — CLI
- `libsql` — Turso/libSQL support

No Java. No system packages. Python 3.10+.

## License

MIT
