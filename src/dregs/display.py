"""Display name resolution using standard property fallback."""
from __future__ import annotations

DISPLAY_PROPERTIES = [
    "http://www.w3.org/2000/01/rdf-schema#label",
    "http://www.w3.org/2004/02/skos/core#prefLabel",
    "http://schema.org/name",
    "http://xmlns.com/foaf/0.1/name",
    "http://purl.org/dc/terms/title",
]


def get_display_name(node_uri: str, store) -> str:
    """Get human-readable name for a node using standard property fallback.

    Tries rdfs:label, skos:prefLabel, schema:name, foaf:name, dcterms:title
    in order. Falls back to URI fragment or last path segment.
    """
    conn = store._connect()
    for prop in DISPLAY_PROPERTIES:
        row = conn.execute(
            "SELECT object FROM triples WHERE subject = ? AND predicate = ? LIMIT 1",
            (node_uri, prop),
        ).fetchone()
        if row:
            return row[0]

    # Fallback: URI fragment
    if "#" in node_uri:
        return node_uri.split("#")[-1]
    # Fallback: last path segment
    if "/" in node_uri:
        return node_uri.split("/")[-1]
    return node_uri
