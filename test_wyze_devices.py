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
from typing import Any
from unittest.mock import patch

import wyze_devices

SCRIPT_TEXT = Path(wyze_devices.__file__).read_text()
PYPROJECT_TEXT = (Path(wyze_devices.__file__).resolve().parent / "pyproject.toml").read_text()


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


class FakeBulbs:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def turn_on(self, **kwargs: str) -> None:
        self.calls.append(("on", kwargs))

    def turn_off(self, **kwargs: str) -> None:
        self.calls.append(("off", kwargs))

    def set_brightness(self, **kwargs: str | int) -> None:
        self.calls.append(("brightness", kwargs))

    def set_color_temp(self, **kwargs: str | int) -> None:
        self.calls.append(("temperature", kwargs))

    def set_color(self, **kwargs: str) -> None:
        self.calls.append(("color", kwargs))

    def info(self, **_kwargs: str) -> SimpleNamespace:
        return SimpleNamespace(is_on=True, brightness=70, color_temp=3500, color="FF8800")


class LaggingFakeBulbs(FakeBulbs):
    def __init__(self, states: list[bool]) -> None:
        super().__init__()
        self.states = states

    def info(self, **_kwargs: str) -> SimpleNamespace:
        state = self.states.pop(0) if self.states else True
        return SimpleNamespace(is_on=state, brightness=70, color_temp=3500, color="FF8800")


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
        self.bulbs = FakeBulbs()
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
        self.assertIn("uv run --script wyze_devices.py skill --uninstall", help_text)
        self.assertIn("python wyze_devices.py list --all --json", help_text)
        self.assertIn("python wyze_devices.py skill --json", help_text)
        self.assertIn("python wyze_devices.py lookup plug", help_text)
        self.assertIn('python wyze_devices.py control "entry camera" on --json', help_text)
        self.assertNotIn("outdoor", help_text.casefold())

    def test_script_has_uv_inline_dependency_metadata(self) -> None:
        self.assertIn("# /// script", SCRIPT_TEXT)
        self.assertIn('# requires-python = ">=3.12,<3.15"', SCRIPT_TEXT)
        self.assertIn('"certifi>=2024.2.2"', SCRIPT_TEXT)
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

    def test_default_db_path_uses_explicit_environment_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "custom.sqlite3"

            with patch.dict(os.environ, {"WYZE_DEVICES_DB": str(db_path)}, clear=True):
                self.assertEqual(db_path.resolve(), wyze_devices.default_db_path())

    def test_default_db_path_uses_platform_app_data_locations(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "home"
            local_app_data = Path(tmpdir) / "local-app-data"
            xdg_data = Path(tmpdir) / "xdg-data"

            with (
                patch.object(Path, "home", return_value=home),
                patch.object(wyze_devices.sys, "platform", "darwin"),
                patch.dict(os.environ, {}, clear=True),
            ):
                self.assertEqual(
                    home / "Library" / "Application Support" / "wyze-local-devices" / "devices.sqlite3",
                    wyze_devices.default_db_path(),
                )

            with (
                patch.object(wyze_devices.sys, "platform", "win32"),
                patch.dict(os.environ, {"LOCALAPPDATA": str(local_app_data)}, clear=True),
            ):
                self.assertEqual(
                    local_app_data / "wyze-local-devices" / "devices.sqlite3",
                    wyze_devices.default_db_path(),
                )

            with (
                patch.object(wyze_devices.sys, "platform", "linux"),
                patch.dict(os.environ, {"XDG_DATA_HOME": str(xdg_data)}, clear=True),
            ):
                self.assertEqual(
                    xdg_data / "wyze-local-devices" / "devices.sqlite3",
                    wyze_devices.default_db_path(),
                )

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

    def test_control_device_dispatches_mesh_light_action(self) -> None:
        client = FakeClient([])
        light = device("Corner", mac="AA:BB:03", dtype="MeshLight", model="HL_A19C2")

        result = wyze_devices.control_device(client, light, "on")

        self.assertEqual("turned on bulb", result)
        self.assertEqual([("on", {"device_mac": "AA:BB:03", "device_model": "HL_A19C2"})], client.bulbs.calls)

    def test_normalize_hex_color_accepts_hash_prefix_and_uppercases(self) -> None:
        self.assertEqual("FF8800", wyze_devices.normalize_hex_color("#ff8800"))

    def test_normalize_hex_color_rejects_invalid_values(self) -> None:
        with self.assertRaises(argparse.ArgumentTypeError):
            wyze_devices.normalize_hex_color("orange")

    def test_adjusted_brightness_moves_within_bounds(self) -> None:
        self.assertEqual(90, wyze_devices.adjusted_brightness(70, "brighter", 20))
        self.assertEqual(50, wyze_devices.adjusted_brightness("70", "dimmer", 20))
        self.assertEqual(100, wyze_devices.adjusted_brightness(95, "increase", 20))
        self.assertEqual(1, wyze_devices.adjusted_brightness(5, "decrease", 20))

    def test_adjusted_brightness_uses_directional_fallback_when_current_is_unknown(self) -> None:
        self.assertEqual(100, wyze_devices.adjusted_brightness(None, "brighter", 20))
        self.assertEqual(1, wyze_devices.adjusted_brightness(None, "dimmer", 20))

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

    def test_run_control_can_verify_mesh_light(self) -> None:
        client = FakeClient([device("Corner", mac="AA:BB:03", dtype="MeshLight", model="HL_A19C2")])
        args = argparse.Namespace(query="corner", action="on", json=True, verify=True)
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            exit_code = wyze_devices.run_control(client, args)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(0, exit_code)
        self.assertEqual("turned on bulb", payload[0]["status"])
        self.assertEqual(
            {"type": "MeshLight", "is_on": True, "brightness": 70, "temperature": 3500, "color": "FF8800"},
            payload[0]["verification"],
        )

    def test_run_control_retries_until_mesh_light_verifies_expected_state(self) -> None:
        client = FakeClient([device("Corner", mac="AA:BB:03", dtype="MeshLight", model="HL_A19C2")])
        client.bulbs = LaggingFakeBulbs([False, True])
        args = argparse.Namespace(query="corner", action="on", json=True, verify=True)
        stdout = io.StringIO()

        with (
            patch("wyze_devices.time.sleep") as sleep,
            contextlib.redirect_stdout(stdout),
        ):
            exit_code = wyze_devices.run_control(client, args)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(0, exit_code)
        self.assertEqual(
            {"type": "MeshLight", "is_on": True, "brightness": 70, "temperature": 3500, "color": "FF8800"},
            payload[0]["verification"],
        )
        sleep.assert_called_once_with(1)

    def test_run_set_light_sets_brightness_temperature_and_color(self) -> None:
        client = FakeClient([device("Corner", mac="AA:BB:03", dtype="MeshLight", model="HL_A19C2")])
        args = argparse.Namespace(
            query="corner",
            brightness=70,
            temperature=3500,
            color="FF8800",
            json=True,
            verify=True,
        )
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            exit_code = wyze_devices.run_set_light(client, args)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(0, exit_code)
        self.assertEqual(
            [
                ("brightness", {"device_mac": "AA:BB:03", "device_model": "HL_A19C2", "brightness": 70}),
                ("temperature", {"device_mac": "AA:BB:03", "device_model": "HL_A19C2", "color_temp": 3500}),
                ("color", {"device_mac": "AA:BB:03", "device_model": "HL_A19C2", "color": "FF8800"}),
            ],
            client.bulbs.calls,
        )
        self.assertEqual("set brightness to 70; set temperature to 3500; set color to FF8800", payload[0]["status"])
        self.assertEqual(
            {"type": "MeshLight", "is_on": True, "brightness": 70, "temperature": 3500, "color": "FF8800"},
            payload[0]["verification"],
        )

    def test_run_set_light_requires_at_least_one_setting(self) -> None:
        client = FakeClient([device("Corner", mac="AA:BB:03", dtype="MeshLight", model="HL_A19C2")])
        args = argparse.Namespace(
            query="corner", brightness=None, temperature=None, color=None, json=True, verify=False
        )
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr):
            exit_code = wyze_devices.run_set_light(client, args)

        self.assertEqual(2, exit_code)
        self.assertIn("set-light needs at least one", stderr.getvalue())

    def test_run_adjust_light_increases_from_verified_current_brightness(self) -> None:
        client = FakeClient([device("Corner", mac="AA:BB:03", dtype="MeshLight", model="HL_A19C2")])
        args = argparse.Namespace(
            query="corner",
            direction="brighter",
            step=20,
            min_brightness=1,
            max_brightness=100,
            json=True,
            verify=True,
        )
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            exit_code = wyze_devices.run_adjust_light(client, args)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(0, exit_code)
        self.assertEqual(
            [("brightness", {"device_mac": "AA:BB:03", "device_model": "HL_A19C2", "brightness": 90})],
            client.bulbs.calls,
        )
        self.assertEqual("adjusted brightness from 70 to 90", payload[0]["status"])
        self.assertEqual(90, payload[0]["brightness"])
        self.assertEqual("brighter", payload[0]["requested_direction"])
        self.assertEqual(
            {"type": "MeshLight", "is_on": True, "brightness": 70, "temperature": 3500, "color": "FF8800"},
            payload[0]["verification"],
        )

    def test_run_adjust_light_clamps_dimmer_requests(self) -> None:
        client = FakeClient([device("Corner", mac="AA:BB:03", dtype="MeshLight", model="HL_A19C2")])
        args = argparse.Namespace(
            query="corner",
            direction="dimmer",
            step=90,
            min_brightness=1,
            max_brightness=100,
            json=True,
            verify=False,
        )
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            exit_code = wyze_devices.run_adjust_light(client, args)

        self.assertEqual(0, exit_code)
        self.assertEqual(
            [("brightness", {"device_mac": "AA:BB:03", "device_model": "HL_A19C2", "brightness": 1})],
            client.bulbs.calls,
        )

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
        self.assertEqual("wyze-local-devices", payload["name"])
        self.assertEqual(("skills", "wyze-local-devices"), Path(payload["source"]).parts[-2:])
        self.assertEqual(("skills", "wyze-local-devices", "SKILL.md"), Path(payload["skill_file"]).parts[-3:])
        self.assertEqual(
            ("skills", "wyze-local-devices", "agents", "openai.yaml"),
            Path(payload["agents_metadata"]).parts[-4:],
        )

    def test_bundled_skill_dir_falls_back_to_installed_data_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            installed = Path(tmpdir) / "share" / "wyze-local-devices" / "skills" / "wyze-local-devices"
            (installed / "agents").mkdir(parents=True)
            (installed / "SKILL.md").write_text("---\nname: wyze-local-devices\n---\n")
            (installed / "agents" / "openai.yaml").write_text("interface: {}\n")

            with (
                patch.object(wyze_devices, "SOURCE_SKILL_DIR", Path(tmpdir) / "missing"),
                patch.object(wyze_devices, "INSTALLED_SKILL_DIR", installed),
            ):
                self.assertEqual(installed, wyze_devices.bundled_skill_dir())

    def test_project_metadata_exposes_stable_console_script(self) -> None:
        self.assertIn('[project.scripts]\nwyze-local-devices = "wyze_devices:main"', PYPROJECT_TEXT)

    def test_main_skill_install_copies_skill_to_destination(self) -> None:
        stdout = io.StringIO()

        with tempfile.TemporaryDirectory() as tmpdir:
            destination_root = Path(tmpdir) / "skills"
            with contextlib.redirect_stdout(stdout):
                exit_code = wyze_devices.main(["skill", "--install", "--destination", str(destination_root), "--json"])

            payload = json.loads(stdout.getvalue())
            installed = (destination_root / "wyze-local-devices").resolve()
            self.assertEqual(0, exit_code)
            self.assertEqual(str(installed.resolve()), payload["destination"])
            self.assertTrue((installed / "SKILL.md").exists())
            self.assertTrue((installed / "agents" / "openai.yaml").exists())

            shutil.rmtree(installed)

    def test_main_skill_uninstall_removes_installed_skill(self) -> None:
        stdout = io.StringIO()

        with tempfile.TemporaryDirectory() as tmpdir:
            destination_root = Path(tmpdir) / "skills"
            installed = destination_root / "wyze-local-devices"
            wyze_devices.install_skill(destination_root)

            with contextlib.redirect_stdout(stdout):
                exit_code = wyze_devices.main(["skill", "--uninstall", "--destination", str(destination_root)])

            self.assertEqual(0, exit_code)
            self.assertFalse(installed.exists())
            self.assertIn(f"Uninstalled wyze-local-devices from {installed.resolve()}", stdout.getvalue())

    def test_main_skill_uninstall_is_noop_when_skill_is_absent(self) -> None:
        stdout = io.StringIO()

        with tempfile.TemporaryDirectory() as tmpdir:
            destination_root = Path(tmpdir) / "skills"
            with contextlib.redirect_stdout(stdout):
                exit_code = wyze_devices.main(["skill", "--uninstall", "--destination", str(destination_root)])

            self.assertEqual(0, exit_code)
            self.assertIn("wyze-local-devices is not installed", stdout.getvalue())

    def test_main_skill_uninstall_json_reports_removed_state(self) -> None:
        stdout = io.StringIO()

        with tempfile.TemporaryDirectory() as tmpdir:
            destination_root = Path(tmpdir) / "skills"
            wyze_devices.install_skill(destination_root)

            with contextlib.redirect_stdout(stdout):
                exit_code = wyze_devices.main(
                    ["skill", "--uninstall", "--destination", str(destination_root), "--json"]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(0, exit_code)
        self.assertTrue(payload["removed"])
        self.assertEqual(("skills", "wyze-local-devices"), Path(payload["destination"]).parts[-2:])

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

    def test_main_retries_live_command_with_certifi_for_ssl_verification_failure(self) -> None:
        args = argparse.Namespace(command="list", db_file=None, env_file=None)
        calls = {"count": 0}
        stderr = io.StringIO()

        def fake_run_live_command(*_args: object) -> int:
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("CERTIFICATE_VERIFY_FAILED")
            return 0

        with (
            patch.dict(os.environ, {"WYZE_ACCESS_TOKEN": "token"}, clear=True),
            patch.object(wyze_devices, "parse_args", return_value=args),
            patch.object(wyze_devices, "run_live_command", side_effect=fake_run_live_command),
            patch.object(wyze_devices, "certifi_bundle_candidates", return_value=[Path("/tmp/cacert.pem")]),
            contextlib.redirect_stderr(stderr),
        ):
            exit_code = wyze_devices.main(["list"])

        self.assertEqual(0, exit_code)
        self.assertEqual(2, calls["count"])
        self.assertIn(f"Retrying with certifi CA bundle: {Path('/tmp/cacert.pem')}", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
