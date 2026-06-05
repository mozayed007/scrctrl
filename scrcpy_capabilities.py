#!/usr/bin/env python3
"""Version-aware scrcpy capability catalog for agent integrations."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ScrcpyFeature:
    name: str
    category: str
    description: str
    agent_use: str
    flags: tuple[str, ...] = ()
    platform: str = "all"


@dataclass(frozen=True)
class ScrcpyShortcut:
    action: str
    shortcuts: tuple[str, ...]
    category: str
    mode: str = "mirror"
    agent_use: str = ""


@dataclass(frozen=True)
class ScrcpyOption:
    flag: str
    value_type: str
    category: str
    description: str
    examples: tuple[str, ...] = ()
    safety: str = ""
    platform: str = "all"


@dataclass(frozen=True)
class ScrcpyRecipe:
    name: str
    title: str
    description: str
    args: tuple[str, ...]
    agent_use: str
    requires_package: bool = False
    requires_record_file: bool = False
    platform: str = "all"


FEATURES: tuple[ScrcpyFeature, ...] = (
    ScrcpyFeature("video", "streaming", "Mirror the device display with configurable size, FPS, bitrate and codec.", "Use for human watch mode and visual debugging.", ("--max-size", "--max-fps", "--video-bit-rate", "--video-codec")),
    ScrcpyFeature("audio", "streaming", "Forward device audio, microphone, or playback streams where Android supports it.", "Use when the human operator needs audible feedback.", ("--audio-source", "--audio-codec", "--audio-buffer")),
    ScrcpyFeature("recording", "capture", "Record video or audio to files such as MP4, MKV, OPUS, FLAC or WAV.", "Use to create reproducible traces of an agent session.", ("--record", "--record-format")),
    ScrcpyFeature("virtual_display", "display", "Create an isolated Android virtual display, optionally flex-resized to the scrcpy window.", "Use for app-isolated workflows that should not disturb the main device screen.", ("--new-display", "--flex-display", "--start-app")),
    ScrcpyFeature("camera", "capture", "Mirror or record Android cameras on Android 12+.", "Use for camera inspection or camera recording workflows.", ("--video-source", "--camera-id", "--camera-facing", "--camera-size")),
    ScrcpyFeature("hid_input", "control", "Simulate physical keyboard, mouse, or gamepad input through UHID/AOA modes.", "Use when ADB input is insufficient and the task benefits from real HID semantics.", ("--keyboard", "--mouse", "--gamepad")),
    ScrcpyFeature("otg", "control", "Control only through USB OTG-style keyboard and mouse without ADB debugging.", "Use for recovery/control cases where mirroring is unavailable.", ("--otg", "--keyboard", "--mouse")),
    ScrcpyFeature("clipboard", "control", "Synchronize or inject clipboard content through scrcpy shortcuts and paste modes.", "Use with human oversight for text transfer.", ("--legacy-paste", "--no-clipboard-autosync")),
    ScrcpyFeature("diagnostics", "inspection", "List apps, displays, cameras, camera sizes and encoders from the target device.", "Use before choosing a recipe or device-specific flag.", ("--list-apps", "--list-displays", "--list-cameras", "--list-camera-sizes", "--list-encoders")),
    ScrcpyFeature("window", "desktop", "Control scrcpy window placement, full screen, top-most behavior and decoration.", "Use to create reliable human observation layouts.", ("--fullscreen", "--always-on-top", "--window-title", "--window-width", "--window-height")),
)


SHORTCUTS: tuple[ScrcpyShortcut, ...] = (
    ScrcpyShortcut("quit", ("MOD+q",), "window", agent_use="Tell a human how to close the watch window."),
    ScrcpyShortcut("fullscreen", ("MOD+f", "F11"), "window", agent_use="Tell a human how to maximize observation."),
    ScrcpyShortcut("rotate_display_left", ("MOD+Left",), "display"),
    ScrcpyShortcut("rotate_display_right", ("MOD+Right",), "display"),
    ScrcpyShortcut("flip_display_horizontal", ("MOD+Shift+Left", "MOD+Shift+Right"), "display"),
    ScrcpyShortcut("flip_display_vertical", ("MOD+Shift+Up", "MOD+Shift+Down"), "display"),
    ScrcpyShortcut("pause_display", ("MOD+z",), "display"),
    ScrcpyShortcut("unpause_display", ("MOD+Shift+z",), "display"),
    ScrcpyShortcut("reset_capture_encoding", ("MOD+Shift+r",), "diagnostics"),
    ScrcpyShortcut("resize_pixel_perfect", ("MOD+g",), "window"),
    ScrcpyShortcut("resize_remove_borders", ("MOD+w", "Double-click black borders"), "window"),
    ScrcpyShortcut("home", ("MOD+h", "Middle-click"), "android_navigation", agent_use="ADB equivalent: input keyevent KEYCODE_HOME."),
    ScrcpyShortcut("back", ("MOD+b", "MOD+Backspace", "Right-click"), "android_navigation", agent_use="ADB equivalent: input keyevent KEYCODE_BACK."),
    ScrcpyShortcut("app_switch", ("MOD+s", "4th-click"), "android_navigation", agent_use="ADB equivalent: input keyevent KEYCODE_APP_SWITCH."),
    ScrcpyShortcut("menu", ("MOD+m",), "android_navigation"),
    ScrcpyShortcut("volume_up", ("MOD+Up",), "android_navigation", agent_use="ADB equivalent: input keyevent KEYCODE_VOLUME_UP."),
    ScrcpyShortcut("volume_down", ("MOD+Down",), "android_navigation", agent_use="ADB equivalent: input keyevent KEYCODE_VOLUME_DOWN."),
    ScrcpyShortcut("power", ("MOD+p",), "android_navigation", agent_use="ADB equivalent: input keyevent KEYCODE_POWER."),
    ScrcpyShortcut("screen_off", ("MOD+o",), "device", agent_use="Equivalent launch flag: --turn-screen-off."),
    ScrcpyShortcut("screen_on", ("MOD+Shift+o",), "device"),
    ScrcpyShortcut("rotate_device_screen", ("MOD+r",), "device"),
    ScrcpyShortcut("expand_notifications", ("MOD+n", "5th-click"), "android_system"),
    ScrcpyShortcut("expand_settings", ("MOD+n+n", "Double-5th-click"), "android_system"),
    ScrcpyShortcut("collapse_panels", ("MOD+Shift+n",), "android_system"),
    ScrcpyShortcut("copy", ("MOD+c",), "clipboard"),
    ScrcpyShortcut("cut", ("MOD+x",), "clipboard"),
    ScrcpyShortcut("paste_clipboard", ("MOD+v",), "clipboard"),
    ScrcpyShortcut("inject_clipboard_text", ("MOD+Shift+v",), "clipboard"),
    ScrcpyShortcut("keyboard_settings", ("MOD+k",), "hid", agent_use="ADB equivalent: am start -a android.settings.HARD_KEYBOARD_SETTINGS."),
    ScrcpyShortcut("toggle_fps_counter", ("MOD+i",), "diagnostics", agent_use="Equivalent launch flag: --print-fps starts enabled."),
    ScrcpyShortcut("pinch_zoom_rotate", ("Ctrl+click-and-move",), "gesture"),
    ScrcpyShortcut("tilt_vertical", ("Shift+click-and-move",), "gesture"),
    ScrcpyShortcut("tilt_horizontal", ("Ctrl+Shift+click-and-move",), "gesture"),
    ScrcpyShortcut("install_apk", ("Drag & drop APK",), "file_transfer", agent_use="Prefer explicit human approval before installs."),
    ScrcpyShortcut("push_file", ("Drag & drop non-APK file",), "file_transfer", agent_use="Prefer adb push or explicit human approval."),
    ScrcpyShortcut("camera_torch_on", ("MOD+t",), "camera", mode="camera"),
    ScrcpyShortcut("camera_torch_off", ("MOD+Shift+t",), "camera", mode="camera"),
    ScrcpyShortcut("camera_zoom_in", ("MOD+Up",), "camera", mode="camera"),
    ScrcpyShortcut("camera_zoom_out", ("MOD+Down",), "camera", mode="camera"),
)


OPTIONS: tuple[ScrcpyOption, ...] = (
    ScrcpyOption("--video-codec", "choice:h264|h265|av1", "video", "Select video codec.", ("--video-codec=h265",)),
    ScrcpyOption("--max-size", "integer", "video", "Limit the maximum video dimension.", ("--max-size=1920",)),
    ScrcpyOption("--max-fps", "integer", "video", "Limit display capture frame rate.", ("--max-fps=60",)),
    ScrcpyOption("--video-bit-rate", "bitrate", "video", "Set video bitrate.", ("--video-bit-rate=16M",)),
    ScrcpyOption("--audio-source", "choice", "audio", "Select audio capture source.", ("--audio-source=playback",)),
    ScrcpyOption("--audio-codec", "choice:opus|aac|flac|raw", "audio", "Select audio codec.", ("--audio-codec=opus",)),
    ScrcpyOption("--no-audio", "bool", "audio", "Disable audio forwarding.", ("--no-audio",)),
    ScrcpyOption("--record", "path", "recording", "Record the session to a file.", ("--record=session.mp4",), "May capture sensitive screen content."),
    ScrcpyOption("--record-format", "choice", "recording", "Force recording container/format.", ("--record-format=mp4",)),
    ScrcpyOption("--new-display", "optional:WIDTHxHEIGHT/DPI", "virtual_display", "Create an Android virtual display.", ("--new-display=1920x1080/420", "--new-display")),
    ScrcpyOption("--flex-display", "bool", "virtual_display", "Resize virtual display to match the scrcpy window.", ("--flex-display",)),
    ScrcpyOption("--start-app", "package", "app", "Start an Android app by package or fuzzy name.", ("--start-app=org.videolan.vlc", "--start-app=+?firefox")),
    ScrcpyOption("--keyboard", "choice:disabled|sdk|uhid|aoa", "hid", "Select keyboard input mode.", ("--keyboard=uhid",)),
    ScrcpyOption("--mouse", "choice:disabled|sdk|uhid|aoa", "hid", "Select mouse input mode.", ("--mouse=uhid",)),
    ScrcpyOption("--gamepad", "choice:disabled|uhid|aoa", "hid", "Select gamepad input mode.", ("--gamepad=uhid",)),
    ScrcpyOption("--shortcut-mod", "mod-list", "shortcuts", "Customize the shortcut modifier.", ("--shortcut-mod=rctrl", "--shortcut-mod=lctrl,lsuper")),
    ScrcpyOption("--otg", "bool", "otg", "Run OTG control mode over USB.", ("--otg",), "Control-only mode; may capture keyboard/mouse."),
    ScrcpyOption("--no-control", "bool", "safety", "Mirror read-only without sending controls.", ("--no-control",)),
    ScrcpyOption("--no-window", "bool", "window", "Disable scrcpy window.", ("--no-window",)),
    ScrcpyOption("--fullscreen", "bool", "window", "Start in fullscreen.", ("--fullscreen",)),
    ScrcpyOption("--always-on-top", "bool", "window", "Keep the scrcpy window above other windows.", ("--always-on-top",)),
    ScrcpyOption("--turn-screen-off", "bool", "device", "Turn device screen off immediately while mirroring.", ("--turn-screen-off",)),
    ScrcpyOption("--stay-awake", "bool", "device", "Keep the device awake while plugged in during the session.", ("--stay-awake",)),
    ScrcpyOption("--show-touches", "bool", "device", "Enable show touches during the session.", ("--show-touches",)),
    ScrcpyOption("--display-id", "integer", "display", "Mirror a specific Android display id.", ("--display-id=0",)),
    ScrcpyOption("--crop", "WIDTH:HEIGHT:X:Y", "display", "Crop the mirrored display.", ("--crop=1224:1440:0:0",)),
    ScrcpyOption("--camera-id", "string", "camera", "Select camera id.", ("--camera-id=0",)),
    ScrcpyOption("--camera-facing", "choice:front|back|external", "camera", "Select camera by facing direction.", ("--camera-facing=front",)),
    ScrcpyOption("--camera-size", "WIDTHxHEIGHT", "camera", "Select explicit camera size.", ("--camera-size=1920x1080",)),
    ScrcpyOption("--camera-fps", "integer", "camera", "Set camera capture frame rate.", ("--camera-fps=30",)),
    ScrcpyOption("--camera-torch", "bool", "camera", "Enable torch when camera starts.", ("--camera-torch",)),
    ScrcpyOption("--camera-zoom", "float", "camera", "Set camera zoom initial value.", ("--camera-zoom=2.0",)),
    ScrcpyOption("--list-apps", "bool", "diagnostics", "List installed Android apps.", ("--list-apps",)),
    ScrcpyOption("--list-cameras", "bool", "diagnostics", "List device cameras.", ("--list-cameras",)),
    ScrcpyOption("--list-camera-sizes", "bool", "diagnostics", "List valid camera capture sizes.", ("--list-camera-sizes",)),
    ScrcpyOption("--list-displays", "bool", "diagnostics", "List device displays.", ("--list-displays",)),
    ScrcpyOption("--list-encoders", "bool", "diagnostics", "List available video and audio encoders.", ("--list-encoders",)),
    ScrcpyOption("--v4l2-sink", "path", "linux", "Expose video as a V4L2 sink.", ("--v4l2-sink=/dev/video2",), platform="linux"),
)


RECIPES: tuple[ScrcpyRecipe, ...] = (
    ScrcpyRecipe("high-quality-mirror", "High-quality mirror", "H.265 1080p/60 mirror with audio disabled for responsive human watch mode.", ("--video-codec=h265", "--max-size=1920", "--max-fps=60", "--no-audio"), "Use when a human needs a sharp low-latency observation window."),
    ScrcpyRecipe("read-only-watch", "Read-only watch", "Mirror without sending input controls.", ("--no-control", "--stay-awake"), "Use beside ADB/CUA sessions so humans can watch without accidental clicks."),
    ScrcpyRecipe("virtual-app", "Virtual display app", "Start one app in a virtual display.", ("--new-display", "--flex-display", "--start-app={package}"), "Use for isolated app workflows.", requires_package=True),
    ScrcpyRecipe("camera-recording", "Camera recording", "Record a camera stream to an MP4 file.", ("--video-source=camera", "--video-codec=h265", "--camera-size=1920x1080", "--record={record_file}"), "Use for camera inspection or reproducible camera traces.", requires_record_file=True),
    ScrcpyRecipe("hid-input", "HID keyboard and mouse", "Mirror with UHID keyboard and mouse.", ("--keyboard=uhid", "--mouse=uhid"), "Use when HID input semantics are more reliable than ADB input."),
    ScrcpyRecipe("otg-control", "OTG control", "Control-only OTG mode over USB.", ("--otg",), "Use for USB control recovery when ADB mirroring is not available."),
)


def get_scrcpy_version(scrcpy_exe: Path) -> dict[str, str]:
    try:
        completed = subprocess.run([str(scrcpy_exe), "--version"], capture_output=True, text=True, timeout=10)
    except Exception as exc:
        return {"version": "unknown", "raw": "", "error": str(exc)}
    first_line = (completed.stdout or completed.stderr or "").splitlines()[0] if (completed.stdout or completed.stderr) else ""
    match = re.search(r"scrcpy\s+([^\s]+)", first_line)
    return {"version": match.group(1) if match else "unknown", "raw": (completed.stdout or completed.stderr or "").strip()}


def get_scrcpy_help(scrcpy_exe: Path) -> str:
    try:
        completed = subprocess.run([str(scrcpy_exe), "--help"], capture_output=True, text=True, timeout=15)
    except Exception:
        return ""
    return completed.stdout or completed.stderr or ""


def parse_help_options(help_text: str) -> set[str]:
    options: set[str] = set()
    for match in re.finditer(r"(?<![\w-])(--[a-z0-9][a-z0-9-]*)(?:[=\s,\[]|$)", help_text, flags=re.IGNORECASE):
        options.add(match.group(1))
    return options


def build_catalog(scrcpy_exe: Path) -> dict[str, Any]:
    help_text = get_scrcpy_help(scrcpy_exe)
    available_options = parse_help_options(help_text)
    version = get_scrcpy_version(scrcpy_exe)
    return {
        "version": version,
        "features": [asdict(item) for item in FEATURES],
        "shortcuts": [asdict(item) for item in SHORTCUTS],
        "options": [
            {**asdict(item), "available": item.flag in available_options if available_options else None}
            for item in OPTIONS
        ],
        "recipes": [asdict(item) for item in RECIPES],
        "help_detected_options": sorted(available_options),
    }


def recommend_recipe(
    name: str,
    *,
    package: str | None = None,
    record_file: str | None = None,
    scrcpy_exe: Path | None = None,
) -> dict[str, Any]:
    recipe = next((item for item in RECIPES if item.name == name), None)
    if recipe is None:
        raise ValueError(f"Unknown scrcpy recipe: {name}")
    if recipe.requires_package and not package:
        raise ValueError(f"Recipe '{name}' requires package")
    if recipe.requires_record_file and not record_file:
        raise ValueError(f"Recipe '{name}' requires record_file")
    args = [
        arg.format(package=package or "", record_file=record_file or "")
        for arg in recipe.args
    ]
    command = [str(scrcpy_exe), *args] if scrcpy_exe else args
    return {
        "recipe": asdict(recipe),
        "args": args,
        "command": command,
        "notes": [
            "Use ADB screenshots/actions for exact automation coordinates.",
            "Use scrcpy as watch, recording or HID input surface.",
            "Review the exact command before launching generated args.",
        ],
    }


def validate_scrcpy_args(args: Sequence[str], *, known_options: set[str] | None = None) -> dict[str, Any]:
    if known_options is None:
        known_options = {option.flag for option in OPTIONS}
    errors: list[str] = []
    normalized: list[str] = []
    known_short = {"-K", "-M", "-G", "-d", "-e", "-f", "-n", "-N", "-S", "-t", "-x"}
    for arg in args:
        normalized.append(arg)
        if not arg:
            errors.append("Empty argument is not allowed")
            continue
        if arg.startswith("--"):
            flag = arg.split("=", 1)[0]
            if flag not in known_options:
                errors.append(f"Unknown scrcpy option: {flag}")
            continue
        if arg in known_short:
            continue
        errors.append(f"Malformed or unsupported scrcpy arg: {arg}")
    return {"ok": not errors, "args": normalized, "errors": errors}
