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
uv build
```

After building, smoke test the installed wheel when changing packaging,
entry points, or bundled skill files:

```bash
python -m venv /tmp/wyze-local-devices-smoke
/tmp/wyze-local-devices-smoke/bin/python -m pip install --no-deps dist/wyze_local_devices-0.1.0-py3-none-any.whl
/tmp/wyze-local-devices-smoke/bin/wyze-local-devices --help
/tmp/wyze-local-devices-smoke/bin/wyze-local-devices skill --json
```

Do not commit real Wyze credentials, `.env` files, or local SQLite discovery caches.
