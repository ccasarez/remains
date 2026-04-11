"""SQLite triple store with validation-on-load."""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from rdflib import OWL, RDF, RDFS, Graph, Literal, Namespace, URIRef, BNode
from rdflib.term import Node

from dregs.models import GraphInfo, Triple, ValidationResult

PROV = Namespace("http://www.w3.org/ns/prov#")
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")
SH = Namespace("http://www.w3.org/ns/shacl#")

_WELL_KNOWN_NS = [
    "http://www.w3.org/2002/07/owl#",
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "http://www.w3.org/2000/01/rdf-schema#",
    "http://www.w3.org/2001/XMLSchema#",
    "http://www.w3.org/ns/shacl#",
    "http://www.w3.org/ns/prov#",
    "http://www.w3.org/2004/02/skos/core#",
]

_INIT_SQL = """
CREATE TABLE IF NOT EXISTS triples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object TEXT NOT NULL,
    object_type TEXT NOT NULL,
    datatype TEXT NOT NULL DEFAULT '',
    lang TEXT NOT NULL DEFAULT '',
    graph TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sp ON triples(subject, predicate);
CREATE INDEX IF NOT EXISTS idx_po ON triples(predicate, object);
CREATE INDEX IF NOT EXISTS idx_os ON triples(object, predicate);
CREATE INDEX IF NOT EXISTS idx_graph ON triples(graph);
CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_triple
    ON triples(subject, predicate, object, object_type, datatype, lang, graph);

CREATE TABLE IF NOT EXISTS graphs (
    uri TEXT PRIMARY KEY,
    label TEXT,
    graph_type TEXT NOT NULL,
    source_file TEXT,
    created_at TEXT,
    triple_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS prefixes (
    prefix TEXT PRIMARY KEY,
    namespace TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

_DEFAULT_PREFIXES = {
    "owl": "http://www.w3.org/2002/07/owl#",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "prov": "http://www.w3.org/ns/prov#",
    "sh": "http://www.w3.org/ns/shacl#",
}


def _short(uri: Node) -> str:
    s = str(uri)
    if "#" in s:
        return s.split("#")[-1]
    return s.split("/")[-1]


def _is_well_known(uri: URIRef) -> bool:
    s = str(uri)
    return any(s.startswith(ns) for ns in _WELL_KNOWN_NS)


def _rdflib_triple_to_row(s: Node, p: Node, o: Node, graph: str) -> Optional[tuple]:
    """Convert rdflib triple to SQLite row.

    BNode subjects are stored as ``_:{id}`` strings.
    Returns None for unsupported node types (non-URI predicates, etc.).
    """
    # Subject
    if isinstance(s, BNode):
        subj = f"_:{s}"
    elif isinstance(s, URIRef):
        subj = str(s)
    else:
        return None

    # Predicate
    if isinstance(p, URIRef):
        pred = str(p)
    else:
        return None

    # Object — datatype/lang use "" (not None) so the UNIQUE index works
    if isinstance(o, URIRef):
        return (subj, pred, str(o), "uri", "", "", graph)
    elif isinstance(o, BNode):
        return (subj, pred, f"_:{o}", "bnode", "", "", graph)
    elif isinstance(o, Literal):
        if o.language:
            return (subj, pred, str(o), "lang_literal", "", o.language, graph)
        elif o.datatype:
            return (subj, pred, str(o), "typed_literal", str(o.datatype), "", graph)
        else:
            return (subj, pred, str(o), "literal", "", "", graph)
    return None


def _rows_to_rdflib_graph(rows: list[tuple]) -> Graph:
    """Convert SQLite rows back to rdflib Graph."""
    g = Graph()
    for row in rows:
        # row: (subject, predicate, object, object_type, datatype, lang)
        subj_str, pred_str, obj_str, obj_type, datatype, lang = row[:6]

        if subj_str.startswith("_:"):
            subj = BNode(subj_str[2:])
        else:
            subj = URIRef(subj_str)

        pred = URIRef(pred_str)

        if obj_type == "uri":
            obj = URIRef(obj_str)
        elif obj_type == "bnode":
            obj = BNode(obj_str[2:] if obj_str.startswith("_:") else obj_str)
        elif obj_type == "lang_literal":
            obj = Literal(obj_str, lang=lang or None)
        elif obj_type == "typed_literal":
            obj = Literal(obj_str, datatype=URIRef(datatype)) if datatype else Literal(obj_str)
        else:
            obj = Literal(obj_str)

        g.add((subj, pred, obj))
    return g


class DregsStore:
    """SQLite-backed RDF triple store."""

    def __init__(self, dsn: str | Path | None = None):
        resolved = dsn if dsn is not None else os.environ.get("DREGS_DSN")
        if resolved is None:
            raise ValueError("No DSN. Pass a path/URL or set DREGS_DSN.")
        self._dsn = str(resolved).strip()
        # Backward compat: expose db_path for local file DSNs
        if self._dsn.startswith(("libsql://", "https://", "http://")):
            self.db_path: Path | None = None
        else:
            self.db_path = Path(self._dsn)
        self._conn = None

    def _connect(self):
        if self._conn is not None:
            return self._conn

        dsn = self._dsn

        if dsn.startswith(("libsql://", "https://", "http://")):
            try:
                import libsql
            except ImportError:
                raise ImportError(
                    "Remote Turso databases require the libsql package. "
                    "Install with: pip install dregs[turso]"
                )
            self._conn = libsql.connect(
                database=dsn,
                auth_token=os.environ.get("DREGS_AUTH_TOKEN", "").strip(),
            )
        elif os.environ.get("DREGS_SYNC_URL", "").strip():
            try:
                import libsql
            except ImportError:
                raise ImportError(
                    "Embedded replica mode requires the libsql package. "
                    "Install with: pip install dregs[turso]"
                )
            self._conn = libsql.connect(
                database=dsn,
                sync_url=os.environ["DREGS_SYNC_URL"].strip(),
                auth_token=os.environ.get("DREGS_AUTH_TOKEN", "").strip(),
            )
            self._conn.sync()
        else:
            self._conn = sqlite3.connect(dsn)

        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
        except Exception:
            pass
        try:
            self._conn.execute("PRAGMA foreign_keys=ON")
        except Exception:
            pass

        return self._conn

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def init(
        self,
        schema_path: Optional[Path] = None,
        shacl_path: Optional[Path] = None,
    ) -> dict:
        """Initialize database. Load schema and/or SHACL shapes."""
        conn = self._connect()
        conn.executescript(_INIT_SQL)

        # Store metadata
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            ("version", "0.1.0"),
        )
        conn.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            ("created_at", now),
        )

        # Store default prefixes
        for prefix, ns in _DEFAULT_PREFIXES.items():
            conn.execute(
                "INSERT OR REPLACE INTO prefixes (prefix, namespace) VALUES (?, ?)",
                (prefix, ns),
            )

        result = {"schema_triples": 0, "shacl_triples": 0}

        if schema_path:
            g = Graph()
            g.parse(str(schema_path), format="turtle")
            graph_uri = f"file:{schema_path.name}"
            count = self._insert_graph(conn, g, graph_uri, "schema", schema_path.name)
            result["schema_triples"] = count

            # Extract prefixes from schema
            for prefix, ns in g.namespaces():
                if prefix:
                    conn.execute(
                        "INSERT OR REPLACE INTO prefixes (prefix, namespace) VALUES (?, ?)",
                        (str(prefix), str(ns)),
                    )

        if shacl_path:
            g = Graph()
            g.parse(str(shacl_path), format="turtle")
            graph_uri = f"file:{shacl_path.name}"
            count = self._insert_graph(conn, g, graph_uri, "shacl", shacl_path.name)
            result["shacl_triples"] = count

        conn.commit()
        return result

    def _insert_graph(
        self,
        conn: sqlite3.Connection,
        g: Graph,
        graph_uri: str,
        graph_type: str,
        source_file: Optional[str] = None,
        label: Optional[str] = None,
    ) -> int:
        """Insert rdflib Graph into SQLite under a named graph."""
        now = datetime.now(timezone.utc).isoformat()
        rows = []
        for s, p, o in g:
            row = _rdflib_triple_to_row(s, p, o, graph_uri)
            if row:
                rows.append(row)

        conn.executemany(
            """INSERT OR IGNORE INTO triples
               (subject, predicate, object, object_type, datatype, lang, graph)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )

        # Count actual triples stored (INSERT OR IGNORE may skip duplicates)
        actual = conn.execute(
            "SELECT COUNT(*) FROM triples WHERE graph = ?", (graph_uri,)
        ).fetchone()[0]

        conn.execute(
            """INSERT OR REPLACE INTO graphs
               (uri, label, graph_type, source_file, created_at, triple_count)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (graph_uri, label or source_file or graph_uri, graph_type, source_file, now, actual),
        )

        return actual

    def load(
        self,
        data_path: Path,
        graph_name: Optional[str] = None,
        validate: bool = True,
    ) -> dict:
        """Load Turtle data into the store. Validates against schema/SHACL by default."""
        conn = self._connect()

        # Parse input data
        data_graph = Graph()
        data_graph.parse(str(data_path), format="turtle")

        if validate:
            # Pull schema and shacl from DB
            schema_graph = self._load_graphs_by_type(conn, "schema")
            shacl_graph = self._load_graphs_by_type(conn, "shacl")

            if len(schema_graph) == 0:
                raise ValueError("No schema loaded. Run 'dregs init --schema' first.")

            result = run_validation(
                schema_graph=schema_graph,
                data_graph=data_graph,
                shacl_graph=shacl_graph if len(shacl_graph) > 0 else None,
            )

            if not result.conforms:
                return {
                    "loaded": False,
                    "validation": result,
                }

        # Determine graph URI
        graph_uri = graph_name or f"file:{data_path.name}"

        count = self._insert_graph(
            conn, data_graph, graph_uri, "data", data_path.name, label=graph_name
        )
        conn.commit()

        return {
            "loaded": True,
            "triple_count": count,
            "graph": graph_uri,
        }

    def _load_graphs_by_type(self, conn: sqlite3.Connection, graph_type: str) -> Graph:
        """Load all graphs of a given type into a single rdflib Graph."""
        rows = conn.execute(
            """SELECT subject, predicate, object, object_type, datatype, lang
               FROM triples
               WHERE graph IN (SELECT uri FROM graphs WHERE graph_type = ?)""",
            (graph_type,),
        ).fetchall()
        return _rows_to_rdflib_graph(rows)

    def load_all_graphs(self) -> Graph:
        """Load all triples into a single rdflib Graph (union graph)."""
        conn = self._connect()
        rows = conn.execute(
            "SELECT subject, predicate, object, object_type, datatype, lang FROM triples"
        ).fetchall()
        return _rows_to_rdflib_graph(rows)

    def load_graph(self, graph_uri: str) -> Graph:
        """Load a specific named graph into rdflib Graph."""
        conn = self._connect()
        rows = conn.execute(
            """SELECT subject, predicate, object, object_type, datatype, lang
               FROM triples WHERE graph = ?""",
            (graph_uri,),
        ).fetchall()
        return _rows_to_rdflib_graph(rows)

    def export_by_type(self, graph_type: str) -> str:
        """Export graphs of a given type as Turtle."""
        conn = self._connect()
        g = self._load_graphs_by_type(conn, graph_type)

        # Bind prefixes
        for row in conn.execute("SELECT prefix, namespace FROM prefixes").fetchall():
            g.bind(row[0], Namespace(row[1]))

        return g.serialize(format="turtle")

    def export_graph(self, graph_uri: str) -> str:
        """Export a specific named graph as Turtle."""
        conn = self._connect()
        g = self.load_graph(graph_uri)

        for row in conn.execute("SELECT prefix, namespace FROM prefixes").fetchall():
            g.bind(row[0], Namespace(row[1]))

        return g.serialize(format="turtle")

    def list_graphs(self) -> list[GraphInfo]:
        """List all named graphs."""
        conn = self._connect()
        rows = conn.execute(
            "SELECT uri, label, graph_type, source_file, created_at, triple_count FROM graphs"
        ).fetchall()
        return [
            GraphInfo(
                uri=r[0], label=r[1], graph_type=r[2],
                source_file=r[3], created_at=r[4], triple_count=r[5],
            )
            for r in rows
        ]

    def drop_graph(self, graph_uri: str) -> int:
        """Delete a named graph and its triples. Returns count of deleted triples."""
        conn = self._connect()
        cursor = conn.execute("DELETE FROM triples WHERE graph = ?", (graph_uri,))
        count = cursor.rowcount
        conn.execute("DELETE FROM graphs WHERE uri = ?", (graph_uri,))
        conn.commit()
        return count

    def stats(self) -> dict:
        """Return database statistics."""
        conn = self._connect()
        total = conn.execute("SELECT COUNT(*) FROM triples").fetchone()[0]
        graph_count = conn.execute("SELECT COUNT(*) FROM graphs").fetchone()[0]
        by_type = conn.execute(
            "SELECT graph_type, COUNT(*), SUM(triple_count) FROM graphs GROUP BY graph_type"
        ).fetchall()
        version = conn.execute(
            "SELECT value FROM metadata WHERE key = 'version'"
        ).fetchone()
        created = conn.execute(
            "SELECT value FROM metadata WHERE key = 'created_at'"
        ).fetchone()

        return {
            "total_triples": total,
            "graph_count": graph_count,
            "by_type": {r[0]: {"graphs": r[1], "triples": r[2] or 0} for r in by_type},
            "version": version[0] if version else "unknown",
            "created_at": created[0] if created else "unknown",
        }

    def get_prefixes(self) -> dict[str, str]:
        """Return prefix -> namespace mapping."""
        conn = self._connect()
        rows = conn.execute("SELECT prefix, namespace FROM prefixes").fetchall()
        return {r[0]: r[1] for r in rows}


# === Validation (absorbed from owl-guard) ===


def run_validation(
    schema_graph: Graph,
    data_graph: Graph,
    shacl_graph: Optional[Graph] = None,
    reasoning_regime: str = "owlrl",
    require_provenance: bool = False,
) -> ValidationResult:
    """Full validation pipeline: SHACL -> OWL reasoning -> schema checks."""
    result = ValidationResult()

    # Combine schema + data for reasoning
    combined = Graph()
    for t in schema_graph:
        combined.add(t)
    for t in data_graph:
        combined.add(t)

    result.total_triples_before = len(combined)

    # SHACL validation BEFORE reasoning (closed-world check on raw data)
    if shacl_graph and len(shacl_graph) > 0:
        result.shacl_conforms, result.shacl_violations = _run_shacl(
            combined, shacl_graph
        )

    # OWL Reasoning
    result.owl_inferred_triples = _run_owl_reasoning(combined, reasoning_regime)
    result.total_triples_after = len(combined)

    # Schema structure checks
    result.schema_violations = _run_schema_checks(
        schema_graph, combined, require_provenance
    )

    result.conforms = result.shacl_conforms and len(result.schema_violations) == 0
    return result


def _run_owl_reasoning(graph: Graph, regime: str = "owlrl") -> int:
    """Run OWL-RL reasoning. Returns count of inferred triples."""
    import owlrl

    before = len(graph)
    regimes = {
        "owlrl": owlrl.OWLRL_Semantics,
        "rdfs": owlrl.RDFSClosure,
        "both": owlrl.OWLRL_Extension,
    }
    semantics = regimes.get(regime, owlrl.OWLRL_Semantics)
    owlrl.DeductiveClosure(semantics).expand(graph)
    return len(graph) - before


def _run_shacl(data_graph: Graph, shacl_graph: Graph) -> tuple[bool, list[str]]:
    """Run SHACL validation. Returns (conforms, violations)."""
    from pyshacl import validate

    conforms, results_graph, results_text = validate(
        data_graph,
        shacl_graph=shacl_graph,
        inference="none",
        serialize_report_graph="turtle",
    )

    violations = []
    if not conforms:
        rg = None
        if isinstance(results_graph, (str, bytes)):
            rg = Graph()
            rg.parse(data=results_graph, format="turtle")
        elif isinstance(results_graph, Graph):
            rg = results_graph

        if rg:
            for result_node in rg.subjects(RDF.type, SH.ValidationResult):
                focus = rg.value(result_node, SH.focusNode)
                path = rg.value(result_node, SH.resultPath)
                msg = rg.value(result_node, SH.resultMessage)
                focus_s = _short(focus) if focus else "?"
                path_s = _short(path) if path else "?"
                msg_s = str(msg) if msg else "constraint violated"
                violations.append(f"[{focus_s}] {path_s}: {msg_s}")
        else:
            for line in results_text.strip().split("\n"):
                line = line.strip()
                if line.startswith("Message:"):
                    violations.append(line)

    return conforms, violations


def _run_schema_checks(
    schema_graph: Graph,
    combined_graph: Graph,
    require_provenance: bool = False,
) -> list[str]:
    """Check instances conform to OWL schema structure."""
    violations = []

    # Gather schema classes
    schema_classes: set[URIRef] = set()
    for s in schema_graph.subjects(RDF.type, OWL.Class):
        if isinstance(s, URIRef):
            schema_classes.add(s)
    for s in schema_graph.subjects(RDF.type, RDFS.Class):
        if isinstance(s, URIRef):
            schema_classes.add(s)

    # Identify abstract (non-leaf) classes
    parents: set[URIRef] = set()
    for _, _, parent in schema_graph.triples((None, RDFS.subClassOf, None)):
        if isinstance(parent, URIRef):
            parents.add(parent)
    abstract_classes = schema_classes & parents
    leaf_classes = schema_classes - parents

    # Find instance subjects — only exclude actual schema definitions,
    # not every URI that appears as a subject in the schema graph.
    _SCHEMA_DEF_TYPES = {
        OWL.Class,
        OWL.ObjectProperty,
        OWL.DatatypeProperty,
        OWL.AnnotationProperty,
        OWL.Ontology,
        RDFS.Class,
        RDFS.Datatype,
    }
    schema_definitions: set[Node] = set()
    for def_type in _SCHEMA_DEF_TYPES:
        for s in schema_graph.subjects(RDF.type, def_type):
            schema_definitions.add(s)
    instance_subjects = set(combined_graph.subjects()) - schema_definitions

    # Provenance source URIs
    prov_sources: set[URIRef] = set()
    for obj in combined_graph.objects(predicate=PROV.wasDerivedFrom):
        if isinstance(obj, URIRef):
            prov_sources.add(obj)

    for subj in instance_subjects:
        if not isinstance(subj, URIRef):
            continue
        if _is_well_known(subj):
            continue
        if subj in prov_sources:
            continue

        types = set(combined_graph.objects(subj, RDF.type))
        user_types = {t for t in types if isinstance(t, URIRef) and not _is_well_known(t)}

        if not user_types:
            if not types:
                violations.append(f"NO_TYPE: {subj} has no rdf:type")
            continue

        has_leaf = any(t in leaf_classes for t in user_types)

        for t in user_types:
            if t not in schema_classes:
                violations.append(
                    f"UNKNOWN_TYPE: {_short(subj)} typed as {_short(t)} -- not in schema"
                )
            elif t in abstract_classes and not has_leaf:
                violations.append(
                    f"ABSTRACT_TYPE: {_short(subj)} typed as abstract class {_short(t)} -- use leaf class"
                )

        if require_provenance:
            if not set(combined_graph.objects(subj, PROV.wasDerivedFrom)):
                violations.append(
                    f"NO_PROVENANCE: {_short(subj)} missing prov:wasDerivedFrom"
                )

    return violations


def validate_files(
    ontology_path: Path,
    data_path: Path,
    shacl_path: Optional[Path] = None,
    reasoning_regime: str = "owlrl",
    require_provenance: bool = False,
) -> ValidationResult:
    """Validate from file paths (standalone mode, no DB)."""
    schema_graph = Graph()
    schema_graph.parse(str(ontology_path), format="turtle")

    data_graph = Graph()
    data_graph.parse(str(data_path), format="turtle")

    shacl_graph = None
    if shacl_path:
        shacl_graph = Graph()
        shacl_graph.parse(str(shacl_path), format="turtle")

    return run_validation(
        schema_graph=schema_graph,
        data_graph=data_graph,
        shacl_graph=shacl_graph,
        reasoning_regime=reasoning_regime,
        require_provenance=require_provenance,
    )
