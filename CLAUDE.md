# CLAUDE.md

## Running Tests

Install the project with test dependencies:

```
pip install -e ".[test]"
```

Run all tests:

```
python -m pytest tests/ -v
```

Run only local tests (no remote database required):

```
python -m pytest tests/ -v --ignore=tests/test_turso_remote.py
```

Note: `test_turso_remote.py` requires a live Turso database connection and will fail without network access.
