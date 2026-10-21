# Contributing

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
ruff check . && ruff format --check . && mypy && pytest
```

- steep has no runtime dependencies; please keep it that way.
- Tests never touch the real registries: `tests/conftest.py` starts a local HTTP server and
  points steep at it via the `STEEP_*_URL` variables. Add a route there for new behaviour.
- New lockfile format: add a parser to `src/steep/lockfiles.py`, register it in `PARSERS`,
  and add a test in `tests/test_lockfiles.py`.
- New ecosystem: subclass `Registry` in `src/steep/registries.py` and add it to `build_registries`.
