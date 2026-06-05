#!/usr/bin/env python3
"""Agent-facing APIs for ScrCtrl.

This module keeps agent and CUA-style automation prompt-free and JSON-safe
while delegating profile, ADB, and scrcpy behavior to ScrcpyManager.
"""

from __future__ import annotations

import base64
import contextlib
import io
import json
import re
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path
from subprocess import Popen
from typing import Any

from scrcpy_manager import (
    ADB_EXE,
    DEFAULT_ADB_PORT,
    SCRCPY_EXE,
    Device,
    ScrcpyManager,
    is_valid_package_name,
    quote_command,
    sanitize_profile_name,
)

KEYEVENTS: dict[str, str] = {
    "back": "KEYCODE_BACK",
    "home": "KEYCODE_HOME",
    "enter": "KEYCODE_ENTER",
    "tab": "KEYCODE_TAB",
    "space": "KEYCODE_SPACE",
    "escape": "KEYCODE_ESCAPE",
    "esc": "KEYCODE_ESCAPE",
    "app_switch": "KEYCODE_APP_SWITCH",
    "recent": "KEYCODE_APP_SWITCH",
    "power": "KEYCODE_POWER",
    "volume_up": "KEYCODE_VOLUME_UP",
    "volume_down": "KEYCODE_VOLUME_DOWN",
    "menu": "KEYCODE_MENU",
    "search": "KEYCODE_SEARCH",
    "delete": "KEYCODE_DEL",
    "del": "KEYCODE_DEL",
}

RISKY_TEXT_PATTERNS = (
    "password",
    "passcode",
    "credit card",
    "card number",
    "cvv",
    "otp",
    "2fa",
    "delete",
    "erase",
    "factory reset",
    "reset",
    "purchase",
    "buy",
    "pay",
    "payment",
    "permission",
    "allow",
)

RISKY_PACKAGES = (
    "com.android.vending",
    "com.google.android.permissioncontroller",
    "com.android.permissioncontroller",
    "com.google.android.packageinstaller",
    "com.android.packageinstaller",
    "com.android.settings",
)


def _jsonable_process_result(value: int | Popen[Any]) -> dict[str, Any]:
    if isinstance(value, Popen):
        return {"status": "launched", "pid": value.pid}
    return {"status": "completed", "exit_code": value}


def _normalize_allowed_packages(allowed_packages: list[str] | None) -> set[str]:
    if not allowed_packages:
        return set()
    return {package.strip() for package in allowed_packages if package.strip()}


def _adb_input_text(value: str) -> str:
    """Escape text for `adb shell input text`.

    The Android input command uses `%s` for spaces. Passing the command through
    subprocess argument lists avoids host-shell quoting issues.
    """
    return value.replace("%", "%25").replace(" ", "%s")


@dataclass
class AndroidActionLog:
    action: str
    status: str
    timestamp: float
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class AndroidSession:
    session_id: str
    serial: str
    goal: str
    allowed_packages: set[str] = field(default_factory=set)
    observe_only: bool = False
    created_at: float = field(default_factory=time.time)
    last_screenshot: str = ""
    last_ui_dump: str = ""
    current_package: str = ""
    action_log: list[AndroidActionLog] = field(default_factory=list)
    pending_approvals: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "serial": self.serial,
            "goal": self.goal,
            "allowed_packages": sorted(self.allowed_packages),
            "observe_only": self.observe_only,
            "created_at": self.created_at,
            "last_screenshot": self.last_screenshot,
            "last_ui_dump": self.last_ui_dump,
            "current_package": self.current_package,
            "action_log": [asdict(item) for item in self.action_log],
            "pending_approvals": list(self.pending_approvals),
        }


class AndroidComputer:
    """ADB-backed Android computer environment."""

    def __init__(self, manager: ScrcpyManager, serial: str, artifact_dir: Path | None = None) -> None:
        self.manager = manager
        self.serial = serial
        self.artifact_dir = artifact_dir or Path(tempfile.gettempdir()) / "scrctrl-agent"
        self.artifact_dir.mkdir(parents=True, exist_ok=True)

    def screenshot(self, *, include_base64: bool = False) -> dict[str, Any]:
        completed = self.manager.run(
            [str(ADB_EXE), "-s", self.serial, "exec-out", "screencap", "-p"],
            text=False,
            capture_output=True,
        )
        raw = completed.stdout or b""
        if isinstance(raw, str):
            raw_bytes = raw.encode("latin1")
        else:
            raw_bytes = raw
        path = self.artifact_dir / f"{self.serial}-{int(time.time() * 1000)}.png"
        path.write_bytes(raw_bytes)
        result: dict[str, Any] = {
            "serial": self.serial,
            "path": str(path),
            "bytes": len(raw_bytes),
            "format": "png",
            "adb": ["exec-out", "screencap", "-p"],
        }
        if include_base64:
            result["base64"] = base64.b64encode(raw_bytes).decode("ascii")
        return result

    def dump_ui(self) -> dict[str, Any]:
        remote_path = "/sdcard/window_dump.xml"
        dump = self.manager.adb("-s", self.serial, "shell", "uiautomator", "dump", remote_path)
        xml_result = self.manager.adb("-s", self.serial, "exec-out", "cat", remote_path)
        xml_text = (xml_result.stdout or "").strip()
        path = self.artifact_dir / f"{self.serial}-{int(time.time() * 1000)}.xml"
        path.write_text(xml_text, encoding="utf-8")
        nodes = self._summarize_ui_nodes(xml_text)
        return {
            "serial": self.serial,
            "path": str(path),
            "dump_output": (dump.stdout or dump.stderr or "").strip(),
            "nodes": nodes,
            "node_count": len(nodes),
            "adb": ["shell", "uiautomator", "dump", remote_path],
        }

    def tap(self, x: int, y: int) -> dict[str, Any]:
        completed = self.manager.adb("-s", self.serial, "shell", "input", "tap", str(x), str(y))
        return self._completed("tap", completed.returncode, {"x": x, "y": y})

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> dict[str, Any]:
        completed = self.manager.adb(
            "-s",
            self.serial,
            "shell",
            "input",
            "swipe",
            str(x1),
            str(y1),
            str(x2),
            str(y2),
            str(duration_ms),
        )
        return self._completed(
            "swipe",
            completed.returncode,
            {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "duration_ms": duration_ms},
        )

    def type_text(self, text: str) -> dict[str, Any]:
        escaped = _adb_input_text(text)
        completed = self.manager.adb("-s", self.serial, "shell", "input", "text", escaped)
        return self._completed("type_text", completed.returncode, {"text": text, "adb_text": escaped})

    def keyevent(self, key: str) -> dict[str, Any]:
        key_name = KEYEVENTS.get(key.strip().lower(), key.strip())
        completed = self.manager.adb("-s", self.serial, "shell", "input", "keyevent", key_name)
        return self._completed("keyevent", completed.returncode, {"key": key, "keyevent": key_name})

    def start_app(self, package: str) -> dict[str, Any]:
        if not is_valid_package_name(package):
            raise ValueError(f"Invalid package name: {package}")
        completed = self.manager.adb(
            "-s",
            self.serial,
            "shell",
            "monkey",
            "-p",
            package,
            "-c",
            "android.intent.category.LAUNCHER",
            "1",
        )
        return self._completed("start_app", completed.returncode, {"package": package})

    def wait(self, seconds: float = 1.0) -> dict[str, Any]:
        time.sleep(max(0.0, seconds))
        return {"status": "completed", "action": "wait", "seconds": seconds}

    def current_foreground_package(self) -> str:
        commands = (
            ["cmd", "window", "get-top-activity"],
            ["dumpsys", "window", "windows"],
            ["dumpsys", "activity", "activities"],
        )
        patterns = (
            re.compile(r"([a-zA-Z0-9_]+(?:\.[a-zA-Z0-9_]+)+)/"),
            re.compile(r"packageName=([a-zA-Z0-9_]+(?:\.[a-zA-Z0-9_]+)+)"),
        )
        for command in commands:
            try:
                output = self.manager.adb_shell(self.serial, command)
            except Exception:
                continue
            for pattern in patterns:
                match = pattern.search(output)
                if match:
                    return match.group(1)
        return ""

    @staticmethod
    def _summarize_ui_nodes(xml_text: str) -> list[dict[str, str]]:
        if not xml_text:
            return []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return []
        nodes: list[dict[str, str]] = []
        for node in root.iter("node"):
            attrs = {
                "text": node.attrib.get("text", ""),
                "resource_id": node.attrib.get("resource-id", ""),
                "class": node.attrib.get("class", ""),
                "content_desc": node.attrib.get("content-desc", ""),
                "bounds": node.attrib.get("bounds", ""),
                "clickable": node.attrib.get("clickable", ""),
                "enabled": node.attrib.get("enabled", ""),
            }
            if any(attrs.values()):
                nodes.append(attrs)
        return nodes

    @staticmethod
    def _completed(action: str, returncode: int, details: dict[str, Any]) -> dict[str, Any]:
        return {"status": "completed" if returncode == 0 else "failed", "action": action, "returncode": returncode, **details}


class AgentService:
    """Prompt-free service layer for agent integrations."""

    def __init__(self, manager: ScrcpyManager | None = None, artifact_dir: Path | None = None) -> None:
        self.manager = manager or ScrcpyManager()
        self.artifact_dir = artifact_dir or Path(tempfile.gettempdir()) / "scrctrl-agent"
        self.sessions: dict[str, AndroidSession] = {}

    def capabilities(self) -> dict[str, Any]:
        return {
            "name": "ScrCtrl Agent",
            "version": "1",
            "surfaces": ["mcp", "cli-json"],
            "resources": [
                "scrctrl://devices",
                "scrctrl://profiles",
                "scrctrl://profiles/{name}",
                "scrctrl://quality-presets",
                "scrctrl://last-used",
                "scrctrl://agent/capabilities",
            ],
            "tools": [
                "list_devices",
                "list_profiles",
                "get_profile",
                "get_quality_presets",
                "build_scrcpy_command",
                "discover_wireless",
                "connect_wireless",
                "pair_wireless",
                "shutdown_adb",
                "launch_profile",
                "quick_launch",
                "launch_app",
                "start_mirror",
                "android_session_start",
                "android_screenshot",
                "android_dump_ui",
                "android_tap",
                "android_swipe",
                "android_type_text",
                "android_keyevent",
                "android_start_app",
                "android_wait",
                "approve_action",
            ],
            "safety": {
                "default": "human approval for risky actions",
                "observe_only_supported": True,
                "package_allowlist_supported": True,
                "arbitrary_adb_shell": False,
            },
        }

    def list_devices(self) -> dict[str, Any]:
        return {"devices": [asdict(device) for device in self.manager.list_devices()]}

    def list_profiles(self) -> dict[str, Any]:
        return {"profiles": self.manager.list_profiles()}

    def get_profile(self, profile_name: str) -> dict[str, Any]:
        return {"profile": self.manager.get_profile(profile_name)}

    def get_quality_presets(self) -> dict[str, Any]:
        parser = self.manager.get_quality_config()
        return {
            "quality_presets": [
                {"name": section, **{key: parser.get(section, key, fallback="") for key in parser.options(section)}}
                for section in parser.sections()
            ]
        }

    def get_last_used(self) -> dict[str, Any]:
        parser = self.manager.get_last_used()
        return {"last_used": dict(parser.items("lastused")) if parser.has_section("lastused") else {}}

    def build_scrcpy_command(
        self,
        profile_name: str,
        *,
        connection: str | None = None,
        connection_type: str | None = None,
        mode_override: str | None = None,
        quality_override: str | None = None,
        extra: list[str] | None = None,
    ) -> dict[str, Any]:
        profile = self.manager.get_profile(profile_name)
        resolved_connection = connection or profile.get("serial") or (
            f"{profile.get('ip')}:{DEFAULT_ADB_PORT}" if profile.get("ip") else ""
        )
        resolved_type = connection_type or ("wireless" if ":" in resolved_connection else "USB")
        args = self.manager.build_scrcpy_args(
            profile=profile,
            connection=resolved_connection,
            connection_type=resolved_type,
            mode_override=mode_override,
            quality_override=quality_override,
            extra=extra or [],
        )
        command = [str(SCRCPY_EXE), *args]
        return {
            "profile": profile_name,
            "connection": resolved_connection,
            "connection_type": resolved_type,
            "args": args,
            "command": command,
            "command_text": quote_command(command),
        }

    def discover_wireless(self) -> dict[str, Any]:
        return {"devices": [asdict(device) for device in self.manager.mdns_discover()]}

    def connect_wireless(self, ipport: str) -> dict[str, Any]:
        (success, message, serial), output = self._call_quietly(self.manager.connect_wireless, ipport)
        return {"success": success, "message": message, "serial": serial, "output": output}

    def pair_wireless(self, ipport: str, pairing_code: str) -> dict[str, Any]:
        (success, message), output = self._call_quietly(self.manager.pair_device, ipport, pairing_code)
        return {"success": success, "message": message, "output": output}

    def shutdown_adb(self) -> dict[str, Any]:
        exit_code, output = self._call_quietly(self.manager.shutdown)
        return {"exit_code": exit_code, "output": output}

    def launch_profile(
        self,
        profile_name: str,
        *,
        extra: list[str] | None = None,
        quality_override: str | None = None,
        detach: bool = True,
    ) -> dict[str, Any]:
        result, output = self._call_quietly(
            self.manager.launch_profile,
            profile_name,
            extra=extra or [],
            quality_override=quality_override,
            detach=detach,
        )
        payload = _jsonable_process_result(result)
        payload["output"] = output
        return payload

    def quick_launch(
        self,
        profile_name: str | None = None,
        *,
        extra: list[str] | None = None,
        quality_override: str | None = None,
        detach: bool = True,
    ) -> dict[str, Any]:
        result, output = self._call_quietly(
            self.manager.quick_launch,
            profile_name,
            extra=extra or [],
            quality_override=quality_override,
            detach=detach,
        )
        payload = _jsonable_process_result(result)
        payload["output"] = output
        return payload

    def launch_app(
        self,
        serial: str,
        package: str,
        *,
        mode: str = "mirror",
        flex_display: bool = False,
        detach: bool = True,
    ) -> dict[str, Any]:
        if not is_valid_package_name(package):
            raise ValueError(f"Invalid package name: {package}")
        if mode not in {"mirror", "virtual", "app_only"}:
            raise ValueError("mode must be one of: mirror, virtual, app_only")
        if mode == "app_only":
            computer = AndroidComputer(self.manager, serial, self.artifact_dir)
            return computer.start_app(package)
        args = ["-s", serial, f"--start-app={package}", "--window-title", f"scrcpy - {serial} ({package})"]
        if mode == "virtual":
            args.append("--new-display")
            if flex_display:
                args.append("--flex-display")
        result = self.manager.scrcpy(args, detach=detach)
        return _jsonable_process_result(result)

    def start_mirror(self, profile_or_serial: str, *, detach: bool = True) -> dict[str, Any]:
        try:
            self.manager.get_profile(profile_or_serial)
            return self.launch_profile(profile_or_serial, detach=detach)
        except ValueError:
            device = Device(serial=profile_or_serial, state="device", kind="WIRELESS" if ":" in profile_or_serial else "USB")
            temp_profile_name = sanitize_profile_name(profile_or_serial)
            profile = {
                "name": temp_profile_name,
                "nickname": profile_or_serial,
                "ip": "",
                "serial": profile_or_serial,
                "quality": "balanced",
                "mode": "mirror",
            }
            args = self.manager.build_scrcpy_args(profile=profile, connection=device.serial, connection_type=device.kind)
            return _jsonable_process_result(self.manager.scrcpy(args, detach=detach))

    def android_session_start(
        self,
        profile_or_serial: str,
        goal: str,
        *,
        allowed_packages: list[str] | None = None,
        observe_only: bool = False,
    ) -> dict[str, Any]:
        serial = self._resolve_serial(profile_or_serial)
        session = AndroidSession(
            session_id=str(uuid.uuid4()),
            serial=serial,
            goal=goal,
            allowed_packages=_normalize_allowed_packages(allowed_packages),
            observe_only=observe_only,
        )
        session.current_package = AndroidComputer(self.manager, serial, self.artifact_dir).current_foreground_package()
        self.sessions[session.session_id] = session
        self._log(session, "session_start", "completed", {"profile_or_serial": profile_or_serial})
        return {"session": session.to_dict()}

    def android_screenshot(self, session_id: str, *, include_base64: bool = False) -> dict[str, Any]:
        session = self._session(session_id)
        result = AndroidComputer(self.manager, session.serial, self.artifact_dir).screenshot(include_base64=include_base64)
        session.last_screenshot = result["path"]
        self._log(session, "screenshot", "completed", {"path": result["path"]})
        return {"session": session.to_dict(), "screenshot": result}

    def android_dump_ui(self, session_id: str) -> dict[str, Any]:
        session = self._session(session_id)
        result = AndroidComputer(self.manager, session.serial, self.artifact_dir).dump_ui()
        session.last_ui_dump = result["path"]
        self._log(session, "dump_ui", "completed", {"path": result["path"], "node_count": result["node_count"]})
        return {"session": session.to_dict(), "ui": result}

    def android_tap(self, session_id: str, x: int, y: int) -> dict[str, Any]:
        return self._control(session_id, "tap", {"x": x, "y": y})

    def android_swipe(self, session_id: str, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> dict[str, Any]:
        return self._control(
            session_id,
            "swipe",
            {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "duration_ms": duration_ms},
        )

    def android_type_text(self, session_id: str, text: str) -> dict[str, Any]:
        return self._control(session_id, "type_text", {"text": text})

    def android_keyevent(self, session_id: str, key: str) -> dict[str, Any]:
        return self._control(session_id, "keyevent", {"key": key})

    def android_start_app(self, session_id: str, package: str) -> dict[str, Any]:
        return self._control(session_id, "start_app", {"package": package})

    def android_wait(self, session_id: str, seconds: float = 1.0) -> dict[str, Any]:
        session = self._session(session_id)
        result = AndroidComputer(self.manager, session.serial, self.artifact_dir).wait(seconds)
        self._log(session, "wait", "completed", {"seconds": seconds})
        return {"session": session.to_dict(), "result": result}

    def approve_action(self, session_id: str, approval_id: str) -> dict[str, Any]:
        session = self._session(session_id)
        action = session.pending_approvals.pop(approval_id, None)
        if not action:
            raise ValueError(f"Approval '{approval_id}' was not found")
        result = self._execute_control(session, action["action"], action["params"])
        self._log(session, action["action"], result.get("status", "completed"), {"approval_id": approval_id, **action["params"]})
        return {"session": session.to_dict(), "result": result}

    def _resolve_serial(self, profile_or_serial: str) -> str:
        try:
            profile = self.manager.get_profile(profile_or_serial)
        except ValueError:
            return profile_or_serial
        serial = profile.get("serial", "")
        connected = {device.serial for device in self.manager.list_devices()}
        if serial and serial in connected:
            return serial
        ip = profile.get("ip", "")
        if ip:
            (success, message, connected_serial), _output = self._call_quietly(
                self.manager.connect_wireless,
                f"{ip}:{DEFAULT_ADB_PORT}",
            )
            if success and connected_serial:
                return str(connected_serial)
            raise RuntimeError(f"Failed to connect to {ip}: {message}")
        if serial:
            return serial
        raise RuntimeError(f"Profile '{profile_or_serial}' has no usable serial or IP")

    def _control(self, session_id: str, action: str, params: dict[str, Any]) -> dict[str, Any]:
        session = self._session(session_id)
        policy = self._check_policy(session, action, params)
        if policy:
            self._log(session, action, policy["status"], params)
            return {"session": session.to_dict(), **policy}
        result = self._execute_control(session, action, params)
        self._log(session, action, result.get("status", "completed"), params)
        return {"session": session.to_dict(), "result": result}

    def _execute_control(self, session: AndroidSession, action: str, params: dict[str, Any]) -> dict[str, Any]:
        computer = AndroidComputer(self.manager, session.serial, self.artifact_dir)
        if action == "tap":
            result = computer.tap(int(params["x"]), int(params["y"]))
        elif action == "swipe":
            result = computer.swipe(
                int(params["x1"]),
                int(params["y1"]),
                int(params["x2"]),
                int(params["y2"]),
                int(params.get("duration_ms", 300)),
            )
        elif action == "type_text":
            result = computer.type_text(str(params["text"]))
        elif action == "keyevent":
            result = computer.keyevent(str(params["key"]))
        elif action == "start_app":
            result = computer.start_app(str(params["package"]))
            session.current_package = str(params["package"])
        else:
            raise ValueError(f"Unsupported Android action: {action}")
        if action != "start_app":
            session.current_package = computer.current_foreground_package() or session.current_package
        return result

    def _check_policy(self, session: AndroidSession, action: str, params: dict[str, Any]) -> dict[str, Any] | None:
        if session.observe_only:
            return {"status": "blocked", "reason": "Session is observe-only"}

        package = str(params.get("package", ""))
        if package and session.allowed_packages and package not in session.allowed_packages:
            return {
                "status": "blocked",
                "reason": f"Package '{package}' is outside the session allowlist",
            }

        if session.allowed_packages and session.current_package and session.current_package not in session.allowed_packages:
            return {
                "status": "blocked",
                "reason": f"Current package '{session.current_package}' is outside the session allowlist",
            }

        if package in RISKY_PACKAGES:
            return self._approval_required(session, action, params, f"Package '{package}' may change apps, permissions, or purchases")

        if action == "type_text":
            text = str(params.get("text", "")).lower()
            for pattern in RISKY_TEXT_PATTERNS:
                if pattern in text:
                    return self._approval_required(session, action, params, f"Text contains risky term '{pattern}'")
        return None

    def _approval_required(
        self,
        session: AndroidSession,
        action: str,
        params: dict[str, Any],
        reason: str,
    ) -> dict[str, Any]:
        approval_id = str(uuid.uuid4())
        session.pending_approvals[approval_id] = {"action": action, "params": params, "reason": reason}
        return {"status": "approval_required", "approval_id": approval_id, "reason": reason}

    def _session(self, session_id: str) -> AndroidSession:
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError(f"Session '{session_id}' was not found")
        return session

    @staticmethod
    def _log(session: AndroidSession, action: str, status: str, details: dict[str, Any]) -> None:
        session.action_log.append(AndroidActionLog(action=action, status=status, timestamp=time.time(), details=details))

    @staticmethod
    def _call_quietly(func: Any, *args: Any, **kwargs: Any) -> tuple[Any, str]:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            result = func(*args, **kwargs)
        return result, buffer.getvalue().strip()


def to_json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, sort_keys=True)
