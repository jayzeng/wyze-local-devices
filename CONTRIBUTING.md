# Contributing

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e ".[dev]"
```

## Checks

Run these before opening a pull request:

```bash
ruff format --check .
ruff check .
mypy wyze_devices.py test_wyze_devices.py
python -m unittest
```

Do not commit real Wyze credentials, `.env` files, or local SQLite discovery caches.
