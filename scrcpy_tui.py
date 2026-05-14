#!/usr/bin/env python3
"""Textual TUI for scrcpy Device Manager.

Provides a rich terminal interface for managing and launching scrcpy
sessions. Falls back gracefully if Textual is not installed.
"""

from __future__ import annotations

import subprocess
from typing import ClassVar

# Textual imports with graceful fallback
try:
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Horizontal, Vertical, VerticalScroll
    from textual.reactive import reactive
    from textual.screen import ModalScreen, Screen
    from textual.widgets import (
        Button,
        Checkbox,
        DataTable,
        Footer,
        Header,
        Input,
        Select,
        Static,
    )

    TEXTUAL_AVAILABLE = True
except ImportError:
    TEXTUAL_AVAILABLE = False

from scrcpy_manager import Device, ScrcpyManager


def _safe_int(value: str, default: int = 0) -> int:
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


class MessageScreen(ModalScreen[None]):
    """Modal screen to display a message with an OK button."""

    def __init__(self, message: str, title: str = "Message") -> None:
        self.message_text = message
        self.title_text = title
        super().__init__()

    def compose(self) -> ComposeResult:
        yield Static(self.title_text, classes="dialog-title")
        yield Static(self.message_text, classes="dialog-body")
        yield Button("OK", id="ok", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok":
            self.dismiss()


class ConfirmScreen(ModalScreen[bool]):
    """Modal screen for yes/no confirmation."""

    def __init__(self, message: str, title: str = "Confirm") -> None:
        self.message_text = message
        self.title_text = title
        super().__init__()

    def compose(self) -> ComposeResult:
        yield Static(self.title_text, classes="dialog-title")
        yield Static(self.message_text, classes="dialog-body")
        with Horizontal(classes="dialog-buttons"):
            yield Button("Yes", id="yes", variant="success")
            yield Button("No", id="no", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "yes":
            self.dismiss(True)
        elif event.button.id == "no":
            self.dismiss(False)


class PairingScreen(ModalScreen[str | None]):
    """Modal screen to enter a pairing code."""

    def __init__(self, device_name: str, ipport: str) -> None:
        self.device_name = device_name
        self.ipport = ipport
        super().__init__()

    def compose(self) -> ComposeResult:
        yield Static(f"Pairing with {self.device_name}", classes="dialog-title")
        yield Static(f"Address: {self.ipport}\nEnter pairing code from device (4-8 digits):", classes="dialog-body")
        yield Input(placeholder="e.g. 046882", id="pairing_code")
        with Horizontal(classes="dialog-buttons"):
            yield Button("Pair", id="pair", variant="primary")
            yield Button("Cancel", id="cancel", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "pair":
            code = self.query_one("#pairing_code", Input).value.strip()
            if code and code.isdigit() and 4 <= len(code) <= 8:
                self.dismiss(code)
            else:
                self.app.notify("Invalid code. Must be 4-8 digits.", severity="error")
        elif event.button.id == "cancel":
            self.dismiss(None)


class ProfileEditScreen(ModalScreen[dict[str, str] | None]):
    """Modal screen to add or edit a device profile."""

    def __init__(self, manager: ScrcpyManager, profile: dict[str, str] | None = None) -> None:
        self.manager = manager
        self.profile = profile or {}
        super().__init__()

    def compose(self) -> ComposeResult:
        is_edit = bool(self.profile.get("name"))
        yield Static("Edit Profile" if is_edit else "Add Profile", classes="dialog-title")
        yield Static("Profile ID (no spaces)", classes="label")
        yield Input(value=self.profile.get("name", ""), id="profile_id", disabled=is_edit)
        yield Static("Display Name", classes="label")
        yield Input(value=self.profile.get("nickname", ""), id="nickname")
        yield Static("IP Address (for wireless)", classes="label")
        yield Input(value=self.profile.get("ip", ""), id="ip")
        yield Static("USB Serial (for USB)", classes="label")
        yield Input(value=self.profile.get("serial", ""), id="serial")
        yield Static("Quality", classes="label")
        qualities = [(q, q) for q in ["low", "balanced", "high", "ultra"]]
        current_q = self.profile.get("quality", "balanced")
        yield Select(qualities, value=current_q, id="quality")
        yield Static("Mode", classes="label")
        modes = [(m, m) for m in ["mirror", "otg", "camera"]]
        current_m = self.profile.get("mode", "mirror")
        yield Select(modes, value=current_m, id="mode")
        yield Static("Keep device active", classes="label")
        keep_active_val = self.profile.get("keep_active", "").lower() in {"__yes__", "yes", "y", "true"}
        yield Checkbox("Prevent sleep (--keep-active)", value=keep_active_val, id="keep_active")
        yield Static("Background color (optional)", classes="label")
        yield Input(
            value=self.profile.get("background_color", ""), placeholder="#234567 or 234567", id="background_color"
        )
        with Horizontal(classes="dialog-buttons"):
            yield Button("Save", id="save", variant="primary")
            yield Button("Cancel", id="cancel", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "save":
            profile_id = self.query_one("#profile_id", Input).value.strip()
            nickname = self.query_one("#nickname", Input).value.strip()
            ip = self.query_one("#ip", Input).value.strip()
            serial = self.query_one("#serial", Input).value.strip()
            quality_select = self.query_one("#quality", Select)
            mode_select = self.query_one("#mode", Select)
            keep_active_box = self.query_one("#keep_active", Checkbox)
            background_color_input = self.query_one("#background_color", Input)
            quality = str(quality_select.value) if quality_select.value else "balanced"
            mode = str(mode_select.value) if mode_select.value else "mirror"
            keep_active = "__YES__" if keep_active_box.value else ""
            background_color = background_color_input.value.strip()

            if not profile_id:
                self.app.notify("Profile ID is required.", severity="error")
                return
            if not ip and not serial:
                self.app.notify("IP or Serial is required.", severity="error")
                return

            result = {
                "name": profile_id,
                "nickname": nickname or profile_id,
                "ip": ip,
                "serial": serial,
                "quality": quality,
                "mode": mode,
                "keep_active": keep_active,
                "background_color": background_color,
            }
            self.dismiss(result)


class CameraSetupScreen(ModalScreen[list[str] | None]):
    """Modal screen for camera mode options."""

    def __init__(self) -> None:
        super().__init__()

    def compose(self) -> ComposeResult:
        yield Static("Camera Mode Setup", classes="dialog-title")
        yield Static("Camera ID (0=back, 1=front)", classes="label")
        yield Input(value="0", id="camera_id")
        yield Static("Aspect Ratio", classes="label")
        ratios = [("16:9", "1"), ("4:3", "2"), ("1:1", "3"), ("Native", "4")]
        yield Select(ratios, value="1", id="aspect")
        yield Static("Quality", classes="label")
        qualities = [("Low (640x480, 2Mbps)", "1"), ("Balanced (720p, 4Mbps)", "2"), ("High (1080p, 8Mbps)", "3")]
        yield Select(qualities, value="2", id="quality")
        yield Static("Zoom level (1.0=default, leave empty)", classes="label")
        yield Input(placeholder="1.0", id="zoom")
        with Horizontal(classes="dialog-buttons"):
            yield Button("Launch", id="launch", variant="primary")
            yield Button("Cancel", id="cancel", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "launch":
            args: list[str] = []
            camera_id = self.query_one("#camera_id", Input).value.strip() or "0"
            args.extend(["--video-source=camera", f"--camera-id={camera_id}"])
            aspect_map = {"1": "16:9", "2": "4:3", "3": "1:1"}
            aspect_val = str(self.query_one("#aspect", Select).value)
            if aspect_val in aspect_map:
                args.append(f"--camera-ar={aspect_map[aspect_val]}")
            quality_val = str(self.query_one("#quality", Select).value)
            quality_map = {"1": "camera_low", "2": "camera_balanced", "3": "camera_high"}
            preset = quality_map.get(quality_val, "camera_balanced")
            zoom = self.query_one("#zoom", Input).value.strip()
            self.dismiss([preset, *args, *([f"--camera-zoom={zoom}"] if zoom else [])])


class QuickAppScreen(ModalScreen[list[str] | None]):
    """Modal screen for quick app launcher."""

    def __init__(self) -> None:
        super().__init__()

    def compose(self) -> ComposeResult:
        yield Static("Quick App Launcher", classes="dialog-title")
        yield Static("Launch mode", classes="label")
        modes = [("Mirror + Launch app", "1"), ("Virtual display + Launch app", "2"), ("Launch app only", "3")]
        yield Select(modes, value="1", id="mode")
        yield Static("Package name (e.g. com.android.settings)", classes="label")
        yield Input(placeholder="com.android.settings", id="package")
        with Horizontal(classes="dialog-buttons"):
            yield Button("Launch", id="launch", variant="primary")
            yield Button("Cancel", id="cancel", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "launch":
            package = self.query_one("#package", Input).value.strip()
            if not package:
                self.app.notify("Package name is required.", severity="error")
                return
            mode_val = str(self.query_one("#mode", Select).value)
            args: list[str] = [f"--start-app={package}"]
            if mode_val == "2":
                args.append("--new-display")
            self.dismiss(args)


class DiscoverListScreen(ModalScreen[tuple[ScrcpyManager, str, str] | None]):
    """Modal screen to select a discovered wireless device."""

    def __init__(self, manager: ScrcpyManager, items: list[tuple[str, str, str]]) -> None:
        self.manager = manager
        self.items = items
        super().__init__()

    def compose(self) -> ComposeResult:
        yield Static("Discovered Devices", classes="dialog-title")
        table = DataTable(id="discover-table")
        table.add_columns("#", "Name", "Address", "Source")
        table.cursor_type = "row"
        table.zebra_stripes = True
        for i, (name, ipport, source) in enumerate(self.items, 1):
            table.add_row(str(i), name, ipport, source)
        yield table
        with Horizontal(classes="dialog-buttons"):
            yield Button("Connect", id="connect", variant="primary")
            yield Button("Cancel", id="cancel", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "connect":
            table = self.query_one("#discover-table", DataTable)
            row = table.cursor_row
            if row is None or not (0 <= row < len(self.items)):
                self.app.notify("Select a device to connect.", severity="error")
                return
            name, ipport, _source = self.items[row]
            self.dismiss((self.manager, ipport, name))


class InputScreen(ModalScreen[str | None]):
    """Modal screen for simple text input."""

    def __init__(self, label: str, default: str = "") -> None:
        self.label = label
        self.default = default
        super().__init__()

    def compose(self) -> ComposeResult:
        yield Static(self.label, classes="dialog-title")
        yield Input(value=self.default, id="input_value")
        with Horizontal(classes="dialog-buttons"):
            yield Button("Save", id="save", variant="primary")
            yield Button("Cancel", id="cancel", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "save":
            value = self.query_one("#input_value", Input).value.strip()
            if not value:
                self.app.notify(f"{self.label} is required.", severity="error")
                return
            self.dismiss(value)


class ProfileListScreen(ModalScreen[None]):
    """Screen to manage profiles (list, add, edit, delete)."""

    def __init__(self, manager: ScrcpyManager) -> None:
        self.manager = manager
        super().__init__()

    def compose(self) -> ComposeResult:
        yield Static("Profile Manager", classes="dialog-title")
        table = DataTable(id="profile-table")
        table.add_columns("#", "Name", "IP", "Serial", "Quality")
        table.cursor_type = "row"
        table.zebra_stripes = True
        yield table
        with Horizontal(classes="dialog-buttons"):
            yield Button("Add", id="add", variant="primary")
            yield Button("Edit", id="edit", variant="warning")
            yield Button("Delete", id="delete", variant="error")
            yield Button("Close", id="close", variant="default")

    def on_mount(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        table = self.query_one("#profile-table", DataTable)
        table.clear()
        profiles = self.manager.list_profiles()
        for i, p in enumerate(profiles, 1):
            table.add_row(str(i), p["nickname"], p.get("ip", ""), p.get("serial", ""), p["quality"])

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "close":
            self.dismiss()
        elif bid == "add":
            self.app.push_screen(ProfileEditScreen(self.manager), self._on_profile_saved)
        elif bid == "edit":
            table = self.query_one("#profile-table", DataTable)
            row = table.cursor_row
            profiles = self.manager.list_profiles()
            if row is None or not (0 <= row < len(profiles)):
                self.app.notify("Select a profile to edit.", severity="error")
                return
            self.app.push_screen(ProfileEditScreen(self.manager, profiles[row]), self._on_profile_saved)
        elif bid == "delete":
            table = self.query_one("#profile-table", DataTable)
            row = table.cursor_row
            profiles = self.manager.list_profiles()
            if row is None or not (0 <= row < len(profiles)):
                self.app.notify("Select a profile to delete.", severity="error")
                return
            target = profiles[row]
            self.app.push_screen(
                ConfirmScreen(f"Delete profile '{target['name']}'?", "Delete"),
                lambda confirmed: self._on_delete(confirmed, target["name"]),
            )

    def _on_profile_saved(self, result: dict[str, str] | None) -> None:
        if result is None:
            return
        try:
            self.manager.save_profile(
                profile_name=result["name"],
                nickname=result["nickname"],
                ip=result.get("ip", ""),
                serial=result.get("serial", ""),
                quality=result.get("quality", "balanced"),
                mode=result.get("mode", "mirror"),
                keep_active=result.get("keep_active", ""),
                background_color=result.get("background_color", ""),
            )
            self.app.notify(f"Profile '{result['name']}' saved")
            self._refresh()
        except Exception as exc:
            self.app.push_screen(MessageScreen(str(exc), "Save Error"))

    def _on_delete(self, confirmed: bool | None, name: str) -> None:
        if confirmed:
            self.manager.delete_profile(name)
            self.app.notify(f"Deleted '{name}'")
            self._refresh()


class MainScreen(Screen[None]):
    """Main screen showing devices, profiles, and action buttons."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("d", "detect", "Detect"),
        Binding("f", "discover", "Discover"),
        Binding("s", "setup", "Setup"),
        Binding("c", "camera", "Camera"),
        Binding("p", "quickapp", "QuickApp"),
        Binding("a", "profiles", "Profiles"),
        Binding("l", "quick_launch", "Quick Launch"),
        Binding("u", "update", "Update"),
        Binding("x", "shutdown", "Shutdown"),
    ]

    CSS: ClassVar[str] = """"
    Screen { align: center middle; }
    #main-container { width: 100%; height: 100%; layout: horizontal; }
    #devices-panel { width: 35%; height: 100%; border: round $primary; padding: 1; }
    #profiles-panel { width: 35%; height: 100%; border: round $primary; padding: 1; }
    #actions-panel { width: 30%; height: 100%; border: round $primary; padding: 1; }
    .panel-title { text-align: center; text-style: bold; margin-bottom: 1; }
    .panel-subtitle { text-align: center; color: $text-muted; margin-bottom: 1; }
    DataTable { height: 1fr; }
    .action-btn { margin: 1; width: 100%; }
    #status { height: auto; text-align: center; color: $text-muted; padding: 1; }
    """

    devices_data: reactive[list[Device]] = reactive(list)
    profiles_data: reactive[list[dict[str, str]]] = reactive(list)
    status_message: reactive[str] = reactive("Ready")

    def __init__(self, manager: ScrcpyManager) -> None:
        self.manager = manager
        super().__init__()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main-container"):
            with Vertical(id="devices-panel"):
                yield Static("Connected Devices", classes="panel-title")
                yield Static("No devices", classes="panel-subtitle")
                table = DataTable(id="devices-table")
                table.add_columns("#", "Name", "Type", "Model")
                table.cursor_type = "row"
                table.zebra_stripes = True
                yield table

            with Vertical(id="profiles-panel"):
                yield Static("Saved Profiles", classes="panel-title")
                yield Static("No profiles", classes="panel-subtitle")
                table = DataTable(id="profiles-table")
                table.add_columns("#", "Name", "Status")
                table.cursor_type = "row"
                table.zebra_stripes = True
                yield table

            with VerticalScroll(id="actions-panel"):
                yield Static("Actions", classes="panel-title")
                yield Button("[L] Quick Launch", id="act-quick", variant="primary", classes="action-btn")
                yield Button("[D] Detect Devices", id="act-detect", classes="action-btn")
                yield Button("[F] Discover", id="act-discover", classes="action-btn")
                yield Button("[S] Setup Wireless", id="act-setup", classes="action-btn")
                yield Button("[C] Camera Mode", id="act-camera", classes="action-btn")
                yield Button("[P] Quick App", id="act-quickapp", classes="action-btn")
                yield Button("[A] Profiles", id="act-profiles", classes="action-btn")
                yield Button("[U] Update scrcpy", id="act-update", classes="action-btn")
                yield Button("[X] Shutdown ADB", id="act-shutdown", classes="action-btn")
                yield Button("[R] Refresh", id="act-refresh", classes="action-btn")
                yield Button("[Q] Quit", id="act-quit", classes="action-btn")

        yield Static("Ready", id="status")
        yield Footer()

    def on_mount(self) -> None:
        # Auto-reconnect saved wireless profiles on startup
        try:
            reconnected = self.manager.auto_connect_profiles()
            if reconnected:
                self.app.notify(f"Auto-reconnected: {', '.join(reconnected)}")
        except Exception:
            pass

        # Non-blocking background update check (notification only in TUI)
        if self.manager.get_pref_bool("auto_check_updates", True):
            try:
                from scrcpy_cli import check_updates_silent

                newer = check_updates_silent()
                if newer:
                    self.app.notify(
                        f"Update available: {newer}. Press [U] to update.",
                        severity="information",
                        timeout=8,
                    )
            except Exception:
                pass

        self.refresh_data()
        self.set_interval(3, self.refresh_data)

    def refresh_data(self) -> None:
        try:
            self.devices_data = self.manager.list_devices()
            self.profiles_data = self.manager.list_profiles()
            self.status_message = f"{len(self.devices_data)} device(s), {len(self.profiles_data)} profile(s)"
        except Exception as exc:
            self.status_message = f"Error: {exc}"

    def watch_devices_data(self, devices: list[Device]) -> None:
        table = self.query_one("#devices-table", DataTable)
        table.clear()
        subtitle = self.query_one("#devices-panel .panel-subtitle", Static)
        if not devices:
            subtitle.update("No devices connected")
        else:
            subtitle.update(f"{len(devices)} connected")
            for index, device in enumerate(devices, start=1):
                icon = "📶" if device.kind == "WIRELESS" else "🔌"
                table.add_row(str(index), device.display_name, icon, device.model or "Unknown")

    def watch_profiles_data(self, profiles: list[dict[str, str]]) -> None:
        table = self.query_one("#profiles-table", DataTable)
        table.clear()
        subtitle = self.query_one("#profiles-panel .panel-subtitle", Static)
        if not profiles:
            subtitle.update("No saved profiles")
        else:
            subtitle.update(f"{len(profiles)} saved")
            for index, profile in enumerate(profiles, start=1):
                status = profile.get("ip", "") or profile.get("serial", "") or "manual"
                table.add_row(str(index), profile["nickname"], status)

    def watch_status_message(self, message: str) -> None:
        self.query_one("#status", Static).update(message)

    def _get_selected_device(self) -> Device | None:
        table = self.query_one("#devices-table", DataTable)
        if table.cursor_row is None:
            return None
        idx = table.cursor_row
        if 0 <= idx < len(self.devices_data):
            return self.devices_data[idx]
        return None

    def _get_selected_profile(self) -> dict[str, str] | None:
        table = self.query_one("#profiles-table", DataTable)
        if table.cursor_row is None:
            return None
        idx = table.cursor_row
        if 0 <= idx < len(self.profiles_data):
            return self.profiles_data[idx]
        return None

    def _launch_profile(self, profile_name: str) -> None:
        self.status_message = f"Launching {profile_name}..."
        try:
            result = self.manager.launch_profile(profile_name, detach=True)
            if isinstance(result, subprocess.Popen):
                self.app.notify(f"Launched {profile_name} (pid {result.pid})")
            elif result != 0:
                self.app.push_screen(MessageScreen(f"scrcpy exited with code {result}", "Launch Error"))
            else:
                self.app.notify(f"Launched {profile_name}")
        except Exception as exc:
            self.app.push_screen(MessageScreen(str(exc), "Launch Error"))
        self.refresh_data()

    def _launch_device(self, device: Device) -> None:
        self.status_message = f"Launching {device.display_name}..."
        try:
            result = self.manager.launch_connected_device(device, detach=True)
            if isinstance(result, subprocess.Popen):
                self.app.notify(f"Launched {device.display_name} (pid {result.pid})")
            elif result != 0:
                self.app.push_screen(MessageScreen(f"scrcpy exited with code {result}", "Launch Error"))
            else:
                self.app.notify(f"Launched {device.display_name}")
        except Exception as exc:
            self.app.push_screen(MessageScreen(str(exc), "Launch Error"))
        self.refresh_data()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        table_id = event.data_table.id
        if table_id == "devices-table":
            device = self._get_selected_device()
            if device:
                self._launch_device(device)
        elif table_id == "profiles-table":
            profile = self._get_selected_profile()
            if profile:
                self._launch_profile(profile["name"])

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "act-quit":
            self.app.exit()
        elif button_id == "act-refresh":
            self.refresh_data()
            self.app.notify("Refreshed")
        elif button_id == "act-detect":
            self.action_detect()
        elif button_id == "act-discover":
            self.action_discover()
        elif button_id == "act-setup":
            self.action_setup()
        elif button_id == "act-camera":
            self.action_camera()
        elif button_id == "act-quickapp":
            self.action_quickapp()
        elif button_id == "act-profiles":
            self.action_profiles()
        elif button_id == "act-quick":
            self.action_quick_launch()
        elif button_id == "act-update":
            self.action_update()
        elif button_id == "act-shutdown":
            self.action_shutdown()

    def action_refresh(self) -> None:
        self.refresh_data()
        self.app.notify("Refreshed")

    def action_detect(self) -> None:
        self.app.push_screen(
            MessageScreen("Use the device list on the left. Auto-refresh is active.", "Device Detection")
        )

    def action_discover(self) -> None:
        self.status_message = "Discovering..."
        try:
            devices = self.manager.mdns_discover()
            if not devices:
                self.app.push_screen(
                    MessageScreen("No devices found via mDNS.\nEnable Wireless Debugging on Android 11+.", "Discovery")
                )
                return

            items: list[tuple[str, str, str]] = []
            for d in devices:
                items.append((d.name, d.ipport, d.source))

            # Simple selection via message
            lines = ["Select a device to connect:\n"]
            for i, (name, ipport, source) in enumerate(items, 1):
                lines.append(f"[{i}] {name}  ({ipport})  [{source}]")
            lines.append("\nEnter the number in the input below:")

            self.app.push_screen(
                DiscoverListScreen(self.manager, items),
                self._on_discover_result,
            )
        except Exception as exc:
            self.app.push_screen(MessageScreen(str(exc), "Discovery Error"))
        self.refresh_data()

    def _on_discover_result(self, result: tuple[ScrcpyManager, str, str] | None) -> None:
        if result is None:
            return
        manager, ipport, name = result
        self.status_message = f"Connecting to {name}..."
        try:
            success, message, serial = manager.connect_wireless(ipport)
            if not success or not serial:
                self.app.push_screen(MessageScreen(message, "Connection Failed"))
                return
            self.app.push_screen(
                ConfirmScreen(f"Save '{name}' as a profile?", "Save Profile"),
                lambda save: self._on_save_profile(save, manager, name, ipport, serial),
            )
        except Exception as exc:
            self.app.push_screen(MessageScreen(str(exc), "Connection Error"))
        self.refresh_data()

    def _on_save_profile(self, save: bool | None, manager: ScrcpyManager, name: str, ipport: str, serial: str) -> None:
        if not save:
            # Launch without saving
            temp_profile = {
                "name": name,
                "nickname": name,
                "ip": ipport.split(":")[0],
                "serial": "",
                "quality": "balanced",
                "mode": "mirror",
                "keep_active": "",
                "background_color": "",
            }
            try:
                args = manager.build_scrcpy_args(
                    profile=temp_profile,
                    connection=serial,
                    connection_type="wireless",
                )
                self._run_scrcpy(args)
            except Exception as exc:
                self.app.push_screen(MessageScreen(str(exc), "Launch Error"))
            return

        def on_profile_id(profile_id: str | None) -> None:
            if not profile_id:
                return
            try:
                manager.save_profile(
                    profile_name=profile_id,
                    nickname=name,
                    ip=ipport.split(":")[0],
                    serial="",
                    quality="balanced",
                    mode="mirror",
                    keep_active="",
                    background_color="",
                )
                self.app.notify(f"Saved profile '{profile_id}'")
                self._launch_profile(profile_id)
            except Exception as exc:
                self.app.push_screen(MessageScreen(str(exc), "Save Error"))

        self.app.push_screen(InputScreen("Profile ID", name), on_profile_id)

    def action_setup(self) -> None:
        self.app.push_screen(
            ConfirmScreen(
                "Wireless Setup Wizard\n\nRequirements:\n- USB debugging enabled\n- Device connected via USB\n- Computer authorized\n\nProceed?",
                "Setup Wireless",
            ),
            self._on_setup_confirm,
        )

    def _on_setup_confirm(self, confirmed: bool | None) -> None:
        if not confirmed:
            return
        self.status_message = "Running wireless setup..."
        try:
            self.manager.setup_wireless()
            self.app.notify("Wireless setup complete")
        except Exception as exc:
            self.app.push_screen(MessageScreen(str(exc), "Setup Error"))
        self.refresh_data()

    def action_camera(self) -> None:
        devices = self.manager.list_devices()
        if not devices:
            self.app.push_screen(MessageScreen("No connected devices found.", "Camera Mode"))
            return
        self.app.push_screen(
            CameraSetupScreen(),
            self._on_camera_result,
        )

    def _on_camera_result(self, result: list[str] | None) -> None:
        if result is None:
            return
        preset = result[0]
        extra_args = result[1:]
        devices = self.manager.list_devices()
        if not devices:
            self.app.push_screen(MessageScreen("No devices found.", "Camera Mode"))
            return
        # Use first device for simplicity; could add device selection screen
        selected = devices[0]
        settings = self.manager.get_quality_settings(preset)
        args = ["-s", selected.serial, *extra_args]
        if settings.get("video_bitrate"):
            args.append(f"--video-bit-rate={settings['video_bitrate']}")
        if settings.get("resolution"):
            args.append(f"--camera-size={settings['resolution']}")
        args.extend(["--window-title", f"scrcpy - {selected.display_name} (Camera Mode)"])
        self._run_scrcpy(args)

    def action_quickapp(self) -> None:
        devices = self.manager.list_devices()
        if not devices:
            self.app.push_screen(MessageScreen("No connected devices found.", "Quick App"))
            return
        self.app.push_screen(
            QuickAppScreen(),
            self._on_quickapp_result,
        )

    def _on_quickapp_result(self, result: list[str] | None) -> None:
        if result is None:
            return
        devices = self.manager.list_devices()
        selected = devices[0]
        args = ["-s", selected.serial, *result]
        args.extend(["--window-title", f"scrcpy - {selected.display_name} (App)"])
        self._run_scrcpy(args)

    def action_profiles(self) -> None:
        self.app.push_screen(
            ProfileListScreen(self.manager),
            lambda _: self.refresh_data(),
        )

    def action_quick_launch(self) -> None:
        self.status_message = "Quick launching..."
        try:
            result = self.manager.quick_launch(detach=True)
            if isinstance(result, subprocess.Popen):
                self.app.notify(f"Quick launch started (pid {result.pid})")
            elif result != 0:
                self.app.push_screen(MessageScreen(f"scrcpy exited with code {result}", "Launch Error"))
            else:
                self.app.notify("Quick launch succeeded")
        except Exception as exc:
            self.app.push_screen(MessageScreen(str(exc), "Quick Launch Error"))
        self.refresh_data()

    def action_shutdown(self) -> None:
        self.app.push_screen(
            ConfirmScreen("Disconnect all ADB connections and stop the server?", "Shutdown ADB"),
            self._on_shutdown_confirm,
        )

    def _on_shutdown_confirm(self, confirmed: bool | None) -> None:
        if confirmed:
            self.status_message = "Shutting down ADB..."
            try:
                self.manager.shutdown()
                self.app.notify("ADB shutdown complete")
            except Exception as exc:
                self.app.push_screen(MessageScreen(str(exc), "Shutdown Error"))
            self.refresh_data()

    def action_update(self) -> None:
        self.app.push_screen(
            ConfirmScreen(
                "Download and install the latest scrcpy/adb binaries from GitHub?\n"
                "A backup of the current bin/ folder will be created.",
                "Update scrcpy",
            ),
            self._on_update_confirm,
        )

    def _on_update_confirm(self, confirmed: bool | None) -> None:
        if not confirmed:
            return
        self.status_message = "Updating scrcpy..."
        try:
            from scrcpy_cli import update_scrcpy

            result = update_scrcpy()
            if result == 0:
                self.app.notify("scrcpy updated successfully! Restart to use new binaries.")
            else:
                self.app.push_screen(MessageScreen("Update failed. Check the logs for details.", "Update Error"))
        except Exception as exc:
            self.app.push_screen(MessageScreen(str(exc), "Update Error"))
        self.refresh_data()


class ScrcpyTuiApp(App[None]):
    """Textual TUI application for scrcpy Device Manager."""

    CSS = """
    .dialog-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }
    .dialog-body {
        margin: 1 0;
    }
    .dialog-buttons {
        align: center middle;
        height: auto;
        margin-top: 1;
    }
    .label {
        margin-top: 1;
        color: $text-muted;
    }
    """

    def __init__(self, manager: ScrcpyManager) -> None:
        self.manager = manager
        super().__init__()

    def on_mount(self) -> None:
        self.push_screen(MainScreen(self.manager))


def run_tui(manager: ScrcpyManager) -> None:
    """Run the Textual TUI."""
    if not TEXTUAL_AVAILABLE:
        raise ImportError("Textual is required for the TUI. Install it with:\n  pip install textual")
    app = ScrcpyTuiApp(manager)
    app.run()
