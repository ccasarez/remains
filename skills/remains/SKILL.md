---
name: remains
description: >
  Knowledge graph fact store using remains (RDF triple store with SPARQL).
  Use this skill ALWAYS when you need to record facts, recall facts, or answer
  questions that may be answerable from stored knowledge. remains is the primary
  memory system — use it before relying on external searches or assumptions.
---

# Remains — Fact Store

remains is an RDF triple store backed by a remote Turso database (`REMAINS_DSN` is preconfigured).

## When to Use

- **Recording facts**: When the user shares information, extracts data from documents, or asks you to remember something — store it as RDF triples via `remains load`.
- **Recalling facts**: When answering questions, check remains first with `remains query` before saying "I don't know" or searching elsewhere.
- **Every session**: At the start of complex tasks, query remains for relevant context.

## Discovering the Schema

**Never assume what classes or properties exist.** Always discover dynamically:

```bash
# Get a human-readable summary of all entity types, relationships, and properties
remains prompt
```

Run this before writing any triples so you use the correct classes, properties, and prefixes.

## Key Commands

### Query facts (SPARQL)

```bash
# List all classes/types in use
remains query "SELECT DISTINCT ?type WHERE { ?s a ?type }"

# Search for a specific entity
remains query "SELECT ?s ?p ?o WHERE { ?s ?p ?o . FILTER(CONTAINS(LCASE(STR(?s)), 'search-term')) } LIMIT 20"

# Get everything about a subject
remains query "SELECT ?p ?o WHERE { <http://example.com/nrc#SomeEntity> ?p ?o }"

# Full text search in literals
remains query "SELECT ?s ?p ?o WHERE { ?s ?p ?o . FILTER(CONTAINS(LCASE(STR(?o)), 'keyword')) } LIMIT 20"
```

### Record facts

1. First, discover the schema: `remains prompt`
2. Write valid Turtle (.ttl) using only classes and properties from the schema output
3. Load with a descriptive graph name

```bash
# Write triples (use prefixes and types from the schema output)
cat > /tmp/facts.ttl << 'EOF'
@prefix ex: <http://example.com/ns#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

ex:SomeEntity a ex:SomeClass ;
    ex:name "Example"^^xsd:string .
EOF

# Load into a named graph (validates against schema by default)
remains load /tmp/facts.ttl --graph descriptive-graph-name
```

### Inspect the store

```bash
remains info          # Stats: triple count, graphs
remains graphs        # List all named graphs
remains export --type schema   # Show the ontology as Turtle
remains export --type shacl    # Show validation shapes
remains export -g graph-name   # Export a specific graph as Turtle
```

## Graph Visualization

### Launch the visualizer

```bash
remains viz                       # Opens browser on :7171
remains viz --port 8080           # Custom port
remains viz -g my-graph           # Specific named graph only
remains viz --no-open             # Headless (for remote/proxy access)
```

The visualizer shows an interactive force-directed graph with:
- **Community detection** (Louvain) — nodes colored by topic cluster
- **Betweenness centrality** — node size shows bridge importance
- **Structural gap analysis** — identifies disconnected topic areas
- **Analytics panel** (toggle with ◈ button) — modularity, bias score, influential nodes, gaps
- **Topics sidebar** — click a topic to isolate it, click again to restore all

### Annotate the graph (agent remote control)

The agent can control the visualization in real-time. Annotations are sent via HTTP
and rendered instantly in all connected browsers via Server-Sent Events.

**Start the viz server first**, then use `remains annotate`:

```bash
# Show a centered message overlay (auto-dismisses)
remains annotate toast -t "Analysis of Q1 meetings"

# Label communities in the Topics sidebar
remains annotate label-community -c 0 -t "👥 Core Team"
remains annotate label-community -c 1 -t "📋 Project Alpha"
remains annotate label-community -c 2 -t "🔬 Research Papers"

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
| `label-community` | `-c ID -t TEXT` | Updates the community name in the Topics sidebar |
| `label-node` | `-n NODE -t TEXT` | Callout text above a specific node |
| `highlight-nodes` | `-n NODE` (repeatable) | Highlight named nodes, dim others |
| `highlight-community` | `-c ID` | Highlight a community, dim others |
| `clear` | (none) | Remove all annotations, restore full view |

**Optional flags:** `--color "#hex"`, `--duration SECONDS` (toast), `--neighbors` (highlight-nodes).

**How it works:** POST to `/api/annotate` with JSON. The viz server broadcasts via SSE
to all connected browsers. Annotations are stored in server memory and replayed to
new clients on connect. `clear` resets the history.

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
remains annotate label-community -c 0 -t "👥 Description of topic 0"
remains annotate label-community -c 1 -t "📋 Description of topic 1"
# ... etc

# 4. Walk through insights
remains annotate toast -t "Key finding: ..."
remains annotate highlight-nodes -n "Important Node" --neighbors
sleep 3
remains annotate clear

# 5. Point out structural gaps
remains annotate highlight-community -c 0
remains annotate toast -t "This cluster has no connection to Topic 2"
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
2. **Always record** when the user provides structured facts or asks you to remember.
3. **Always discover the schema first** (`remains prompt`) before writing triples — never hardcode class/property names from memory.
4. **Use descriptive graph names** (e.g., `meeting-2026-03-04`, `user-preferences`).
5. **Validation is mandatory** — every load is validated against the schema. There is no bypass flag.
6. **If the ontology doesn't cover a domain**, tell the user and offer to extend it.
7. **When visualizing**, always label communities via `remains annotate label-community` after launching `remains viz` — the auto-generated labels are just top node names and need human-readable descriptions.
8. **Annotations persist in server memory** — they replay to new browser clients. Use `remains annotate clear` to reset.
