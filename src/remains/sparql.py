"""SPARQL query execution against the SQLite store."""
from __future__ import annotations

from typing import Optional

from rdflib import Graph, Namespace

from remains.models import QueryResult
from remains.store import RemainsStore


def execute_sparql(
    store: RemainsStore,
    sparql: str,
    format: str = "table",
) -> QueryResult:
    """Execute SPARQL against the store (union of all graphs)."""
    g = store.load_all_graphs()

    # Bind prefixes for nicer output
    prefixes = store.get_prefixes()
    for prefix, ns in prefixes.items():
        g.bind(prefix, Namespace(ns))

    # Detect query type from first non-comment, non-PREFIX line
    sparql_upper = sparql.strip().upper()
    query_type = "select"
    for line in sparql_upper.split("\n"):
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("PREFIX"):
            continue
        if stripped.startswith("CONSTRUCT") or stripped.startswith("DESCRIBE"):
            query_type = "construct"
        elif stripped.startswith("ASK"):
            query_type = "ask"
        break

    result = g.query(sparql)

    if query_type == "construct":
        # CONSTRUCT/DESCRIBE returns a graph
        out_graph = Graph()
        for prefix, ns in prefixes.items():
            out_graph.bind(prefix, Namespace(ns))
        for t in result:
            out_graph.add(t)
        return QueryResult(
            graph_serialization=out_graph.serialize(format="turtle")
        )
    elif query_type == "ask":
        # ASK returns a boolean
        return QueryResult(
            variables=["result"],
            bindings=[{"result": bool(result)}],
        )
    else:
        # SELECT returns bindings
        variables = [str(v) for v in result.vars] if result.vars else []
        bindings = []
        for row in result:
            binding = {}
            for i, var in enumerate(variables):
                val = row[i]
                if val is not None:
                    # Shorten URIs using known prefixes
                    val_str = str(val)
                    for prefix, ns in prefixes.items():
                        if val_str.startswith(ns):
                            val_str = f"{prefix}:{val_str[len(ns):]}"
                            break
                    binding[var] = val_str
                else:
                    binding[var] = ""
            bindings.append(binding)

        return QueryResult(variables=variables, bindings=bindings)
