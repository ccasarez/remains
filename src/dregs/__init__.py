"""dregs: SQLite-backed RDF triple store with SPARQL, OWL reasoning, and SHACL validation."""
from dregs.store import DregsStore, run_validation, validate_files
from dregs.sparql import execute_sparql
from dregs.prompt import generate_prompt_context

__version__ = "0.1.0"
__all__ = [
    "DregsStore",
    "run_validation",
    "validate_files",
    "execute_sparql",
    "generate_prompt_context",
]
