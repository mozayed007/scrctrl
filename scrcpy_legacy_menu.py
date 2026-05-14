#!/usr/bin/env python3
"""Legacy terminal menu interface for scrcpy Device Manager.

Provides interactive input()-based menus for environments where the
Textual TUI is not available or not desired.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from scrcpy_manager import (
    DEFAULT_ADB_PORT,
    DEFAULT_MODE,
    DEFAULT_QUALITY,
    Device,
    ScrcpyManager,
    clear_screen,
    is_valid_camera_id,
    is_valid_ipv4,
    is_valid_package_name,
    press_enter,
    prompt,
    prompt_yes_no,
    quote_command,
    sanitize_profile_name,
)

if TYPE_CHECKING:
    import subprocess

logger = logging.getLogger(__name__)


class LegacyMenu(ScrcpyManager):
    """ScrcpyManager extended with legacy terminal menus."""

    def discover_menu(self) -> int:
        """Interactive menu for discovering and connecting to wireless devices.

        Returns:
            0 on success or cancel, 1 on error
        """
        import time

        try:
            clear_screen()
            print("Network Device Discovery\n")
            devices = self.mdns_discover()
            if not devices:
                print("No devices found via mDNS.")
                print("Enable Wireless Debugging on Android 11+ and keep the device on the same network.")
                return 1

            # Group devices by service type for better display
            pairing_devices = [d for d in devices if d.service_type == "_adb-tls-pairing._tcp"]
            connect_devices = [d for d in devices if d.service_type == "_adb-tls-connect._tcp"]
            legacy_devices = [d for d in devices if d.service_type == "_adb._tcp"]

            if pairing_devices:
                print("Devices requiring pairing (Android 11+):\n")
                for index, device in enumerate(pairing_devices, start=1):
                    print(f"[{index}] {device.name}")
                    print(f"    Address: {device.ipport}")
                    print(f"    Type:    Pairing required\n")

            if connect_devices:
                print("Already paired devices (Android 11+):\n")
                for index, device in enumerate(connect_devices, start=len(pairing_devices) + 1):
                    print(f"[{index}] {device.name}")
                    print(f"    Address: {device.ipport}")
                    print(f"    Type:    Ready to connect\n")

            if legacy_devices:
                print("Legacy devices (Android <11):\n")
                for index, device in enumerate(legacy_devices, start=len(pairing_devices) + len(connect_devices) + 1):
                    print(f"[{index}] {device.name}")
                    print(f"    Address: {device.ipport}")
                    print(f"    Type:    Legacy TCP\n")

            # Combine all devices for selection
            all_devices = pairing_devices + connect_devices + legacy_devices

            choice = prompt("Select device number, or press Enter to cancel")
            if not choice:
                return 0
            if not choice.isdigit() or not (1 <= int(choice) <= len(all_devices)):
                print("Invalid selection.")
                return 1

            selected = all_devices[int(choice) - 1]
            connected_serial = None

            # Handle different service types
            if selected.service_type == "_adb-tls-pairing._tcp":
                # Need to pair first
                print(f"\nPairing with {selected.name}")
                print(f"Address: {selected.ipport}")
                pairing_code = prompt("Enter pairing code from device (usually 6 digits)")
                # More flexible validation - allow 4-8 digit codes
                if not pairing_code or len(pairing_code) < 4 or len(pairing_code) > 8 or not pairing_code.isdigit():
                    print("Invalid pairing code. Must be 4-8 digits.")
                    return 1

                success, message = self.pair_device(selected.ipport, pairing_code)
                if not success:
                    print(f"Pairing failed: {message}")
                    print("Note: Pairing codes expire after a few minutes. Try refreshing the pairing code on your device.")
                    return 1

                print(f"\n{message}")
                print("Waiting for device to appear in connection list...")
                time.sleep(2)

                # Rediscover to find the connect port
                devices_after_pairing = self.mdns_discover()
                connect_devices_after = [d for d in devices_after_pairing if d.service_type == "_adb-tls-connect._tcp"]

                # Find device with same IP
                selected_ip = selected.ipport.split(":")[0]
                connect_device = None
                for device in connect_devices_after:
                    if device.ipport.startswith(selected_ip):
                        connect_device = device
                        break

                if not connect_device:
                    print("Device paired but not found in connection list. Please try discovery again.")
                    return 1

                print(f"Found connection port: {connect_device.ipport}")
                selected = connect_device

            # Now connect (for both _adb-tls-connect and _adb._tcp)
            success, message, connected_serial = self.connect_wireless(selected.ipport)
            if not success or not connected_serial:
                raise RuntimeError(f"Failed to connect to {selected.ipport}: {message}")

            if prompt_yes_no("Save this device as a profile", default=True):
                profile_name = sanitize_profile_name(
                    prompt("Profile ID", sanitize_profile_name(selected.name))
                )
                nickname = prompt("Display name", selected.name)
                # Save IP without port for Android 11+ devices (ports can change)
                # For legacy devices, we can save the full IP:port
                ip_to_save = selected.ipport.split(":")[0] if selected.service_type != "_adb._tcp" else selected.ipport
                self.save_profile(
                    profile_name=profile_name,
                    nickname=nickname,
                    ip=ip_to_save,
                    serial="",
                    quality=DEFAULT_QUALITY,
                    mode=DEFAULT_MODE,
                    keep_active="",
                    background_color="",
                )
                return self.launch_profile(
                    profile_name,
                    connection=connected_serial,
                    connection_type="wireless",
                )
            temp_profile = {
                "name": sanitize_profile_name(selected.name),
                "nickname": selected.name,
                "ip": selected.ipport.split(":")[0],
                "serial": "",
                "quality": DEFAULT_QUALITY,
                "mode": DEFAULT_MODE,
                "keep_active": "",
                "background_color": "",
            }
            args = self.build_scrcpy_args(
                profile=temp_profile,
                connection=connected_serial,
                connection_type="wireless",
            )
            print()
            return self.scrcpy(args)
        except KeyboardInterrupt:
            print("\n")
            return 0

    def setup_wireless(self) -> int:
        """Run wireless ADB setup wizard for a USB-connected device.

        Returns:
            0 on success

        Raises:
            RuntimeError: If setup fails at any step
        """
        clear_screen()
        print("Wireless Setup Wizard\n")
        print("Requirements:")
        print("- USB debugging enabled")
        print("- Device connected via USB")
        print("- Computer authorized on the device\n")
        press_enter()

        device = self.select_usb_device()
        print(f"\nUsing USB device: {device.display_name} ({device.serial})")
        self.adb("-s", device.serial, "tcpip", str(DEFAULT_ADB_PORT), check=True)

        detected_ip = self.detect_device_ip(device.serial)
        device_ip = prompt("Detected device IP", detected_ip) if detected_ip else prompt("Device IP")
        if not device_ip:
            raise RuntimeError("No device IP was provided.")
        if not is_valid_ipv4(device_ip):
            raise RuntimeError(f"Invalid IP address: {device_ip}")

        self.adb("disconnect")
        success, message, connected_serial = self.connect_wireless(f"{device_ip}:{DEFAULT_ADB_PORT}")
        if not success or not connected_serial:
            raise RuntimeError(f"Failed to connect to {device_ip}:{DEFAULT_ADB_PORT}: {message}")

        print("\nWireless connection succeeded.")
        print(f"Connection: {connected_serial}")
        print(f"Model:      {device.model or self.adb_shell(connected_serial, ['getprop', 'ro.product.model'])}")

        if prompt_yes_no("Save this device to profiles", default=True):
            default_profile = sanitize_profile_name(device.model or "Device")
            profile_name = sanitize_profile_name(prompt("Profile ID", default_profile))
            nickname = prompt("Display name", device.model or profile_name)
            self.save_profile(
                profile_name=profile_name,
                nickname=nickname,
                ip=device_ip,
                serial=device.serial,
                quality="balanced",
                mode="mirror",
                keep_active="",
                background_color="",
            )
            self.set_last_used(profile_name, "wireless", connected_serial)
            print(f"Saved profile '{profile_name}'.")
        return 0

    def camera_mode(self) -> int:
        """Launch scrcpy in camera mode for a connected device.

        Returns:
            Scrcpy process exit code

        Raises:
            RuntimeError: If no devices found or invalid selection
        """
        devices = self.list_devices()
        if not devices:
            raise RuntimeError("No connected devices found.")

        print("\nCamera mode\n")
        for index, device in enumerate(devices, start=1):
            print(f"[{index}] {device.display_name} ({device.model})")
        choice = prompt("Device")
        if not choice.isdigit() or not (1 <= int(choice) <= len(devices)):
            raise RuntimeError("Invalid device selection.")
        selected = devices[int(choice) - 1]

        camera_id = prompt("Camera ID", "0")
        while not is_valid_camera_id(camera_id):
            print("Invalid camera ID. Must be a non-negative integer.")
            camera_id = prompt("Camera ID", "0")

        aspect_choice = prompt("Aspect ratio 1=16:9, 2=4:3, 3=1:1, 4=native", "1")
        aspect_map = {"1": "16:9", "2": "4:3", "3": "1:1"}
        quality_choice = prompt("Quality 1=low, 2=balanced, 3=high", "2")
        quality_map = {"1": "camera_low", "2": "camera_balanced", "3": "camera_high"}
        preset = quality_map.get(quality_choice, "camera_balanced")
        settings = self.get_quality_settings(preset)

        torch = prompt_yes_no("Enable camera torch", default=False)
        zoom_input = prompt("Camera zoom level (1.0 = default, leave empty)", "")

        profile = {
            "name": selected.display_name,
            "nickname": selected.display_name,
            "quality": preset,
            "mode": "camera",
            "keep_active": "",
            "background_color": "",
        }
        args = ["-s", selected.serial, "--video-source=camera", f"--camera-id={camera_id}"]
        if aspect_choice in aspect_map:
            args.append(f"--camera-ar={aspect_map[aspect_choice]}")
        if torch:
            args.append("--camera-torch")
        if zoom_input:
            try:
                float(zoom_input)
                args.append(f"--camera-zoom={zoom_input}")
            except ValueError:
                print(f"Invalid zoom value '{zoom_input}', ignoring.")
        if prompt_yes_no("Disable audio", default=False):
            args.append("--no-audio")
        if settings["video_bitrate"]:
            args.append(f"--video-bit-rate={settings['video_bitrate']}")
        if settings["resolution"]:
            args.append(f"--camera-size={settings['resolution']}")
        args.extend(["--window-title", f"scrcpy - {selected.display_name} (Camera Mode)"])
        print(f"\nCommand: {quote_command(args)}\n")
        return self.scrcpy(args)

    def quick_app(self) -> int:
        """Launch an app on a connected device with scrcpy.

        Returns:
            Scrcpy process exit code or app launch result

        Raises:
            RuntimeError: If no devices found or invalid selection
        """
        devices = self.list_devices()
        if not devices:
            raise RuntimeError("No connected devices found.")

        print("\nQuick app launcher\n")
        for index, device in enumerate(devices, start=1):
            print(f"[{index}] {device.display_name} ({device.model})")
        choice = prompt("Device")
        if not choice.isdigit() or not (1 <= int(choice) <= len(devices)):
            raise RuntimeError("Invalid device selection.")
        selected = devices[int(choice) - 1]

        print("\nMode:")
        print("[1] Mirror + launch app")
        print("[2] Virtual display + launch app")
        print("[3] Launch app only")
        mode_choice = prompt("Mode", "1")
        package_name = prompt("Package name")
        if not package_name:
            raise RuntimeError("No package name provided.")
        if not is_valid_package_name(package_name):
            raise RuntimeError(f"Invalid package name format: {package_name}")

        if mode_choice == "3":
            completed = self.adb(
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
            print((completed.stdout or completed.stderr or "").strip())
            return completed.returncode

        args = ["-s", selected.serial, f"--start-app={package_name}"]
        if mode_choice == "2":
            args.append("--new-display")
            if prompt_yes_no("Use flex display (resizable window)", default=False):
                args.append("--flex-display")
        args.extend(["--window-title", f"scrcpy - {selected.display_name} ({package_name})"])
        print(f"\nCommand: {quote_command(args)}\n")
        return self.scrcpy(args)

    def profiles_menu(self) -> int:
        """Interactive menu for managing device profiles.

        Returns:
            0 when exiting the menu
        """
        while True:
            try:
                clear_screen()
                print("Profile Manager\n")
                print("[L] List profiles")
                print("[A] Add profile")
                print("[E] Edit profile")
                print("[D] Delete profile")
                print("[Q] Back\n")
                choice = input("Select option: ").strip().lower()

                if choice == "l":
                    clear_screen()
                    profiles = self.list_profiles()
                    if not profiles:
                        print("No saved profiles.")
                    else:
                        for index, profile in enumerate(profiles, start=1):
                            print(f"[{index}] {profile['nickname']} ({profile['name']})")
                            if profile["ip"]:
                                print(f"    IP:      {profile['ip']}")
                            if profile["serial"]:
                                print(f"    Serial:  {profile['serial']}")
                            print(f"    Quality: {profile['quality']}")
                            print(f"    Mode:    {profile['mode']}\n")
                    press_enter()
                    continue

                if choice == "a":
                    clear_screen()
                    profile_name = sanitize_profile_name(prompt("Profile ID"))
                    nickname = prompt("Display name", profile_name)
                    ip = prompt("IP address", "")
                    serial = prompt("USB serial", "")
                    quality = prompt("Quality", "balanced")
                    mode = prompt("Mode", "mirror")
                    keep_active = "__YES__" if prompt_yes_no("Keep device active (prevent sleep)", default=False) else ""
                    background_color = prompt("Background color hex (e.g. #234567, leave empty for default)", "")
                    self.save_profile(
                        profile_name=profile_name,
                        nickname=nickname,
                        ip=ip,
                        serial=serial,
                        quality=quality,
                        mode=mode,
                        keep_active=keep_active,
                        background_color=background_color,
                    )
                    print(f"\nSaved profile '{profile_name}'.")
                    press_enter()
                    continue

                if choice == "e":
                    profiles = self.list_profiles()
                    if not profiles:
                        print("\nNo profiles to edit.")
                        press_enter()
                        continue
                    clear_screen()
                    for index, profile in enumerate(profiles, start=1):
                        print(f"[{index}] {profile['nickname']} ({profile['name']})")
                    selected = prompt("Profile number")
                    if not selected.isdigit() or not (1 <= int(selected) <= len(profiles)):
                        print("\nInvalid selection.")
                        press_enter()
                        continue
                    current = profiles[int(selected) - 1]
                    nickname = prompt("Display name", current["nickname"])
                    ip = prompt("IP address", current["ip"])
                    serial = prompt("USB serial", current["serial"])
                    quality = prompt("Quality", current["quality"])
                    mode = prompt("Mode", current["mode"])
                    keep_active_default = current.get("keep_active", "")
                    keep_active = "__YES__" if prompt_yes_no("Keep device active (prevent sleep)", default=keep_active_default.lower() in {"__yes__", "yes", "y", "true"}) else ""
                    background_color = prompt("Background color hex", current.get("background_color", ""))
                    self.save_profile(
                        profile_name=current["name"],
                        nickname=nickname,
                        ip=ip,
                        serial=serial,
                        quality=quality,
                        mode=mode,
                        keep_active=keep_active,
                        background_color=background_color,
                    )
                    print("\nProfile updated.")
                    press_enter()
                    continue

                if choice == "d":
                    profiles = self.list_profiles()
                    if not profiles:
                        print("\nNo profiles to delete.")
                        press_enter()
                        continue
                    clear_screen()
                    for index, profile in enumerate(profiles, start=1):
                        print(f"[{index}] {profile['nickname']} ({profile['name']})")
                    selected = prompt("Profile number")
                    if not selected.isdigit() or not (1 <= int(selected) <= len(profiles)):
                        print("\nInvalid selection.")
                        press_enter()
                        continue
                    target = profiles[int(selected) - 1]
                    if prompt_yes_no(f"Delete profile '{target['name']}'", default=False):
                        self.delete_profile(target["name"])
                        print("\nProfile deleted.")
                    press_enter()
                    continue

                if choice == "q":
                    return 0
            except KeyboardInterrupt:
                print("\n")
                return 0

    def main_menu(self) -> int:
        """Display and handle the main interactive menu.

        Returns:
            0 on quit, scrcpy exit code on device launch
        """
        prefs = self.get_user_prefs()
        timeout_value = prefs.get("preferences", "quick_launch_timeout", fallback="3").strip() or "3"

        if timeout_value != "0":
            last_used = self.get_last_used()
            last_profile = last_used.get("lastused", "profile", fallback="").strip()
            last_conn = last_used.get("lastused", "last_connection", fallback="").strip()
            if last_profile and last_conn:
                print("\nQuick launch is available.")
                print(f"Last profile:    {last_profile}")
                print(f"Last connection: {last_conn}")
                if prompt_yes_no("Launch last used device now", default=False):
                    return self.quick_launch()

        while True:
            clear_screen()
            devices = self.list_devices()
            profiles = self.list_profiles()
            print("scrcpy Device Manager\n")

            menu_map: dict[str, tuple[str, object]] = {}
            counter = 1

            print("Connected devices:\n")
            if not devices:
                print("  No connected devices.\n")
            else:
                for device in devices:
                    key = str(counter)
                    menu_map[key] = ("device", device)
                    # Add visual indicator for device type
                    kind_icon = "📶" if device.kind == "WIRELESS" else "🔌"
                    print(f"  [{key}] {kind_icon} {device.kind:<8} {device.display_name} ({device.model})")
                    counter += 1
                    # Limit display to prevent overflow
                    if counter > 9:
                        print(f"  ... and {len(devices) - 9} more device(s). Use [D] to see all.")
                        break
                print()

            print("Saved profiles:\n")
            if not profiles:
                print("  No saved profiles.\n")
            else:
                for profile in profiles:
                    key = str(counter)
                    menu_map[key] = ("profile", profile["name"])
                    status = profile["ip"] or profile["serial"] or "manual"
                    print(f"  [{key}] 📱 PROFILE  {profile['nickname']} ({status})")
                    counter += 1
                    # Limit display to prevent overflow
                    if counter > 18:  # 9 devices + 9 profiles
                        print(f"  ... and {len(profiles) - (counter - 10)} more profile(s). Use [A] to manage.")
                        break
                print()

            print("[L] Quick launch")
            print("[A] Profile manager")
            print("[D] Detect devices")
            print("[S] Setup wireless")
            print("[F] Find/discover devices")
            print("[C] Camera mode")
            print("[P] Quick app launcher")
            print("[X] Shutdown adb")
            print("[R] Refresh")
            print("[Q] Quit\n")

            try:
                choice = input("Select option: ").strip().lower()
            except EOFError:
                print("\nEOF received. Exiting...")
                return 0
            except KeyboardInterrupt:
                print("\nOperation cancelled.")
                continue

            if choice in menu_map:
                kind, payload = menu_map[choice]
                try:
                    if kind == "device":
                        return_code = self.launch_connected_device(payload)  # type: ignore[arg-type]
                    else:
                        return_code = self.launch_profile(payload)  # type: ignore[arg-type]
                    if return_code != 0:
                        print(f"\nscrcpy exited with code {return_code}")
                        press_enter()
                except KeyboardInterrupt:
                    print("\nOperation cancelled.")
                    press_enter()
                except (RuntimeError, ValueError, OSError) as exc:
                    logger.error(f"Launch error: {exc}")
                    print(f"\nError: {exc}")
                    press_enter()
                except Exception as exc:
                    logger.error(f"Unexpected error during launch: {exc}")
                    print(f"\nUnexpected error: {exc}")
                    press_enter()
                continue

            try:
                if choice == "l":
                    return_code = self.quick_launch()
                    if return_code != 0:
                        print(f"\nscrcpy exited with code {return_code}")
                        press_enter()
                elif choice == "a":
                    self.profiles_menu()
                elif choice == "d":
                    clear_screen()
                    self.detect_devices()
                    press_enter()
                elif choice == "s":
                    self.setup_wireless()
                    press_enter()
                elif choice == "f":
                    self.discover_menu()
                    press_enter()
                elif choice == "c":
                    self.camera_mode()
                elif choice == "p":
                    self.quick_app()
                elif choice == "x":
                    self.shutdown()
                    press_enter()
                elif choice == "r":
                    continue
                elif choice == "q":
                    return 0
            except KeyboardInterrupt:
                print("\nOperation cancelled.")
                press_enter()
            except (RuntimeError, ValueError, OSError) as exc:
                logger.error(f"Menu operation error: {exc}")
                print(f"\nError: {exc}")
                press_enter()
            except Exception as exc:
                logger.error(f"Unexpected error in menu: {exc}")
                print(f"\nUnexpected error: {exc}")
                press_enter()
