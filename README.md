# Wyze local devices

[![CI](https://github.com/jayzeng/wyze-local-devices/actions/workflows/ci.yml/badge.svg)](https://github.com/jayzeng/wyze-local-devices/actions/workflows/ci.yml)
[![CodeQL](https://github.com/jayzeng/wyze-local-devices/actions/workflows/codeql.yml/badge.svg)](https://github.com/jayzeng/wyze-local-devices/actions/workflows/codeql.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Lists connected/online Wyze devices and caches discovered devices using
[`wyze-sdk`](https://github.com/shauntarves/wyze-sdk).

## Features

- List online Wyze devices or include offline devices.
- Cache device discovery results to SQLite for fast local lookup.
- Look up cached devices by nickname, MAC, type, or model.
- Turn matching Wyze plugs and cameras on or off.
- Bundle an installable agent skill for generic outdoor-light workflows.
- Emit JSON for automation and agent workflows.

## Run with uv

Recommended path: run the script with `uv`.

`wyze_devices.py` includes inline dependency metadata, so `uv` can create an
isolated run environment from the script itself. You do not need to create a
virtualenv, activate it, or run `pip install -r requirements.txt` first:

```bash
uv run --script wyze_devices.py --help
uv run --script wyze_devices.py list
uv run --script wyze_devices.py list --all --json
uv run --script wyze_devices.py list --discover
uv run --script wyze_devices.py skill --json
uv run --script wyze_devices.py skill --install
uv run --script wyze_devices.py lookup camera
uv run --script wyze_devices.py control "desk plug" off
uv run --script wyze_devices.py control "entry camera" on --json
```

On first use, `uv` may resolve/download packages into its cache if they are not
already available locally. After that, it reuses the cache, so later runs do not
repeat the install work.

The script auto-loads the nearest `.env` in this folder or any parent folder. It supports these variables:

```bash
WYZE_EMAIL=you@example.com
WYZE_PASSWORD=your-wyze-password
WYZE_KEY_ID=your-wyze-api-key-id
WYZE_API_KEY=your-wyze-api-key
# Optional: WYZE_TOTP_KEY=base32totpsecret
```

Lower-case aliases like `wyze_api_key` are also supported.

Copy `.env.example` to `.env` for a local starting point. Do not commit real
credentials or token values.

Token auth is also supported when you already have Wyze tokens:

```bash
WYZE_ACCESS_TOKEN=your-access-token
WYZE_REFRESH_TOKEN=your-refresh-token
```

`list` and `control` always need Wyze credentials because they call the live
Wyze API. `lookup` only needs credentials when the local discovery cache is
missing, empty, or older than 30 days.

## Run the single CLI

If you already installed dependencies into your active Python environment, you
can also run it with `python`:

```bash
python wyze_devices.py --help
```

Common commands:

```bash
python wyze_devices.py list
python wyze_devices.py list --all       # include offline devices
python wyze_devices.py list --json      # JSON output
python wyze_devices.py list --discover  # save fetched devices to SQLite
python wyze_devices.py skill --json     # print bundled agent skill metadata
python wyze_devices.py skill --install  # install the bundled agent skill
python wyze_devices.py lookup camera    # query the local discovery cache
python wyze_devices.py control plug off # turn matching live plugs/cameras off
python wyze_devices.py --env-file ../.env list
```

The default output is a table of connected/online devices with nickname, type/model, local IP/SSID/RSSI when Wyze returns those fields, and MAC.

Use `--json` when another tool or future skill needs stable machine-readable
output. Device rows may include these fields when Wyze returns them:

```json
{
  "nickname": "Desk plug",
  "mac": "AA:BB:CC:DD:EE:FF",
  "type": "Plug",
  "model": "WLPP1",
  "product_type": "Plug",
  "online": true,
  "ip": "192.168.1.20",
  "ssid": "wifi",
  "rssi": -50,
  "firmware_version": "1.0",
  "hardware_version": "1.0",
  "timezone": "America/Los_Angeles"
}
```

## Agent skill

This repo bundles a generic Codex/OpenAI agent skill at
`skills/wyze-outdoor-lights/`. The skill does not hard-code personal device
names, MAC addresses, paths, or home details. It teaches agents to discover the
current Wyze inventory, identify outdoor-light targets from user-provided or
discovered names, and run the local `wyze_devices.py` CLI with verification.

Show the skill metadata without contacting Wyze:

```bash
uv run --script wyze_devices.py skill --json
```

Install it into the default Codex skills directory:

```bash
uv run --script wyze_devices.py skill --install
```

By default, installation copies the bundled skill to `$CODEX_HOME/skills` when
`CODEX_HOME` is set, or `~/.codex/skills` otherwise. To install into another
agent skills directory, pass `--destination`:

```bash
uv run --script wyze_devices.py skill --install --destination /path/to/agent/skills
```

After installation, an agent can invoke the `wyze-outdoor-lights` skill for
requests such as "turn off the outdoor lights" and should use this repository's
CLI rather than a generic smart-home API.

## Local discovery cache

Use `--discover` with `list` to persist the fetched device inventory into a
local SQLite cache. The visible `list` output still respects filters like the
default online-only view, but discovery stores every device returned by Wyze.
The cache stores normalized device metadata keyed by MAC address, so later
discoveries update existing rows.

```bash
python wyze_devices.py list --all --discover
python wyze_devices.py lookup
python wyze_devices.py lookup plug
python wyze_devices.py lookup --json WYZEC1
```

`lookup` reads the local cache when it is fresh. If the cache is missing, empty,
or older than 30 days, `lookup` first refreshes discovery from Wyze and then
returns the local result. A fresh cache does not require Wyze credentials or an
API call.

By default, the cache is stored in the OS app data directory. Override it with
`--db-file` or `WYZE_DEVICES_DB`:

```bash
python wyze_devices.py --db-file ./devices.sqlite3 list --discover
python wyze_devices.py --db-file ./devices.sqlite3 lookup plug
```

## Control devices

Use `control` to turn matching live Wyze plugs or cameras on or off. The query
is matched case-insensitively against nickname, MAC, type, or model. Parent
controller plugs are skipped because individual outlets are controlled
separately.

```bash
python wyze_devices.py control "desk plug" off
python wyze_devices.py control "entry camera" on --json
python wyze_devices.py control plug off --verify --json
```

`control --json` returns one row per matched live device. Each row includes the
device fields above plus:

```json
{
  "action": "off",
  "status": "turned off plug"
}
```

With `--verify`, plug rows also include a `verification` object with the
post-command `is_on` value when the Wyze API supports it. Camera verification is
reported as command-sent because the SDK does not expose the same state check.

## Tests

```bash
uv run --script wyze_devices.py --help
python -m unittest
```

## Development

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Run the same checks used in CI:

```bash
ruff format --check .
ruff check .
mypy wyze_devices.py test_wyze_devices.py
python -m unittest
```

## Security

See [SECURITY.md](SECURITY.md) for vulnerability reporting and credential
handling guidance.

## License

MIT. See [LICENSE](LICENSE).
