#!/usr/bin/env python3
"""Textual TUI modal screens for scrcpy Device Manager."""

from __future__ import annotations

from typing import ClassVar

from scrcpy_manager import (
    AUDIO_CODECS,
    AUDIO_SOURCES,
    DEFAULT_MODE,
    DEFAULT_QUALITY,
    MODES,
    ORIENTATIONS,
    QUALITY_PRESETS,
    RECORD_FORMATS,
    RENDER_FITS,
    VIDEO_CODECS,
    ProfileField,
    PROFILE_FIELDS,
    ScrcpyManager,
    is_profile_bool_yes,
    sanitize_profile_name,
)

try:
    from textual.app import ComposeResult
    from textual.containers import Horizontal
    from textual.screen import ModalScreen
    from textual.widgets import (
        Button,
        Checkbox,
        DataTable,
        Input,
        Select,
        Static,
    )

    TEXTUAL_AVAILABLE = True
except ImportError:
    TEXTUAL_AVAILABLE = False

if TEXTUAL_AVAILABLE:

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
            yield Static(
                f"Address: {self.ipport}\nEnter pairing code from device (4-8 digits):",
                classes="dialog-body",
            )
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

        def __init__(self, profile: dict[str, str] | None = None) -> None:
            self.profile = profile or {}
            super().__init__()

        def compose(self) -> ComposeResult:
            is_edit = bool(self.profile.get("name"))
            yield Static("Edit Profile" if is_edit else "Add Profile", classes="dialog-title")
            yield Static("Profile ID (no spaces)", classes="label")
            yield Input(value=self.profile.get("name", ""), id="profile_id", disabled=is_edit)

            current_section = ""
            for field in PROFILE_FIELDS:
                if field.section and field.section != current_section:
                    current_section = field.section
                    yield Static(f"▸ {field.section}", classes="section-header")

                yield Static(field.label, classes="label")
                if field.type == "choice":
                    choices = [("", "")] + [(c, c) for c in field.choices]
                    yield Select(choices, value=self.profile.get(field.name, field.default), id=field.name)
                elif field.type == "bool":
                    val = is_profile_bool_yes(self.profile.get(field.name, field.default))
                    yield Checkbox(field.label, value=val, id=field.name)
                else:
                    yield Input(value=self.profile.get(field.name, field.default), id=field.name)

            with Horizontal(classes="dialog-buttons"):
                yield Button("Save", id="save", variant="primary")
                yield Button("Cancel", id="cancel", variant="default")

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "cancel":
                self.dismiss(None)
            elif event.button.id == "save":
                profile_id = self.query_one("#profile_id", Input).value.strip()
                if not profile_id:
                    self.app.notify("Profile ID is required.", severity="error")
                    return

                result: dict[str, str] = {"name": profile_id}
                for field in PROFILE_FIELDS:
                    if field.type == "bool":
                        widget = self.query_one(f"#{field.name}", Checkbox)
                        result[field.name] = "yes" if widget.value else ""
                    elif field.type == "choice":
                        widget = self.query_one(f"#{field.name}", Select)
                        result[field.name] = str(widget.value)
                    else:
                        widget = self.query_one(f"#{field.name}", Input)
                        result[field.name] = widget.value.strip()

                if not result.get("ip") and not result.get("serial"):
                    self.app.notify("Profile must have either an IP or serial.", severity="error")
                    return

                self.dismiss(result)

    class HelpScreen(ModalScreen[None]):
        """Modal screen showing scrcpy keyboard shortcuts."""

        def compose(self) -> ComposeResult:
            yield Static("scrcpy Keyboard Shortcuts", classes="dialog-title")
            yield Static(
                "MOD = Left Alt or Left Super (Windows key)\n\n"
                "Navigation:\n"
                "  MOD + h     Home\n"
                "  MOD + b     Back\n"
                "  MOD + s     App Switcher (Recent Apps)\n"
                "  MOD + n     Notifications\n"
                "  MOD + m     Menu\n\n"
                "Display:\n"
                "  MOD + f / F11    Fullscreen\n"
                "  MOD + g          Resize 1:1\n"
                "  MOD + w          Remove black borders\n"
                "  MOD + r          Rotate device\n"
                "  MOD + p          Power button\n"
                "  MOD + o          Turn screen off\n"
                "  MOD + Shift + o  Turn screen on\n\n"
                "Volume:\n"
                "  MOD + Up     Volume Up\n"
                "  MOD + Down   Volume Down\n\n"
                "Clipboard (Android 7+):\n"
                "  MOD + c     Copy\n"
                "  MOD + x     Cut\n"
                "  MOD + v     Paste\n"
                "  MOD + Shift+v  Paste as key events\n\n"
                "Mouse (in scrcpy window):\n"
                "  Right-click     Back (or Power on)\n"
                "  Middle-click    Home\n"
                "  4th button      App Switcher\n"
                "  5th button      Notifications\n\n"
                "Gestures:\n"
                "  Ctrl+drag       Pinch-to-zoom\n"
                "  Shift+drag      Tilt (2-finger scroll)\n"
                "  Ctrl+Shift+drag Horizontal tilt\n\n"
                "Window:\n"
                "  MOD + q     Quit scrcpy\n"
                "  MOD + i     FPS counter\n"
                "  MOD + z     Pause display\n"
                "  MOD + Shift+z  Unpause\n",
                classes="dialog-body",
            )
            with Horizontal(classes="dialog-buttons"):
                yield Button("Close", id="close", variant="primary")

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "close":
                self.dismiss()

    class LaunchOptionsScreen(ModalScreen[list[str] | None]):
        """Modal screen for one-off launch overrides without editing the profile."""

        def __init__(self, manager: ScrcpyManager, profile: dict[str, str]) -> None:
            self.manager = manager
            self.profile = profile
            super().__init__()

        def compose(self) -> ComposeResult:
            yield Static(f"Launch Options: {self.profile['nickname']}", classes="dialog-title")
            yield Static("Override quality for this launch", classes="label")
            qualities = [("Profile default", "")] + [(q, q) for q in QUALITY_PRESETS if not q.startswith("camera_")]
            yield Select(qualities, value="", id="override_quality")
            yield Static("Override video codec", classes="label")
            vcodecs = [("Profile default", "")] + [(c, c) for c in VIDEO_CODECS]
            yield Select(vcodecs, value="", id="override_video_codec")
            yield Static("Override audio codec", classes="label")
            acodecs = [("Profile default", "")] + [(c, c) for c in AUDIO_CODECS]
            yield Select(acodecs, value="", id="override_audio_codec")
            yield Checkbox("Fullscreen", value=False, id="fullscreen")
            yield Checkbox("Always on top", value=False, id="always_on_top")
            yield Checkbox("Disable screensaver", value=False, id="disable_screensaver")
            yield Checkbox("Turn screen off", value=False, id="turn_screen_off")
            yield Checkbox("Print FPS", value=False, id="print_fps")
            with Horizontal(classes="dialog-buttons"):
                yield Button("Launch", id="launch", variant="primary")
                yield Button("Cancel", id="cancel", variant="default")

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "cancel":
                self.dismiss(None)
            elif event.button.id == "launch":
                extra: list[str] = []
                q = str(self.query_one("#override_quality", Select).value)
                if q:
                    settings = self.manager.get_quality_settings(q)
                    bitrate = settings.get("video_bitrate", "8M")
                    extra.append(f"--video-bit-rate={bitrate}")
                vc = str(self.query_one("#override_video_codec", Select).value)
                if vc:
                    extra.append(f"--video-codec={vc}")
                ac = str(self.query_one("#override_audio_codec", Select).value)
                if ac:
                    extra.append(f"--audio-codec={ac}")
                if self.query_one("#fullscreen", Checkbox).value:
                    extra.append("--fullscreen")
                if self.query_one("#always_on_top", Checkbox).value:
                    extra.append("--always-on-top")
                if self.query_one("#disable_screensaver", Checkbox).value:
                    extra.append("--disable-screensaver")
                if self.query_one("#turn_screen_off", Checkbox).value:
                    extra.append("--turn-screen-off")
                if self.query_one("#print_fps", Checkbox).value:
                    extra.append("--print-fps")
                self.dismiss(extra)

    class CameraSetupScreen(ModalScreen[list[str] | None]):
        """Modal screen for camera mode options."""

        def __init__(self) -> None:
            super().__init__()

        def compose(self) -> ComposeResult:
            yield Static("Camera Mode Setup", classes="dialog-title")
            yield Static("Camera ID (0=back, 1=front)", classes="label")
            yield Input(value="0", id="camera_id")
            yield Static("Camera facing", classes="label")
            facings = [("Auto (first)", ""), ("Back", "back"), ("Front", "front"), ("External", "external")]
            yield Select(facings, value="", id="camera_facing")
            yield Static("Aspect Ratio", classes="label")
            ratios = [("16:9", "1"), ("4:3", "2"), ("1:1", "3"), ("Native", "4")]
            yield Select(ratios, value="1", id="aspect")
            yield Static("Quality", classes="label")
            qualities = [
                ("Low (640x480, 2Mbps)", "1"),
                ("Balanced (720p, 4Mbps)", "2"),
                ("High (1080p, 8Mbps)", "3"),
            ]
            yield Select(qualities, value="2", id="quality")
            yield Static("Camera FPS (leave empty for default 30)", classes="label")
            yield Input(placeholder="30", id="camera_fps")
            yield Checkbox("High-speed capture mode", value=False, id="camera_high_speed")
            yield Checkbox("Torch on start", value=False, id="camera_torch")
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
                facing = str(self.query_one("#camera_facing", Select).value)
                if facing:
                    args.append(f"--camera-facing={facing}")
                aspect_map = {"1": "16:9", "2": "4:3", "3": "1:1"}
                aspect_val = str(self.query_one("#aspect", Select).value)
                if aspect_val in aspect_map:
                    args.append(f"--camera-ar={aspect_map[aspect_val]}")
                quality_val = str(self.query_one("#quality", Select).value)
                quality_map = {"1": "camera_low", "2": "camera_balanced", "3": "camera_high"}
                preset = quality_map.get(quality_val, "camera_balanced")
                fps = self.query_one("#camera_fps", Input).value.strip()
                if fps:
                    args.append(f"--camera-fps={fps}")
                if self.query_one("#camera_high_speed", Checkbox).value:
                    args.append("--camera-high-speed")
                if self.query_one("#camera_torch", Checkbox).value:
                    args.append("--camera-torch")
                zoom = self.query_one("#zoom", Input).value.strip()
                if zoom:
                    args.append(f"--camera-zoom={zoom}")
                self.dismiss([preset, *args])

    class QuickAppScreen(ModalScreen[list[str] | None]):
        """Modal screen for quick app launcher."""

        def __init__(self) -> None:
            super().__init__()

        def compose(self) -> ComposeResult:
            yield Static("Quick App Launcher", classes="dialog-title")
            yield Static("Launch mode", classes="label")
            modes = [
                ("Mirror + Launch app", "1"),
                ("Virtual display + Launch app", "2"),
                ("Launch app only", "3"),
            ]
            yield Select(modes, value="1", id="mode")
            yield Static("Package name (e.g. com.android.settings)", classes="label")
            yield Input(placeholder="com.android.settings", id="package")
            yield Static("Virtual display spec (e.g. 1920x1080/160)", classes="label")
            yield Input(placeholder="Leave empty for default size", id="new_display_spec")
            yield Checkbox("Flex display (resizable)", value=False, id="flex_display")
            yield Checkbox("Keep device active", value=False, id="keep_active")
            yield Checkbox("No system decorations", value=False, id="no_vd_decorations")
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
                    display_spec = self.query_one("#new_display_spec", Input).value.strip()
                    if display_spec:
                        args.append(f"--new-display={display_spec}")
                    else:
                        args.append("--new-display")
                    if self.query_one("#flex_display", Checkbox).value:
                        args.append("--flex-display")
                    if self.query_one("#no_vd_decorations", Checkbox).value:
                        args.append("--no-vd-system-decorations")
                if self.query_one("#keep_active", Checkbox).value:
                    args.append("--keep-active")
                self.dismiss(args)

    class DiscoverListScreen(ModalScreen[tuple[ScrcpyManager, str, str, str] | None]):
        """Modal screen to select a discovered wireless device."""

        def __init__(self, manager: ScrcpyManager, items: list[tuple[str, str, str, str]]) -> None:
            self.manager = manager
            self.items = items
            super().__init__()

        def compose(self) -> ComposeResult:
            yield Static("Discovered Devices", classes="dialog-title")
            table: DataTable = DataTable(id="discover-table")
            table.add_columns("#", "Name", "Address", "Type", "Source")
            table.cursor_type = "row"
            table.zebra_stripes = True
            for i, (name, ipport, source, service_type) in enumerate(self.items, 1):
                type_label = {
                    "_adb-tls-pairing._tcp": "Pairing",
                    "_adb-tls-connect._tcp": "Connect",
                    "_adb._tcp": "Legacy",
                }.get(service_type, service_type)
                table.add_row(str(i), name, ipport, type_label, source)
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
                name, ipport, _source, service_type = self.items[row]
                self.dismiss((self.manager, ipport, name, service_type))

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
            table: DataTable = DataTable(id="profile-table")
            table.add_columns("#", "Name", "IP", "Serial", "Quality", "Mode", "Video", "Audio", "Fit")
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
                table.add_row(
                    str(i),
                    p["nickname"],
                    p.get("ip", ""),
                    p.get("serial", ""),
                    p["quality"],
                    p.get("mode", "mirror"),
                    p.get("video_codec", ""),
                    p.get("audio_codec", ""),
                    p.get("render_fit", ""),
                )

        def on_button_pressed(self, event: Button.Pressed) -> None:
            bid = event.button.id
            if bid == "close":
                self.dismiss()
            elif bid == "add":
                self.app.push_screen(ProfileEditScreen(), self._on_profile_saved)
            elif bid == "edit":
                table = self.query_one("#profile-table", DataTable)
                row = table.cursor_row
                profiles = self.manager.list_profiles()
                if row is None or not (0 <= row < len(profiles)):
                    self.app.notify("Select a profile to edit.", severity="error")
                    return
                self.app.push_screen(ProfileEditScreen(profiles[row]), self._on_profile_saved)
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
                name = result.pop("name")
                self.manager.save_profile(name, **result)
                self.app.notify(f"Profile '{name}' saved")
                self._refresh()
            except Exception as exc:
                self.app.push_screen(MessageScreen(str(exc), "Save Error"))

        def _on_delete(self, confirmed: bool | None, name: str) -> None:
            if confirmed:
                self.manager.delete_profile(name)
                self.app.notify(f"Deleted '{name}'")
                self._refresh()
