# Contributing

## Local setup

```bash
uv sync --extra dev
```

Use Python 3.12 or 3.13.

## Checks

Run these before opening a pull request:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy wyze_devices.py test_wyze_devices.py
uv run python -m unittest
```

Do not commit real Wyze credentials, `.env` files, or local SQLite discovery caches.
