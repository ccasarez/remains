# remains v2 — Simplified Architecture

## Design Principles

1. **One SQLite DB = one knowledge domain** — no multi-graph complexity
2. **3 fixed graphs** — data, ontology, shacl. Nothing else.
3. **System/user split** — remains ships system ontology + shapes, user provides domain-specific ones
4. **Standard vocabularies** — reuse rdfs:label, schema:name, skos:prefLabel. Don't invent.
5. **Topics are first-class data** — reified as remains:Topic instances in default data graph, queryable, vizualizable
6. **Domains scope LLM extraction** — reified as remains:Domain instances in ontology graph, grouping classes for `remains prompt --domain X`
7. **Multiple knowledge bases = multiple databases** — use REMAINS_DSN to switch

## DB Structure

```
One SQLite database:
  DEFAULT graph  = user data + topics (remains:Topic instances live here)
  urn:ontology   = system ontology + user ontology + domains (merged)
  urn:shacl      = system shapes + user shapes (merged)
```

No other graphs. No named data graphs. No profiles. Topics are just data.

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
@prefix sh:    <http://www.w3.org/ns/shacl#> .
@prefix xsd:   <http://www.w3.org/2001/XMLSchema#> .

<urn:remains:system> a owl:Ontology ;
    rdfs:label "remains System Ontology" ;
    owl:imports <http://www.w3.org/2000/01/rdf-schema> ,
                <http://www.w3.org/2004/02/skos/core> .

# --- Topic ---

remains:Topic a owl:Class ;
    rdfs:label "Topic" ;
    rdfs:comment "Thematic grouping of entities in the knowledge graph" .

remains:member a owl:ObjectProperty ;
    rdfs:domain remains:Topic ;
    rdfs:label "member" ;
    rdfs:comment "Entity belonging to this topic" .

remains:createdBy a owl:DatatypeProperty ;
    rdfs:domain remains:Topic ;
    rdfs:range xsd:string ;
    rdfs:comment "Algorithm or user that created this topic" .

remains:modularity a owl:DatatypeProperty ;
    rdfs:domain remains:Topic ;
    rdfs:range xsd:decimal ;
    rdfs:comment "Modularity score from community detection" .

remains:color a owl:DatatypeProperty ;
    rdfs:domain remains:Topic ;
    rdfs:range xsd:string ;
    rdfs:comment "Display color (hex)" .

# --- Domain (ontology-level grouping for scoped LLM prompts) ---

remains:Domain a owl:Class ;
    rdfs:label "Domain" ;
    rdfs:comment "Named subset of ontology classes for scoped LLM extraction prompts" .

remains:includesClass a owl:ObjectProperty ;
    rdfs:domain remains:Domain ;
    rdfs:range owl:Class ;
    rdfs:label "includes class" ;
    rdfs:comment "An ontology class included in this domain" .

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
@prefix xsd:      <http://www.w3.org/2001/XMLSchema#> .

# Topic must have label and at least one member
remains-sh:TopicShape a sh:NodeShape ;
    sh:targetClass remains:Topic ;
    sh:property [
        sh:path rdfs:label ;
        sh:minCount 1 ;
        sh:datatype xsd:string ;
        sh:message "Topic must have rdfs:label"
    ] ;
    sh:property [
        sh:path remains:member ;
        sh:minCount 1 ;
        sh:nodeKind sh:IRI ;
        sh:message "Topic must have at least one member"
    ] ;
    sh:property [
        sh:path remains:createdBy ;
        sh:maxCount 1 ;
        sh:datatype xsd:string
    ] ;
    sh:property [
        sh:path remains:modularity ;
        sh:maxCount 1 ;
        sh:datatype xsd:decimal
    ] .

# Domain must have label and at least one class
remains-sh:DomainShape a sh:NodeShape ;
    sh:targetClass remains:Domain ;
    sh:property [
        sh:path rdfs:label ;
        sh:minCount 1 ;
        sh:datatype xsd:string ;
        sh:message "Domain must have rdfs:label"
    ] ;
    sh:property [
        sh:path remains:includesClass ;
        sh:minCount 1 ;
        sh:nodeKind sh:IRI ;
        sh:message "Domain must include at least one class"
    ] .

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

# --- Domains (scoped class subsets for LLM extraction) ---
# These live in urn:ontology alongside class definitions

<urn:remains:domain#meetings> a remains:Domain ;
    rdfs:label "Meetings" ;
    remains:includesClass :Meeting, :Person, :Task .

<urn:remains:domain#people> a remains:Domain ;
    rdfs:label "People" ;
    remains:includesClass :Person .
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

## Topics

### Storage
Topics are data. They live in the default data graph alongside everything else — just instances of `remains:Topic` from the system ontology. Validated by system shapes like any other class.

```turtle
@prefix remains: <urn:remains:system#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix : <urn:domain:meetings#> .

# These triples live in the DEFAULT data graph

<urn:remains:topic#nlp-research> a remains:Topic ;
    rdfs:label "NLP Research" ;
    rdfs:comment "Natural language processing papers and projects" ;
    remains:member :paper-123, :paper-456, :project-bert ;
    remains:createdBy "manual" ;
    remains:color "#d64141" .

<urn:remains:topic#0> a remains:Topic ;
    rdfs:label "Database Systems" ;
    remains:member :neo4j, :postgres, :ep-12, :ep-16 ;
    remains:createdBy "louvain" ;
    remains:modularity 0.72 ;
    remains:color "#62e889" .
```

### CLI Commands

```bash
# Auto-detect topics from graph structure
remains detect-topics
# Runs Louvain community detection, stores topics in default graph

# Name auto-detected topics
remains name-topic 0 "Database Systems"

# Manual topic creation
remains create-topic nlp-research --name "NLP Research"
remains add-to-topic nlp-research --member paper-123 --member paper-456

# List topics
remains topics

# Viz uses topics for coloring and sidebar
remains viz
remains viz --topic nlp-research   # filter to topic members
```

## CLI Commands (Complete)

### Initialize
```bash
# Create new domain database
remains init meetings.db \
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

# Scoped prompt (only classes in domain + their properties)
remains prompt --domain meetings
# Only includes: Meeting, Person, Task
# Plus properties where domain/range is one of those classes
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
#   Domains: 2 (meetings, people)
#   Topics: 6
#   Created: 2026-04-12
```

### Domains
```bash
remains domains                      # List all domains
# Output:
#   meetings   3 classes   "Meetings"
#   people     1 classes   "People"

remains create-domain projects \     # Create domain
  --class Project --class Task --class Milestone

remains add-to-domain projects \     # Add class to existing domain
  --class Person
```

### Topics
```bash
remains detect-topics                # Auto-detect via community detection
remains create-topic NAME            # Manual topic
remains add-to-topic NAME --member X # Add members
remains name-topic ID "Label"       # Name auto-detected topic
remains topics                       # List all topics
```

### Viz
```bash
remains viz                          # Full graph
remains viz --topic NAME             # Filter to topic
```

## Multiple Domains

```bash
# Different databases for different domains
export REMAINS_DSN=meetings.db
remains init --ontology meetings.ttl --shacl meetings-shapes.ttl
remains load meeting-data.ttl

export REMAINS_DSN=finance.db
remains init --ontology finance.ttl --shacl finance-shapes.ttl
remains load transactions.ttl

export REMAINS_DSN=people.db
remains init --ontology people.ttl --shacl people-shapes.ttl
remains load employees.ttl
```

Cross-domain linking = URI references. Applications join across DBs as needed. remains doesn't.

## Namespace Protection

System namespaces (`remains:`, `remains-sh:`) are immutable by user commands:

```bash
remains update-ontology evil.ttl
# evil.ttl contains: remains:Topic rdfs:label "Hacked" .
# ERROR: Cannot modify system namespace (urn:remains:system#)

remains update-shacl evil-shapes.ttl
# ERROR: Cannot modify system namespace (urn:remains:shapes#)
```

## Validation

```bash
remains check
```

Runs two passes:
1. **System shapes** (remains-sh:) against default data graph — validates topics, display names
2. **User shapes** against default data graph — validates domain data

Reports separately:
```
System validation:
  ✓ remains-sh:TopicShape — 6 topics validated
  ✓ remains-sh:DisplayNameShape — 245 instances validated

User validation:
  ✓ :PersonShape — 42 instances validated
  ✗ :MeetingShape — 1 violation
    Focus: :meeting-orphan
    Message: Meeting must have rdfs:label
```

## Migration from Current remains

Current remains has named data graphs in single DB. Migration:

```bash
# Export each domain's data
REMAINS_DSN=old-remains.db remains export -g nrc-meeting-* > nrc-data.ttl
REMAINS_DSN=old-remains.db remains export -g goingmeta > gm-data.ttl

# Create new domain DBs
REMAINS_DSN=nrc.db remains init --ontology nrc.ttl --shacl nrc-shapes.ttl
REMAINS_DSN=nrc.db remains load nrc-data.ttl

REMAINS_DSN=goingmeta.db remains init --ontology gm.ttl --shacl gm-shapes.ttl
REMAINS_DSN=goingmeta.db remains load gm-data.ttl
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

### Phase 2: Domains
- [ ] `remains create-domain` / `remains add-to-domain` commands
- [ ] `remains domains` list command
- [ ] Domains stored as remains:Domain instances in urn:ontology graph
- [ ] Update `remains prompt --domain X` to filter classes/properties to domain members
- [ ] System shape validation for domains (remains-sh:DomainShape)

### Phase 3: Topics
- [ ] `remains detect-topics` using Louvain from viz analytics
- [ ] `remains create-topic` / `remains add-to-topic` / `remains name-topic`
- [ ] `remains topics` list command
- [ ] Topics stored as remains:Topic instances in default data graph

### Phase 4: Display names
- [ ] Implement `get_display_name()` fallback chain
- [ ] Update viz node labels to use display names
- [ ] Update CLI output formatting

### Phase 5: Viz integration
- [ ] Load topics from default graph on viz start
- [ ] Color nodes by topic membership
- [ ] `--topic` filter flag
- [ ] Topic sidebar populated from stored topics

### Phase 6: Schema updates
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
