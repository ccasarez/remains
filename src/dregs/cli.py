"""CLI for dregs: SQLite-backed RDF triple store."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from dregs.models import ValidationResult
from dregs.store import DregsStore, validate_files


@click.group()
@click.version_option(version="0.1.0")
def cli():
    """dregs: SQLite RDF triple store with SPARQL, OWL reasoning, and SHACL validation.

    \b
    Quick start:
      dregs init my.db --schema ontology.ttl --shacl shapes.ttl
      dregs load my.db data.ttl --graph emails
      dregs query my.db "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 10"
      dregs export my.db --type schema
    """
    pass


@cli.command()
@click.argument("db", type=click.Path(path_type=Path))
@click.option("--schema", "-s", type=click.Path(exists=True, path_type=Path), help="OWL ontology file (.ttl)")
@click.option("--shacl", type=click.Path(exists=True, path_type=Path), help="SHACL shapes file (.ttl)")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def init(db: Path, schema: Path | None, shacl: Path | None, as_json: bool):
    """Initialize a new triple store database.

    \b
    DB  Path to SQLite database (created if not exists)
    """
    store = DregsStore(db)
    try:
        result = store.init(schema_path=schema, shacl_path=shacl)
        if as_json:
            click.echo(json.dumps(result, indent=2))
        else:
            click.echo(f"Initialized {db}")
            if result["schema_triples"]:
                click.echo(f"  Schema: {result['schema_triples']} triples")
            if result["shacl_triples"]:
                click.echo(f"  SHACL:  {result['shacl_triples']} triples")
    finally:
        store.close()


@cli.command()
@click.argument("db", type=click.Path(exists=True, path_type=Path))
@click.argument("data", type=click.Path(exists=True, path_type=Path))
@click.option("--graph", "-g", default=None, help="Named graph label.")
@click.option("--no-validate", is_flag=True, help="Skip validation.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def load(db: Path, data: Path, graph: str | None, no_validate: bool, as_json: bool):
    """Load Turtle data into the store.

    Validates against stored schema/SHACL by default. Rejects invalid data.

    \b
    DB    Path to existing dregs database
    DATA  Turtle file (.ttl) to load
    """
    store = DregsStore(db)
    try:
        result = store.load(data, graph_name=graph, validate=not no_validate)

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
    if source.suffix in (".db", ".sqlite", ".sqlite3"):
        # DB mode
        store = DregsStore(source)
        try:
            conn = store._connect()
            schema_graph = store._load_graphs_by_type(conn, "schema")
            shacl_graph = store._load_graphs_by_type(conn, "shacl")

            from rdflib import Graph
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
@click.argument("db", type=click.Path(exists=True, path_type=Path))
@click.argument("sparql", type=str)
@click.option("--format", "-f", "fmt", type=click.Choice(["table", "json", "turtle"]), default="table", help="Output format.")
@click.option("--graph", "-g", default=None, help="Query specific named graph only.")
def query(db: Path, sparql: str, fmt: str, graph: str | None):
    """Execute a SPARQL query against the store.

    \b
    DB      Path to dregs database
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
@click.argument("db", type=click.Path(exists=True, path_type=Path))
@click.option("--type", "-t", "graph_type", type=click.Choice(["schema", "shacl", "data", "all"]), required=True, help="Type of graph to export.")
@click.option("--graph", "-g", default=None, help="Export specific named graph.")
def export(db: Path, graph_type: str, graph: str | None):
    """Export graphs from the store as Turtle.

    \b
    DB  Path to dregs database
    """
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
@click.argument("source", type=click.Path(exists=True, path_type=Path))
def prompt(source: Path):
    """Generate LLM extraction prompt context from ontology.

    \b
    Two modes:
      dregs prompt my.db            Extract from DB's schema graph
      dregs prompt ontology.ttl     Standalone from file

    \b
    SOURCE  dregs database or OWL ontology file
    """
    from dregs.prompt import prompt_from_file, prompt_from_store

    if source.suffix in (".db", ".sqlite", ".sqlite3"):
        store = DregsStore(source)
        try:
            click.echo(prompt_from_store(store))
        finally:
            store.close()
    else:
        click.echo(prompt_from_file(source))


@cli.command()
@click.argument("db", type=click.Path(exists=True, path_type=Path))
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def info(db: Path, as_json: bool):
    """Show database statistics.

    \b
    DB  Path to dregs database
    """
    store = DregsStore(db)
    try:
        s = store.stats()
        if as_json:
            click.echo(json.dumps(s, indent=2))
        else:
            click.echo(f"Database: {db}")
            click.echo(f"Version:  {s['version']}")
            click.echo(f"Created:  {s['created_at']}")
            click.echo(f"Triples:  {s['total_triples']}")
            click.echo(f"Graphs:   {s['graph_count']}")
            for gtype, counts in s["by_type"].items():
                click.echo(f"  {gtype}: {counts['graphs']} graphs, {counts['triples']} triples")
    finally:
        store.close()


@cli.command()
@click.argument("db", type=click.Path(exists=True, path_type=Path))
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def graphs(db: Path, as_json: bool):
    """List all named graphs in the store.

    \b
    DB  Path to dregs database
    """
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
@click.argument("db", type=click.Path(exists=True, path_type=Path))
@click.option("--graph", "-g", required=True, help="Graph URI to drop.")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def drop(db: Path, graph: str, yes: bool, as_json: bool):
    """Delete a named graph and all its triples.

    \b
    DB  Path to dregs database
    """
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


if __name__ == "__main__":
    cli()
