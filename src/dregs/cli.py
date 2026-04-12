"""CLI for dregs: SQLite-backed RDF triple store."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from dregs.models import ValidationResult
from dregs.store import DregsStore, validate_files


_SQLITE_MAGIC = b"SQLite format 3\x00"


def _is_sqlite(path: Path) -> bool:
    """Detect SQLite files by magic bytes instead of file extension."""
    try:
        with open(path, "rb") as f:
            return f.read(16) == _SQLITE_MAGIC
    except (OSError, IsADirectoryError):
        return False


@click.group()
@click.version_option(version="0.1.0")
def cli():
    """dregs: SQLite RDF triple store with SPARQL, OWL reasoning, and SHACL validation.

    \b
    Quick start:
      dregs init --db my.db --schema ontology.ttl --shacl shapes.ttl
      dregs load data.ttl --db my.db --graph emails
      dregs query "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 10" --db my.db
      dregs export --db my.db --type schema

    Set DREGS_DSN to skip --db on every command.
    """
    pass


@cli.command()
@click.option("--db", "-d", type=click.Path(path_type=Path), default=None, help="Path or URL to database (or set DREGS_DSN).")
@click.option("--schema", "-s", type=click.Path(exists=True, path_type=Path), help="OWL ontology file (.ttl)")
@click.option("--shacl", type=click.Path(exists=True, path_type=Path), help="SHACL shapes file (.ttl)")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def init(db: Path | None, schema: Path | None, shacl: Path | None, as_json: bool):
    """Initialize a new triple store database."""
    store = DregsStore(db)
    try:
        result = store.init(schema_path=schema, shacl_path=shacl)
        if as_json:
            click.echo(json.dumps(result, indent=2))
        else:
            click.echo(f"Initialized {db or store._dsn}")
            if result["schema_triples"]:
                click.echo(f"  Schema: {result['schema_triples']} triples")
            if result["shacl_triples"]:
                click.echo(f"  SHACL:  {result['shacl_triples']} triples")
    finally:
        store.close()


@cli.command()
@click.argument("data", type=click.Path(exists=True, path_type=Path))
@click.option("--db", "-d", type=click.Path(path_type=Path), default=None, help="Path or URL to database (or set DREGS_DSN).")
@click.option("--graph", "-g", default=None, help="Named graph label.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def load(data: Path, db: Path | None, graph: str | None, as_json: bool):
    """Load Turtle data into the store.

    Always validates against stored schema/SHACL. Rejects invalid data.

    \b
    DATA  Turtle file (.ttl) to load
    """
    store = DregsStore(db)
    try:
        result = store.load(data, graph_name=graph)

        if not result["loaded"]:
            # Validation failed
            vr: ValidationResult = result["validation"]
            if as_json:
                click.echo(json.dumps(vr.to_dict(), indent=2))
            else:
                click.echo(vr.summary())
            sys.exit(1)
        else:
            if as_json:
                click.echo(json.dumps({
                    "loaded": True,
                    "triple_count": result["triple_count"],
                    "graph": result["graph"],
                }, indent=2))
            else:
                click.echo(f"Loaded {result['triple_count']} triples into graph '{result['graph']}'")
    finally:
        store.close()


@cli.command()
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.argument("data", type=click.Path(exists=True, path_type=Path))
@click.option("--shacl", "-s", type=click.Path(exists=True, path_type=Path), help="SHACL shapes file.")
@click.option("--regime", "-r", type=click.Choice(["owlrl", "rdfs", "both"]), default="owlrl", help="Reasoning regime.")
@click.option("--require-provenance", "-p", is_flag=True, help="Require prov:wasDerivedFrom.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def check(
    source: Path,
    data: Path,
    shacl: Path | None,
    regime: str,
    require_provenance: bool,
    as_json: bool,
):
    """Validate RDF data against an ontology or dregs database.

    \b
    Two modes:
      dregs check my.db data.ttl           Validate against DB's schema/SHACL
      dregs check ontology.ttl data.ttl    Standalone validation (no DB)

    \b
    SOURCE  dregs database (.db/.sqlite) or OWL ontology (.ttl)
    DATA    Turtle file to validate
    """
    # Detect mode: is SOURCE a database or a TTL file?
    if _is_sqlite(source):
        # DB mode
        store = DregsStore(source)
        try:
            conn = store._connect()
            schema_graph = store._load_graphs_by_type(conn, "schema")

            # --shacl flag overrides DB shapes; fall back to DB shapes
            from rdflib import Graph
            if shacl:
                shacl_graph = Graph()
                shacl_graph.parse(str(shacl), format="turtle")
            else:
                shacl_graph = store._load_graphs_by_type(conn, "shacl")

            data_graph = Graph()
            data_graph.parse(str(data), format="turtle")

            from dregs.store import run_validation
            result = run_validation(
                schema_graph=schema_graph,
                data_graph=data_graph,
                shacl_graph=shacl_graph if len(shacl_graph) > 0 else None,
                reasoning_regime=regime,
                require_provenance=require_provenance,
            )
        finally:
            store.close()
    else:
        # Standalone mode
        result = validate_files(
            ontology_path=source,
            data_path=data,
            shacl_path=shacl,
            reasoning_regime=regime,
            require_provenance=require_provenance,
        )

    if as_json:
        click.echo(json.dumps(result.to_dict(), indent=2))
    else:
        click.echo(result.summary())

    sys.exit(0 if result.conforms else 1)


@cli.command()
@click.argument("sparql", type=str)
@click.option("--db", "-d", type=click.Path(path_type=Path), default=None, help="Path or URL to database (or set DREGS_DSN).")
@click.option("--format", "-f", "fmt", type=click.Choice(["table", "json", "turtle"]), default="table", help="Output format.")
@click.option("--graph", "-g", default=None, help="Query specific named graph only.")
def query(sparql: str, db: Path | None, fmt: str, graph: str | None):
    """Execute a SPARQL query against the store.

    \b
    SPARQL  SPARQL query string
    """
    from dregs.sparql import execute_sparql

    store = DregsStore(db)
    try:
        result = execute_sparql(store, sparql, graph_uri=graph, format=fmt)

        if fmt == "json":
            click.echo(json.dumps(result.to_dict(), indent=2))
        elif fmt == "turtle":
            if result.graph_serialization:
                click.echo(result.graph_serialization)
            else:
                click.echo("(CONSTRUCT/DESCRIBE query returned no triples)")
        else:
            click.echo(result.to_table())
    finally:
        store.close()


@cli.command()
@click.option("--db", "-d", type=click.Path(path_type=Path), default=None, help="Path or URL to database (or set DREGS_DSN).")
@click.option("--type", "-t", "graph_type", type=click.Choice(["schema", "shacl", "data", "all"]), required=True, help="Type of graph to export.")
@click.option("--graph", "-g", default=None, help="Export specific named graph.")
def export(db: Path | None, graph_type: str, graph: str | None):
    """Export graphs from the store as Turtle."""
    store = DregsStore(db)
    try:
        if graph:
            click.echo(store.export_graph(graph))
        elif graph_type == "all":
            # Export everything
            from rdflib import Graph as RGraph, Namespace
            g = store.load_all_graphs()
            for prefix, ns in store.get_prefixes().items():
                g.bind(prefix, Namespace(ns))
            click.echo(g.serialize(format="turtle"))
        else:
            click.echo(store.export_by_type(graph_type))
    finally:
        store.close()


@cli.command()
@click.argument("source", type=click.Path(exists=True, path_type=Path), required=False, default=None)
@click.option("--db", "-d", default=None, help="Path or URL to database (or set DREGS_DSN).")
def prompt(source: Path | None, db: str | None):
    """Generate LLM extraction prompt context from ontology.

    \b
    Three modes:
      dregs prompt                  Use --db or DREGS_DSN
      dregs prompt my.db            Extract from DB's schema graph
      dregs prompt ontology.ttl     Standalone from file

    \b
    SOURCE  dregs database or OWL ontology file (optional if --db / DREGS_DSN set)
    """
    from dregs.prompt import prompt_from_file, prompt_from_store

    if source is not None and not _is_sqlite(source):
        # Standalone file mode
        click.echo(prompt_from_file(source))
    else:
        # DB mode: use explicit source, --db, or DREGS_DSN
        store = DregsStore(source or db)
        try:
            click.echo(prompt_from_store(store))
        finally:
            store.close()


@cli.command()
@click.option("--db", "-d", type=click.Path(path_type=Path), default=None, help="Path or URL to database (or set DREGS_DSN).")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def info(db: Path | None, as_json: bool):
    """Show database statistics."""
    store = DregsStore(db)
    try:
        s = store.stats()
        if as_json:
            click.echo(json.dumps(s, indent=2))
        else:
            click.echo(f"Database: {db or store._dsn}")
            click.echo(f"Version:  {s['version']}")
            click.echo(f"Created:  {s['created_at']}")
            click.echo(f"Triples:  {s['total_triples']}")
            click.echo(f"Graphs:   {s['graph_count']}")
            for gtype, counts in s["by_type"].items():
                click.echo(f"  {gtype}: {counts['graphs']} graphs, {counts['triples']} triples")
    finally:
        store.close()


@cli.command()
@click.option("--db", "-d", type=click.Path(path_type=Path), default=None, help="Path or URL to database (or set DREGS_DSN).")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def graphs(db: Path | None, as_json: bool):
    """List all named graphs in the store."""
    store = DregsStore(db)
    try:
        graph_list = store.list_graphs()
        if as_json:
            click.echo(json.dumps([{
                "uri": g.uri, "label": g.label, "type": g.graph_type,
                "source": g.source_file, "triples": g.triple_count,
            } for g in graph_list], indent=2))
        else:
            if not graph_list:
                click.echo("(no graphs)")
            else:
                for g in graph_list:
                    click.echo(f"  {g.uri}  [{g.graph_type}]  {g.triple_count} triples  ({g.label})")
    finally:
        store.close()


@cli.command()
@click.option("--db", "-d", type=click.Path(path_type=Path), default=None, help="Path or URL to database (or set DREGS_DSN).")
@click.option("--graph", "-g", required=True, help="Graph URI to drop.")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def drop(db: Path | None, graph: str, yes: bool, as_json: bool):
    """Delete a named graph and all its triples."""
    if not yes:
        click.confirm(f"Drop graph '{graph}' and all its triples?", abort=True)

    store = DregsStore(db)
    try:
        count = store.drop_graph(graph)
        if as_json:
            click.echo(json.dumps({"dropped": graph, "triples_deleted": count}))
        else:
            click.echo(f"Dropped '{graph}': {count} triples deleted")
    finally:
        store.close()


@cli.command()
@click.option("--db", "-d", type=click.Path(path_type=Path), default=None, help="Path or URL to database (or set DREGS_DSN).")
@click.option("--port", "-p", type=int, default=7171, help="Port to serve on.")
@click.option("--graph", "-g", default=None, help="Visualize specific named graph only.")
@click.option("--no-open", is_flag=True, help="Don't auto-open browser.")
def viz(db: Path | None, port: int, graph: str | None, no_open: bool):
    """Launch interactive knowledge graph visualizer.

    Opens a force-directed graph in your browser showing all entities
    and their relationships. Hover to highlight connections, click for
    details, search to filter, drag to rearrange.

    \b
    Keys:
      /       Focus search
      Escape  Clear search & info panel
      Scroll  Zoom in/out
      Drag    Pan (background) or move node
    """
    from dregs.viz import serve_viz

    store = DregsStore(db)
    try:
        serve_viz(store, port=port, graph_uri=graph, open_browser=not no_open)
    finally:
        store.close()


@cli.command()
@click.argument("annotation_type", type=click.Choice([
    "label-community", "label-node", "highlight-nodes",
    "highlight-community", "toast", "clear",
]))
@click.option("--port", "-p", type=int, default=7171, help="Viz server port.")
@click.option("--text", "-t", default=None, help="Annotation text.")
@click.option("--community", "-c", type=int, default=None, help="Community ID.")
@click.option("--node", "-n", multiple=True, help="Node ID or label (repeatable).")
@click.option("--color", default=None, help="Color (hex).")
@click.option("--duration", type=int, default=5, help="Toast duration (seconds).")
@click.option("--neighbors/--no-neighbors", default=False, help="Show neighbors when highlighting.")
@click.option("--host", default="localhost", help="Viz server host.")
def annotate(
    annotation_type: str,
    port: int,
    text: str | None,
    community: int | None,
    node: tuple[str, ...],
    color: str | None,
    duration: int,
    neighbors: bool,
    host: str,
):
    """Send annotations to a running dregs viz server.

    The viz server receives annotations via SSE and renders them
    in real-time on the graph. Use this to narrate, highlight,
    and annotate the graph from scripts or agents.

    \b
    Annotation types:
      label-community      Add text label at community centroid
      label-node           Add text callout above a node
      highlight-nodes      Highlight specific nodes, dim others
      highlight-community  Highlight a community, dim others
      toast                Show a centered message overlay
      clear                Remove all annotations, reset view

    \b
    Examples:
      dregs annotate toast -t "Welcome to the NRC knowledge graph"
      dregs annotate label-community -c 0 -t "Commissioners"
      dregs annotate highlight-nodes -n "Bradley R. Crowell" -n "Annie Caputo"
      dregs annotate highlight-community -c 2
      dregs annotate label-node -n "Affirmation Session" -t "Bridge node (BC=0.37)"
      dregs annotate clear
    """
    import urllib.request
    import urllib.error

    annotation = {"type": annotation_type}
    if text:
        annotation["text"] = text
    if community is not None:
        annotation["community"] = community
    if node:
        if annotation_type == "label-node":
            annotation["node"] = node[0]
        else:
            annotation["nodes"] = list(node)
    if color:
        annotation["color"] = color
    if duration != 5:
        annotation["duration"] = duration
    if neighbors:
        annotation["showNeighbors"] = True

    url = f"http://{host}:{port}/api/annotate"
    data = json.dumps(annotation).encode("utf-8")

    try:
        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=5)
        result = json.loads(resp.read())
        if result.get("ok"):
            click.echo(f"Sent {annotation_type} to {result.get('clients', 0)} client(s)")
        else:
            click.echo(f"Error: {result}")
            sys.exit(1)
    except urllib.error.URLError as e:
        click.echo(f"Cannot reach viz server at {url}: {e}")
        click.echo("Is 'dregs viz' running?")
        sys.exit(1)


if __name__ == "__main__":
    cli()
