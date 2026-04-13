# remains v2 — Simplified Architecture

## Design Principles

1. **One SQLite DB** — no multi-graph complexity
2. **3 fixed graphs** — data, ontology, shacl. Nothing else.
3. **System/user split** — remains ships system ontology + shapes, user provides domain-specific ones
4. **Standard vocabularies** — reuse rdfs:label, schema:name, skos:prefLabel. Don't invent.

## DB Structure

```
One SQLite database:
  DEFAULT graph  = user data
  urn:ontology   = system ontology + user ontology (merged)
  urn:shacl      = system shapes + user shapes (merged)
```

No other graphs. No named data graphs. No profiles.

```sql
CREATE TABLE triples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object TEXT NOT NULL,
    object_type TEXT NOT NULL,   -- 'uri' | 'literal' | 'bnode'
    datatype TEXT NOT NULL DEFAULT '',
    lang TEXT NOT NULL DEFAULT '',
    graph TEXT NOT NULL           -- '' | 'urn:ontology' | 'urn:shacl'
);

CREATE TABLE metadata (
    key TEXT PRIMARY KEY,
    value TEXT
);
```

## Namespace Convention

### System (protected, immutable by user)
```turtle
@prefix remains:    <urn:remains:system#> .     # System ontology classes/properties
@prefix remains-sh: <urn:remains:shapes#> .     # System SHACL shapes
```

### User (domain-specific, editable)
```turtle
@prefix : <urn:domain:meetings#> .          # User-defined (set at init)
```

### Standard imports (reused, not invented)
```turtle
@prefix rdfs:   <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos:   <http://www.w3.org/2004/02/skos/core#> .
@prefix schema: <http://schema.org/> .
@prefix foaf:   <http://xmlns.com/foaf/0.1/> .
@prefix dcterms: <http://purl.org/dc/terms/> .
```

## System Ontology (bundled with remains)

```turtle
# system-ontology.ttl
@prefix remains: <urn:remains:system#> .
@prefix owl:   <http://www.w3.org/2002/07/owl#> .
@prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .

<urn:remains:system> a owl:Ontology ;
    rdfs:label "remains System Ontology" .

# --- Display Name Constraint ---

remains:RequiresDisplayName a rdfs:Class ;
    rdfs:label "Requires Display Name" ;
    rdfs:comment "Marker: instances of subclasses must have rdfs:label, skos:prefLabel, or schema:name" .
```

## System Shapes (bundled with remains)

```turtle
# system-shapes.ttl
@prefix remains:    <urn:remains:system#> .
@prefix remains-sh: <urn:remains:shapes#> .
@prefix sh:       <http://www.w3.org/ns/shacl#> .
@prefix rdfs:     <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos:     <http://www.w3.org/2004/02/skos/core#> .
@prefix schema:   <http://schema.org/> .

# All leaf classes marked RequiresDisplayName must have a display property
remains-sh:DisplayNameShape a sh:NodeShape ;
    sh:targetClass remains:RequiresDisplayName ;
    sh:or (
        [ sh:path rdfs:label ; sh:minCount 1 ]
        [ sh:path skos:prefLabel ; sh:minCount 1 ]
        [ sh:path schema:name ; sh:minCount 1 ]
    ) ;
    sh:message "Instance must have rdfs:label, skos:prefLabel, or schema:name" .
```

## User Ontology (example: meetings domain)

```turtle
# meetings.ttl
@prefix : <urn:domain:meetings#> .
@prefix remains: <urn:remains:system#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix schema: <http://schema.org/> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

:Person a owl:Class, remains:RequiresDisplayName ;
    rdfs:label "Person" .

:Meeting a owl:Class, remains:RequiresDisplayName ;
    rdfs:label "Meeting" .

:Task a owl:Class, remains:RequiresDisplayName ;
    rdfs:label "Task" .

:attendedBy a owl:ObjectProperty ;
    rdfs:domain :Meeting ;
    rdfs:range :Person .

:date a owl:DatatypeProperty ;
    rdfs:domain :Meeting ;
    rdfs:range xsd:date .
```

## User Shapes (example)

```turtle
# meetings-shapes.ttl
@prefix : <urn:domain:meetings#> .
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix schema: <http://schema.org/> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

:PersonShape a sh:NodeShape ;
    sh:targetClass :Person ;
    sh:property [
        sh:path schema:name ;
        sh:minCount 1 ;
        sh:datatype xsd:string ;
        sh:message "Person must have schema:name"
    ] .

:MeetingShape a sh:NodeShape ;
    sh:targetClass :Meeting ;
    sh:property [
        sh:path rdfs:label ;
        sh:minCount 1 ;
        sh:message "Meeting must have rdfs:label"
    ] ;
    sh:property [
        sh:path :attendedBy ;
        sh:class :Person
    ] ;
    sh:property [
        sh:path :date ;
        sh:maxCount 1 ;
        sh:datatype xsd:date
    ] .
```

## Display Name Resolution

Code-level fallback chain. No custom annotation needed.

```python
DISPLAY_PROPERTIES = [
    "http://www.w3.org/2000/01/rdf-schema#label",
    "http://www.w3.org/2004/02/skos/core#prefLabel",
    "http://schema.org/name",
    "http://xmlns.com/foaf/0.1/name",
    "http://purl.org/dc/terms/title",
]

def get_display_name(node_uri: str, store: TripleStore) -> str:
    for prop in DISPLAY_PROPERTIES:
        result = store.query_one(
            f'SELECT ?v WHERE {{ <{node_uri}> <{prop}> ?v }} LIMIT 1'
        )
        if result:
            return result
    # Fallback: URI fragment or last path segment
    return node_uri.split('#')[-1].split('/')[-1]
```

Used by viz for node labels, CLI for output formatting.

## CLI Commands (Complete)

### Initialize
```bash
# Create the database
remains init \
  --ontology meetings.ttl \
  --shacl meetings-shapes.ttl

# Internally:
# 1. Create DB with schema
# 2. Load system-ontology.ttl into urn:ontology
# 3. Load user ontology into urn:ontology (merged)
# 4. Load system-shapes.ttl into urn:shacl
# 5. Load user shapes into urn:shacl (merged)
```

### Load Data
```bash
# Load triples into default graph
remains load meeting-2026-04-12.ttl

# Validates against urn:shacl automatically
# Error if data violates system or user shapes
```

### Query
```bash
# Query data
remains query "SELECT * WHERE { ?s a :Meeting }"

# All commands implicitly target current DB (REMAINS_DSN)
```

### Prompt
```bash
# Full prompt (all classes in ontology)
remains prompt
```

### Validate
```bash
remains check
# Output:
#   System validation: 2 shapes, 0 violations
#   User validation: 5 shapes, 0 violations
#   Total: 156 triples validated
```

### Update Schema
```bash
# Replace user ontology (system ontology preserved)
remains update-ontology meetings-v2.ttl

# Replace user shapes (system shapes preserved)
remains update-shacl meetings-v2-shapes.ttl

# Dry run: validate data against new schema first
remains update-ontology meetings-v2.ttl --dry-run
```

### Export
```bash
remains export                       # Data only (default graph)
remains export --ontology            # User ontology triples only
remains export --shacl               # User shapes only
remains export --all                 # Everything
```

### Info
```bash
remains info
# Output:
#   Database: meetings.db
#   Data triples: 2,455
#   Ontology triples: 122 (system: 45, user: 77)
#   SHACL triples: 89 (system: 31, user: 58)
#   Created: 2026-04-12
```

### Viz
```bash
remains viz                          # Full graph
```

## Namespace Protection

System namespaces (`remains:`, `remains-sh:`) are immutable by user commands:

```bash
remains update-ontology evil.ttl
# evil.ttl contains: remains:RequiresDisplayName rdfs:label "Hacked" .
# ERROR: Cannot modify system namespace (urn:remains:system#)

remains update-shacl evil-shapes.ttl
# ERROR: Cannot modify system namespace (urn:remains:shapes#)
```

## Validation

```bash
remains check
```

Runs system + user shapes against the default data graph:

```
System validation:
  ✓ remains-sh:DisplayNameShape — 245 instances validated

User validation:
  ✓ :PersonShape — 42 instances validated
  ✗ :MeetingShape — 1 violation
    Focus: :meeting-orphan
    Message: Meeting must have rdfs:label
```

## Implementation Phases

### Phase 1: Core DB restructure
- [ ] New DB schema (3 fixed graphs, metadata table)
- [ ] Bundle system-ontology.ttl and system-shapes.ttl
- [ ] `remains init` command (loads system + user ontology/shapes)
- [ ] Namespace protection on update commands
- [ ] Update `remains load` to target default graph only
- [ ] Update `remains prompt` to read from urn:ontology
- [ ] Update `remains check` with system/user split validation
- [ ] Update `remains export` with --ontology/--shacl/--all flags
- [ ] `remains info` with system/user triple counts

### Phase 2: Display names
- [ ] Implement `get_display_name()` fallback chain
- [ ] Update viz node labels to use display names
- [ ] Update CLI output formatting

### Phase 3: Schema updates
- [ ] `remains update-ontology` (preserves system, replaces user)
- [ ] `remains update-shacl` (preserves system, replaces user)
- [ ] `--dry-run` flag for pre-validation

## Files Shipped with remains

```
remains/
├── src/remains/
│   ├── cli.py
│   ├── store.py
│   ├── prompt.py
│   ├── viz.py
│   ├── analytics.py
│   ├── display.py         # NEW: display name resolution
│   └── system/
│       ├── system-ontology.ttl
│       └── system-shapes.ttl
```
