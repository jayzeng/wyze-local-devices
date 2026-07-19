# Wyze local devices

[![CI](https://github.com/jayzeng/wyze-local-devices/actions/workflows/ci.yml/badge.svg)](https://github.com/jayzeng/wyze-local-devices/actions/workflows/ci.yml)
[![CodeQL](https://github.com/jayzeng/wyze-local-devices/actions/workflows/codeql.yml/badge.svg)](https://github.com/jayzeng/wyze-local-devices/actions/workflows/codeql.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Lists, caches, looks up, and controls Wyze devices using
[`wyze-sdk`](https://github.com/shauntarves/wyze-sdk), from either a standalone
script or the installed `wyze-local-devices` command.

## Features

- List online Wyze devices by default, or include offline devices with `--all`.
- Cache device discovery results to SQLite for fast local lookup.
- Look up cached devices by nickname, MAC, type, or model.
- Auto-refresh stale or missing discovery cache entries before lookup.
- Turn matching Wyze plugs, bulbs, and cameras on or off.
- Skip parent outdoor-plug controllers so individual child outlets can be controlled separately.
- Set matching Wyze light brightness, color temperature, and RGB color.
- Adjust Wyze light brightness relative to the current value with configurable step and clamps.
- Verify plug and bulb state after commands when the Wyze API exposes it.
- Retry live commands with discovered `certifi` CA bundles when local certificate validation fails.
- Bundle an installable Codex/OpenAI agent skill for generic outdoor-light workflows.
- Emit stable JSON for automation and agent workflows.

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
uv run --script wyze_devices.py skill --uninstall
uv run --script wyze_devices.py lookup camera
uv run --script wyze_devices.py control "desk plug" off
uv run --script wyze_devices.py adjust-light "corner" brighter --step 20 --verify --json
uv run --script wyze_devices.py set-light "corner" --brightness 70 --temperature 3500
uv run --script wyze_devices.py set-light "corner" --color ff8800 --verify --json
uv run --script wyze_devices.py control "entry camera" on --json
```

On first use, `uv` may resolve/download packages into its cache if they are not
already available locally. After that, it reuses the cache, so later runs do not
repeat the install work.

Python 3.12, 3.13, or 3.14 is supported by this package metadata.

## Install as a CLI

For repeated use on a machine, install the project into an isolated tool
environment:

```bash
uv tool install .
wyze-local-devices --help
wyze-local-devices lookup --json
wyze-local-devices control "desk plug" off --verify --json
```

The installed command bundles the same agent skill as the source checkout under
the package data directory, so `wyze-local-devices skill --install` works after
installation too.

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

Token auth is also supported when you already have Wyze tokens. The access
token is enough to attempt login; include a refresh token when you have one:

```bash
WYZE_ACCESS_TOKEN=your-access-token
WYZE_REFRESH_TOKEN=your-refresh-token
```

`list`, `control`, `set-light`, and `adjust-light` always need Wyze credentials
because they call the live Wyze API. `lookup` uses the local cache without
credentials when the cache is fresh. If the cache is missing, empty, or older
than 30 days, `lookup` refreshes discovery from Wyze first and then returns the
local result.

If the local Python environment cannot validate Wyze's HTTPS certificate chain,
the CLI retries live commands with discovered `certifi` CA bundles and prints
each bundle path to stderr. If those retries fail too, the Wyze SDK error is
reported.

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
python wyze_devices.py skill --uninstall # remove bundled agent skill
python wyze_devices.py lookup camera    # query the local discovery cache
python wyze_devices.py control plug off # turn matching live plugs/cameras off
python wyze_devices.py adjust-light corner brighter --verify
python wyze_devices.py set-light corner --brightness 70
python wyze_devices.py set-light corner --temperature 3500
python wyze_devices.py set-light corner --color ff8800 --verify
python wyze_devices.py --env-file ../.env list
```

The default output is a table of connected/online devices with nickname, online
state, type/model, local IP/SSID/RSSI when Wyze returns those fields, and MAC.

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
`skills/wyze-local-devices/`. The skill does not hard-code personal device
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
`CODEX_HOME` is set, or `~/.codex/skills` otherwise. If the project has been
installed as a package, the command reads the skill from the installed package
data when the source checkout is not present. To install into another agent
skills directory, pass `--destination`:

```bash
uv run --script wyze_devices.py skill --install --destination /path/to/agent/skills
```

Uninstall it from the default Codex skills directory:

```bash
uv run --script wyze_devices.py skill --uninstall
```

Use the same `--destination` value to uninstall from a non-default agent skills
directory:

```bash
uv run --script wyze_devices.py skill --uninstall --destination /path/to/agent/skills
```

After installation, an agent can invoke the `wyze-local-devices` skill for
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

Use `control` to turn matching live Wyze plugs, bulbs, or cameras on or off. The
query is matched case-insensitively against nickname, MAC, type, or model.
Parent controller plugs are skipped because individual outlets are controlled
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

With `--verify`, plug and bulb rows include a `verification` object where the
Wyze API supports a state check. Verification retries up to four times for
`control` commands until the expected power state is observed. Bulb
verification can also include `brightness`, `temperature`, and `color`. Camera
verification is reported as command-sent because the SDK does not expose the
same state check.

## Adjust lights

Use `adjust-light` for relative brightness requests such as "make the corner
lamp brighter" or "dim the patio light." Supported directions are `brighter`,
`dimmer`, `up`, `down`, `increase`, and `decrease`. The command fetches the
current bulb brightness, applies `--step`, clamps the result between
`--min-brightness` and `--max-brightness`, then sets the target brightness.

```bash
python wyze_devices.py adjust-light corner brighter --verify --json
python wyze_devices.py adjust-light corner dimmer --step 15 --verify --json
python wyze_devices.py adjust-light corner increase --step 10 --min-brightness 10 --max-brightness 90
```

If the current brightness cannot be read, `brighter` falls back to the maximum
brightness and `dimmer` falls back to the minimum brightness. The same fallback
direction applies to the aliases: `up` and `increase` use the maximum;
`down` and `decrease` use the minimum.

Use `set-light` when you already know the exact brightness, color temperature,
or RGB color to set. At least one of `--brightness`, `--temperature`, or
`--color` is required, and `--color` accepts either `ff8800` or `#ff8800`:

```bash
python wyze_devices.py set-light corner --brightness 70
python wyze_devices.py set-light corner --temperature 3500
python wyze_devices.py set-light corner --color ff8800 --verify
```

## Tests

```bash
uv run --script wyze_devices.py --help
uv run python -m unittest
```

## Development

```bash
uv sync --extra dev
```

Run the same checks used in CI:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy wyze_devices.py test_wyze_devices.py
uv run python -m unittest
uv build
```

## Security

See [SECURITY.md](SECURITY.md) for vulnerability reporting and credential
handling guidance.

## License

MIT. See [LICENSE](LICENSE).
