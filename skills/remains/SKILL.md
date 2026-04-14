---
name: remains
description: >
  Knowledge graph fact store using remains (RDF triple store with SPARQL).
  Use this skill ALWAYS when you need to record facts, recall facts, or answer
  questions that may be answerable from stored knowledge. remains is the primary
  memory system — use it before relying on external searches or assumptions.
---

# Remains — Fact Store

remains is an RDF triple store backed by a remote Turso database
(`REMAINS_DSN` is preconfigured).

**The CLI is the source of truth.** Run `remains --help` and
`remains <command> --help` whenever you need the authoritative list of
commands and flags. The notes below cover strategy (when to call what) and
patterns that `--help` cannot convey.

## When to Use

- **Recording facts**: When the user shares information, extracts data from
  documents, or asks you to remember something — store it as RDF triples via
  `remains load`.
- **Recalling facts**: When answering questions, check remains first with
  `remains query` before saying "I don't know" or searching elsewhere.
- **Every session**: At the start of complex tasks, query remains for
  relevant context.

## How the store is organized

remains has three fixed graphs: the default data graph, `urn:ontology`, and
`urn:shacl`. You do not create named graphs per load — every `remains load`
inserts into the default data graph, and validation runs against the
ontology + shapes automatically.

## Discovering the Schema

**Never assume what classes or properties exist.** Always discover
dynamically before writing any triples:

```bash
remains prompt                     # whole ontology
```

This emits a human-readable summary of entity types, relationships, and
properties. Use the exact prefixes, class names, and property names it
returns.

## Querying facts (SPARQL)

```bash
# List all classes/types in use
remains query "SELECT DISTINCT ?type WHERE { ?s a ?type }"

# Search for a specific entity
remains query "SELECT ?s ?p ?o WHERE { ?s ?p ?o . FILTER(CONTAINS(LCASE(STR(?s)), 'search-term')) } LIMIT 20"

# Get everything about a subject
remains query "SELECT ?p ?o WHERE { <http://example.com/nrc#SomeEntity> ?p ?o }"

# Full-text search in literals
remains query "SELECT ?s ?p ?o WHERE { ?s ?p ?o . FILTER(CONTAINS(LCASE(STR(?o)), 'keyword')) } LIMIT 20"
```

`remains query --format json|turtle|table` switches output. `CONSTRUCT` and
`ASK` also work.

## Recording facts

1. Discover the schema: `remains prompt`.
2. Write valid Turtle using only classes and properties from the schema
   output.
3. Load it. Validation runs automatically against the ontology and SHACL
   shapes; there is no bypass flag.

```bash
cat > /tmp/facts.ttl << 'EOF'
@prefix ex: <http://example.com/ns#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

ex:SomeEntity a ex:SomeClass ;
    ex:name "Example"^^xsd:string .
EOF

remains load /tmp/facts.ttl
```

If validation fails, `remains load` exits non-zero and prints SHACL
violations. Read them, fix the Turtle, retry.

## Inspecting the store

```bash
remains info                       # triple counts
remains export --what data         # dump user data as Turtle
remains export --what ontology     # dump user ontology (no system triples)
remains export --what shacl        # dump user shapes (no system triples)
remains export --what all          # dump everything
```

See `remains export --help` for the full list of `--what` values.

## Graph Visualization

### Launch the visualizer

```bash
remains viz                          # Opens browser on :7171
remains viz --port 8080              # Custom port
remains viz --no-open                # Headless (for remote/proxy access)
remains viz -o graph.html            # Static HTML export (no server)
```

Scope the view with `--query "CONSTRUCT { ... }"` or
`--focus <uri> [--hops N]` (mutually exclusive). See `remains viz --help`.

The visualizer shows an interactive force-directed graph with:
- **Class coloring** — nodes colored by RDF type (class), with a clickable legend to filter
- **Betweenness centrality** — node size shows bridge importance
- **Structural gap analysis** — identifies disconnected areas
- **Analytics panel** (toggle with ◈ button) — modularity, bias score,
  influential nodes, gaps
- **Communities sidebar** — click a community to isolate it, click again to
  restore all

### Annotate the graph (agent remote control)

The agent can control the visualization in real-time. Annotations are sent
via HTTP and rendered instantly in all connected browsers via Server-Sent
Events.

**Start the viz server first**, then use `remains annotate`:

```bash
# Show a centered message overlay (auto-dismisses)
remains annotate toast -t "Analysis of Q1 meetings"

# Label communities in the Communities sidebar
remains annotate label-community -c 0 -t "👥 Core Team"
remains annotate label-community -c 1 -t "📋 Project Alpha"

# Highlight specific nodes (by label or ID), dim everything else
remains annotate highlight-nodes -n "Alice" -n "Bob"
remains annotate highlight-nodes -n "Alice" --neighbors   # include neighbors

# Highlight an entire community
remains annotate highlight-community -c 2

# Add a callout label above a node
remains annotate label-node -n "Alice" -t "Bridge node (BC=0.37)"

# Clear all annotations and reset the view
remains annotate clear
```

**Annotation types reference:**

| Type | Required flags | What it does |
|---|---|---|
| `toast` | `-t TEXT` | Centered overlay message, auto-dismisses |
| `label-community` | `-c ID -t TEXT` | Updates the community name in the Communities sidebar |
| `label-node` | `-n NODE -t TEXT` | Callout text above a specific node |
| `highlight-nodes` | `-n NODE` (repeatable) | Highlight named nodes, dim others |
| `highlight-community` | `-c ID` | Highlight a community, dim others |
| `clear` | (none) | Remove all annotations, restore full view |

Optional flags: `--color "#hex"`, `--duration SECONDS` (toast), `--neighbors`
(highlight-nodes). See `remains annotate --help` for the full list.

**How it works:** POST to `/api/annotate` with JSON. The viz server
broadcasts via SSE to all connected browsers. Annotations are stored in
server memory and replayed to new clients on connect. `clear` resets the
history.

```bash
# Equivalent curl (for scripts or non-CLI agents):
curl -X POST http://localhost:7171/api/annotate \
  -H 'Content-Type: application/json' \
  -d '{"type":"toast","text":"Hello from agent"}'
```

### Narration workflow (recommended pattern)

When the user asks you to explain or present a knowledge graph:

```bash
# 1. Start the viz if not already running
remains viz --no-open --port 7171 &

# 2. Get the analytics to understand the graph
curl -s http://localhost:7171/api/analytics | python3 -m json.tool

# 3. Label the communities based on their content
remains annotate label-community -c 0 -t "👥 Description of community 0"
remains annotate label-community -c 1 -t "📋 Description of community 1"
# ... etc

# 4. Walk through insights
remains annotate toast -t "Key finding: ..."
remains annotate highlight-nodes -n "Important Node" --neighbors
sleep 3
remains annotate clear

# 5. Point out structural gaps
remains annotate highlight-community -c 0
remains annotate toast -t "This cluster has no connection to Community 2"
```

### API endpoints

| Endpoint | Method | Returns |
|---|---|---|
| `/` | GET | Interactive graph HTML |
| `/api/graph` | GET | Full graph data + analytics JSON |
| `/api/analytics` | GET | Analytics only (communities, BC, gaps) |
| `/api/events` | GET | SSE stream for live annotations |
| `/api/annotate` | POST | Send annotation JSON, broadcasts to clients |

## Rules

1. **Always query before answering** if the question might be in the store.
2. **Always record** when the user provides structured facts or asks you to
   remember.
3. **Always discover the schema first** (`remains prompt`) before writing
   triples — never hardcode class or property names from memory.
4. **Validation is mandatory** — every load is validated against the
   ontology and SHACL shapes. There is no bypass flag.
5. **If the ontology doesn't cover a domain**, tell the user and offer to
   extend it with `remains update-ontology`.
6. **Annotations persist in server memory** — they replay to new browser
   clients. Use `remains annotate clear` to reset.
7. **When a flag or argument isn't documented here, check
   `remains <command> --help`.** The CLI is the authoritative reference.
