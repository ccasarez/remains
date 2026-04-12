# dregs v2 — Simplified Architecture

## Design Principles

1. **One SQLite DB = one knowledge domain** — no multi-graph complexity
2. **3 fixed graphs** — data, ontology, shacl. Nothing else.
3. **System/user split** — dregs ships system ontology + shapes, user provides domain-specific ones
4. **Standard vocabularies** — reuse rdfs:label, schema:name, skos:prefLabel. Don't invent.
5. **Topics are first-class data** — reified as dregs:Topic instances in default data graph, queryable, vizualizable
6. **Domains scope LLM extraction** — reified as dregs:Domain instances in ontology graph, grouping classes for `dregs prompt --domain X`
7. **Multiple knowledge bases = multiple databases** — use DREGS_DSN to switch

## DB Structure

```
One SQLite database:
  DEFAULT graph  = user data + topics (dregs:Topic instances live here)
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
@prefix dregs:    <urn:dregs:system#> .     # System ontology classes/properties
@prefix dregs-sh: <urn:dregs:shapes#> .     # System SHACL shapes
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

## System Ontology (bundled with dregs)

```turtle
# system-ontology.ttl
@prefix dregs: <urn:dregs:system#> .
@prefix owl:   <http://www.w3.org/2002/07/owl#> .
@prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
@prefix sh:    <http://www.w3.org/ns/shacl#> .
@prefix xsd:   <http://www.w3.org/2001/XMLSchema#> .

<urn:dregs:system> a owl:Ontology ;
    rdfs:label "dregs System Ontology" ;
    owl:imports <http://www.w3.org/2000/01/rdf-schema> ,
                <http://www.w3.org/2004/02/skos/core> .

# --- Topic ---

dregs:Topic a owl:Class ;
    rdfs:label "Topic" ;
    rdfs:comment "Thematic grouping of entities in the knowledge graph" .

dregs:member a owl:ObjectProperty ;
    rdfs:domain dregs:Topic ;
    rdfs:label "member" ;
    rdfs:comment "Entity belonging to this topic" .

dregs:createdBy a owl:DatatypeProperty ;
    rdfs:domain dregs:Topic ;
    rdfs:range xsd:string ;
    rdfs:comment "Algorithm or user that created this topic" .

dregs:modularity a owl:DatatypeProperty ;
    rdfs:domain dregs:Topic ;
    rdfs:range xsd:decimal ;
    rdfs:comment "Modularity score from community detection" .

dregs:color a owl:DatatypeProperty ;
    rdfs:domain dregs:Topic ;
    rdfs:range xsd:string ;
    rdfs:comment "Display color (hex)" .

# --- Domain (ontology-level grouping for scoped LLM prompts) ---

dregs:Domain a owl:Class ;
    rdfs:label "Domain" ;
    rdfs:comment "Named subset of ontology classes for scoped LLM extraction prompts" .

dregs:includesClass a owl:ObjectProperty ;
    rdfs:domain dregs:Domain ;
    rdfs:range owl:Class ;
    rdfs:label "includes class" ;
    rdfs:comment "An ontology class included in this domain" .

# --- Display Name Constraint ---

dregs:RequiresDisplayName a rdfs:Class ;
    rdfs:label "Requires Display Name" ;
    rdfs:comment "Marker: instances of subclasses must have rdfs:label, skos:prefLabel, or schema:name" .
```

## System Shapes (bundled with dregs)

```turtle
# system-shapes.ttl
@prefix dregs:    <urn:dregs:system#> .
@prefix dregs-sh: <urn:dregs:shapes#> .
@prefix sh:       <http://www.w3.org/ns/shacl#> .
@prefix rdfs:     <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos:     <http://www.w3.org/2004/02/skos/core#> .
@prefix schema:   <http://schema.org/> .
@prefix xsd:      <http://www.w3.org/2001/XMLSchema#> .

# Topic must have label and at least one member
dregs-sh:TopicShape a sh:NodeShape ;
    sh:targetClass dregs:Topic ;
    sh:property [
        sh:path rdfs:label ;
        sh:minCount 1 ;
        sh:datatype xsd:string ;
        sh:message "Topic must have rdfs:label"
    ] ;
    sh:property [
        sh:path dregs:member ;
        sh:minCount 1 ;
        sh:nodeKind sh:IRI ;
        sh:message "Topic must have at least one member"
    ] ;
    sh:property [
        sh:path dregs:createdBy ;
        sh:maxCount 1 ;
        sh:datatype xsd:string
    ] ;
    sh:property [
        sh:path dregs:modularity ;
        sh:maxCount 1 ;
        sh:datatype xsd:decimal
    ] .

# Domain must have label and at least one class
dregs-sh:DomainShape a sh:NodeShape ;
    sh:targetClass dregs:Domain ;
    sh:property [
        sh:path rdfs:label ;
        sh:minCount 1 ;
        sh:datatype xsd:string ;
        sh:message "Domain must have rdfs:label"
    ] ;
    sh:property [
        sh:path dregs:includesClass ;
        sh:minCount 1 ;
        sh:nodeKind sh:IRI ;
        sh:message "Domain must include at least one class"
    ] .

# All leaf classes marked RequiresDisplayName must have a display property
dregs-sh:DisplayNameShape a sh:NodeShape ;
    sh:targetClass dregs:RequiresDisplayName ;
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
@prefix dregs: <urn:dregs:system#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix schema: <http://schema.org/> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

:Person a owl:Class, dregs:RequiresDisplayName ;
    rdfs:label "Person" .

:Meeting a owl:Class, dregs:RequiresDisplayName ;
    rdfs:label "Meeting" .

:Task a owl:Class, dregs:RequiresDisplayName ;
    rdfs:label "Task" .

:attendedBy a owl:ObjectProperty ;
    rdfs:domain :Meeting ;
    rdfs:range :Person .

:date a owl:DatatypeProperty ;
    rdfs:domain :Meeting ;
    rdfs:range xsd:date .

# --- Domains (scoped class subsets for LLM extraction) ---
# These live in urn:ontology alongside class definitions

<urn:dregs:domain#meetings> a dregs:Domain ;
    rdfs:label "Meetings" ;
    dregs:includesClass :Meeting, :Person, :Task .

<urn:dregs:domain#people> a dregs:Domain ;
    rdfs:label "People" ;
    dregs:includesClass :Person .
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
Topics are data. They live in the default data graph alongside everything else — just instances of `dregs:Topic` from the system ontology. Validated by system shapes like any other class.

```turtle
@prefix dregs: <urn:dregs:system#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix : <urn:domain:meetings#> .

# These triples live in the DEFAULT data graph

<urn:dregs:topic#nlp-research> a dregs:Topic ;
    rdfs:label "NLP Research" ;
    rdfs:comment "Natural language processing papers and projects" ;
    dregs:member :paper-123, :paper-456, :project-bert ;
    dregs:createdBy "manual" ;
    dregs:color "#d64141" .

<urn:dregs:topic#0> a dregs:Topic ;
    rdfs:label "Database Systems" ;
    dregs:member :neo4j, :postgres, :ep-12, :ep-16 ;
    dregs:createdBy "louvain" ;
    dregs:modularity 0.72 ;
    dregs:color "#62e889" .
```

### CLI Commands

```bash
# Auto-detect topics from graph structure
dregs detect-topics
# Runs Louvain community detection, stores topics in default graph

# Name auto-detected topics
dregs name-topic 0 "Database Systems"

# Manual topic creation
dregs create-topic nlp-research --name "NLP Research"
dregs add-to-topic nlp-research --member paper-123 --member paper-456

# List topics
dregs topics

# Viz uses topics for coloring and sidebar
dregs viz
dregs viz --topic nlp-research   # filter to topic members
```

## CLI Commands (Complete)

### Initialize
```bash
# Create new domain database
dregs init meetings.db \
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
dregs load meeting-2026-04-12.ttl

# Validates against urn:shacl automatically
# Error if data violates system or user shapes
```

### Query
```bash
# Query data
dregs query "SELECT * WHERE { ?s a :Meeting }"

# All commands implicitly target current DB (DREGS_DSN)
```

### Prompt
```bash
# Full prompt (all classes in ontology)
dregs prompt

# Scoped prompt (only classes in domain + their properties)
dregs prompt --domain meetings
# Only includes: Meeting, Person, Task
# Plus properties where domain/range is one of those classes
```

### Validate
```bash
dregs check
# Output:
#   System validation: 2 shapes, 0 violations
#   User validation: 5 shapes, 0 violations
#   Total: 156 triples validated
```

### Update Schema
```bash
# Replace user ontology (system ontology preserved)
dregs update-ontology meetings-v2.ttl

# Replace user shapes (system shapes preserved)
dregs update-shacl meetings-v2-shapes.ttl

# Dry run: validate data against new schema first
dregs update-ontology meetings-v2.ttl --dry-run
```

### Export
```bash
dregs export                       # Data only (default graph)
dregs export --ontology            # User ontology triples only
dregs export --shacl               # User shapes only
dregs export --all                 # Everything
```

### Info
```bash
dregs info
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
dregs domains                      # List all domains
# Output:
#   meetings   3 classes   "Meetings"
#   people     1 classes   "People"

dregs create-domain projects \     # Create domain
  --class Project --class Task --class Milestone

dregs add-to-domain projects \     # Add class to existing domain
  --class Person
```

### Topics
```bash
dregs detect-topics                # Auto-detect via community detection
dregs create-topic NAME            # Manual topic
dregs add-to-topic NAME --member X # Add members
dregs name-topic ID "Label"       # Name auto-detected topic
dregs topics                       # List all topics
```

### Viz
```bash
dregs viz                          # Full graph
dregs viz --topic NAME             # Filter to topic
```

## Multiple Domains

```bash
# Different databases for different domains
export DREGS_DSN=meetings.db
dregs init --ontology meetings.ttl --shacl meetings-shapes.ttl
dregs load meeting-data.ttl

export DREGS_DSN=finance.db
dregs init --ontology finance.ttl --shacl finance-shapes.ttl
dregs load transactions.ttl

export DREGS_DSN=people.db
dregs init --ontology people.ttl --shacl people-shapes.ttl
dregs load employees.ttl
```

Cross-domain linking = URI references. Applications join across DBs as needed. dregs doesn't.

## Namespace Protection

System namespaces (`dregs:`, `dregs-sh:`) are immutable by user commands:

```bash
dregs update-ontology evil.ttl
# evil.ttl contains: dregs:Topic rdfs:label "Hacked" .
# ERROR: Cannot modify system namespace (urn:dregs:system#)

dregs update-shacl evil-shapes.ttl
# ERROR: Cannot modify system namespace (urn:dregs:shapes#)
```

## Validation

```bash
dregs check
```

Runs two passes:
1. **System shapes** (dregs-sh:) against default data graph — validates topics, display names
2. **User shapes** against default data graph — validates domain data

Reports separately:
```
System validation:
  ✓ dregs-sh:TopicShape — 6 topics validated
  ✓ dregs-sh:DisplayNameShape — 245 instances validated

User validation:
  ✓ :PersonShape — 42 instances validated
  ✗ :MeetingShape — 1 violation
    Focus: :meeting-orphan
    Message: Meeting must have rdfs:label
```

## Migration from Current dregs

Current dregs has named data graphs in single DB. Migration:

```bash
# Export each domain's data
DREGS_DSN=old-dregs.db dregs export -g nrc-meeting-* > nrc-data.ttl
DREGS_DSN=old-dregs.db dregs export -g goingmeta > gm-data.ttl

# Create new domain DBs
DREGS_DSN=nrc.db dregs init --ontology nrc.ttl --shacl nrc-shapes.ttl
DREGS_DSN=nrc.db dregs load nrc-data.ttl

DREGS_DSN=goingmeta.db dregs init --ontology gm.ttl --shacl gm-shapes.ttl
DREGS_DSN=goingmeta.db dregs load gm-data.ttl
```

## Implementation Phases

### Phase 1: Core DB restructure
- [ ] New DB schema (3 fixed graphs, metadata table)
- [ ] Bundle system-ontology.ttl and system-shapes.ttl
- [ ] `dregs init` command (loads system + user ontology/shapes)
- [ ] Namespace protection on update commands
- [ ] Update `dregs load` to target default graph only
- [ ] Update `dregs prompt` to read from urn:ontology
- [ ] Update `dregs check` with system/user split validation
- [ ] Update `dregs export` with --ontology/--shacl/--all flags
- [ ] `dregs info` with system/user triple counts

### Phase 2: Domains
- [ ] `dregs create-domain` / `dregs add-to-domain` commands
- [ ] `dregs domains` list command
- [ ] Domains stored as dregs:Domain instances in urn:ontology graph
- [ ] Update `dregs prompt --domain X` to filter classes/properties to domain members
- [ ] System shape validation for domains (dregs-sh:DomainShape)

### Phase 3: Topics
- [ ] `dregs detect-topics` using Louvain from viz analytics
- [ ] `dregs create-topic` / `dregs add-to-topic` / `dregs name-topic`
- [ ] `dregs topics` list command
- [ ] Topics stored as dregs:Topic instances in default data graph

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
- [ ] `dregs update-ontology` (preserves system, replaces user)
- [ ] `dregs update-shacl` (preserves system, replaces user)
- [ ] `--dry-run` flag for pre-validation

## Files Shipped with dregs

```
dregs/
├── src/dregs/
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
