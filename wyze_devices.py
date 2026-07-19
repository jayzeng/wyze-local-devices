#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12,<3.15"
# dependencies = [
#   "python-dotenv>=1.0.0",
#   "protobuf==5.29.6",
#   "wyze-sdk==2.3.6",
# ]
# [tool.uv]
# override-dependencies = ["protobuf==5.29.6"]
# ///
"""Wyze local device CLI.

Examples:
  uv run --script wyze_devices.py list
  uv run --script wyze_devices.py list --discover
  uv run --script wyze_devices.py lookup camera
  uv run --script wyze_devices.py control "desk plug" off
  python wyze_devices.py list
  python wyze_devices.py list --all --json
  python wyze_devices.py lookup plug
  python wyze_devices.py control "entry camera" on --json
  python wyze_devices.py --env-file ../.env list
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sqlite3
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Never

ENV_ALIASES = {
    "email": ("WYZE_EMAIL", "wyze_email"),
    "password": ("WYZE_PASSWORD", "wyze_password"),
    "key_id": ("WYZE_KEY_ID", "WYZE_API_KEY_ID", "wyze_key_id", "wyze_api_key_id"),
    "api_key": ("WYZE_API_KEY", "wyze_api_key"),
    "access_token": ("WYZE_ACCESS_TOKEN", "wyze_access_token", "WYZE_TOKEN", "wyze_token"),
    "refresh_token": ("WYZE_REFRESH_TOKEN", "wyze_refresh_token"),
    "totp_key": ("WYZE_TOTP_KEY", "wyze_totp_key"),
}

CACHE_MAX_AGE_DAYS = 30
CONTROLLER_PLUG_MODELS = {"WLPPO"}
PLUG_TYPES = {"Plug", "OutdoorPlug"}
CAMERA_TYPES = {"Camera"}
APP_NAME = "wyze-local-devices"
SKILL_NAME = "wyze-outdoor-lights"
SKILL_DIR = Path(__file__).resolve().parent / "skills" / SKILL_NAME

# Avoid noisy wyze-sdk warnings that dump full raw device payloads.
logging.getLogger("wyze_sdk.models.devices").setLevel(logging.ERROR)


class CliParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        self.print_help(sys.stderr)
        self.exit(2, f"\nerror: {message}\n")


def find_env_file(explicit_path: str | None) -> Path | None:
    if explicit_path:
        path = Path(explicit_path).expanduser().resolve()
        return path if path.exists() else None

    candidates: list[Path] = []
    cwd = Path.cwd().resolve()
    script_dir = Path(__file__).resolve().parent
    for start in (cwd, script_dir):
        candidates.extend(parent / ".env" for parent in (start, *start.parents))

    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.exists():
            return candidate
    return None


def default_db_path() -> Path:
    configured = os.getenv("WYZE_DEVICES_DB")
    if configured:
        return Path(configured).expanduser().resolve()

    if sys.platform == "darwin":
        data_dir = Path.home() / "Library" / "Application Support" / APP_NAME
    elif sys.platform == "win32":
        base = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA")
        data_dir = Path(base).expanduser() / APP_NAME if base else Path.home() / f".{APP_NAME}"
    else:
        base = os.getenv("XDG_DATA_HOME")
        data_dir = Path(base).expanduser() / APP_NAME if base else Path.home() / ".local" / "share" / APP_NAME

    return data_dir / "devices.sqlite3"


def resolve_db_path(explicit_path: str | None) -> Path:
    if explicit_path:
        return Path(explicit_path).expanduser().resolve()
    return default_db_path()


def first_env(names: Sequence[str]) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return None


def load_credentials(env_file: Path | None) -> dict[str, str | None]:
    if env_file:
        try:
            from dotenv import load_dotenv
        except ImportError:
            print(
                "python-dotenv is not installed; install requirements.txt to load .env files.",
                file=sys.stderr,
            )
        else:
            load_dotenv(env_file, override=False)

    return {key: first_env(names) for key, names in ENV_ALIASES.items()}


def open_device_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS devices (
            mac TEXT PRIMARY KEY,
            nickname TEXT,
            type TEXT,
            model TEXT,
            product_type TEXT,
            online INTEGER NOT NULL DEFAULT 0,
            ip TEXT,
            ssid TEXT,
            rssi INTEGER,
            firmware_version TEXT,
            hardware_version TEXT,
            timezone TEXT,
            discovered_at TEXT NOT NULL
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_devices_nickname ON devices(nickname)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_devices_model ON devices(model)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_devices_type ON devices(type)")
    return connection


def persist_devices(devices: Sequence[dict[str, Any]], db_path: Path) -> int:
    discovered_at = datetime.now(UTC).isoformat()
    rows = [
        (
            device.get("mac"),
            device.get("nickname"),
            device.get("type"),
            device.get("model"),
            device.get("product_type"),
            int(bool(device.get("online"))),
            device.get("ip"),
            device.get("ssid"),
            device.get("rssi"),
            device.get("firmware_version"),
            device.get("hardware_version"),
            device.get("timezone"),
            discovered_at,
        )
        for device in devices
        if device.get("mac")
    ]

    with open_device_db(db_path) as connection:
        connection.executemany(
            """
            INSERT INTO devices (
                mac,
                nickname,
                type,
                model,
                product_type,
                online,
                ip,
                ssid,
                rssi,
                firmware_version,
                hardware_version,
                timezone,
                discovered_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(mac) DO UPDATE SET
                nickname=excluded.nickname,
                type=excluded.type,
                model=excluded.model,
                product_type=excluded.product_type,
                online=excluded.online,
                ip=excluded.ip,
                ssid=excluded.ssid,
                rssi=excluded.rssi,
                firmware_version=excluded.firmware_version,
                hardware_version=excluded.hardware_version,
                timezone=excluded.timezone,
                discovered_at=excluded.discovered_at
            """,
            rows,
        )
    return len(rows)


def cached_devices(db_path: Path, query: str | None = None) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []

    sql = """
        SELECT
            nickname,
            mac,
            type,
            model,
            product_type,
            online,
            ip,
            ssid,
            rssi,
            firmware_version,
            hardware_version,
            timezone,
            discovered_at
        FROM devices
    """
    params: tuple[str, ...] = ()
    if query:
        pattern = f"%{query.casefold()}%"
        sql += """
            WHERE lower(coalesce(nickname, '')) LIKE ?
               OR lower(coalesce(mac, '')) LIKE ?
               OR lower(coalesce(type, '')) LIKE ?
               OR lower(coalesce(model, '')) LIKE ?
        """
        params = (pattern, pattern, pattern, pattern)
    sql += " ORDER BY lower(coalesce(nickname, '')), mac"

    with open_device_db(db_path) as connection:
        rows = connection.execute(sql, params).fetchall()

    columns = [
        "nickname",
        "mac",
        "type",
        "model",
        "product_type",
        "online",
        "ip",
        "ssid",
        "rssi",
        "firmware_version",
        "hardware_version",
        "timezone",
        "discovered_at",
    ]
    devices: list[dict[str, Any]] = []
    for row in rows:
        item = dict(zip(columns, row, strict=True))
        item["online"] = bool(item["online"])
        devices.append({key: value for key, value in item.items() if value not in (None, "")})
    return devices


def latest_discovery_time(db_path: Path) -> datetime | None:
    if not db_path.exists():
        return None

    with open_device_db(db_path) as connection:
        row = connection.execute("SELECT max(discovered_at) FROM devices").fetchone()

    if not row or not row[0]:
        return None

    try:
        discovered_at = datetime.fromisoformat(row[0])
    except ValueError:
        return None

    if discovered_at.tzinfo is None:
        return discovered_at.replace(tzinfo=UTC)
    return discovered_at


def discovery_cache_needs_refresh(db_path: Path, max_age_days: int = CACHE_MAX_AGE_DAYS) -> bool:
    latest = latest_discovery_time(db_path)
    if latest is None:
        return True
    return datetime.now(UTC) - latest > timedelta(days=max_age_days)


def refresh_discovery_cache(client: Any, db_path: Path) -> int:
    devices = [device_to_dict(device) for device in client.devices_list()]
    return persist_devices(devices, db_path)


def missing_credentials_message(creds: dict[str, str | None], env_file: Path | None) -> str:
    have_token = bool(creds["access_token"])
    have_login = all(creds[name] for name in ("email", "password", "key_id", "api_key"))
    if have_token or have_login:
        return ""

    loaded = f"Loaded env file: {env_file}" if env_file else "No .env file found."
    missing_login = [name for name in ("email", "password", "key_id", "api_key") if not creds[name]]
    aliases = {name: "/".join(ENV_ALIASES[name]) for name in ("email", "password", "key_id", "api_key", "access_token")}
    return (
        f"{loaded}\n"
        "wyze-sdk needs either WYZE_ACCESS_TOKEN, or a full login set.\n"
        f"Missing for login: {', '.join(missing_login)}\n\n"
        "Add these to .env (variable aliases supported by this script):\n"
        f"  {aliases['email']}\n"
        f"  {aliases['password']}\n"
        f"  {aliases['key_id']}\n"
        f"  {aliases['api_key']}\n\n"
        "Your existing wyze_api_key can be used for the API key value, but Wyze also requires the key ID."
    )


def make_client(creds: dict[str, str | None]) -> Any:
    try:
        from wyze_sdk import Client
    except ImportError as exc:
        raise RuntimeError(
            "wyze-sdk is not installed; run `uv sync` or `uv run --script wyze_devices.py ...`."
        ) from exc

    if creds["access_token"]:
        return Client(
            token=creds["access_token"],
            refresh_token=creds["refresh_token"],
        )

    return Client(
        email=creds["email"],
        password=creds["password"],
        key_id=creds["key_id"],
        api_key=creds["api_key"],
        totp_key=creds["totp_key"],
    )


def attr(device: Any, name: str) -> Any:
    try:
        return getattr(device, name)
    except Exception:
        return None


def product_model(device: Any) -> str:
    product = attr(device, "product")
    return attr(product, "model") or ""


def device_type(device: Any) -> str:
    return attr(device, "type") or ""


def device_to_dict(device: Any) -> dict[str, Any]:
    product = attr(device, "product")
    timezone = attr(device, "timezone")
    data = {
        "nickname": attr(device, "nickname"),
        "mac": attr(device, "mac"),
        "type": attr(device, "type"),
        "model": attr(product, "model") if product else None,
        "product_type": attr(product, "type") if product else None,
        "online": bool(attr(device, "is_online")),
        "ip": attr(device, "ip"),
        "ssid": attr(device, "ssid"),
        "rssi": attr(device, "rssi"),
        "firmware_version": attr(device, "firmware_version"),
        "hardware_version": attr(device, "hardware_version"),
        "timezone": attr(timezone, "name") if timezone else None,
    }
    return {key: value for key, value in data.items() if value not in (None, "")}


def is_controller_plug(device: Any) -> bool:
    mac = attr(device, "mac") or ""
    return product_model(device) in CONTROLLER_PLUG_MODELS and "-" not in mac


def print_table(devices: list[dict[str, Any]], columns: Sequence[str] | None = None) -> None:
    if not devices:
        print("No matching Wyze devices found.")
        return

    if columns is None:
        columns = ["nickname", "online", "type", "model", "ip", "ssid", "rssi", "mac"]
    widths = {col: max(len(col), *(len(str(device.get(col, ""))) for device in devices)) for col in columns}
    print("  ".join(col.upper().ljust(widths[col]) for col in columns))
    print("  ".join("-" * widths[col] for col in columns))
    for device in devices:
        print("  ".join(str(device.get(col, "")).ljust(widths[col]) for col in columns))


def device_matches_query(device: Any, query: str) -> bool:
    pattern = query.casefold()
    product = attr(device, "product")
    values = [
        attr(device, "nickname"),
        attr(device, "mac"),
        attr(device, "type"),
        attr(product, "model") if product else None,
    ]
    return any(pattern in str(value).casefold() for value in values if value)


def control_device(client: Any, device: Any, action: str) -> str:
    mac = attr(device, "mac")
    model = product_model(device)
    dtype = device_type(device)

    if is_controller_plug(device):
        return "skipped parent/controller; individual outlets are controlled separately"

    if dtype in PLUG_TYPES:
        method = client.plugs.turn_on if action == "on" else client.plugs.turn_off
        method(device_mac=mac, device_model=model)
        return f"turned {action} plug"

    if dtype in CAMERA_TYPES:
        method = client.cameras.turn_on if action == "on" else client.cameras.turn_off
        method(device_mac=mac, device_model=model)
        return f"turned {action} camera"

    return f"skipped unsupported type/model: {dtype or 'unknown'}/{model or 'unknown'}"


def verification_rows(client: Any, devices: Sequence[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for device in sorted(devices, key=lambda item: (attr(item, "nickname") or "").casefold()):
        name = attr(device, "nickname") or attr(device, "mac") or "unnamed device"
        dtype = device_type(device)
        mac = attr(device, "mac")

        if is_controller_plug(device):
            rows.append({"nickname": name, "mac": mac, "status": "parent/controller skipped"})
        elif dtype in PLUG_TYPES:
            info = client.plugs.info(device_mac=mac)
            rows.append({"nickname": name, "mac": mac, "type": dtype, "is_on": getattr(info, "is_on", None)})
        elif dtype in CAMERA_TYPES:
            rows.append({"nickname": name, "mac": mac, "type": dtype, "status": "camera command sent"})
    return rows


def print_verification(client: Any, devices: Sequence[Any]) -> None:
    for row in verification_rows(client, devices):
        name = row["nickname"]
        if "is_on" in row:
            print(f"VERIFY: {name} - plug is_on={row['is_on']}")
        else:
            print(f"VERIFY: {name} - {row['status']}")


def print_cli_error(exc: Exception) -> None:
    response = getattr(exc, "response", None)
    if response is not None:
        print(
            f"Wyze HTTP error: {getattr(response, 'status_code', 'unknown')} {getattr(response, 'reason', '')}",
            file=sys.stderr,
        )
        text = getattr(response, "text", "")
        if text:
            print(text, file=sys.stderr)
        return

    name = exc.__class__.__name__
    if name in {"HTTPError", "RequestException"} or name.startswith("Wyze"):
        print(f"Wyze SDK error: {exc}", file=sys.stderr)
    else:
        print(f"Error: {exc}", file=sys.stderr)


def default_agent_skills_dir() -> Path:
    configured = os.getenv("CODEX_HOME")
    if configured:
        return Path(configured).expanduser().resolve() / "skills"
    return Path.home() / ".codex" / "skills"


def skill_manifest(destination: Path | None = None) -> dict[str, str]:
    manifest = {
        "name": SKILL_NAME,
        "source": str(SKILL_DIR),
        "skill_file": str(SKILL_DIR / "SKILL.md"),
        "agents_metadata": str(SKILL_DIR / "agents" / "openai.yaml"),
    }
    if destination is not None:
        manifest["destination"] = str(destination)
    return manifest


def install_skill(destination_root: Path) -> Path:
    if not SKILL_DIR.exists():
        raise FileNotFoundError(f"Bundled skill not found: {SKILL_DIR}")

    destination = destination_root / SKILL_NAME
    destination_root.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(SKILL_DIR, destination)
    return destination


def run_skill(args: argparse.Namespace) -> int:
    destination_root = Path(args.destination).expanduser().resolve() if args.destination else default_agent_skills_dir()
    destination = destination_root / SKILL_NAME

    if args.install:
        destination = install_skill(destination_root)
        if args.json:
            print(json.dumps(skill_manifest(destination), indent=2, sort_keys=True))
        else:
            print(f"Installed {SKILL_NAME} to {destination}")
        return 0

    if args.json:
        print(json.dumps(skill_manifest(destination), indent=2, sort_keys=True))
    else:
        print(f"Skill: {SKILL_NAME}")
        print(f"Source: {SKILL_DIR}")
        print(f"Install destination: {destination}")
        print("Install with: uv run --script wyze_devices.py skill --install")
    return 0


def run_list(client: Any, args: argparse.Namespace) -> int:
    discovered_devices = [device_to_dict(device) for device in client.devices_list()]
    devices = list(discovered_devices)
    if not args.all:
        devices = [device for device in devices if device.get("online")]

    devices.sort(key=lambda device: str(device.get("nickname", "")).casefold())

    if args.json:
        print(json.dumps(devices, indent=2, sort_keys=True))
    else:
        print_table(devices)

    if args.discover:
        count = persist_devices(discovered_devices, resolve_db_path(args.db_file))
        print(
            f"Discovered {count} device{'s' if count != 1 else ''} into {resolve_db_path(args.db_file)}.",
            file=sys.stderr,
        )
    return 0


def run_lookup(args: argparse.Namespace) -> int:
    devices = cached_devices(resolve_db_path(args.db_file), args.query)
    if not devices:
        print("No cached Wyze devices found.")
        return 0

    if args.json:
        print(json.dumps(devices, indent=2, sort_keys=True))
    else:
        print_table(devices)
    return 0


def run_control(client: Any, args: argparse.Namespace) -> int:
    devices = [device for device in client.devices_list() if device_matches_query(device, args.query)]
    devices.sort(key=lambda device: (attr(device, "nickname") or "").casefold())

    if not devices:
        if args.json:
            print(json.dumps([], indent=2, sort_keys=True))
        else:
            print("No matching live Wyze devices found.")
        return 0

    rows = []
    for device in devices:
        status = control_device(client, device, args.action)
        item = device_to_dict(device)
        item["action"] = args.action
        item["status"] = status
        rows.append(item)

    if args.verify:
        verification_by_mac = {row.get("mac"): row for row in verification_rows(client, devices) if row.get("mac")}
        for row in rows:
            verification = verification_by_mac.get(row.get("mac"))
            if verification:
                row["verification"] = {
                    key: value for key, value in verification.items() if key not in {"nickname", "mac"}
                }

    if args.json:
        print(json.dumps(rows, indent=2, sort_keys=True))
    else:
        print_table(rows, ["nickname", "action", "status", "type", "model", "mac"])

    return 0


def build_parser() -> argparse.ArgumentParser:
    examples = "\n".join(
        [
            "Examples:",
            "  uv run --script wyze_devices.py list",
            "  uv run --script wyze_devices.py list --discover",
            "  uv run --script wyze_devices.py skill --install",
            "  uv run --script wyze_devices.py lookup camera",
            '  uv run --script wyze_devices.py control "desk plug" off',
            "  python wyze_devices.py list",
            "  python wyze_devices.py list --all --json",
            "  python wyze_devices.py skill --json",
            "  python wyze_devices.py lookup plug",
            '  python wyze_devices.py control "entry camera" on --json',
            "  python wyze_devices.py --env-file ../.env list",
        ]
    )
    parser = CliParser(
        description="List and cache Wyze devices from one script.",
        epilog=examples,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--env-file",
        help="Path to .env. Defaults to the nearest .env in the current/script directory ancestry.",
    )
    parser.add_argument(
        "--db-file",
        help=("Path to the local SQLite discovery cache. Defaults to WYZE_DEVICES_DB or the OS app data directory."),
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    skill_parser = subparsers.add_parser(
        "skill",
        help="Show or install the bundled agent skill.",
        description=(
            "Show or install the bundled agent skill. This command is offline and does not require Wyze credentials."
        ),
    )
    skill_parser.add_argument(
        "--install",
        action="store_true",
        help="Install the bundled skill into the agent skills directory.",
    )
    skill_parser.add_argument(
        "--destination",
        help="Agent skills root directory. Defaults to $CODEX_HOME/skills or ~/.codex/skills.",
    )
    skill_parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON instead of text.",
    )

    list_parser = subparsers.add_parser(
        "list",
        help="List Wyze devices.",
        description="List Wyze devices. By default only online devices are shown.",
    )
    list_parser.add_argument(
        "--all",
        action="store_true",
        help="Show offline devices too. By default only connected/online devices are printed.",
    )
    list_parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON instead of a table.",
    )
    list_parser.add_argument(
        "--discover",
        action="store_true",
        help="Persist the fetched device inventory into the local SQLite discovery cache.",
    )

    lookup_parser = subparsers.add_parser(
        "lookup",
        help="Look up devices from the local discovery cache.",
        description=(
            "Look up discovered devices. Refreshes the local cache first when "
            f"it is missing, empty, or older than {CACHE_MAX_AGE_DAYS} days."
        ),
    )
    lookup_parser.add_argument(
        "query",
        nargs="?",
        help="Optional case-insensitive match against nickname, MAC, type, or model.",
    )
    lookup_parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON instead of a table.",
    )

    control_parser = subparsers.add_parser(
        "control",
        help="Turn matching live Wyze plugs or cameras on or off.",
        description=(
            "Turn matching live Wyze plugs or cameras on or off. The query is "
            "matched case-insensitively against nickname, MAC, type, or model."
        ),
    )
    control_parser.add_argument(
        "query",
        help="Case-insensitive match against nickname, MAC, type, or model.",
    )
    control_parser.add_argument(
        "action",
        choices=("on", "off"),
        help="Desired power state.",
    )
    control_parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON instead of a table.",
    )
    control_parser.add_argument(
        "--verify",
        action="store_true",
        help="After sending commands, fetch plug state where supported and include verification.",
    )

    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if not raw_argv:
        build_parser().print_help()
        return 0

    args = parse_args(raw_argv)
    if args.command == "skill":
        return run_skill(args)

    db_path = resolve_db_path(args.db_file)
    needs_refresh = args.command == "lookup" and discovery_cache_needs_refresh(db_path)
    if args.command == "lookup" and not needs_refresh:
        return run_lookup(args)

    env_file = find_env_file(args.env_file)
    creds = load_credentials(env_file)

    message = missing_credentials_message(creds, env_file)
    if message:
        print(message, file=sys.stderr)
        return 2

    try:
        client = make_client(creds)
        if args.command == "list":
            return run_list(client, args)
        if args.command == "lookup":
            count = refresh_discovery_cache(client, db_path)
            print(
                f"Discovery cache refreshed with {count} device{'s' if count != 1 else ''} into {db_path}.",
                file=sys.stderr,
            )
            return run_lookup(args)
        if args.command == "control":
            return run_control(client, args)
    except Exception as exc:
        print_cli_error(exc)
        return 1

    print(f"Unknown command: {args.command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
