#!/usr/bin/env python3
"""Minimal MCP stdio server for ScrCtrl.

The server implements the MCP JSON-RPC methods used by local agent clients
without adding a runtime dependency. Tool results are JSON text payloads.
"""

from __future__ import annotations

import json
import sys
import traceback
from collections.abc import Callable
from typing import Any

from scrcpy_agent import AgentService

PROTOCOL_VERSION = "2025-03-26"


def _schema(properties: dict[str, dict[str, Any]], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


TOOLS: dict[str, dict[str, Any]] = {
    "list_devices": {
        "description": "List connected ADB devices.",
        "inputSchema": _schema({}),
    },
    "list_profiles": {
        "description": "List saved ScrCtrl device profiles.",
        "inputSchema": _schema({}),
    },
    "get_profile": {
        "description": "Read one ScrCtrl profile by name.",
        "inputSchema": _schema({"profile_name": {"type": "string"}}, ["profile_name"]),
    },
    "get_quality_presets": {
        "description": "List quality presets from config/quality.ini.",
        "inputSchema": _schema({}),
    },
    "build_scrcpy_command": {
        "description": "Build the scrcpy command for a profile without launching it.",
        "inputSchema": _schema(
            {
                "profile_name": {"type": "string"},
                "connection": {"type": "string"},
                "connection_type": {"type": "string"},
                "mode_override": {"type": "string"},
                "quality_override": {"type": "string"},
                "extra": {"type": "array", "items": {"type": "string"}},
            },
            ["profile_name"],
        ),
    },
    "discover_wireless": {
        "description": "Discover wireless-debuggable Android devices via ADB mDNS.",
        "inputSchema": _schema({}),
    },
    "connect_wireless": {
        "description": "Connect to a wireless ADB endpoint such as 192.168.1.20:5555.",
        "inputSchema": _schema({"ipport": {"type": "string"}}, ["ipport"]),
    },
    "pair_wireless": {
        "description": "Pair with an Android 11+ wireless debugging endpoint.",
        "inputSchema": _schema(
            {"ipport": {"type": "string"}, "pairing_code": {"type": "string"}},
            ["ipport", "pairing_code"],
        ),
    },
    "shutdown_adb": {
        "description": "Disconnect ADB devices and stop the ADB server.",
        "inputSchema": _schema({}),
    },
    "launch_profile": {
        "description": "Launch scrcpy for a saved profile. Defaults to detached mode.",
        "inputSchema": _schema(
            {
                "profile_name": {"type": "string"},
                "extra": {"type": "array", "items": {"type": "string"}},
                "quality_override": {"type": "string"},
                "detach": {"type": "boolean"},
            },
            ["profile_name"],
        ),
    },
    "quick_launch": {
        "description": "Quick launch the last used profile or an explicitly named profile.",
        "inputSchema": _schema(
            {
                "profile_name": {"type": "string"},
                "extra": {"type": "array", "items": {"type": "string"}},
                "quality_override": {"type": "string"},
                "detach": {"type": "boolean"},
            },
        ),
    },
    "launch_app": {
        "description": "Launch an Android app by package, optionally through scrcpy.",
        "inputSchema": _schema(
            {
                "serial": {"type": "string"},
                "package": {"type": "string"},
                "mode": {"type": "string", "enum": ["mirror", "virtual", "app_only"]},
                "flex_display": {"type": "boolean"},
                "detach": {"type": "boolean"},
            },
            ["serial", "package"],
        ),
    },
    "start_mirror": {
        "description": "Start mirroring a profile or connected serial.",
        "inputSchema": _schema(
            {"profile_or_serial": {"type": "string"}, "detach": {"type": "boolean"}}, ["profile_or_serial"]
        ),
    },
    "android_session_start": {
        "description": "Start an Android CUA-style session. Control tools require the returned session_id.",
        "inputSchema": _schema(
            {
                "profile_or_serial": {"type": "string"},
                "goal": {"type": "string"},
                "allowed_packages": {"type": "array", "items": {"type": "string"}},
                "observe_only": {"type": "boolean"},
            },
            ["profile_or_serial", "goal"],
        ),
    },
    "android_screenshot": {
        "description": "Capture a direct device screenshot for a session.",
        "inputSchema": _schema(
            {"session_id": {"type": "string"}, "include_base64": {"type": "boolean"}}, ["session_id"]
        ),
    },
    "android_dump_ui": {
        "description": "Dump and summarize the Android UI hierarchy for a session.",
        "inputSchema": _schema({"session_id": {"type": "string"}}, ["session_id"]),
    },
    "android_tap": {
        "description": "Tap device coordinates in a session.",
        "inputSchema": _schema(
            {"session_id": {"type": "string"}, "x": {"type": "integer"}, "y": {"type": "integer"}},
            ["session_id", "x", "y"],
        ),
    },
    "android_swipe": {
        "description": "Swipe between device coordinates in a session.",
        "inputSchema": _schema(
            {
                "session_id": {"type": "string"},
                "x1": {"type": "integer"},
                "y1": {"type": "integer"},
                "x2": {"type": "integer"},
                "y2": {"type": "integer"},
                "duration_ms": {"type": "integer"},
            },
            ["session_id", "x1", "y1", "x2", "y2"],
        ),
    },
    "android_type_text": {
        "description": "Type text into the active Android input field.",
        "inputSchema": _schema({"session_id": {"type": "string"}, "text": {"type": "string"}}, ["session_id", "text"]),
    },
    "android_keyevent": {
        "description": "Send an Android keyevent by common key name or KEYCODE_* value.",
        "inputSchema": _schema({"session_id": {"type": "string"}, "key": {"type": "string"}}, ["session_id", "key"]),
    },
    "android_start_app": {
        "description": "Start an Android app inside an existing session.",
        "inputSchema": _schema(
            {"session_id": {"type": "string"}, "package": {"type": "string"}}, ["session_id", "package"]
        ),
    },
    "android_wait": {
        "description": "Wait for the device UI to settle.",
        "inputSchema": _schema({"session_id": {"type": "string"}, "seconds": {"type": "number"}}, ["session_id"]),
    },
    "approve_action": {
        "description": "Approve and execute one pending risky Android action.",
        "inputSchema": _schema(
            {"session_id": {"type": "string"}, "approval_id": {"type": "string"}},
            ["session_id", "approval_id"],
        ),
    },
    "get_scrcpy_version": {
        "description": "Return the bundled scrcpy version.",
        "inputSchema": _schema({}),
    },
    "list_scrcpy_features": {
        "description": "List curated scrcpy feature groups and agent use cases.",
        "inputSchema": _schema({}),
    },
    "list_scrcpy_options": {
        "description": "List curated scrcpy options with local help availability.",
        "inputSchema": _schema({}),
    },
    "list_scrcpy_shortcuts": {
        "description": "List scrcpy keyboard and mouse shortcuts.",
        "inputSchema": _schema({}),
    },
    "recommend_scrcpy_recipe": {
        "description": "Return recipe-generated scrcpy args for a known workflow.",
        "inputSchema": _schema(
            {
                "name": {"type": "string"},
                "package": {"type": "string"},
                "record_file": {"type": "string"},
            },
            ["name"],
        ),
    },
    "validate_scrcpy_args": {
        "description": "Validate explicit scrcpy extra args against the bundled binary's option surface.",
        "inputSchema": _schema({"args": {"type": "array", "items": {"type": "string"}}}, ["args"]),
    },
    "list_apps": {
        "description": "Run scrcpy --list-apps for a device serial.",
        "inputSchema": _schema({"serial": {"type": "string"}}, ["serial"]),
    },
    "list_cameras": {
        "description": "Run scrcpy --list-cameras for a device serial.",
        "inputSchema": _schema({"serial": {"type": "string"}}, ["serial"]),
    },
    "list_camera_sizes": {
        "description": "Run scrcpy --list-camera-sizes for a device serial.",
        "inputSchema": _schema({"serial": {"type": "string"}}, ["serial"]),
    },
    "list_displays": {
        "description": "Run scrcpy --list-displays for a device serial.",
        "inputSchema": _schema({"serial": {"type": "string"}}, ["serial"]),
    },
    "list_encoders": {
        "description": "Run scrcpy --list-encoders for a device serial.",
        "inputSchema": _schema({"serial": {"type": "string"}}, ["serial"]),
    },
}


PROMPTS: dict[str, str] = {
    "connect-my-device": "Use ScrCtrl tools to discover, pair, or connect my Android device. Ask before pairing.",
    "launch-profile": "Use ScrCtrl profiles and launch the requested device profile with suitable quality settings.",
    "debug-android-app": "Start an Android session, capture screenshots and UI dumps, then inspect the requested app.",
    "operate-android-device": "Operate the Android device using only session-scoped tools and respect approval_required responses.",
    "record-device-session": "Build or launch a ScrCtrl profile with recording enabled and report the command that will run.",
}


class ScrcpyMcpServer:
    def __init__(self, service: AgentService | None = None) -> None:
        self.service = service or AgentService()

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        message_id = message.get("id")
        try:
            if method == "notifications/initialized":
                return None
            if method == "initialize":
                return self._result(
                    message_id,
                    {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                        "serverInfo": {"name": "scrctrl", "version": "1.0.0"},
                    },
                )
            if method == "tools/list":
                return self._result(message_id, {"tools": self._tools_list()})
            if method == "tools/call":
                params = message.get("params") or {}
                return self._tool_call(message_id, params.get("name", ""), params.get("arguments") or {})
            if method == "resources/list":
                return self._result(message_id, {"resources": self._resources_list()})
            if method == "resources/templates/list":
                return self._result(
                    message_id,
                    {
                        "resourceTemplates": [
                            {
                                "uriTemplate": "scrctrl://profiles/{name}",
                                "name": "profile",
                                "title": "ScrCtrl profile",
                                "mimeType": "application/json",
                            }
                        ]
                    },
                )
            if method == "resources/read":
                uri = (message.get("params") or {}).get("uri", "")
                return self._resource_read(message_id, uri)
            if method == "prompts/list":
                return self._result(message_id, {"prompts": self._prompts_list()})
            if method == "prompts/get":
                name = (message.get("params") or {}).get("name", "")
                return self._prompt_get(message_id, name)
            return self._error(message_id, -32601, f"Unknown method: {method}")
        except Exception as exc:
            return self._error(message_id, -32000, str(exc), {"traceback": traceback.format_exc()})

    def _tool_call(self, message_id: Any, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        handlers: dict[str, Callable[..., dict[str, Any]]] = {
            "list_devices": self.service.list_devices,
            "list_profiles": self.service.list_profiles,
            "get_profile": self.service.get_profile,
            "get_quality_presets": self.service.get_quality_presets,
            "build_scrcpy_command": self.service.build_scrcpy_command,
            "discover_wireless": self.service.discover_wireless,
            "connect_wireless": self.service.connect_wireless,
            "pair_wireless": self.service.pair_wireless,
            "shutdown_adb": self.service.shutdown_adb,
            "launch_profile": self.service.launch_profile,
            "quick_launch": self.service.quick_launch,
            "launch_app": self.service.launch_app,
            "start_mirror": self.service.start_mirror,
            "android_session_start": self.service.android_session_start,
            "android_screenshot": self.service.android_screenshot,
            "android_dump_ui": self.service.android_dump_ui,
            "android_tap": self.service.android_tap,
            "android_swipe": self.service.android_swipe,
            "android_type_text": self.service.android_type_text,
            "android_keyevent": self.service.android_keyevent,
            "android_start_app": self.service.android_start_app,
            "android_wait": self.service.android_wait,
            "approve_action": self.service.approve_action,
            "get_scrcpy_version": self.service.get_scrcpy_version,
            "list_scrcpy_features": self.service.list_scrcpy_features,
            "list_scrcpy_options": self.service.list_scrcpy_options,
            "list_scrcpy_shortcuts": self.service.list_scrcpy_shortcuts,
            "recommend_scrcpy_recipe": self.service.recommend_scrcpy_recipe,
            "validate_scrcpy_args": self.service.validate_scrcpy_args,
            "list_apps": self.service.list_apps,
            "list_cameras": self.service.list_cameras,
            "list_camera_sizes": self.service.list_camera_sizes,
            "list_displays": self.service.list_displays,
            "list_encoders": self.service.list_encoders,
        }
        handler = handlers.get(name)
        if not handler:
            return self._error(message_id, -32602, f"Unknown tool: {name}")
        try:
            data = handler(**arguments)
            return self._result(message_id, {"content": [{"type": "text", "text": json.dumps(data, indent=2)}]})
        except Exception as exc:
            payload = {"error": str(exc)}
            return self._result(
                message_id,
                {"content": [{"type": "text", "text": json.dumps(payload, indent=2)}], "isError": True},
            )

    def _resource_read(self, message_id: Any, uri: str) -> dict[str, Any]:
        if uri == "scrctrl://devices":
            data = self.service.list_devices()
        elif uri == "scrctrl://profiles":
            data = self.service.list_profiles()
        elif uri.startswith("scrctrl://profiles/"):
            data = self.service.get_profile(uri.removeprefix("scrctrl://profiles/"))
        elif uri == "scrctrl://quality-presets":
            data = self.service.get_quality_presets()
        elif uri == "scrctrl://last-used":
            data = self.service.get_last_used()
        elif uri == "scrctrl://agent/capabilities":
            data = self.service.capabilities()
        elif uri == "scrctrl://scrcpy/version":
            data = self.service.get_scrcpy_version()
        elif uri == "scrctrl://scrcpy/features":
            data = self.service.list_scrcpy_features()
        elif uri == "scrctrl://scrcpy/options":
            data = self.service.list_scrcpy_options()
        elif uri == "scrctrl://scrcpy/shortcuts":
            data = self.service.list_scrcpy_shortcuts()
        elif uri == "scrctrl://scrcpy/recipes":
            data = self.service.list_scrcpy_recipes()
        else:
            return self._error(message_id, -32602, f"Unknown resource: {uri}")
        return self._result(
            message_id,
            {"contents": [{"uri": uri, "mimeType": "application/json", "text": json.dumps(data, indent=2)}]},
        )

    def _prompt_get(self, message_id: Any, name: str) -> dict[str, Any]:
        text = PROMPTS.get(name)
        if not text:
            return self._error(message_id, -32602, f"Unknown prompt: {name}")
        return self._result(
            message_id,
            {
                "description": text,
                "messages": [
                    {
                        "role": "user",
                        "content": {"type": "text", "text": text},
                    }
                ],
            },
        )

    @staticmethod
    def _tools_list() -> list[dict[str, Any]]:
        return [{"name": name, **definition} for name, definition in TOOLS.items()]

    @staticmethod
    def _resources_list() -> list[dict[str, str]]:
        return [
            {
                "uri": "scrctrl://devices",
                "name": "devices",
                "title": "Connected devices",
                "mimeType": "application/json",
            },
            {
                "uri": "scrctrl://profiles",
                "name": "profiles",
                "title": "Saved profiles",
                "mimeType": "application/json",
            },
            {
                "uri": "scrctrl://quality-presets",
                "name": "quality-presets",
                "title": "Quality presets",
                "mimeType": "application/json",
            },
            {
                "uri": "scrctrl://last-used",
                "name": "last-used",
                "title": "Last used profile",
                "mimeType": "application/json",
            },
            {
                "uri": "scrctrl://agent/capabilities",
                "name": "agent-capabilities",
                "title": "Agent capabilities",
                "mimeType": "application/json",
            },
            {
                "uri": "scrctrl://scrcpy/version",
                "name": "scrcpy-version",
                "title": "scrcpy version",
                "mimeType": "application/json",
            },
            {
                "uri": "scrctrl://scrcpy/features",
                "name": "scrcpy-features",
                "title": "scrcpy features",
                "mimeType": "application/json",
            },
            {
                "uri": "scrctrl://scrcpy/options",
                "name": "scrcpy-options",
                "title": "scrcpy options",
                "mimeType": "application/json",
            },
            {
                "uri": "scrctrl://scrcpy/shortcuts",
                "name": "scrcpy-shortcuts",
                "title": "scrcpy shortcuts",
                "mimeType": "application/json",
            },
            {
                "uri": "scrctrl://scrcpy/recipes",
                "name": "scrcpy-recipes",
                "title": "scrcpy recipes",
                "mimeType": "application/json",
            },
        ]

    @staticmethod
    def _prompts_list() -> list[dict[str, str]]:
        return [
            {"name": name, "title": name.replace("-", " ").title(), "description": description}
            for name, description in PROMPTS.items()
        ]

    @staticmethod
    def _result(message_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": message_id, "result": result}

    @staticmethod
    def _error(message_id: Any, code: int, message: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        error: dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        return {"jsonrpc": "2.0", "id": message_id, "error": error}


def main() -> int:
    server = ScrcpyMcpServer()
    for line in sys.stdin:
        if not line.strip():
            continue
        response: dict[str, Any] | None
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            response = ScrcpyMcpServer._error(None, -32700, str(exc))
        else:
            response = server.handle(message)
        if response is not None:
            sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
