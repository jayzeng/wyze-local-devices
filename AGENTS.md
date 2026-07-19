# Repository Guidelines

## Project Structure & Module Organization

This repository is a compact Python CLI package for discovering and controlling local Wyze devices.

- `wyze_devices.py` contains the CLI entry point, device cache logic, Wyze SDK integration, and skill install/uninstall commands.
- `test_wyze_devices.py` contains the `unittest` test suite with fake Wyze clients and devices.
- `skills/wyze-local-devices/` contains the bundled Codex/OpenAI agent skill and metadata.
- `README.md`, `CONTRIBUTING.md`, and `SECURITY.md` document user workflows, contributor checks, and credential handling.
- `.env.example` shows supported environment variables; never commit a real `.env` or SQLite discovery cache.

## Build, Test, and Development Commands

- `uv sync --extra dev` installs runtime and development dependencies.
- `uv run --script wyze_devices.py --help` runs the standalone script with inline `uv` metadata.
- `uv run --script wyze_devices.py list --all --json` lists devices as JSON; requires valid Wyze credentials.
- `uv run ruff format --check .` verifies formatting.
- `uv run ruff check .` runs Ruff lint rules.
- `uv run mypy wyze_devices.py test_wyze_devices.py` runs static typing checks.
- `uv run python -m unittest` runs the full test suite.

## Coding Style & Naming Conventions

Use Python 3.12-compatible code. Ruff is configured for a 120-character line length and rules `E`, `F`, `I`, `UP`, `B`, and `SIM`. Keep functions typed; mypy is configured with `disallow_untyped_defs = true`. Use `snake_case` for functions, variables, and test methods, `UPPER_SNAKE_CASE` for constants, and descriptive argparse option names that match README examples.

## Testing Guidelines

Follow test-driven development for behavior changes: write or update a focused failing unit test first, implement the smallest code change that makes it pass, then refactor with the test still green. Tests use the standard library `unittest` framework. Add tests near related behavior in `test_wyze_devices.py`, preferably with focused fake clients instead of live Wyze API calls. Name tests `test_<behavior>`.

Every change that touches Python behavior, CLI output, packaging, or bundled skill metadata must include relevant unit test coverage. Before handing work back or opening a pull request, run the full local checks from `CONTRIBUTING.md` and ensure they pass:

- `uv run ruff format --check .`
- `uv run ruff check .`
- `uv run mypy wyze_devices.py test_wyze_devices.py`
- `uv run python -m unittest`
- `uv build`

GitHub CI must also pass before merging. Do not mark a change complete when required local checks or GitHub checks are failing; either fix the failure or document the blocker clearly.

## Commit & Pull Request Guidelines

Recent history uses conventional-style commit prefixes such as `fix:`, `ci:`, and `chore:`. Keep commits scoped and imperative, for example `fix: handle token-only credentials`. Pull requests should include a concise behavior summary, the unit tests added or updated, the commands run for validation, linked issues when relevant, and screenshots or terminal snippets only when they clarify CLI output or skill behavior.

## Security & Configuration Tips

This project can read Wyze account credentials and control devices. Keep secrets in environment variables or a local `.env`; do not commit credentials, tokens, logs containing secrets, or local cache databases. Use `--json` for automation, and avoid adding personal device names, MAC addresses, paths, or home details to the bundled skill.
