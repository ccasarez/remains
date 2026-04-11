"""Generate LLM extraction prompt context from OWL ontology."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from rdflib import OWL, RDF, RDFS, Graph, Namespace, URIRef
from rdflib.term import Node

SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")


def _short(uri: Node) -> str:
    s = str(uri)
    if "#" in s:
        return s.split("#")[-1]
    return s.split("/")[-1]


def generate_prompt_context(g: Graph) -> str:
    """Generate structured prompt context from an OWL ontology graph.

    Lists all classes, properties, and skos:example annotations.
    Feed this to an LLM to schema-lock extraction output.
    """
    lines = ["# Ontology Schema for Extraction", ""]
    lines.append("Extract ONLY the following entity types and relationships.")
    lines.append("Do NOT invent new types. Output as Turtle (TTL) format.")
    lines.append("")

    # Classes
    lines.append("## Entity Types")
    for cls in sorted(g.subjects(RDF.type, OWL.Class)):
        if not isinstance(cls, URIRef):
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

    # Object Properties
    lines.append("## Relationships (Object Properties)")
    for prop in sorted(g.subjects(RDF.type, OWL.ObjectProperty)):
        if not isinstance(prop, URIRef):
            continue
        label = g.value(prop, RDFS.label) or _short(prop)
        domain = g.value(prop, RDFS.domain)
        range_ = g.value(prop, RDFS.range)
        d_str = _short(domain) if domain else "?"
        r_str = _short(range_) if range_ else "?"
        lines.append(f"- {label}: {d_str} -> {r_str}")

    lines.append("")

    # Data Properties
    lines.append("## Data Properties")
    for prop in sorted(g.subjects(RDF.type, OWL.DatatypeProperty)):
        if not isinstance(prop, URIRef):
            continue
        label = g.value(prop, RDFS.label) or _short(prop)
        domain = g.value(prop, RDFS.domain)
        range_ = g.value(prop, RDFS.range)
        d_str = _short(domain) if domain else "?"
        r_str = _short(range_) if range_ else "?"
        lines.append(f"- {label}: {d_str} -> {r_str}")

    return "\n".join(lines)


def prompt_from_file(ontology_path: Path) -> str:
    """Generate prompt context from an ontology file."""
    g = Graph()
    g.parse(str(ontology_path), format="turtle")
    return generate_prompt_context(g)


def prompt_from_store(store) -> str:
    """Generate prompt context from a dregs store's schema graph."""
    g = store._load_graphs_by_type(store._connect(), "schema")
    return generate_prompt_context(g)
