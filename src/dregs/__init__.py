"""dregs: SQLite-backed RDF triple store with SPARQL, OWL reasoning, and SHACL validation."""
from dregs.store import DregsStore, run_validation, validate_files
from dregs.sparql import execute_sparql
from dregs.prompt import prompt_from_store, prompt_from_file
from dregs.display import get_display_name

__version__ = "0.2.0"
__all__ = [
    "DregsStore",
    "run_validation",
    "validate_files",
    "execute_sparql",
    "prompt_from_store",
    "prompt_from_file",
    "get_display_name",
]
