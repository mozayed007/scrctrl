#!/usr/bin/env python3
"""Textual TUI for scrcpy Device Manager.

Provides a rich terminal interface for managing and launching scrcpy
sessions. Falls back gracefully if Textual is not installed.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar, TypeVar

from scrcpy_manager import Device, ScrcpyManager, sanitize_profile_name

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


async def _to_thread(func: Callable[..., _T], *args: Any, **kwargs: Any) -> _T:
    if hasattr(asyncio, "to_thread"):
        return await asyncio.to_thread(func, *args, **kwargs)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: func(*args, **kwargs))


# Textual imports and all dependent classes live inside the try block
# so the module remains importable when Textual is not installed.
try:
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Horizontal, Vertical, VerticalScroll
    from textual.reactive import reactive
    from textual.screen import Screen
    from textual.widgets import (
        Button,
        DataTable,
        Footer,
        Header,
        Static,
    )

    from scrcpy_tui_screens import (
        TEXTUAL_AVAILABLE,
        CameraSetupScreen,
        ConfirmScreen,
        DeviceSelectScreen,
        DiscoverListScreen,
        HelpScreen,
        LaunchOptionsScreen,
        MessageScreen,
        PairingScreen,
        ProfileEditScreen,
        ProfileListScreen,
        QuickAppScreen,
    )

    def _safe_int(value: str, default: int = 0) -> int:
        try:
            return int(value)
        except (ValueError, TypeError):
            return default

    class MainScreen(Screen[None]):
        """Main screen showing devices, profiles, and action buttons."""

        BINDINGS: ClassVar[list[Binding]] = [  # type: ignore[assignment]
            Binding("q", "quit", "Quit"),
            Binding("r", "refresh", "Refresh"),
            Binding("d", "detect", "Detect"),
            Binding("f", "discover", "Discover"),
            Binding("s", "setup", "Setup"),
            Binding("c", "camera", "Camera"),
            Binding("p", "quickapp", "QuickApp"),
            Binding("a", "profiles", "Profiles"),
            Binding("l", "quick_launch", "Quick Launch"),
            Binding("o", "launch_options", "Launch Options"),
            Binding("u", "update", "Update"),
            Binding("x", "shutdown", "Shutdown"),
            Binding("h", "help", "Help"),
        ]

        CSS: ClassVar[str] = """  # type: ignore[assignment]
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
            self._tasks: set[asyncio.Task[None]] = set()
            super().__init__()

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            with Horizontal(id="main-container"):
                with Vertical(id="devices-panel"):
                    yield Static("Connected Devices", classes="panel-title")
                    yield Static("No devices", classes="panel-subtitle")
                    dev_table: DataTable = DataTable(id="devices-table")
                    dev_table.add_columns("#", "Name", "Type", "Model")
                    dev_table.cursor_type = "row"
                    dev_table.zebra_stripes = True
                    yield dev_table

                with Vertical(id="profiles-panel"):
                    yield Static("Saved Profiles", classes="panel-title")
                    yield Static("No profiles", classes="panel-subtitle")
                    prof_table: DataTable = DataTable(id="profiles-table")
                    prof_table.add_columns("#", "Name", "Quality", "Mode", "Video", "Audio")
                    prof_table.cursor_type = "row"
                    prof_table.zebra_stripes = True
                    yield prof_table

                with VerticalScroll(id="actions-panel"):
                    yield Static("Actions", classes="panel-title")
                    yield Button("[L] Quick Launch", id="act-quick", variant="primary", classes="action-btn")
                    yield Button("[O] Launch Options", id="act-launch-opts", classes="action-btn")
                    yield Button("[D] Detect Devices", id="act-detect", classes="action-btn")
                    yield Button("[F] Discover", id="act-discover", classes="action-btn")
                    yield Button("[S] Setup Wireless", id="act-setup", classes="action-btn")
                    yield Button("[C] Camera Mode", id="act-camera", classes="action-btn")
                    yield Button("[P] Quick App", id="act-quickapp", classes="action-btn")
                    yield Button("[A] Profiles", id="act-profiles", classes="action-btn")
                    yield Button("[H] Help", id="act-help", classes="action-btn")
                    yield Button("[U] Update scrcpy", id="act-update", classes="action-btn")
                    yield Button("[X] Shutdown ADB", id="act-shutdown", classes="action-btn")
                    yield Button("[R] Refresh", id="act-refresh", classes="action-btn")
                    yield Button("[Q] Quit", id="act-quit", classes="action-btn")

            yield Static("Ready", id="status")
            yield Footer()

        def _run_bg(self, coro: Awaitable[None]) -> None:
            """Run a coroutine in the background with error handling."""

            async def _wrapper() -> None:
                try:
                    await coro
                except Exception as exc:
                    self.app.notify(f"Error: {exc}", severity="error")
                    logger.exception("Background task failed")

            task = asyncio.create_task(_wrapper())
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

        async def on_mount(self) -> None:
            # Show UI immediately, do slow operations in background
            await self._refresh_data_async()
            self.set_interval(3, self.refresh_data)
            self._run_bg(self._background_auto_connect())
            self._run_bg(self._background_update_check())

        async def _background_auto_connect(self) -> None:
            """Auto-reconnect saved wireless profiles without blocking UI."""
            try:
                reconnected = await _to_thread(self.manager.auto_connect_profiles)
                if reconnected:
                    self.app.notify(f"Auto-reconnected: {', '.join(reconnected)}")
                    self.refresh_data()
            except Exception:
                pass

        async def _background_update_check(self) -> None:
            """Check for updates in background without blocking UI."""
            if not self.manager.get_pref_bool("auto_check_updates", True):
                return
            try:
                from scrcpy_cli import check_updates_silent

                newer = await _to_thread(check_updates_silent)
                if newer:
                    self.app.notify(
                        f"Update available: {newer}. Press [U] to update.",
                        severity="information",
                        timeout=8,
                    )
            except Exception:
                pass

        async def _refresh_data_async(self) -> None:
            try:
                self.devices_data = await _to_thread(self.manager.list_devices)
                self.profiles_data = self.manager.list_profiles()
                self.status_message = f"{len(self.devices_data)} device(s), {len(self.profiles_data)} profile(s)"
            except Exception as exc:
                self.status_message = f"Error: {exc}"

        def refresh_data(self) -> None:
            self._run_bg(self._refresh_data_async())

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
                    table.add_row(
                        str(index),
                        profile["nickname"],
                        profile.get("quality", "balanced"),
                        profile.get("mode", "mirror"),
                        profile.get("video_codec", "-") or "default",
                        profile.get("audio_codec", "-") or "default",
                    )

        def watch_status_message(self, message: str) -> None:
            self.query_one("#status", Static).update(message)

        def action_quit(self) -> None:
            self.app.exit()

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

        def _run_scrcpy(self, args: list[str]) -> None:
            """Run scrcpy with given args and handle result."""
            try:
                result = self.manager.scrcpy(args, detach=True)
                if isinstance(result, subprocess.Popen):
                    self.app.notify(f"scrcpy started (pid {result.pid})")
                elif result != 0:
                    self.app.push_screen(MessageScreen(f"scrcpy exited with code {result}", "Launch Error"))
                else:
                    self.app.notify("scrcpy launched")
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
                self._run_bg(self.action_discover())
            elif button_id == "act-setup":
                self.action_setup()
            elif button_id == "act-camera":
                self._run_bg(self.action_camera())
            elif button_id == "act-quickapp":
                self._run_bg(self.action_quickapp())
            elif button_id == "act-profiles":
                self.action_profiles()
            elif button_id == "act-quick":
                self._run_bg(self.action_quick_launch())
            elif button_id == "act-launch-opts":
                self.action_launch_options()
            elif button_id == "act-help":
                self.action_help()
            elif button_id == "act-update":
                self.action_update()
            elif button_id == "act-shutdown":
                self.action_shutdown()

        def action_refresh(self) -> None:
            self.refresh_data()
            self.app.notify("Refreshed")

        def action_help(self) -> None:
            self.app.push_screen(HelpScreen())

        def action_detect(self) -> None:
            self.app.push_screen(
                MessageScreen("Use the device list on the left. Auto-refresh is active.", "Device Detection")
            )

        async def action_discover(self) -> None:
            self.status_message = "Discovering..."
            try:
                devices = await _to_thread(self.manager.mdns_discover)
                if not devices:
                    self.app.push_screen(
                        MessageScreen(
                            "No devices found via mDNS.\nEnable Wireless Debugging on Android 11+.", "Discovery"
                        )
                    )
                    return

                items: list[tuple[str, str, str, str]] = []
                for d in devices:
                    items.append((d.name, d.ipport, d.source, d.service_type))

                self.app.push_screen(
                    DiscoverListScreen(self.manager, items),
                    self._on_discover_result,
                )
            except Exception as exc:
                self.app.push_screen(MessageScreen(str(exc), "Discovery Error"))
            self.refresh_data()

        def _on_discover_result(self, result: tuple[ScrcpyManager, str, str, str] | None) -> None:
            if result is None:
                return
            manager, ipport, name, service_type = result
            if service_type == "_adb-tls-pairing._tcp":
                self.app.push_screen(
                    PairingScreen(name, ipport),
                    lambda code: self._on_pairing_code(code, manager, ipport, name),
                )
            else:
                self._run_bg(self._do_discover_connect(result))

        async def _do_discover_connect(self, result: tuple[ScrcpyManager, str, str, str]) -> None:
            manager, ipport, name, service_type = result
            self.status_message = f"Connecting to {name}..."
            try:
                success, message, serial = await _to_thread(lambda: manager.connect_wireless(ipport))
                if not success or not serial:
                    self.app.push_screen(MessageScreen(message, "Connection Failed"))
                    return
                self.app.push_screen(
                    ConfirmScreen(f"Save '{name}' as a profile?", "Save Profile"),
                    lambda save: self._on_save_profile(save, manager, name, ipport, serial, service_type),
                )
            except Exception as exc:
                self.app.push_screen(MessageScreen(str(exc), "Connection Error"))
            self.refresh_data()

        def _on_pairing_code(self, code: str | None, manager: ScrcpyManager, ipport: str, name: str) -> None:
            if code is None:
                return
            self._run_bg(self._do_pair_and_connect(code, manager, ipport, name))

        async def _do_pair_and_connect(self, code: str, manager: ScrcpyManager, ipport: str, name: str) -> None:
            self.status_message = f"Pairing with {name}..."
            try:
                success, message = await _to_thread(lambda: manager.pair_device(ipport, code))
                if not success:
                    self.app.push_screen(MessageScreen(message, "Pairing Failed"))
                    return
                self.app.notify(f"Paired with {name}")
                await asyncio.sleep(2)

                devices = await _to_thread(manager.mdns_discover)
                selected_ip = ipport.split(":")[0]
                connect_device = None
                for d in devices:
                    if d.service_type == "_adb-tls-connect._tcp":
                        d_ip = d.ipport.split(":")[0]
                        if d_ip == selected_ip:
                            connect_device = d
                            break

                if not connect_device:
                    self.app.push_screen(
                        MessageScreen(
                            "Device paired but not found in connection list. Please try discovery again.",
                            "Connection Not Found",
                        )
                    )
                    return

                self.app.notify(f"Found connection port: {connect_device.ipport}")
                await self._do_discover_connect((manager, connect_device.ipport, name, connect_device.service_type))
            except Exception as exc:
                self.app.push_screen(MessageScreen(str(exc), "Pairing Error"))
            self.refresh_data()

        def _on_save_profile(
            self, save: bool | None, manager: ScrcpyManager, name: str, ipport: str, serial: str, service_type: str
        ) -> None:
            ip_to_save = ipport if service_type == "_adb._tcp" else ipport.split(":")[0]
            if not save:
                # Launch without saving
                temp_profile = {
                    "name": name,
                    "nickname": name,
                    "ip": ip_to_save,
                    "serial": "",
                    "quality": "balanced",
                    "mode": "mirror",
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

            def on_profile_edit(result: dict[str, str] | None) -> None:
                if not result:
                    return
                try:
                    name = result.pop("name")
                    manager.save_profile(name, **result)
                    self.app.notify(f"Saved profile '{name}'")
                    self._launch_profile(name)
                except Exception as exc:
                    self.app.push_screen(MessageScreen(str(exc), "Save Error"))

            # Pre-fill profile edit with discovered device info
            prefill = {
                "name": sanitize_profile_name(name),
                "nickname": name,
                "ip": ip_to_save,
                "serial": "",
                "quality": "balanced",
                "mode": "mirror",
            }
            self.app.push_screen(ProfileEditScreen(prefill), on_profile_edit)

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
            self._run_bg(self._do_setup())

        async def _do_setup(self) -> None:
            self.status_message = "Running wireless setup..."
            try:
                await _to_thread(self.manager.setup_wireless)  # type: ignore[attr-defined]
                self.app.notify("Wireless setup complete")
            except Exception as exc:
                self.app.push_screen(MessageScreen(str(exc), "Setup Error"))
            self.refresh_data()

        async def action_camera(self) -> None:
            devices = await _to_thread(self.manager.list_devices)
            if not devices:
                self.app.push_screen(MessageScreen("No connected devices found.", "Camera Mode"))
                return
            if len(devices) == 1:
                self._open_camera_setup(devices[0])
                return
            self.app.push_screen(
                DeviceSelectScreen(devices, "Camera Mode Device"),
                lambda device: self._open_camera_setup(device) if device else None,
            )

        def _open_camera_setup(self, device: Device) -> None:
            self.app.push_screen(
                CameraSetupScreen(),
                lambda result: self._on_camera_result(result, device),
            )

        def _on_camera_result(self, result: list[str] | None, device: Device) -> None:
            if result is None:
                return
            self._run_bg(self._do_camera_launch(result, device))

        async def _do_camera_launch(self, result: list[str], selected: Device) -> None:
            preset = result[0]
            extra_args = result[1:]
            settings = self.manager.get_quality_settings(preset)
            args = ["-s", selected.serial, *extra_args]
            if settings.get("video_bitrate"):
                args.append(f"--video-bit-rate={settings['video_bitrate']}")
            if settings.get("resolution"):
                args.append(f"--camera-size={settings['resolution']}")
            args.extend(["--window-title", f"scrcpy - {selected.display_name} (Camera Mode)"])
            self._run_scrcpy(args)

        async def action_quickapp(self) -> None:
            devices = await _to_thread(self.manager.list_devices)
            if not devices:
                self.app.push_screen(MessageScreen("No connected devices found.", "Quick App"))
                return
            if len(devices) == 1:
                self._open_quickapp_setup(devices[0])
                return
            self.app.push_screen(
                DeviceSelectScreen(devices, "Quick App Device"),
                lambda device: self._open_quickapp_setup(device) if device else None,
            )

        def _open_quickapp_setup(self, device: Device) -> None:
            self.app.push_screen(
                QuickAppScreen(),
                lambda result: self._on_quickapp_result(result, device),
            )

        def _on_quickapp_result(self, result: list[str] | None, device: Device) -> None:
            if result is None:
                return
            self._run_bg(self._do_quickapp_launch(result, device))

        async def _do_quickapp_launch(self, result: list[str], selected: Device) -> None:
            if result and result[0] == "__ADB_START_APP__":
                package_name = result[1]
                completed = await _to_thread(
                    lambda: self.manager.adb(
                        "-s",
                        selected.serial,
                        "shell",
                        "monkey",
                        "-p",
                        package_name,
                        "-c",
                        "android.intent.category.LAUNCHER",
                        "1",
                    )
                )
                output = (completed.stdout or completed.stderr or "").strip()
                if completed.returncode == 0:
                    self.app.notify(f"Launched {package_name}")
                else:
                    self.app.push_screen(MessageScreen(output or "ADB app launch failed.", "Quick App Error"))
                self.refresh_data()
                return
            args = ["-s", selected.serial, *result]
            args.extend(["--window-title", f"scrcpy - {selected.display_name} (App)"])
            self._run_scrcpy(args)

        def action_profiles(self) -> None:
            self.app.push_screen(
                ProfileListScreen(self.manager),
                lambda _: self.refresh_data(),
            )

        async def action_quick_launch(self) -> None:
            self.status_message = "Quick launching..."
            try:
                result = await _to_thread(lambda: self.manager.quick_launch(detach=True))
                if isinstance(result, subprocess.Popen):
                    self.app.notify(f"Quick launch started (pid {result.pid})")
                elif result != 0:
                    self.app.push_screen(MessageScreen(f"scrcpy exited with code {result}", "Launch Error"))
                else:
                    self.app.notify("Quick launch succeeded")
            except Exception as exc:
                self.app.push_screen(MessageScreen(str(exc), "Quick Launch Error"))
            self.refresh_data()

        def action_launch_options(self) -> None:
            profile = self._get_selected_profile()
            if not profile:
                self.app.notify("Select a profile first to use launch options.", severity="warning")
                return
            self.app.push_screen(
                LaunchOptionsScreen(self.manager, profile),
                lambda extra: self._on_launch_options(extra, profile["name"]),
            )

        def _on_launch_options(self, extra: list[str] | None, profile_name: str) -> None:
            if extra is None:
                return
            self.status_message = f"Launching {profile_name} with options..."
            try:
                result = self.manager.launch_profile(profile_name, extra=extra, detach=True)
                if isinstance(result, subprocess.Popen):
                    self.app.notify(f"Launched {profile_name} with options (pid {result.pid})")
                elif result != 0:
                    self.app.push_screen(MessageScreen(f"scrcpy exited with code {result}", "Launch Error"))
                else:
                    self.app.notify(f"Launched {profile_name} with options")
            except Exception as exc:
                self.app.push_screen(MessageScreen(str(exc), "Launch Error"))
            self.refresh_data()

        def action_shutdown(self) -> None:
            self.app.push_screen(
                ConfirmScreen("Disconnect all ADB connections and stop the server?", "Shutdown ADB"),
                self._on_shutdown_confirm,
            )

        def _on_shutdown_confirm(self, confirmed: bool | None) -> None:
            if confirmed:
                self._run_bg(self._do_shutdown())

        async def _do_shutdown(self) -> None:
            self.status_message = "Shutting down ADB..."
            try:
                await _to_thread(self.manager.shutdown)
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
            self._run_bg(self._do_update())

        async def _do_update(self) -> None:
            self.status_message = "Updating scrcpy..."
            try:
                from scrcpy_cli import update_scrcpy

                result = await _to_thread(update_scrcpy)
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
        .section-header {
            text-style: bold;
            color: $primary;
            margin-top: 1;
            margin-bottom: 1;
        }
        #profile-edit-scroll {
            height: 1fr;
            max-height: 70%;
        }
        """

        def __init__(self, manager: ScrcpyManager) -> None:
            self.manager = manager
            super().__init__()

        def on_mount(self) -> None:
            self.push_screen(MainScreen(self.manager))

    def run_tui(manager: ScrcpyManager) -> None:
        """Run the Textual TUI."""
        app = ScrcpyTuiApp(manager)
        app.run()

except ImportError:
    TEXTUAL_AVAILABLE = False

    def run_tui(manager: ScrcpyManager) -> None:  # noqa: ARG001
        """Stub when Textual is not installed."""
        raise ImportError("Textual is required for the TUI. Install it with:\n  pip install textual")


if __name__ == "__main__":
    try:
        manager = ScrcpyManager()
        run_tui(manager)
    except ImportError as exc:
        print(exc)
        raise SystemExit(1) from None
    except SystemExit:
        raise
    except Exception as exc:
        print(f"Error: {exc}")
        raise SystemExit(1) from exc
