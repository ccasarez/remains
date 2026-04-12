"""SQLite triple store with 3 fixed graphs and system/user split."""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from rdflib import OWL, RDF, RDFS, Graph, Literal, Namespace, URIRef, BNode
from rdflib.term import Node

from dregs.models import Triple, ValidationResult

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
    "dregs": "urn:dregs:system#",
    "dregs-sh": "urn:dregs:shapes#",
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
    """Convert rdflib triple to SQLite row."""
    if isinstance(s, BNode):
        subj = f"_:{s}"
    elif isinstance(s, URIRef):
        subj = str(s)
    else:
        return None

    if isinstance(p, URIRef):
        pred = str(p)
    else:
        return None

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
    """SQLite-backed RDF triple store with 3 fixed graphs.

    Graphs:
        '' (default)   — user data + topics
        'urn:ontology' — system ontology + user ontology
        'urn:shacl'    — system shapes + user shapes
    """

    _XDG_DEFAULT_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "dregs"
    _XDG_DEFAULT_DB = _XDG_DEFAULT_DIR / "dregs.db"
    _SYSTEM_ONTOLOGY = Path(__file__).parent / "system" / "system-ontology.ttl"
    _SYSTEM_SHAPES = Path(__file__).parent / "system" / "system-shapes.ttl"
    _SYSTEM_NAMESPACES = ("urn:dregs:system#", "urn:dregs:shapes#")

    def __init__(self, dsn: str | Path | None = None):
        resolved = dsn if dsn is not None else os.environ.get("DREGS_DSN")
        self._used_default = False
        if resolved is None:
            self._XDG_DEFAULT_DIR.mkdir(parents=True, exist_ok=True)
            resolved = self._XDG_DEFAULT_DB
            self._used_default = True
        self._dsn = str(resolved).strip()
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
            import libsql
            self._conn = libsql.connect(
                database=dsn,
                auth_token=os.environ.get("DREGS_AUTH_TOKEN", "").strip(),
            )
        elif os.environ.get("DREGS_SYNC_URL", "").strip():
            import libsql
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

    # -----------------------------------------------------------------
    # Init
    # -----------------------------------------------------------------

    def init(
        self,
        ontology_path: Optional[Path] = None,
        shacl_path: Optional[Path] = None,
    ) -> dict:
        """Initialize database with 3 fixed graphs.

        Loads system ontology + shapes automatically.
        User ontology and shapes are merged into the same graphs.
        """
        conn = self._connect()
        conn.executescript(_INIT_SQL)

        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            ("version", "0.2.0"),
        )
        conn.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            ("created_at", now),
        )

        for prefix, ns in _DEFAULT_PREFIXES.items():
            conn.execute(
                "INSERT OR REPLACE INTO prefixes (prefix, namespace) VALUES (?, ?)",
                (prefix, ns),
            )

        result = {"system_ontology_triples": 0, "user_ontology_triples": 0,
                  "system_shacl_triples": 0, "user_shacl_triples": 0}

        # Load system ontology into urn:ontology
        if self._SYSTEM_ONTOLOGY.exists():
            g = Graph()
            g.parse(str(self._SYSTEM_ONTOLOGY), format="turtle")
            count = self._insert_triples(conn, g, "urn:ontology")
            result["system_ontology_triples"] = count
            for prefix, ns in g.namespaces():
                if prefix:
                    conn.execute(
                        "INSERT OR REPLACE INTO prefixes (prefix, namespace) VALUES (?, ?)",
                        (str(prefix), str(ns)),
                    )

        # Load user ontology into urn:ontology
        if ontology_path:
            g = Graph()
            g.parse(str(ontology_path), format="turtle")
            count = self._insert_triples(conn, g, "urn:ontology")
            result["user_ontology_triples"] = count
            for prefix, ns in g.namespaces():
                if prefix:
                    conn.execute(
                        "INSERT OR REPLACE INTO prefixes (prefix, namespace) VALUES (?, ?)",
                        (str(prefix), str(ns)),
                    )

        # Load system shapes into urn:shacl
        if self._SYSTEM_SHAPES.exists():
            g = Graph()
            g.parse(str(self._SYSTEM_SHAPES), format="turtle")
            count = self._insert_triples(conn, g, "urn:shacl")
            result["system_shacl_triples"] = count

        # Load user shapes into urn:shacl
        if shacl_path:
            g = Graph()
            g.parse(str(shacl_path), format="turtle")
            count = self._insert_triples(conn, g, "urn:shacl")
            result["user_shacl_triples"] = count

        conn.commit()
        return result

    # -----------------------------------------------------------------
    # Load
    # -----------------------------------------------------------------

    def load(self, data_path: Path) -> dict:
        """Load Turtle data into default graph. Validates against ontology + shapes."""
        conn = self._connect()

        data_graph = Graph()
        data_graph.parse(str(data_path), format="turtle")

        schema_graph = self._load_graph(conn, "urn:ontology")
        shacl_graph = self._load_graph(conn, "urn:shacl")

        if len(schema_graph) == 0:
            raise ValueError("No ontology loaded. Run 'dregs init' first.")

        result = run_validation(
            schema_graph=schema_graph,
            data_graph=data_graph,
            shacl_graph=shacl_graph if len(shacl_graph) > 0 else None,
        )

        if not result.conforms:
            return {"loaded": False, "validation": result}

        count = self._insert_triples(conn, data_graph, "")
        conn.commit()
        return {"loaded": True, "triple_count": count}

    # -----------------------------------------------------------------
    # Query helpers
    # -----------------------------------------------------------------

    def _insert_triples(self, conn, g: Graph, graph: str) -> int:
        """Insert rdflib Graph triples into a specific graph. Returns count."""
        rows = []
        for s, p, o in g:
            row = _rdflib_triple_to_row(s, p, o, graph)
            if row:
                rows.append(row)
        conn.executemany(
            """INSERT OR IGNORE INTO triples
               (subject, predicate, object, object_type, datatype, lang, graph)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        return len(rows)

    def _load_graph(self, conn, graph: str) -> Graph:
        """Load a specific graph into rdflib Graph."""
        rows = conn.execute(
            "SELECT subject, predicate, object, object_type, datatype, lang FROM triples WHERE graph = ?",
            (graph,),
        ).fetchall()
        return _rows_to_rdflib_graph(rows)

    def load_all_graphs(self) -> Graph:
        """Load all triples into a single rdflib Graph (union graph)."""
        conn = self._connect()
        rows = conn.execute(
            "SELECT subject, predicate, object, object_type, datatype, lang FROM triples"
        ).fetchall()
        return _rows_to_rdflib_graph(rows)

    def load_data_graph(self) -> Graph:
        """Load default data graph into rdflib Graph."""
        conn = self._connect()
        return self._load_graph(conn, "")

    def load_ontology_graph(self) -> Graph:
        """Load ontology graph into rdflib Graph."""
        conn = self._connect()
        return self._load_graph(conn, "urn:ontology")

    # -----------------------------------------------------------------
    # Update schema
    # -----------------------------------------------------------------

    def update_ontology(self, ontology_path: Path) -> int:
        """Replace user ontology triples. System triples protected."""
        self._check_no_system_namespace(ontology_path)
        conn = self._connect()
        conn.execute(
            "DELETE FROM triples WHERE graph = 'urn:ontology' AND subject NOT LIKE 'urn:dregs:%'",
        )
        g = Graph()
        g.parse(str(ontology_path), format="turtle")
        count = self._insert_triples(conn, g, "urn:ontology")
        conn.commit()
        return count

    def update_shacl(self, shacl_path: Path) -> int:
        """Replace user SHACL triples. System shapes protected."""
        self._check_no_system_namespace(shacl_path)
        conn = self._connect()
        conn.execute(
            "DELETE FROM triples WHERE graph = 'urn:shacl' AND subject NOT LIKE 'urn:dregs:%'",
        )
        g = Graph()
        g.parse(str(shacl_path), format="turtle")
        count = self._insert_triples(conn, g, "urn:shacl")
        conn.commit()
        return count

    def _check_no_system_namespace(self, ttl_path: Path):
        """Raise ValueError if file contains system namespace triples."""
        g = Graph()
        g.parse(str(ttl_path), format="turtle")
        for s, _, _ in g:
            s_str = str(s)
            for ns in self._SYSTEM_NAMESPACES:
                if s_str.startswith(ns):
                    raise ValueError(
                        f"Cannot modify system namespace ({ns}). "
                        f"Subject {s_str} is protected."
                    )

    # -----------------------------------------------------------------
    # Export
    # -----------------------------------------------------------------

    def export(self, what: str = "data") -> str:
        """Export data, ontology, shacl, or all as Turtle.

        Args:
            what: 'data' (default graph), 'ontology' (user only),
                  'shacl' (user only), 'all' (everything)
        """
        conn = self._connect()

        if what == "data":
            g = self._load_graph(conn, "")
        elif what == "ontology":
            rows = conn.execute(
                "SELECT subject, predicate, object, object_type, datatype, lang "
                "FROM triples WHERE graph = 'urn:ontology' AND subject NOT LIKE 'urn:dregs:%'",
            ).fetchall()
            g = _rows_to_rdflib_graph(rows)
        elif what == "shacl":
            rows = conn.execute(
                "SELECT subject, predicate, object, object_type, datatype, lang "
                "FROM triples WHERE graph = 'urn:shacl' AND subject NOT LIKE 'urn:dregs:%'",
            ).fetchall()
            g = _rows_to_rdflib_graph(rows)
        elif what == "all":
            rows = conn.execute(
                "SELECT subject, predicate, object, object_type, datatype, lang FROM triples",
            ).fetchall()
            g = _rows_to_rdflib_graph(rows)
        else:
            raise ValueError(f"Unknown export type: {what}")

        for prefix, ns in self.get_prefixes().items():
            g.bind(prefix, Namespace(ns))
        return g.serialize(format="turtle")

    # -----------------------------------------------------------------
    # Stats
    # -----------------------------------------------------------------

    def stats(self) -> dict:
        """Return database statistics."""
        conn = self._connect()
        data = conn.execute("SELECT COUNT(*) FROM triples WHERE graph = ''").fetchone()[0]
        ont = conn.execute("SELECT COUNT(*) FROM triples WHERE graph = 'urn:ontology'").fetchone()[0]
        shacl = conn.execute("SELECT COUNT(*) FROM triples WHERE graph = 'urn:shacl'").fetchone()[0]
        version = conn.execute("SELECT value FROM metadata WHERE key = 'version'").fetchone()
        created = conn.execute("SELECT value FROM metadata WHERE key = 'created_at'").fetchone()

        topic_count = conn.execute(
            "SELECT COUNT(DISTINCT subject) FROM triples WHERE graph = '' AND predicate = ? AND object = ?",
            (str(RDF.type), "urn:dregs:system#Topic"),
        ).fetchone()[0]

        domain_count = conn.execute(
            "SELECT COUNT(DISTINCT subject) FROM triples WHERE graph = 'urn:ontology' AND predicate = ? AND object = ?",
            (str(RDF.type), "urn:dregs:system#Domain"),
        ).fetchone()[0]

        return {
            "data_triples": data,
            "ontology_triples": ont,
            "shacl_triples": shacl,
            "topics": topic_count,
            "domains": domain_count,
            "version": version[0] if version else "unknown",
            "created_at": created[0] if created else "unknown",
        }

    def get_prefixes(self) -> dict[str, str]:
        """Return prefix -> namespace mapping."""
        conn = self._connect()
        rows = conn.execute("SELECT prefix, namespace FROM prefixes").fetchall()
        return {r[0]: r[1] for r in rows}

    # -----------------------------------------------------------------
    # Domains (urn:ontology graph)
    # -----------------------------------------------------------------

    def create_domain(self, slug: str, label: str, class_uris: list[str]):
        """Create a domain in urn:ontology graph."""
        conn = self._connect()
        domain_uri = f"urn:dregs:domain#{slug}"
        rows = [
            (domain_uri, str(RDF.type), "urn:dregs:system#Domain", "uri", "", "", "urn:ontology"),
            (domain_uri, str(RDFS.label), label, "typed_literal",
             str(URIRef("http://www.w3.org/2001/XMLSchema#string")), "", "urn:ontology"),
        ]
        for cls_uri in class_uris:
            rows.append(
                (domain_uri, "urn:dregs:system#includesClass", cls_uri, "uri", "", "", "urn:ontology"),
            )
        conn.executemany(
            """INSERT OR IGNORE INTO triples
               (subject, predicate, object, object_type, datatype, lang, graph)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        conn.commit()

    def add_to_domain(self, slug: str, class_uris: list[str]):
        """Add classes to an existing domain."""
        conn = self._connect()
        domain_uri = f"urn:dregs:domain#{slug}"
        rows = [
            (domain_uri, "urn:dregs:system#includesClass", cls_uri, "uri", "", "", "urn:ontology")
            for cls_uri in class_uris
        ]
        conn.executemany(
            """INSERT OR IGNORE INTO triples
               (subject, predicate, object, object_type, datatype, lang, graph)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        conn.commit()

    def list_domains(self) -> list[dict]:
        """List all domains."""
        conn = self._connect()
        domain_uris = conn.execute(
            "SELECT DISTINCT subject FROM triples WHERE graph = 'urn:ontology' AND predicate = ? AND object = ?",
            (str(RDF.type), "urn:dregs:system#Domain"),
        ).fetchall()

        domains = []
        for (uri,) in domain_uris:
            label_row = conn.execute(
                "SELECT object FROM triples WHERE graph = 'urn:ontology' AND subject = ? AND predicate = ?",
                (uri, str(RDFS.label)),
            ).fetchone()
            classes = conn.execute(
                "SELECT object FROM triples WHERE graph = 'urn:ontology' AND subject = ? AND predicate = ?",
                (uri, "urn:dregs:system#includesClass"),
            ).fetchall()
            domains.append({
                "uri": uri,
                "slug": uri.split("#")[-1],
                "name": label_row[0] if label_row else uri,
                "classes": [r[0] for r in classes],
            })
        return domains

    # -----------------------------------------------------------------
    # Topics (default data graph)
    # -----------------------------------------------------------------

    def create_topic(self, slug: str, label: str, member_uris: list[str]):
        """Create a topic in default data graph."""
        conn = self._connect()
        topic_uri = f"urn:dregs:topic#{slug}"
        rows = [
            (topic_uri, str(RDF.type), "urn:dregs:system#Topic", "uri", "", "", ""),
            (topic_uri, str(RDFS.label), label, "typed_literal",
             str(URIRef("http://www.w3.org/2001/XMLSchema#string")), "", ""),
        ]
        for member_uri in member_uris:
            rows.append(
                (topic_uri, "urn:dregs:system#member", member_uri, "uri", "", "", ""),
            )
        conn.executemany(
            """INSERT OR IGNORE INTO triples
               (subject, predicate, object, object_type, datatype, lang, graph)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        conn.commit()

    def list_topics(self) -> list[dict]:
        """List all topics."""
        conn = self._connect()
        topic_uris = conn.execute(
            "SELECT DISTINCT subject FROM triples WHERE graph = '' AND predicate = ? AND object = ?",
            (str(RDF.type), "urn:dregs:system#Topic"),
        ).fetchall()

        topics = []
        for (uri,) in topic_uris:
            label_row = conn.execute(
                "SELECT object FROM triples WHERE graph = '' AND subject = ? AND predicate = ?",
                (uri, str(RDFS.label)),
            ).fetchone()
            members = conn.execute(
                "SELECT object FROM triples WHERE graph = '' AND subject = ? AND predicate = ?",
                (uri, "urn:dregs:system#member"),
            ).fetchall()
            topics.append({
                "uri": uri,
                "slug": uri.split("#")[-1],
                "name": label_row[0] if label_row else uri,
                "members": [r[0] for r in members],
            })
        return topics


# === Validation ===


def run_validation(
    schema_graph: Graph,
    data_graph: Graph,
    shacl_graph: Optional[Graph] = None,
    reasoning_regime: str = "owlrl",
    require_provenance: bool = False,
) -> ValidationResult:
    """Full validation pipeline: SHACL -> OWL reasoning -> schema checks."""
    result = ValidationResult()

    combined = Graph()
    for t in schema_graph:
        combined.add(t)
    for t in data_graph:
        combined.add(t)

    result.total_triples_before = len(combined)

    if shacl_graph and len(shacl_graph) > 0:
        result.shacl_conforms, result.shacl_violations = _run_shacl(
            combined, shacl_graph
        )

    result.owl_inferred_triples = _run_owl_reasoning(combined, reasoning_regime)
    result.total_triples_after = len(combined)

    result.schema_violations = _run_schema_checks(
        schema_graph, combined, require_provenance
    )

    result.conforms = result.shacl_conforms and len(result.schema_violations) == 0
    return result


def _run_owl_reasoning(graph: Graph, regime: str = "owlrl") -> int:
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
    violations = []

    schema_classes: set[URIRef] = set()
    for s in schema_graph.subjects(RDF.type, OWL.Class):
        if isinstance(s, URIRef):
            schema_classes.add(s)
    for s in schema_graph.subjects(RDF.type, RDFS.Class):
        if isinstance(s, URIRef):
            schema_classes.add(s)

    parents: set[URIRef] = set()
    for _, _, parent in schema_graph.triples((None, RDFS.subClassOf, None)):
        if isinstance(parent, URIRef):
            parents.add(parent)
    abstract_classes = schema_classes & parents
    leaf_classes = schema_classes - parents

    _SCHEMA_DEF_TYPES = {
        OWL.Class, OWL.ObjectProperty, OWL.DatatypeProperty,
        OWL.AnnotationProperty, OWL.Ontology, RDFS.Class, RDFS.Datatype,
    }
    schema_definitions: set[Node] = set()
    for def_type in _SCHEMA_DEF_TYPES:
        for s in schema_graph.subjects(RDF.type, def_type):
            schema_definitions.add(s)
    instance_subjects = set(combined_graph.subjects()) - schema_definitions

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
