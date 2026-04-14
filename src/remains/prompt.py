"""Generate LLM extraction prompt context from ontology + SHACL shapes."""
from __future__ import annotations

from pathlib import Path

from rdflib import Graph, Namespace

PREAMBLE = """\
Use the OWL ontology and SHACL shapes below to extract structured data.
Output valid Turtle (TTL) that conforms to these definitions.
Do NOT invent classes, properties, or shapes beyond what is defined here.
"""


def prompt_from_file(source: Path | str) -> str:
    """Generate prompt context from a Turtle file or TTL string."""
    g = Graph()
    if isinstance(source, Path):
        g.parse(str(source), format="turtle")
    else:
        g.parse(data=source, format="turtle")
    ttl = g.serialize(format="turtle")
    return f"{PREAMBLE}\n{ttl}"


def prompt_from_store(store) -> str:
    """Generate prompt context from a remains store's ontology + shapes."""
    parts = [PREAMBLE]

    ont_ttl = store.export("ontology").strip()
    if ont_ttl:
        parts.append("# --- Ontology ---\n")
        parts.append(ont_ttl)

    shacl_ttl = store.export("shacl").strip()
    if shacl_ttl:
        parts.append("\n# --- SHACL Shapes ---\n")
        parts.append(shacl_ttl)

    return "\n".join(parts)
