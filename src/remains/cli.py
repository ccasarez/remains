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


@click.group()
@click.version_option(version="0.2.0")
def cli():
    """remains: SQLite RDF triple store with 3 fixed graphs.

    \b
    Architecture:
      DEFAULT graph  = user data + topics
      urn:ontology   = system ontology + user ontology
      urn:shacl      = system shapes + user shapes

    \b
    Quick start:
      remains init --ontology ontology.ttl --shacl shapes.ttl
      remains load data.ttl
      remains query "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 10"
      remains prompt
      remains prompt --domain people

    \b
    Multiple domains = multiple databases:
      REMAINS_DSN=meetings.db remains init --ontology meetings.ttl --shacl meetings-shapes.ttl
      REMAINS_DSN=finance.db remains init --ontology finance.ttl --shacl finance-shapes.ttl

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
@click.option("--ontology", type=click.Path(exists=True, path_type=Path), help="OWL ontology file (.ttl)")
@click.option("--shacl", type=click.Path(exists=True, path_type=Path), help="SHACL shapes file (.ttl)")
@click.option("--json", "as_json", is_flag=True)
def init(db: Path | None, ontology: Path | None, shacl: Path | None, as_json: bool):
    """Initialize a new triple store database.

    System ontology and shapes are loaded automatically.
    """
    store = _open_store(db)
    try:
        result = store.init(ontology_path=ontology, shacl_path=shacl)
        if as_json:
            click.echo(json.dumps(result, indent=2))
        else:
            click.echo(f"Initialized {db or store._dsn}")
            click.echo(f"  System ontology: {result['system_ontology_triples']} triples")
            click.echo(f"  User ontology:   {result['user_ontology_triples']} triples")
            click.echo(f"  System shapes:   {result['system_shacl_triples']} triples")
            click.echo(f"  User shapes:     {result['user_shacl_triples']} triples")
    finally:
        store.close()


@cli.command()
@click.argument("data", type=click.Path(exists=True, path_type=Path))
@click.option("--db", "-d", type=click.Path(path_type=Path), default=None)
@click.option("--json", "as_json", is_flag=True)
def load(data: Path, db: Path | None, as_json: bool):
    """Load Turtle data into the default graph.

    Validates against ontology and SHACL shapes. Rejects invalid data.
    """
    store = _open_store(db)
    try:
        result = store.load(data)

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
@click.argument("data", type=click.Path(exists=True, path_type=Path))
@click.option("--db", "-d", type=click.Path(path_type=Path), default=None)
@click.option("--regime", "-r", type=click.Choice(["none", "rdfs", "owlrl", "both"]), default="none")
@click.option("--json", "as_json", is_flag=True)
def check(data: Path, db: Path | None, regime: str, as_json: bool):
    """Validate RDF data against the store's ontology and SHACL shapes.

    Same validation pipeline as 'remains load', but does not commit
    anything to the store. The ontology and shapes are always loaded
    from the database (via --db or REMAINS_DSN).
    """
    from rdflib import Graph
    from remains.store import run_validation

    store = _open_store(db)
    try:
        conn = store._connect()
        schema_graph = store._load_graph(conn, "urn:ontology")
        shacl_graph = store._load_graph(conn, "urn:shacl")

        data_graph = Graph()
        data_graph.parse(str(data), format="turtle")

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
@click.argument("source", type=click.Path(exists=True, path_type=Path), required=False, default=None)
@click.option("--db", "-d", default=None)
@click.option("--domain", default=None, help="Filter prompt to a named domain.")
def prompt(source: Path | None, db: str | None, domain: str | None):
    """Generate LLM extraction prompt context from ontology.

    \b
    Three modes:
      remains prompt                  Use --db or REMAINS_DSN
      remains prompt my.db            Extract from DB's ontology
      remains prompt ontology.ttl     Standalone from file

    \b
    --domain filters to classes in a named domain.
    """
    from remains.prompt import prompt_from_file, prompt_from_store

    if source is not None and not _is_sqlite(source):
        click.echo(prompt_from_file(source))
    else:
        store = RemainsStore(source or db)
        try:
            click.echo(prompt_from_store(store, domain=domain))
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
            click.echo(f"Domains:   {s['domains']}")
            click.echo(f"Topics:    {s['topics']}")
    finally:
        store.close()


@cli.command()
@click.option("--db", "-d", type=click.Path(path_type=Path), default=None)
@click.option("--json", "as_json", is_flag=True)
def domains(db: Path | None, as_json: bool):
    """List all domains."""
    store = _open_store(db)
    try:
        domain_list = store.list_domains()
        if as_json:
            click.echo(json.dumps(domain_list, indent=2))
        else:
            if not domain_list:
                click.echo("(no domains)")
            else:
                for d in domain_list:
                    click.echo(f"  {d['slug']:<20} {len(d['classes'])} classes  \"{d['name']}\"")
    finally:
        store.close()


@cli.command("create-domain")
@click.argument("slug")
@click.option("--name", "-n", required=True)
@click.option("--class", "-c", "classes", multiple=True, required=True, help="Class URI (repeatable)")
@click.option("--db", "-d", type=click.Path(path_type=Path), default=None)
def create_domain(slug: str, name: str, classes: tuple[str, ...], db: Path | None):
    """Create a domain (ontology class grouping for scoped prompts)."""
    store = _open_store(db)
    try:
        store.create_domain(slug, name, list(classes))
        click.echo(f"Created domain '{slug}' with {len(classes)} classes")
    finally:
        store.close()


@cli.command()
@click.option("--db", "-d", type=click.Path(path_type=Path), default=None)
@click.option("--json", "as_json", is_flag=True)
def topics(db: Path | None, as_json: bool):
    """List all topics."""
    store = _open_store(db)
    try:
        topic_list = store.list_topics()
        if as_json:
            click.echo(json.dumps(topic_list, indent=2))
        else:
            if not topic_list:
                click.echo("(no topics)")
            else:
                for t in topic_list:
                    click.echo(f"  {t['slug']:<20} {len(t['members'])} members  \"{t['name']}\"")
    finally:
        store.close()


@cli.command("create-topic")
@click.argument("slug")
@click.option("--name", "-n", required=True)
@click.option("--member", "-m", "members", multiple=True, required=True, help="Member URI (repeatable)")
@click.option("--db", "-d", type=click.Path(path_type=Path), default=None)
def create_topic(slug: str, name: str, members: tuple[str, ...], db: Path | None):
    """Create a topic (data entity grouping)."""
    store = _open_store(db)
    try:
        store.create_topic(slug, name, list(members))
        click.echo(f"Created topic '{slug}' with {len(members)} members")
    finally:
        store.close()


@cli.command("update-ontology")
@click.argument("ontology", type=click.Path(exists=True, path_type=Path))
@click.option("--db", "-d", type=click.Path(path_type=Path), default=None)
def update_ontology(ontology: Path, db: Path | None):
    """Replace user ontology. System ontology is protected."""
    store = _open_store(db)
    try:
        count = store.update_ontology(ontology)
        click.echo(f"Updated user ontology: {count} triples")
    finally:
        store.close()


@cli.command("update-shacl")
@click.argument("shacl", type=click.Path(exists=True, path_type=Path))
@click.option("--db", "-d", type=click.Path(path_type=Path), default=None)
def update_shacl(shacl: Path, db: Path | None):
    """Replace user SHACL shapes. System shapes are protected."""
    store = _open_store(db)
    try:
        count = store.update_shacl(shacl)
        click.echo(f"Updated user shapes: {count} triples")
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
