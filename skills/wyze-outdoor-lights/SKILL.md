---
name: wyze-outdoor-lights
description: Turn Wyze outdoor lights on or off from a local wyze-local-devices repo. Use when the user asks to control outside/outdoor Wyze lights, outdoor plugs, or a discovered set of outdoor light devices, including requests like "turn off my outside lights", "turn them on", or "verify the outdoor lights are off".
---

# Wyze Outdoor Lights

## Workflow

Run commands from `wyze-local-devices`.

Use the local CLI, not a generic smart-home API. Discover the user's current Wyze device names before assuming a target. Outdoor plug controllers often expose child outlets separately, so prefer controlling the discovered child outlets instead of the parent controller when both are present.

Start by listing devices when no current target names have been provided in the conversation:

```bash
uv run --script wyze_devices.py list --all --discover --json
```

Identify the outdoor light targets by user-provided names, room/location words, or discovered device names such as `Outdoor`, `Outside`, `Patio`, `Porch`, `Deck`, `Garden`, or `Yard`. If multiple child outlets match the requested outdoor light group, control all of them with the narrowest shared name prefix or by issuing separate commands for each exact name.

If the CLI intentionally skips a parent outdoor plug controller because child outlets are available, treat that as expected and control the child outlets.

## Commands

Turn a matched outdoor light group off:

```bash
uv run --script wyze_devices.py control "<matched outdoor device name or shared prefix>" off --verify --json
```

Turn a matched outdoor light group on:

```bash
uv run --script wyze_devices.py control "<matched outdoor device name or shared prefix>" on --verify --json
```

Refresh device inventory when the device mapping may have changed:

```bash
uv run --script wyze_devices.py list --all --discover --json
```

## Reporting

After a control command, report each matched device name and its `verification.is_on` value. Treat `is_on: false` as off and `is_on: true` as on.

If the command fails with `SSLCertVerificationError`, rerun with `REQUESTS_CA_BUNDLE` pointing at a local certifi bundle. A common way to locate it is:

```bash
python -m certifi
```

Then rerun, replacing `<certifi bundle path>` with that output:

```bash
REQUESTS_CA_BUNDLE="<certifi bundle path>" uv run --script wyze_devices.py control "<matched outdoor device name or shared prefix>" off --verify --json
```

If the command fails because credentials or tokens are missing, inspect the nearest `.env` expected by `wyze_devices.py` and report that Wyze credentials need to be restored.
