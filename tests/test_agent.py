from __future__ import annotations

import configparser
import json
import tempfile
import unittest
from collections.abc import Sequence
from pathlib import Path
from subprocess import CompletedProcess, Popen
from typing import Any

from scrcpy_agent import AgentService, AndroidComputer
from scrcpy_cli import build_parser
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

    def test_launch_app_app_only_uses_monkey(self) -> None:
        manager = FakeManager()
        service = AgentService(manager)

        result = service.launch_app("USB123", "com.example.app", mode="app_only")

        self.assertEqual(result["status"], "completed")
        self.assertEqual(manager.adb_calls[-1][:6], ("-s", "USB123", "shell", "monkey", "-p", "com.example.app"))

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


if __name__ == "__main__":
    unittest.main()
