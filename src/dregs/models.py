"""Data models for dregs."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Triple:
    """A single RDF triple with graph membership."""
    subject: str
    predicate: str
    object: str
    object_type: str  # uri, literal, typed_literal, lang_literal
    datatype: Optional[str] = None
    lang: Optional[str] = None
    graph: str = "urn:dregs:data"



@dataclass
class ValidationResult:
    """Result of a validation run."""
    conforms: bool = True
    owl_inferred_triples: int = 0
    shacl_conforms: bool = True
    shacl_violations: list[str] = field(default_factory=list)
    schema_violations: list[str] = field(default_factory=list)
    total_triples_before: int = 0
    total_triples_after: int = 0

    def summary(self) -> str:
        lines = [
            "=== dregs check ===",
            f"Triples before reasoning: {self.total_triples_before}",
            f"Triples after reasoning:  {self.total_triples_after}",
            f"Inferred triples:         {self.owl_inferred_triples}",
            f"SHACL conforms:           {self.shacl_conforms}",
            f"SHACL violations:         {len(self.shacl_violations)}",
            f"Schema violations:        {len(self.schema_violations)}",
            f"Overall:                  {'PASS' if self.conforms else 'FAIL'}",
        ]
        if self.shacl_violations:
            lines.append("\n--- SHACL Violations ---")
            for v in self.shacl_violations:
                lines.append(f"  - {v}")
        if self.schema_violations:
            lines.append("\n--- Schema Violations ---")
            for v in self.schema_violations:
                lines.append(f"  - {v}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "conforms": self.conforms,
            "owl_inferred_triples": self.owl_inferred_triples,
            "shacl_conforms": self.shacl_conforms,
            "shacl_violations": self.shacl_violations,
            "schema_violations": self.schema_violations,
            "triples_before": self.total_triples_before,
            "triples_after": self.total_triples_after,
        }


@dataclass
class QueryResult:
    """Result of a SPARQL query."""
    variables: list[str] = field(default_factory=list)
    bindings: list[dict[str, str]] = field(default_factory=list)
    graph_serialization: Optional[str] = None  # for CONSTRUCT queries

    def to_table(self) -> str:
        if self.graph_serialization:
            return self.graph_serialization
        if not self.bindings:
            return "(no results)"

        # Calculate column widths
        widths = {v: len(v) for v in self.variables}
        for row in self.bindings:
            for v in self.variables:
                val = str(row.get(v, ""))
                widths[v] = max(widths[v], len(val))

        # Header
        header = " | ".join(v.ljust(widths[v]) for v in self.variables)
        sep = "-+-".join("-" * widths[v] for v in self.variables)
        lines = [header, sep]

        # Rows
        for row in self.bindings:
            line = " | ".join(
                str(row.get(v, "")).ljust(widths[v]) for v in self.variables
            )
            lines.append(line)

        lines.append(f"\n({len(self.bindings)} results)")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "variables": self.variables,
            "bindings": self.bindings,
            "count": len(self.bindings),
        }
