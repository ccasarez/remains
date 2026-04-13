"""remains: SQLite-backed RDF triple store with SPARQL, OWL reasoning, and SHACL validation."""
from remains.store import RemainsStore, run_validation, validate_files
from remains.sparql import execute_sparql
from remains.prompt import prompt_from_store, prompt_from_file
from remains.display import get_display_name

__version__ = "0.2.0"
__all__ = [
    "RemainsStore",
    "run_validation",
    "validate_files",
    "execute_sparql",
    "prompt_from_store",
    "prompt_from_file",
    "get_display_name",
]
