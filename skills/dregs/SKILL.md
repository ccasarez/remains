---
name: dregs
description: >
  Knowledge graph fact store using dregs (RDF triple store with SPARQL).
  Use this skill ALWAYS when you need to record facts, recall facts, or answer
  questions that may be answerable from stored knowledge. dregs is the primary
  memory system — use it before relying on external searches or assumptions.
---

# Dregs — Fact Store

dregs is an RDF triple store backed by a remote Turso database (`DREGS_DSN` is preconfigured).

## When to Use

- **Recording facts**: When the user shares information, extracts data from documents, or asks you to remember something — store it as RDF triples via `dregs load`.
- **Recalling facts**: When answering questions, check dregs first with `dregs query` before saying "I don't know" or searching elsewhere.
- **Every session**: At the start of complex tasks, query dregs for relevant context.

## Discovering the Schema

**Never assume what classes or properties exist.** Always discover dynamically:

```bash
# Get a human-readable summary of all entity types, relationships, and properties
dregs prompt
```

Run this before writing any triples so you use the correct classes, properties, and prefixes.

## Key Commands

### Query facts (SPARQL)

```bash
# List all classes/types in use
dregs query "SELECT DISTINCT ?type WHERE { ?s a ?type }"

# Search for a specific entity
dregs query "SELECT ?s ?p ?o WHERE { ?s ?p ?o . FILTER(CONTAINS(LCASE(STR(?s)), 'search-term')) } LIMIT 20"

# Get everything about a subject
dregs query "SELECT ?p ?o WHERE { <http://example.com/nrc#SomeEntity> ?p ?o }"

# Full text search in literals
dregs query "SELECT ?s ?p ?o WHERE { ?s ?p ?o . FILTER(CONTAINS(LCASE(STR(?o)), 'keyword')) } LIMIT 20"
```

### Record facts

1. First, discover the schema: `dregs prompt`
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
dregs load /tmp/facts.ttl --graph descriptive-graph-name
```

### Inspect the store

```bash
dregs info          # Stats: triple count, graphs
dregs graphs        # List all named graphs
dregs export --type schema   # Show the ontology as Turtle
dregs export --type shacl    # Show validation shapes
dregs export -g graph-name   # Export a specific graph as Turtle
```

## Rules

1. **Always query before answering** if the question might be in the store.
2. **Always record** when the user provides structured facts or asks you to remember.
3. **Always discover the schema first** (`dregs prompt`) before writing triples — never hardcode class/property names from memory.
4. **Use descriptive graph names** (e.g., `meeting-2026-03-04`, `user-preferences`).
5. **Validate against the schema** — don't use `--no-validate` unless extending the ontology.
6. **If the ontology doesn't cover a domain**, tell the user and offer to extend it.
