"""CLI for remains: SQLite-backed RDF triple store."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from remains.models import ValidationResult
from remains.store import RemainsStore


_SQLITE_MAGIC = b"SQLite format 3\x00"

_LOCAL_DB_HINT = (
    "Hint: This database is local to this machine. For cloud sync or sharing,\n"
    "set up Turso embedded replicas:\n"
    "\n"
    "  export REMAINS_DSN=$XDG_DATA_HOME/remains/remains.db\n"
    "  export REMAINS_SYNC_URL=libsql://your-db.turso.io\n"
    "  export REMAINS_AUTH_TOKEN=your-token\n"
    "\n"
    "See remains --help or https://docs.turso.tech for setup.\n"
)


def _open_store(db: Path | None) -> RemainsStore:
    store = RemainsStore(db)
    if store._used_default:
        click.echo(f"Using default database: {store._dsn}", err=True)
        click.echo(_LOCAL_DB_HINT, err=True)
    return store


def _is_sqlite(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(16) == _SQLITE_MAGIC
    except (OSError, IsADirectoryError):
        return False


def _read_turtle(source: str) -> str:
    """Read TTL from a file path or stdin (when source is '-')."""
    if source == "-":
        return sys.stdin.read()
    return Path(source).read_text()


@click.group()
@click.version_option(version="0.2.0")
def cli():
    """remains: SQLite RDF triple store with 3 fixed graphs.

    \b
    Architecture:
      DEFAULT graph  = user data
      urn:ontology   = system ontology + user ontology
      urn:shacl      = system shapes + user shapes

    \b
    Quick start:
      remains init
      remains load-ontology ontology.ttl
      remains load-shacl shapes.ttl
      remains load data.ttl
      remains query "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 10"
      remains prompt

    \b
    Pipe-friendly (use '-' for stdin):
      cat ontology.ttl | remains load-ontology -
      llm extract | remains load -
      remains export | remains load - -d other.db

    \b
    Environment variables:
      REMAINS_DSN         Database file path or libsql:// URL.
      REMAINS_SYNC_URL    Turso cloud URL for embedded replica mode.
      REMAINS_AUTH_TOKEN   Auth token for Turso Cloud.
      REMAINS_VIZ_URL     Base URL for viz. Use {port} as placeholder.
    """
    pass


@cli.command()
@click.option("--db", "-d", type=click.Path(path_type=Path), default=None)
@click.option("--json", "as_json", is_flag=True)
def init(db: Path | None, as_json: bool):
    """Initialize a new triple store database.

    System ontology and shapes are loaded automatically.
    Use 'load-ontology' and 'load-shacl' to add user schemas.
    """
    store = _open_store(db)
    try:
        result = store.init()
        if as_json:
            click.echo(json.dumps(result, indent=2))
        else:
            click.echo(f"Initialized {db or store._dsn}")
            click.echo(f"  System ontology: {result['system_ontology_triples']} triples")
            click.echo(f"  System shapes:   {result['system_shacl_triples']} triples")
    finally:
        store.close()


@cli.command()
@click.argument("data", type=str)
@click.option("--db", "-d", type=click.Path(path_type=Path), default=None)
@click.option("--json", "as_json", is_flag=True)
def load(data: str, db: Path | None, as_json: bool):
    """Load Turtle data into the default graph.

    Validates against ontology and SHACL shapes. Rejects invalid data.
    Pass '-' to read from stdin.
    """
    store = _open_store(db)
    try:
        ttl = _read_turtle(data)
        result = store.load(ttl)

        if not result["loaded"]:
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
                }, indent=2))
            else:
                click.echo(f"Loaded {result['triple_count']} triples")
    finally:
        store.close()


@cli.command()
@click.argument("data", type=str)
@click.option("--db", "-d", type=click.Path(path_type=Path), default=None)
@click.option("--regime", "-r", type=click.Choice(["none", "rdfs", "owlrl", "both"]), default="none")
@click.option("--json", "as_json", is_flag=True)
def check(data: str, db: Path | None, regime: str, as_json: bool):
    """Validate RDF data against the store's ontology and SHACL shapes.

    Same validation pipeline as 'remains load', but does not commit
    anything to the store. The ontology and shapes are always loaded
    from the database (via --db or REMAINS_DSN).
    Pass '-' to read from stdin.
    """
    from rdflib import Graph
    from remains.store import run_validation

    store = _open_store(db)
    try:
        conn = store._connect()
        schema_graph = store._load_graph(conn, "urn:ontology")
        shacl_graph = store._load_graph(conn, "urn:shacl")

        ttl = _read_turtle(data)
        data_graph = Graph()
        data_graph.parse(data=ttl, format="turtle")

        result = run_validation(
            schema_graph=schema_graph,
            data_graph=data_graph,
            shacl_graph=shacl_graph if len(shacl_graph) > 0 else None,
            reasoning_regime=regime,
        )
    finally:
        store.close()

    if as_json:
        click.echo(json.dumps(result.to_dict(), indent=2))
    else:
        click.echo(result.summary())

    sys.exit(0 if result.conforms else 1)


@cli.command()
@click.argument("sparql", type=str)
@click.option("--db", "-d", type=click.Path(path_type=Path), default=None)
@click.option("--format", "-f", "fmt", type=click.Choice(["table", "json", "turtle"]), default="table")
def query(sparql: str, db: Path | None, fmt: str):
    """Execute a SPARQL query against the store."""
    from remains.sparql import execute_sparql

    store = _open_store(db)
    try:
        result = execute_sparql(store, sparql, format=fmt)

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
@click.option("--db", "-d", type=click.Path(path_type=Path), default=None)
@click.option("--what", "-w", type=click.Choice(["data", "ontology", "shacl", "all"]), default="data")
def export(db: Path | None, what: str):
    """Export graphs as Turtle.

    \b
    --what data      Export user data (default graph)
    --what ontology  Export user ontology only (no system)
    --what shacl     Export user shapes only (no system)
    --what all       Export everything
    """
    store = _open_store(db)
    try:
        click.echo(store.export(what))
    finally:
        store.close()


@cli.command()
@click.argument("source", type=str, required=False, default=None)
@click.option("--db", "-d", default=None)
def prompt(source: str | None, db: str | None):
    """Generate LLM extraction prompt context from ontology.

    \b
    Four modes:
      remains prompt                  Use --db or REMAINS_DSN
      remains prompt my.db            Extract from DB's ontology
      remains prompt ontology.ttl     Standalone from file
      remains prompt -                Read TTL from stdin
    """
    from remains.prompt import prompt_from_file, prompt_from_store

    if source == "-":
        ttl = sys.stdin.read()
        click.echo(prompt_from_file(ttl))
    elif source is not None and not _is_sqlite(Path(source)):
        click.echo(prompt_from_file(Path(source)))
    else:
        store = RemainsStore(source or db)
        try:
            click.echo(prompt_from_store(store))
        finally:
            store.close()


@cli.command()
@click.option("--db", "-d", type=click.Path(path_type=Path), default=None)
@click.option("--json", "as_json", is_flag=True)
def info(db: Path | None, as_json: bool):
    """Show database statistics."""
    store = _open_store(db)
    try:
        s = store.stats()
        if as_json:
            click.echo(json.dumps(s, indent=2))
        else:
            click.echo(f"Database:  {db or store._dsn}")
            click.echo(f"Version:   {s['version']}")
            click.echo(f"Created:   {s['created_at']}")
            click.echo(f"Data:      {s['data_triples']} triples")
            click.echo(f"Ontology:  {s['ontology_triples']} triples")
            click.echo(f"SHACL:     {s['shacl_triples']} triples")
    finally:
        store.close()


@cli.command("load-ontology")
@click.argument("ontology", type=str)
@click.option("--db", "-d", type=click.Path(path_type=Path), default=None)
def load_ontology(ontology: str, db: Path | None):
    """Replace user ontology. System ontology is protected.

    Pass '-' to read from stdin.
    """
    store = _open_store(db)
    try:
        ttl = _read_turtle(ontology)
        count = store.update_ontology(ttl)
        click.echo(f"Loaded user ontology: {count} triples")
    finally:
        store.close()


@cli.command("load-shacl")
@click.argument("shacl", type=str)
@click.option("--db", "-d", type=click.Path(path_type=Path), default=None)
def load_shacl(shacl: str, db: Path | None):
    """Replace user SHACL shapes. System shapes are protected.

    Pass '-' to read from stdin.
    """
    store = _open_store(db)
    try:
        ttl = _read_turtle(shacl)
        count = store.update_shacl(ttl)
        click.echo(f"Loaded user shapes: {count} triples")
    finally:
        store.close()


@cli.command()
@click.option("--db", "-d", type=click.Path(path_type=Path), default=None)
@click.option("--port", "-p", type=int, default=7171)
@click.option("--no-open", is_flag=True)
@click.option(
    "--output", "-o",
    type=click.Path(path_type=Path),
    default=None,
    help="Export a self-contained static HTML file instead of starting the server.",
)
@click.option(
    "--query", "-q", "query_str",
    type=str,
    default=None,
    help="SPARQL CONSTRUCT selecting the subgraph to visualize. "
         "If omitted, the full store is visualized.",
)
@click.option(
    "--focus",
    type=str,
    default=None,
    help="Focus on the N-hop neighborhood of this URI (sugar for a "
         "common CONSTRUCT pattern). Mutually exclusive with --query.",
)
@click.option(
    "--hops",
    type=int,
    default=1,
    help="Number of hops for --focus (default: 1).",
)
def viz(
    db: Path | None,
    port: int,
    no_open: bool,
    output: Path | None,
    query_str: str | None,
    focus: str | None,
    hops: int,
):
    """Launch interactive knowledge graph visualizer.

    \b
    Two modes:
      remains viz -d my.db                       Live server (default)
      remains viz -d my.db -o graph.html         Static HTML export

    \b
    Scoping the visualization:
      --query "CONSTRUCT { ?s ?p ?o } WHERE { ... }"
          Visualize only the subgraph returned by the CONSTRUCT.
      --focus <uri> [--hops N]
          Visualize the N-hop neighborhood around a URI.
    """
    from remains.viz import (
        serve_viz,
        export_viz_html,
        _run_construct_query,
        _focus_subgraph,
    )

    if query_str and focus:
        click.echo("Error: --query and --focus are mutually exclusive.", err=True)
        sys.exit(2)
    if hops < 1:
        click.echo("Error: --hops must be >= 1.", err=True)
        sys.exit(2)

    import os
    base_url = os.environ.get("REMAINS_VIZ_URL")
    if base_url and "{port}" in base_url:
        base_url = base_url.replace("{port}", str(port))
    store = _open_store(db)
    try:
        subgraph = None
        if query_str:
            try:
                subgraph = _run_construct_query(store, query_str)
            except Exception as e:
                click.echo(f"Error running --query: {e}", err=True)
                sys.exit(1)
            if len(subgraph) == 0:
                click.echo(
                    "Warning: --query returned no triples; "
                    "visualization will be empty.",
                    err=True,
                )
        elif focus:
            try:
                subgraph = _focus_subgraph(store, focus, hops)
            except Exception as e:
                click.echo(f"Error building --focus subgraph: {e}", err=True)
                sys.exit(1)
            if len(subgraph) == 0:
                click.echo(
                    f"Warning: no triples found within {hops} hop(s) of {focus}.",
                    err=True,
                )

        if output:
            export_viz_html(store, output, subgraph=subgraph)
            click.echo(f"Wrote {output}")
        else:
            serve_viz(
                store,
                port=port,
                open_browser=not no_open,
                base_url=base_url,
                subgraph=subgraph,
            )
    finally:
        store.close()


@cli.command()
@click.argument("annotation_type", type=click.Choice([
    "label-community", "label-node", "highlight-nodes",
    "highlight-community", "toast", "clear",
]))
@click.option("--port", "-p", type=int, default=7171)
@click.option("--text", "-t", default=None)
@click.option("--community", "-c", type=int, default=None)
@click.option("--node", "-n", multiple=True)
@click.option("--color", default=None)
@click.option("--duration", type=int, default=5)
@click.option("--neighbors/--no-neighbors", default=False)
@click.option("--host", default="localhost")
def annotate(annotation_type, port, text, community, node, color, duration, neighbors, host):
    """Send annotations to a running remains viz server."""
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
        click.echo("Is 'remains viz' running?")
        sys.exit(1)


if __name__ == "__main__":
    cli()
