from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import wyze_devices

SCRIPT_TEXT = Path(wyze_devices.__file__).read_text()


def device(
    nickname: str,
    mac: str = "AA:BB",
    dtype: str = "Plug",
    model: str = "WLPP1",
    online: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        nickname=nickname,
        mac=mac,
        type=dtype,
        product=SimpleNamespace(model=model, type=dtype),
        is_online=online,
        ip="192.168.1.20",
        ssid="wifi",
        rssi=-50,
        firmware_version="1.0",
        hardware_version="1.0",
        timezone=SimpleNamespace(name="America/Los_Angeles"),
    )


class FakePlugs:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    def turn_on(self, **kwargs: str) -> None:
        self.calls.append(("on", kwargs))

    def turn_off(self, **kwargs: str) -> None:
        self.calls.append(("off", kwargs))

    def info(self, **_kwargs: str) -> SimpleNamespace:
        return SimpleNamespace(is_on=True)


class FakeCameras:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    def turn_on(self, **kwargs: str) -> None:
        self.calls.append(("on", kwargs))

    def turn_off(self, **kwargs: str) -> None:
        self.calls.append(("off", kwargs))


class FakeClient:
    def __init__(self, devices: list[SimpleNamespace]) -> None:
        self._devices = devices
        self.plugs = FakePlugs()
        self.cameras = FakeCameras()

    def devices_list(self) -> list[SimpleNamespace]:
        return self._devices


class WyzeDevicesTest(unittest.TestCase):
    def test_build_parser_help_is_llm_readable(self) -> None:
        parser = wyze_devices.build_parser()

        help_text = parser.format_help()

        self.assertIn("List and cache Wyze devices from one script.", help_text)
        self.assertIn("uv run --script wyze_devices.py list", help_text)
        self.assertIn("uv run --script wyze_devices.py skill --install", help_text)
        self.assertIn("python wyze_devices.py list --all --json", help_text)
        self.assertIn("python wyze_devices.py skill --json", help_text)
        self.assertIn("python wyze_devices.py lookup plug", help_text)
        self.assertIn('python wyze_devices.py control "entry camera" on --json', help_text)
        self.assertNotIn("outdoor", help_text.casefold())

    def test_script_has_uv_inline_dependency_metadata(self) -> None:
        self.assertIn("# /// script", SCRIPT_TEXT)
        self.assertIn('# requires-python = ">=3.12,<3.15"', SCRIPT_TEXT)
        self.assertIn('"python-dotenv>=1.0.0"', SCRIPT_TEXT)
        self.assertIn('"protobuf==5.29.6"', SCRIPT_TEXT)
        self.assertIn('"wyze-sdk==2.3.6"', SCRIPT_TEXT)

    def test_missing_credentials_message_accepts_token_or_full_login(self) -> None:
        empty_creds: dict[str, str | None] = {key: None for key in wyze_devices.ENV_ALIASES}
        token_creds = empty_creds | {"access_token": "token"}
        login_creds = empty_creds | {
            "email": "me@example.com",
            "password": "secret",
            "key_id": "key-id",
            "api_key": "api-key",
        }

        self.assertIn("No .env file found.", wyze_devices.missing_credentials_message(empty_creds, None))
        self.assertEqual("", wyze_devices.missing_credentials_message(token_creds, None))
        self.assertEqual("", wyze_devices.missing_credentials_message(login_creds, None))

    def test_find_env_file_prefers_explicit_existing_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text("WYZE_ACCESS_TOKEN=token\n")

            self.assertEqual(env_path.resolve(), wyze_devices.find_env_file(str(env_path)))

    def test_device_to_dict_filters_empty_values(self) -> None:
        result = wyze_devices.device_to_dict(device("Entry plug", online=False))

        self.assertEqual("Entry plug", result["nickname"])
        self.assertEqual("WLPP1", result["model"])
        self.assertFalse(result["online"])
        self.assertNotIn("missing", result)

    def test_control_device_skips_parent_controller_plug(self) -> None:
        client = FakeClient([])
        parent = device("Parent controller", mac="AA:BB", model="WLPPO")

        result = wyze_devices.control_device(client, parent, "off")

        self.assertIn("skipped parent/controller", result)
        self.assertEqual([], client.plugs.calls)

    def test_control_device_dispatches_plug_action(self) -> None:
        client = FakeClient([])
        outlet = device("Entry plug", mac="AA:BB-1", model="WLPP1")

        result = wyze_devices.control_device(client, outlet, "off")

        self.assertEqual("turned off plug", result)
        self.assertEqual([("off", {"device_mac": "AA:BB-1", "device_model": "WLPP1"})], client.plugs.calls)

    def test_run_control_matches_live_devices_and_outputs_json(self) -> None:
        client = FakeClient(
            [
                device("Desk plug", mac="AA:BB:01"),
                device("Entry camera", mac="AA:BB:02", dtype="Camera", model="WYZEC1"),
            ]
        )
        args = argparse.Namespace(query="desk", action="off", json=True, verify=False)
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            exit_code = wyze_devices.run_control(client, args)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(0, exit_code)
        self.assertEqual(["Desk plug"], [item["nickname"] for item in payload])
        self.assertEqual("turned off plug", payload[0]["status"])
        self.assertEqual([("off", {"device_mac": "AA:BB:01", "device_model": "WLPP1"})], client.plugs.calls)

    def test_run_control_can_include_structured_verification(self) -> None:
        client = FakeClient([device("Desk plug", mac="AA:BB:01")])
        args = argparse.Namespace(query="desk", action="on", json=True, verify=True)
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            exit_code = wyze_devices.run_control(client, args)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(0, exit_code)
        self.assertEqual({"type": "Plug", "is_on": True}, payload[0]["verification"])

    def test_run_list_outputs_only_online_devices_by_default(self) -> None:
        client = FakeClient(
            [
                device("Offline", mac="AA:BB:01", online=False),
                device("Online", mac="AA:BB:02", online=True),
            ]
        )
        args = argparse.Namespace(all=False, json=True, discover=False, db_file=None)
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            exit_code = wyze_devices.run_list(client, args)

        self.assertEqual(0, exit_code)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(["Online"], [item["nickname"] for item in payload])

    def test_run_list_discover_persists_fetched_inventory(self) -> None:
        client = FakeClient(
            [
                device("Offline", mac="AA:BB:01", online=False),
                device("Online", mac="AA:BB:02", online=True),
            ]
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "devices.sqlite3"
            args = argparse.Namespace(all=True, json=False, discover=True, db_file=str(db_path))

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = wyze_devices.run_list(client, args)

            cached = wyze_devices.cached_devices(db_path)

        self.assertEqual(0, exit_code)
        self.assertIn("Discovered 2 devices", stderr.getvalue())
        self.assertEqual(["Offline", "Online"], [item["nickname"] for item in cached])

    def test_run_lookup_filters_local_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "devices.sqlite3"
            wyze_devices.persist_devices(
                [
                    wyze_devices.device_to_dict(device("Desk", model="OTHER")),
                    wyze_devices.device_to_dict(device("Entry camera", mac="AA:BB-1", dtype="Camera", model="WYZEC1")),
                ],
                db_path,
            )
            args = argparse.Namespace(query="camera", json=True, db_file=str(db_path))
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = wyze_devices.run_lookup(args)

        self.assertEqual(0, exit_code)
        self.assertEqual(["Entry camera"], [item["nickname"] for item in json.loads(stdout.getvalue())])

    def test_run_list_discover_keeps_json_stdout_parseable(self) -> None:
        client = FakeClient([device("Online", mac="AA:BB:02")])
        stdout = io.StringIO()
        stderr = io.StringIO()

        with tempfile.TemporaryDirectory() as tmpdir:
            args = argparse.Namespace(
                all=False, json=True, discover=True, db_file=str(Path(tmpdir) / "devices.sqlite3")
            )

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = wyze_devices.run_list(client, args)

        self.assertEqual(0, exit_code)
        self.assertEqual(["Online"], [item["nickname"] for item in json.loads(stdout.getvalue())])
        self.assertIn("Discovered 1 device", stderr.getvalue())

    def test_main_uses_single_cli_with_mocked_client(self) -> None:
        client = FakeClient([device("Online")])
        stdout = io.StringIO()

        with (
            patch.dict(os.environ, {"WYZE_ACCESS_TOKEN": "token"}, clear=True),
            patch.object(wyze_devices, "make_client", return_value=client),
            contextlib.redirect_stdout(stdout),
        ):
            exit_code = wyze_devices.main(["list", "--json"])

        self.assertEqual(0, exit_code)
        self.assertEqual("Online", json.loads(stdout.getvalue())[0]["nickname"])

    def test_main_without_args_prints_help_without_error(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = wyze_devices.main([])

        self.assertEqual(0, exit_code)
        self.assertIn("List and cache Wyze devices from one script.", stdout.getvalue())
        self.assertEqual("", stderr.getvalue())

    def test_main_skill_json_reports_bundled_skill_without_credentials(self) -> None:
        stdout = io.StringIO()

        with patch.dict(os.environ, {}, clear=True), contextlib.redirect_stdout(stdout):
            exit_code = wyze_devices.main(["skill", "--json"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(0, exit_code)
        self.assertEqual("wyze-outdoor-lights", payload["name"])
        self.assertTrue(payload["source"].endswith("skills/wyze-outdoor-lights"))
        self.assertTrue(payload["skill_file"].endswith("skills/wyze-outdoor-lights/SKILL.md"))
        self.assertTrue(payload["agents_metadata"].endswith("skills/wyze-outdoor-lights/agents/openai.yaml"))

    def test_main_skill_install_copies_skill_to_destination(self) -> None:
        stdout = io.StringIO()

        with tempfile.TemporaryDirectory() as tmpdir:
            destination_root = Path(tmpdir) / "skills"
            with contextlib.redirect_stdout(stdout):
                exit_code = wyze_devices.main(["skill", "--install", "--destination", str(destination_root), "--json"])

            payload = json.loads(stdout.getvalue())
            installed = (destination_root / "wyze-outdoor-lights").resolve()
            self.assertEqual(0, exit_code)
            self.assertEqual(str(installed.resolve()), payload["destination"])
            self.assertTrue((installed / "SKILL.md").exists())
            self.assertTrue((installed / "agents" / "openai.yaml").exists())

            shutil.rmtree(installed)

    def test_main_lookup_uses_fresh_cache_without_credentials(self) -> None:
        stdout = io.StringIO()

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "devices.sqlite3"
            wyze_devices.persist_devices([wyze_devices.device_to_dict(device("Cached plug"))], db_path)
            with patch.dict(os.environ, {}, clear=True), contextlib.redirect_stdout(stdout):
                exit_code = wyze_devices.main(["--db-file", str(db_path), "lookup"])

        self.assertEqual(0, exit_code)
        self.assertIn("Cached plug", stdout.getvalue())

    def test_main_lookup_refreshes_missing_cache_before_lookup(self) -> None:
        client = FakeClient([device("Discovered plug")])
        stdout = io.StringIO()
        stderr = io.StringIO()

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "devices.sqlite3"
            with (
                patch.dict(os.environ, {"WYZE_ACCESS_TOKEN": "token"}, clear=True),
                patch.object(wyze_devices, "make_client", return_value=client),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                exit_code = wyze_devices.main(["--db-file", str(db_path), "lookup", "plug"])

        self.assertEqual(0, exit_code)
        self.assertIn("Discovery cache refreshed with 1 device", stderr.getvalue())
        self.assertIn("Discovered plug", stdout.getvalue())

    def test_main_lookup_refreshes_stale_cache_before_lookup(self) -> None:
        client = FakeClient([device("Fresh plug", mac="AA:BB:02")])
        stdout = io.StringIO()
        stderr = io.StringIO()

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "devices.sqlite3"
            wyze_devices.persist_devices([wyze_devices.device_to_dict(device("Stale plug", mac="AA:BB:01"))], db_path)
            old_time = (datetime.now(UTC) - timedelta(days=31)).isoformat()
            with wyze_devices.open_device_db(db_path) as connection:
                connection.execute("UPDATE devices SET discovered_at = ?", (old_time,))

            with (
                patch.dict(os.environ, {"WYZE_ACCESS_TOKEN": "token"}, clear=True),
                patch.object(wyze_devices, "make_client", return_value=client),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                exit_code = wyze_devices.main(["--db-file", str(db_path), "lookup", "fresh"])

        self.assertEqual(0, exit_code)
        self.assertIn("Discovery cache refreshed with 1 device", stderr.getvalue())
        self.assertIn("Fresh plug", stdout.getvalue())

    def test_main_control_uses_single_cli_with_mocked_client(self) -> None:
        client = FakeClient([device("Desk plug", mac="AA:BB:01")])
        stdout = io.StringIO()

        with (
            patch.dict(os.environ, {"WYZE_ACCESS_TOKEN": "token"}, clear=True),
            patch.object(wyze_devices, "make_client", return_value=client),
            contextlib.redirect_stdout(stdout),
        ):
            exit_code = wyze_devices.main(["control", "desk", "off", "--json"])

        self.assertEqual(0, exit_code)
        self.assertEqual("turned off plug", json.loads(stdout.getvalue())[0]["status"])


if __name__ == "__main__":
    unittest.main()
