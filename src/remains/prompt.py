"""Generate LLM extraction prompt context from OWL ontology."""
from __future__ import annotations

from pathlib import Path

from rdflib import OWL, RDF, RDFS, Graph, Namespace, URIRef
from rdflib.term import Node

SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")
SYSTEM_NS = "urn:remains:system#"


def _short(uri: Node) -> str:
    s = str(uri)
    if "#" in s:
        return s.split("#")[-1]
    return s.split("/")[-1]


def prompt_from_file(source: Path | str) -> str:
    """Generate prompt context from an ontology file or TTL string."""
    g = Graph()
    if isinstance(source, Path):
        g.parse(str(source), format="turtle")
    else:
        g.parse(data=source, format="turtle")
    return _generate_prompt(g)


def prompt_from_store(store) -> str:
    """Generate prompt context from a remains store's urn:ontology graph."""
    g = store.load_ontology_graph()
    return _generate_prompt(g)


def _generate_prompt(g: Graph) -> str:
    """Generate prompt excluding system classes."""
    lines = ["# Ontology Schema for Extraction", ""]
    lines.append("Extract ONLY the following entity types and relationships.")
    lines.append("Do NOT invent new types. Output as Turtle (TTL) format.")
    lines.append("")

    # Classes (exclude system)
    lines.append("## Entity Types")
    for cls in sorted(g.subjects(RDF.type, OWL.Class)):
        if not isinstance(cls, URIRef):
            continue
        if str(cls).startswith(SYSTEM_NS):
            continue
        label = g.value(cls, RDFS.label) or _short(cls)
        comment = g.value(cls, RDFS.comment) or ""
        parent = g.value(cls, RDFS.subClassOf)
        parent_str = f" (subclass of {_short(parent)})" if parent else ""

        lines.append(f"### {label}{parent_str}")
        if comment:
            lines.append(f"  Definition: {comment}")

        for ex in g.objects(cls, SKOS.example):
            lines.append(f"  {ex}")
        lines.append("")

    # Object Properties (exclude system)
    lines.append("## Relationships (Object Properties)")
    for prop in sorted(g.subjects(RDF.type, OWL.ObjectProperty)):
        if not isinstance(prop, URIRef):
            continue
        if str(prop).startswith(SYSTEM_NS):
            continue
        label = g.value(prop, RDFS.label) or _short(prop)
        domain_cls = g.value(prop, RDFS.domain)
        range_cls = g.value(prop, RDFS.range)
        d_str = _short(domain_cls) if domain_cls else "?"
        r_str = _short(range_cls) if range_cls else "?"
        lines.append(f"- {label}: {d_str} -> {r_str}")

    lines.append("")

    # Data Properties (exclude system)
    lines.append("## Data Properties")
    for prop in sorted(g.subjects(RDF.type, OWL.DatatypeProperty)):
        if not isinstance(prop, URIRef):
            continue
        if str(prop).startswith(SYSTEM_NS):
            continue
        label = g.value(prop, RDFS.label) or _short(prop)
        domain_cls = g.value(prop, RDFS.domain)
        range_cls = g.value(prop, RDFS.range)
        d_str = _short(domain_cls) if domain_cls else "?"
        r_str = _short(range_cls) if range_cls else "?"
        lines.append(f"- {label}: {d_str} -> {r_str}")

    return "\n".join(lines)
