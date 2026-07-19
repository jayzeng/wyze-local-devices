---
name: wyze-local-devices
description: List Wyze devices and control Wyze outdoor lights from a local wyze-local-devices repo. Use when the user asks to list Wyze devices, control outside/outdoor Wyze lights, outdoor plugs, or a discovered set of outdoor light devices, including requests like "list my devices", "turn off my outside lights", "turn them on", "set the outside lights to orange", "make the corner lamp brighter", "dim the patio lights", or "verify the outdoor lights are off".
---

# Wyze Outdoor Lights

## Workflow

Run commands from `wyze-local-devices`.

Use the local CLI, not a generic smart-home API. Discover the user's current Wyze device names before assuming a target. Outdoor plug controllers often expose child outlets separately, so prefer controlling the discovered child outlets instead of the parent controller when both are present.

For inventory-only requests such as "list my devices", start with the local discovery cache because it does not require a live Wyze API call when the cache is fresh:

```bash
uv run --script wyze_devices.py lookup --json
```

If the cache is missing, empty, or stale, the CLI may refresh from Wyze automatically. When a fresh live inventory is explicitly needed, run:

```bash
uv run --script wyze_devices.py lookup --refresh --json
```

If a cached lookup succeeds but does not include the requested device or device group, rerun the lookup once with `--refresh` before concluding that no matching device exists:

```bash
uv run --script wyze_devices.py lookup "<requested device name or group>" --refresh --json
```

If live discovery fails but `lookup --json` succeeds, report the cached devices and include the `discovered_at` timestamp so the user can judge freshness.

Identify the outdoor light targets by user-provided names, room/location words, or discovered device names such as `Outdoor`, `Outside`, `Patio`, `Porch`, `Deck`, `Garden`, or `Yard`. If multiple child outlets match the requested outdoor light group, control all of them with the narrowest shared name prefix or by issuing separate commands for each exact name.

If the CLI intentionally skips a parent outdoor plug controller because child outlets are available, treat that as expected and control the child outlets.

For relative brightness requests such as "brighter", "more bright", "dim", "less bright", "turn up", or "turn down", use `adjust-light` with `--verify --json`. For exact brightness, color temperature, or RGB color changes, use `set-light`. Do not use either command for plug outlets, even if those outlets power lights; plugs only support power on/off through this CLI.

Live commands automatically retry with discovered `certifi` CA bundles when Wyze HTTPS certificate validation fails. Do not manually wrap commands with `REQUESTS_CA_BUNDLE` unless the automatic retry reports that it failed.

## Commands

List cached devices:

```bash
uv run --script wyze_devices.py lookup --json
```

Turn a matched outdoor light group off:

```bash
uv run --script wyze_devices.py control "<matched outdoor device name or shared prefix>" off --verify --json
```

Turn a matched outdoor light group on:

```bash
uv run --script wyze_devices.py control "<matched outdoor device name or shared prefix>" on --verify --json
```

Set brightness on a matched Wyze bulb/light:

```bash
uv run --script wyze_devices.py set-light "<matched outdoor device name or shared prefix>" --brightness 70 --verify --json
```

Make a matched Wyze bulb/light brighter:

```bash
uv run --script wyze_devices.py adjust-light "<matched outdoor device name or shared prefix>" brighter --verify --json
```

Dim a matched Wyze bulb/light:

```bash
uv run --script wyze_devices.py adjust-light "<matched outdoor device name or shared prefix>" dimmer --verify --json
```

Set color temperature on a matched Wyze bulb/light:

```bash
uv run --script wyze_devices.py set-light "<matched outdoor device name or shared prefix>" --temperature 3500 --verify --json
```

Set RGB color on a matched Wyze bulb/light:

```bash
uv run --script wyze_devices.py set-light "<matched outdoor device name or shared prefix>" --color ff8800 --verify --json
```

Refresh device inventory when the device mapping may have changed:

```bash
uv run --script wyze_devices.py lookup --refresh --json
```

## Reporting

After a power control command, report each matched device name and its `verification.is_on` value. Treat `is_on: false` as off and `is_on: true` as on. After a `set-light` or `adjust-light` command, report the matched device name, `status`, and verification fields that are present, such as `brightness`, `temperature`, `color`, and `is_on`. If the requested brightness differs from verified brightness, state both values plainly.

For inventory requests, report cached `lookup --json` results when live discovery fails and clearly state that live refresh was blocked.

If a live command still fails with `SSLCertVerificationError` after the CLI's automatic retry, a common way to locate the certifi bundle for manual diagnosis is:

```bash
python -m certifi
```

Then rerun once, replacing `<certifi bundle path>` with that output:

```bash
REQUESTS_CA_BUNDLE="<certifi bundle path>" uv run --script wyze_devices.py control "<matched outdoor device name or shared prefix>" off --verify --json
```

If that still fails, do not keep retrying certificate environment variables. Use `lookup --json` only for cached inventory, and report that live Wyze API operations such as refresh, control, light adjustment, and verification are blocked by certificate validation.

If the command fails because credentials or tokens are missing, inspect the nearest `.env` expected by `wyze_devices.py` and report that Wyze credentials need to be restored.
