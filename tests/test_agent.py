from __future__ import annotations

import configparser
import contextlib
import io
import json
import tempfile
import unittest
from collections.abc import Sequence
from pathlib import Path
from subprocess import CompletedProcess, Popen
from typing import Any

from scrcpy_agent import AgentService, AndroidComputer
from scrcpy_capabilities import parse_help_options, recommend_recipe, validate_scrcpy_args
from scrcpy_cli import build_parser, run_agent_command
from scrcpy_manager import Device, ScrcpyManager
from scrcpy_mcp import ScrcpyMcpServer


class FakeProcess:
    pid = 12345


class FakeManager(ScrcpyManager):
    def __init__(self) -> None:
        self.adb_calls: list[tuple[str, ...]] = []
        self.run_calls: list[list[str]] = []
        self.scrcpy_calls: list[tuple[list[str], bool]] = []
        self.shell_outputs: list[str] = []

    def list_devices(self) -> list[Device]:
        return [Device(serial="USB123", state="device", kind="USB", model="Pixel", android="15")]

    def get_profile(self, profile_name: str) -> dict[str, str]:
        if profile_name != "MainPhone":
            raise ValueError(f"Profile '{profile_name}' was not found")
        return {
            "name": "MainPhone",
            "nickname": "Main Phone",
            "ip": "",
            "serial": "USB123",
            "quality": "balanced",
            "mode": "mirror",
            "video_codec": "",
            "audio_codec": "",
            "audio_source": "",
            "render_fit": "",
            "window_aspect_ratio_lock": "yes",
        }

    def list_profiles(self) -> list[dict[str, str]]:
        return [self.get_profile("MainPhone")]

    def get_quality_settings(self, preset: str) -> dict[str, str]:
        return {
            "name": preset,
            "video_bitrate": "8M",
            "max_fps": "60",
            "audio_buffer": "10",
            "audio_delay": "40",
            "video_buffer": "30",
            "resolution": "",
            "video_codec": "h264",
            "audio_codec": "opus",
            "audio_source": "output",
        }

    def get_quality_config(self) -> configparser.ConfigParser:
        parser = configparser.ConfigParser(interpolation=None)
        parser.optionxform = str  # type: ignore[method-assign,assignment]
        parser["balanced"] = {"video_bitrate": "8M", "max_fps": "60"}
        return parser

    def get_last_used(self) -> configparser.ConfigParser:
        parser = configparser.ConfigParser(interpolation=None)
        parser["lastused"] = {"profile": "MainPhone", "connection_type": "usb", "last_connection": "USB123"}
        return parser

    def run(
        self,
        args: Sequence[str],
        *,
        check: bool = False,
        capture_output: bool = True,
        text: bool = True,
        timeout: int | None = None,
    ) -> CompletedProcess[Any]:
        del check, capture_output, timeout
        self.run_calls.append(list(args))
        for flag in ("--list-apps", "--list-cameras", "--list-camera-sizes", "--list-displays", "--list-encoders"):
            if flag in args:
                return CompletedProcess(args, 0, stdout=f"{flag} output\nitem.one\n", stderr="")
        stdout: bytes | str = b"\x89PNG\r\n" if not text else ""
        return CompletedProcess(args, 0, stdout=stdout, stderr=b"" if not text else "")

    def adb(self, *args: str, check: bool = False, timeout: int | None = None) -> CompletedProcess[str]:
        del check, timeout
        self.adb_calls.append(args)
        if "cat" in args:
            return CompletedProcess(
                list(args),
                0,
                stdout='<hierarchy><node text="OK" resource-id="button_ok" class="android.widget.Button" bounds="[0,0][10,10]" clickable="true" enabled="true" /></hierarchy>',
                stderr="",
            )
        return CompletedProcess(list(args), 0, stdout="ok", stderr="")

    def adb_shell(self, serial: str, shell_command: Sequence[str]) -> str:
        del serial, shell_command
        if self.shell_outputs:
            return self.shell_outputs.pop(0)
        return "mCurrentFocus=Window{u0 com.example.app/.MainActivity}"

    def scrcpy(self, args: Sequence[str], check: bool = False, detach: bool = False) -> int | Popen[Any]:
        del check
        self.scrcpy_calls.append((list(args), detach))
        if detach:
            return FakeProcess()  # type: ignore[return-value]
        return 0


class AgentServiceTests(unittest.TestCase):
    def test_build_scrcpy_command_returns_json_safe_command(self) -> None:
        service = AgentService(FakeManager())

        result = service.build_scrcpy_command("MainPhone", quality_override="balanced", extra=["--no-control"])

        self.assertEqual(result["profile"], "MainPhone")
        self.assertEqual(result["connection"], "USB123")
        self.assertIn("--video-bit-rate=8M", result["args"])
        self.assertIn("--no-control", result["args"])
        self.assertIn("command_text", result)

    def test_scrcpy_catalog_exposes_known_shortcuts_and_recipes(self) -> None:
        service = AgentService(FakeManager())

        shortcuts = service.list_scrcpy_shortcuts()["shortcuts"]
        recipes = service.list_scrcpy_recipes()["recipes"]

        flattened = {shortcut for item in shortcuts for shortcut in item["shortcuts"]}
        self.assertIn("MOD+q", flattened)
        self.assertIn("MOD+f", flattened)
        self.assertIn("MOD+h", flattened)
        self.assertIn("MOD+b", flattened)
        self.assertIn("MOD+v", flattened)
        self.assertIn("MOD+t", flattened)
        self.assertIn("virtual-app", {item["name"] for item in recipes})

    def test_scrcpy_recipe_substitutes_package_and_command(self) -> None:
        result = recommend_recipe("virtual-app", package="org.videolan.vlc")

        self.assertIn("--start-app=org.videolan.vlc", result["args"])
        self.assertIn("--new-display", result["args"])

    def test_validate_scrcpy_args_accepts_known_and_rejects_unknown(self) -> None:
        known = {"--no-control", "--new-display", "--start-app"}

        accepted = validate_scrcpy_args(
            ["--no-control", "--new-display", "--start-app=org.videolan.vlc"], known_options=known
        )
        rejected = validate_scrcpy_args(["--not-real", "plain-value"], known_options=known)

        self.assertTrue(accepted["ok"])
        self.assertFalse(rejected["ok"])
        self.assertEqual(len(rejected["errors"]), 2)

    def test_parse_help_options_detects_local_style_options(self) -> None:
        options = parse_help_options("    --list-apps\n    --new-display[=[<width>x<height>][/<dpi>]]\n")

        self.assertIn("--list-apps", options)
        self.assertIn("--new-display", options)

    def test_launch_app_app_only_uses_monkey(self) -> None:
        manager = FakeManager()
        service = AgentService(manager)

        result = service.launch_app("USB123", "com.example.app", mode="app_only")

        self.assertEqual(result["status"], "completed")
        self.assertEqual(manager.adb_calls[-1][:6], ("-s", "USB123", "shell", "monkey", "-p", "com.example.app"))

    def test_scrcpy_list_tools_use_scrcpy_safe_list_flags(self) -> None:
        manager = FakeManager()
        service = AgentService(manager)

        result = service.list_apps("USB123")

        self.assertEqual(result["returncode"], 0)
        self.assertIn("item.one", result["lines"])
        self.assertIn("--list-apps", manager.run_calls[-1])

    def test_android_computer_translates_actions(self) -> None:
        manager = FakeManager()
        with tempfile.TemporaryDirectory() as tmp:
            computer = AndroidComputer(manager, "USB123", Path(tmp))

            screenshot = computer.screenshot()
            ui = computer.dump_ui()
            tap = computer.tap(10, 20)
            typed = computer.type_text("hello world")
            key = computer.keyevent("back")

        self.assertTrue(Path(screenshot["path"]).name.endswith(".png"))
        self.assertEqual(ui["node_count"], 1)
        self.assertEqual(tap["status"], "completed")
        self.assertEqual(typed["adb_text"], "hello%sworld")
        self.assertEqual(key["keyevent"], "KEYCODE_BACK")
        self.assertIn("exec-out", manager.run_calls[0])

    def test_policy_blocks_observe_only_control(self) -> None:
        service = AgentService(FakeManager())
        session = service.android_session_start("USB123", "inspect only", observe_only=True)["session"]

        result = service.android_tap(session["session_id"], 1, 2)

        self.assertEqual(result["status"], "blocked")
        self.assertIn("observe-only", result["reason"])

    def test_policy_requires_approval_for_risky_text_and_approval_executes(self) -> None:
        manager = FakeManager()
        service = AgentService(manager)
        session = service.android_session_start(
            "USB123",
            "test app",
            allowed_packages=["com.example.app"],
        )["session"]

        result = service.android_type_text(session["session_id"], "delete account")
        self.assertEqual(result["status"], "approval_required")

        approved = service.approve_action(session["session_id"], result["approval_id"])

        self.assertEqual(approved["result"]["status"], "completed")
        self.assertEqual(manager.adb_calls[-1][-2:], ("text", "delete%saccount"))

    def test_policy_blocks_package_outside_allowlist(self) -> None:
        service = AgentService(FakeManager())
        session = service.android_session_start(
            "USB123",
            "test app",
            allowed_packages=["com.example.app"],
        )["session"]

        result = service.android_start_app(session["session_id"], "com.other.app")

        self.assertEqual(result["status"], "blocked")
        self.assertIn("outside the session allowlist", result["reason"])

    def test_persistent_session_loads_in_new_service(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = Path(tmp) / "sessions"
            first = AgentService(FakeManager(), artifact_dir=Path(tmp) / "artifacts", session_dir=session_dir)
            session = first.android_session_start("USB123", "persist this session")["session"]

            second = AgentService(FakeManager(), artifact_dir=Path(tmp) / "artifacts", session_dir=session_dir)
            result = second.android_tap(session["session_id"], 5, 6)

            session_path = session_dir / f"{session['session_id']}.json"
            self.assertTrue(session_path.exists())
            self.assertEqual(result["result"]["status"], "completed")
            self.assertEqual(result["session"]["session_id"], session["session_id"])
            self.assertGreaterEqual(len(result["session"]["action_log"]), 2)

    def test_persistent_pending_approval_executes_in_new_service(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = Path(tmp) / "sessions"
            first = AgentService(FakeManager(), artifact_dir=Path(tmp) / "artifacts", session_dir=session_dir)
            session = first.android_session_start("USB123", "persist approval", allowed_packages=["com.example.app"])[
                "session"
            ]
            approval = first.android_type_text(session["session_id"], "delete account")

            manager = FakeManager()
            second = AgentService(manager, artifact_dir=Path(tmp) / "artifacts", session_dir=session_dir)
            result = second.approve_action(session["session_id"], approval["approval_id"])

            self.assertEqual(result["result"]["status"], "completed")
            self.assertEqual(manager.adb_calls[-1][-2:], ("text", "delete%saccount"))

    def test_missing_persistent_session_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = AgentService(FakeManager(), session_dir=Path(tmp) / "sessions")

            with self.assertRaises(ValueError):
                service.android_tap("missing-session", 1, 2)


class AgentCliTests(unittest.TestCase):
    def test_agent_parser_accepts_build_command(self) -> None:
        args = build_parser().parse_args(
            ["agent", "build-command", "MainPhone", "--quality", "high", "--extra=--no-control", "--json"]
        )

        self.assertEqual(args.command, "agent")
        self.assertEqual(args.agent_command, "build-command")
        self.assertEqual(args.profile_name, "MainPhone")
        self.assertEqual(args.quality, "high")
        self.assertEqual(args.extra, ["--no-control"])

    def test_agent_parser_accepts_all_expanded_commands(self) -> None:
        cases = [
            ["agent", "doctor", "--json"],
            ["agent", "scrcpy-version", "--json"],
            ["agent", "scrcpy-features", "--json"],
            ["agent", "scrcpy-options", "--json"],
            ["agent", "scrcpy-shortcuts", "--json"],
            ["agent", "scrcpy-recipes", "--json"],
            ["agent", "scrcpy-recipe", "virtual-app", "--package", "org.videolan.vlc", "--json"],
            ["agent", "validate-scrcpy-args", "--json", "--", "--no-control", "--new-display"],
            ["agent", "list-apps", "USB123", "--json"],
            ["agent", "list-cameras", "USB123", "--json"],
            ["agent", "list-camera-sizes", "USB123", "--json"],
            ["agent", "list-displays", "USB123", "--json"],
            ["agent", "list-encoders", "USB123", "--json"],
            ["agent", "discover-wireless", "--json"],
            ["agent", "connect-wireless", "192.168.1.2:5555", "--json"],
            ["agent", "pair-wireless", "192.168.1.2:37199", "123456", "--json"],
            ["agent", "shutdown-adb", "--json"],
            ["agent", "launch-profile", "MainPhone", "--quality", "high", "--extra=--no-control", "--json"],
            ["agent", "quick-launch", "MainPhone", "--foreground", "--json"],
            ["agent", "launch-app", "USB123", "com.example.app", "--mode", "app_only", "--json"],
            ["agent", "start-mirror", "USB123", "--json"],
            ["agent", "screenshot", "session-1", "--include-base64", "--json"],
            ["agent", "dump-ui", "session-1", "--json"],
            ["agent", "tap", "session-1", "10", "20", "--json"],
            ["agent", "swipe", "session-1", "1", "2", "3", "4", "--duration-ms", "100", "--json"],
            ["agent", "type-text", "session-1", "hello", "--json"],
            ["agent", "keyevent", "session-1", "back", "--json"],
            ["agent", "start-app", "session-1", "com.example.app", "--json"],
            ["agent", "wait", "session-1", "0.1", "--json"],
            ["agent", "approve", "session-1", "approval-1", "--json"],
        ]

        for case in cases:
            with self.subTest(case=case):
                args = build_parser().parse_args(case)
                self.assertEqual(args.command, "agent")

    def test_run_agent_command_dispatches_control_to_service(self) -> None:
        service = AgentService(FakeManager())
        session = service.android_session_start("USB123", "tap from cli")["session"]
        args = build_parser().parse_args(["agent", "tap", session["session_id"], "7", "8", "--json"])

        with contextlib.redirect_stdout(io.StringIO()):
            result = run_agent_command(args, service)

        self.assertEqual(result, 0)
        self.assertEqual(service.sessions[session["session_id"]].action_log[-1].action, "tap")

    def test_run_agent_command_dispatches_launch_to_service(self) -> None:
        service = AgentService(FakeManager())
        args = build_parser().parse_args(["agent", "launch-app", "USB123", "com.example.app", "--mode", "app_only"])

        with contextlib.redirect_stdout(io.StringIO()):
            result = run_agent_command(args, service)

        self.assertEqual(result, 0)

    def test_run_agent_command_dispatches_scrcpy_catalog_to_service(self) -> None:
        service = AgentService(FakeManager())
        args = build_parser().parse_args(["agent", "scrcpy-recipe", "virtual-app", "--package", "org.videolan.vlc"])

        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            result = run_agent_command(args, service)

        self.assertEqual(result, 0)
        self.assertIn("org.videolan.vlc", stdout.getvalue())


class McpServerTests(unittest.TestCase):
    def test_tools_list_exposes_android_session_start(self) -> None:
        server = ScrcpyMcpServer(AgentService(FakeManager()))

        response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

        names = {tool["name"] for tool in response["result"]["tools"]}  # type: ignore[index]
        self.assertIn("android_session_start", names)
        self.assertIn("build_scrcpy_command", names)

    def test_tool_call_returns_json_text(self) -> None:
        server = ScrcpyMcpServer(AgentService(FakeManager()))

        response = server.handle(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "get_profile", "arguments": {"profile_name": "MainPhone"}},
            }
        )

        content = response["result"]["content"][0]["text"]  # type: ignore[index]
        payload = json.loads(content)
        self.assertEqual(payload["profile"]["name"], "MainPhone")

    def test_scrcpy_resources_and_tools_return_catalog_data(self) -> None:
        server = ScrcpyMcpServer(AgentService(FakeManager()))

        resource = server.handle(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "resources/read",
                "params": {"uri": "scrctrl://scrcpy/shortcuts"},
            }
        )
        tool = server.handle(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "validate_scrcpy_args", "arguments": {"args": ["--no-control"]}},
            }
        )

        shortcut_payload = json.loads(resource["result"]["contents"][0]["text"])  # type: ignore[index]
        tool_payload = json.loads(tool["result"]["content"][0]["text"])  # type: ignore[index]
        flattened = {shortcut for item in shortcut_payload["shortcuts"] for shortcut in item["shortcuts"]}
        self.assertIn("MOD+q", flattened)
        self.assertTrue(tool_payload["ok"])


if __name__ == "__main__":
    unittest.main()
