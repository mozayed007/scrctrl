#!/usr/bin/env python3
"""Python-based terminal interface for the scrcpy workspace.

This replaces the brittle batch-control flow with a stdlib-only CLI that
reuses the existing config files and bundled binaries in this folder.
"""

from __future__ import annotations

import argparse
import configparser
import logging
import os
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

# Configure logging
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Enable debug logging via environment variable
if os.environ.get("SCRCPY_DEBUG"):
    logger.setLevel(logging.DEBUG)


ROOT = Path(__file__).resolve().parent
BIN_DIR = ROOT / "bin"
CONFIG_DIR = ROOT / "config"
ADB_EXE = BIN_DIR / "adb.exe"
SCRCPY_EXE = BIN_DIR / "scrcpy.exe"
DEVICES_INI = CONFIG_DIR / "devices.ini"
QUALITY_INI = CONFIG_DIR / "quality.ini"
LASTUSED_INI = CONFIG_DIR / "lastused.ini"
USERPREFS_INI = CONFIG_DIR / "userprefs.ini"

# Constants
DEFAULT_ADB_PORT = 5555
DEFAULT_QUALITY = "balanced"
DEFAULT_MODE = "mirror"
NETWORK_INTERFACES = ["wlan0", "wlan1", "eth0", "eth1"]
QUALITY_PRESETS = ["low", "balanced", "high", "ultra", "camera_low", "camera_balanced", "camera_high"]
MODES = ["mirror", "otg", "camera"]
ADB_TIMEOUT = 30  # Seconds to wait for ADB commands
MDNS_TIMEOUT = 10  # Seconds to wait for mDNS discovery


def clear_screen() -> None:
    """Clear the terminal screen using platform-appropriate command."""
    command = "cls" if os.name == "nt" else "clear"
    try:
        subprocess.run(command, shell=True, check=False)
    except Exception:
        # Fallback: print newlines if clear command fails
        print("\n" * 100)


def prompt(message: str, default: str | None = None) -> str:
    """Prompt user for input with optional default.

    Args:
        message: Prompt message to display
        default: Default value if user presses Enter

    Returns:
        User input or default value

    Raises:
        EOFError: If user presses Ctrl+D (EOF)
    """
    suffix = f" [{default}]" if default not in (None, "") else ""
    try:
        value = input(f"{message}{suffix}: ").strip()
    except EOFError:
        print("\n")  # Add newline after Ctrl+D
        raise
    if not value and default is not None:
        return default
    return value


def prompt_yes_no(message: str, default: bool = True) -> bool:
    """Prompt user for yes/no confirmation.

    Args:
        message: Prompt message to display
        default: Default value if user presses Enter

    Returns:
        True for yes, False for no

    Raises:
        EOFError: If user presses Ctrl+D (EOF)
    """
    hint = "Y/n" if default else "y/N"
    try:
        value = input(f"{message} [{hint}]: ").strip().lower()
    except EOFError:
        print("\n")  # Add newline after Ctrl+D
        raise
    if not value:
        return default
    return value in {"y", "yes"}


def press_enter() -> None:
    """Wait for user to press Enter.

    Raises:
        EOFError: If user presses Ctrl+D (EOF)
    """
    try:
        input("\nPress Enter to continue...")
    except EOFError:
        print("\n")
        raise


def sanitize_profile_name(name: str) -> str:
    """Sanitize profile name by keeping only alphanumeric characters.

    Args:
        name: Profile name to sanitize

    Returns:
        Sanitized profile name (max 50 chars, alphanumeric only)
    """
    allowed = []
    for char in name.strip():
        if char.isalnum():
            allowed.append(char)
    result = "".join(allowed) or "Device"
    return result[:50]  # Limit to 50 characters


def normalize_quality_name(name: str) -> str:
    """Normalize quality preset name.

    Args:
        name: Quality preset name to normalize

    Returns:
        Normalized quality preset name in lowercase, or DEFAULT_QUALITY if invalid
    """
    normalized = (name or DEFAULT_QUALITY).strip().lower()
    return normalized if normalized in QUALITY_PRESETS else DEFAULT_QUALITY


def resolution_to_max_size(value: str) -> str:
    text = (value or "").strip().lower()
    if not text:
        return ""
    if "x" in text:
        parts = text.split("x")
        numbers = [part for part in parts if part.isdigit()]
        if numbers:
            return max(numbers, key=int)
    return text


def quote_command(parts: Sequence[str]) -> str:
    """Format command parts as a quoted string for display purposes only.

    Args:
        parts: Command parts to format

    Returns:
        Quoted string representation of the command

    Note:
        This function is for display only and should not be used for command execution.
    """
    return " ".join(shlex.quote(part) for part in parts)


def is_valid_ipv4(ip: str) -> bool:
    """Validate IPv4 address format.

    Args:
        ip: IP address string to validate

    Returns:
        True if valid IPv4 address, False otherwise
    """
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    try:
        return all(0 <= int(part) <= 255 for part in parts)
    except ValueError:
        return False


def is_valid_port(port: str) -> bool:
    """Validate port number.

    Args:
        port: Port number string to validate

    Returns:
        True if valid port (1-65535), False otherwise
    """
    try:
        return 1 <= int(port) <= 65535
    except ValueError:
        return False


def is_valid_camera_id(camera_id: str) -> bool:
    """Validate camera ID.

    Args:
        camera_id: Camera ID string to validate

    Returns:
        True if valid camera ID (non-negative integer), False otherwise
    """
    try:
        return int(camera_id) >= 0
    except ValueError:
        return False


def is_valid_package_name(package_name: str) -> bool:
    """Validate Android package name format.

    Args:
        package_name: Package name to validate

    Returns:
        True if valid package name format, False otherwise
    """
    if not package_name:
        return False
    # Basic validation: at least one dot, alphanumeric and dots only
    parts = package_name.split(".")
    if len(parts) < 2:
        return False
    return all(part.isalnum() for part in parts)


@dataclass
class Device:
    serial: str
    state: str
    kind: str
    model: str = ""
    android: str = ""
    nickname: str = ""

    @property
    def display_name(self) -> str:
        return self.nickname or self.model or self.serial


@dataclass
class DiscoveredDevice:
    name: str
    ipport: str
    source: str = "mDNS"
    service_type: str = "_adb._tcp"  # _adb._tcp, _adb-tls-pairing._tcp, _adb-tls-connect._tcp


class ScrcpyManager:
    """Main manager class for scrcpy device operations.

    This class provides a Python-based interface for managing Android devices
    with scrcpy, replacing the original batch-file implementation. It handles
    device discovery, profile management, wireless setup, and scrcpy launching.
    """

    def __init__(self) -> None:
        """Initialize the ScrcpyManager.

        Raises:
            SystemExit: If required binaries (adb.exe, scrcpy.exe) are missing
        """
        self.ensure_paths()
        self.env = os.environ.copy()
        self.env["PATH"] = str(BIN_DIR) + os.pathsep + self.env.get("PATH", "")

    def ensure_paths(self) -> None:
        """Ensure required binaries and config directory exist.

        Raises:
            SystemExit: If adb.exe or scrcpy.exe are missing from BIN_DIR
        """
        missing = [path.name for path in (ADB_EXE, SCRCPY_EXE) if not path.exists()]
        if missing:
            joined = ", ".join(missing)
            raise SystemExit(f"Missing required binaries in {BIN_DIR}: {joined}")
        CONFIG_DIR.mkdir(exist_ok=True)

    def load_ini(self, path: Path) -> configparser.ConfigParser:
        """Load an INI configuration file.

        Args:
            path: Path to the INI file

        Returns:
            ConfigParser instance with loaded configuration
        """
        parser = configparser.ConfigParser(interpolation=None)
        parser.optionxform = str
        parser.read(path, encoding="utf-8")
        return parser

    def save_ini(self, parser: configparser.ConfigParser, path: Path) -> None:
        """Save configuration to an INI file.

        Args:
            parser: ConfigParser instance to save
            path: Path to save the INI file

        Raises:
            OSError: If file cannot be written (permissions, disk full, etc.)
        """
        try:
            # Create backup if file exists
            if path.exists():
                backup_path = path.with_suffix(path.suffix + ".bak")
                shutil.copy2(path, backup_path)

            with path.open("w", encoding="utf-8", newline="\n") as handle:
                parser.write(handle)
            logger.debug(f"Saved configuration to {path}")
        except OSError as exc:
            logger.error(f"Failed to save configuration to {path}: {exc}")
            raise

    def get_user_prefs(self) -> configparser.ConfigParser:
        """Get user preferences configuration.

        Returns:
            ConfigParser with user preferences, creates preferences section if missing
        """
        parser = self.load_ini(USERPREFS_INI)
        if not parser.has_section("preferences"):
            parser["preferences"] = {}
        return parser

    def get_quality_config(self) -> configparser.ConfigParser:
        """Get quality presets configuration.

        Returns:
            ConfigParser with quality preset definitions
        """
        return self.load_ini(QUALITY_INI)

    def get_device_profiles(self) -> configparser.ConfigParser:
        """Get device profiles configuration.

        Returns:
            ConfigParser with saved device profiles
        """
        return self.load_ini(DEVICES_INI)

    def get_last_used(self) -> configparser.ConfigParser:
        """Get last used device configuration.

        Returns:
            ConfigParser with last used device info, creates section if missing
        """
        parser = self.load_ini(LASTUSED_INI)
        if not parser.has_section("lastused"):
            parser["lastused"] = {}
        return parser

    def set_last_used(self, profile: str, connection_type: str, connection: str) -> None:
        """Save last used device information.

        Args:
            profile: Profile name that was last used
            connection_type: Type of connection (wireless/USB)
            connection: Connection string (serial or IP:port)
        """
        parser = self.get_last_used()
        parser["lastused"]["profile"] = profile
        parser["lastused"]["connection_type"] = connection_type
        parser["lastused"]["last_connection"] = connection
        parser["lastused"]["timestamp"] = str(int(time.time()))
        self.save_ini(parser, LASTUSED_INI)

    def run(
        self,
        args: Sequence[str],
        *,
        check: bool = False,
        capture_output: bool = True,
        text: bool = True,
        timeout: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run a command with configured environment.

        Args:
            args: Command and arguments to run
            check: If True, raise CalledProcessError on non-zero exit
            capture_output: If True, capture stdout/stderr
            text: If True, return output as string
            timeout: Timeout in seconds (None for no timeout)

        Returns:
            CompletedProcess instance with result

        Raises:
            subprocess.TimeoutExpired: If command times out
        """
        try:
            return subprocess.run(
                args,
                cwd=ROOT,
                env=self.env,
                check=check,
                capture_output=capture_output,
                text=text,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            logger.error(f"Command timed out: {' '.join(args)}")
            raise

    def adb(self, *args: str, check: bool = False, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
        """Run an ADB command.

        Args:
            *args: ADB command arguments
            check: If True, raise CalledProcessError on non-zero exit
            timeout: Timeout in seconds (defaults to ADB_TIMEOUT)

        Returns:
            CompletedProcess instance with ADB command result
        """
        if timeout is None:
            timeout = ADB_TIMEOUT
        return self.run([str(ADB_EXE), *args], check=check, timeout=timeout)

    def scrcpy(
        self,
        args: Sequence[str],
        check: bool = False,
        detach: bool = False,
    ) -> int | subprocess.Popen:
        """Run scrcpy with given arguments.

        Args:
            args: Scrcpy command line arguments
            check: If True, raise CalledProcessError on non-zero exit
            detach: If True, launch in background via Popen and return process handle

        Returns:
            Scrcpy process exit code (blocking) or Popen handle (detached)
        """
        cmd = [str(SCRCPY_EXE), *args]
        if detach:
            return subprocess.Popen(cmd, cwd=ROOT, env=self.env)
        completed = subprocess.run(cmd, cwd=ROOT, env=self.env, check=check)
        return completed.returncode

    def adb_shell(self, serial: str, shell_command: Sequence[str]) -> str:
        """Execute a shell command on a device via ADB.

        Args:
            serial: Device serial number
            shell_command: Command and arguments to execute on device

        Returns:
            Command output as stripped string
        """
        completed = self.adb("-s", serial, "shell", *shell_command)
        return (completed.stdout or "").strip()

    def profile_name_for_serial(self, serial: str) -> str | None:
        """Find profile name by device serial number.

        Args:
            serial: Device serial number to search for

        Returns:
            Profile name if found, None otherwise
        """
        profiles = self.get_device_profiles()
        for section in profiles.sections():
            if profiles.get(section, "serial", fallback="").strip() == serial:
                return section
        return None

    def profile_name_for_ip(self, ip: str) -> str | None:
        """Find profile name by IP address.

        Args:
            ip: IP address to search for

        Returns:
            Profile name if found, None otherwise
        """
        profiles = self.get_device_profiles()
        for section in profiles.sections():
            if profiles.get(section, "ip", fallback="").strip() == ip:
                return section
        return None

    def list_devices(self) -> list[Device]:
        """List all connected ADB devices.

        Returns:
            List of Device objects for all connected devices in 'device' state
        """
        completed = self.adb("devices")
        devices: list[Device] = []
        for raw_line in (completed.stdout or "").splitlines()[1:]:
            line = raw_line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            serial, state = parts[0], parts[1]
            if state != "device":
                continue
            kind = "WIRELESS" if ":" in serial else "USB"
            model = self.adb_shell(serial, ["getprop", "ro.product.model"])
            android = self.adb_shell(serial, ["getprop", "ro.build.version.release"])
            profile_name = self.profile_name_for_serial(serial)
            nickname = ""
            if profile_name:
                profiles = self.get_device_profiles()
                nickname = profiles.get(profile_name, "nickname", fallback="").strip()
            devices.append(
                Device(
                    serial=serial,
                    state=state,
                    kind=kind,
                    model=model or "Unknown",
                    android=android,
                    nickname=nickname,
                )
            )
        return devices

    def list_profiles(self) -> list[dict[str, str]]:
        """List all saved device profiles.

        Returns:
            List of dictionaries containing profile information
        """
        parser = self.get_device_profiles()
        profiles: list[dict[str, str]] = []
        for section in parser.sections():
            profiles.append(
                {
                    "name": section,
                    "nickname": parser.get(section, "nickname", fallback=section).strip(),
                    "ip": parser.get(section, "ip", fallback="").strip(),
                    "serial": parser.get(section, "serial", fallback="").strip(),
                    "quality": normalize_quality_name(
                        parser.get(section, "quality", fallback=DEFAULT_QUALITY)
                    ),
                    "mode": parser.get(section, "mode", fallback=DEFAULT_MODE).strip() or DEFAULT_MODE,
                    "keep_active": parser.get(section, "keep_active", fallback="").strip(),
                    "background_color": parser.get(section, "background_color", fallback="").strip(),
                }
            )
        return profiles

    def get_profile(self, profile_name: str) -> dict[str, str]:
        """Get a specific device profile.

        Args:
            profile_name: Name of the profile to retrieve

        Returns:
            Dictionary containing profile information

        Raises:
            ValueError: If profile does not exist
        """
        parser = self.get_device_profiles()
        if not parser.has_section(profile_name):
            raise ValueError(f"Profile '{profile_name}' was not found")
        return {
            "name": profile_name,
            "nickname": parser.get(profile_name, "nickname", fallback=profile_name).strip(),
            "ip": parser.get(profile_name, "ip", fallback="").strip(),
            "serial": parser.get(profile_name, "serial", fallback="").strip(),
            "quality": normalize_quality_name(
                parser.get(profile_name, "quality", fallback=DEFAULT_QUALITY)
            ),
            "mode": parser.get(profile_name, "mode", fallback=DEFAULT_MODE).strip() or DEFAULT_MODE,
            "keep_active": parser.get(profile_name, "keep_active", fallback="").strip(),
            "background_color": parser.get(profile_name, "background_color", fallback="").strip(),
        }

    def save_profile(
        self,
        *,
        profile_name: str,
        nickname: str,
        ip: str = "",
        serial: str = "",
        quality: str = DEFAULT_QUALITY,
        mode: str = DEFAULT_MODE,
        keep_active: str = "",
        background_color: str = "",
    ) -> None:
        """Save or update a device profile.

        Args:
            profile_name: Unique profile identifier
            nickname: Display name for the profile
            ip: IP address (for wireless connections)
            serial: USB serial number (for USB connections)
            quality: Quality preset name
            mode: Display mode (mirror/otg/camera)
            keep_active: Keep device active during session (__YES__/__NO__ or empty)
            background_color: Window background hex color (e.g. #234567) or empty

        Raises:
            ValueError: If profile has neither IP nor serial, or if mode/quality is invalid
        """
        # Validate that profile has at least one connection method
        if not ip and not serial:
            raise ValueError("Profile must have either an IP address or serial number")

        # Validate mode
        if mode and mode not in MODES:
            raise ValueError(f"Invalid mode: {mode}. Must be one of {MODES}")

        parser = self.get_device_profiles()
        if not parser.has_section(profile_name):
            parser.add_section(profile_name)
        parser[profile_name]["nickname"] = nickname or profile_name
        parser[profile_name]["quality"] = normalize_quality_name(quality)
        parser[profile_name]["mode"] = mode or DEFAULT_MODE
        if ip:
            parser[profile_name]["ip"] = ip
        elif parser.has_option(profile_name, "ip"):
            parser.remove_option(profile_name, "ip")
        if serial:
            parser[profile_name]["serial"] = serial
        elif parser.has_option(profile_name, "serial"):
            parser.remove_option(profile_name, "serial")
        if keep_active:
            parser[profile_name]["keep_active"] = keep_active
        elif parser.has_option(profile_name, "keep_active"):
            parser.remove_option(profile_name, "keep_active")
        if background_color:
            parser[profile_name]["background_color"] = background_color
        elif parser.has_option(profile_name, "background_color"):
            parser.remove_option(profile_name, "background_color")
        self.save_ini(parser, DEVICES_INI)

    def delete_profile(self, profile_name: str) -> None:
        """Delete a device profile.

        Args:
            profile_name: Name of the profile to delete
        """
        parser = self.get_device_profiles()
        if parser.remove_section(profile_name):
            self.save_ini(parser, DEVICES_INI)

    def get_quality_settings(self, preset: str) -> dict[str, str]:
        """Get quality settings for a preset.

        Args:
            preset: Quality preset name

        Returns:
            Dictionary with quality settings (bitrate, fps, buffer, resolution)
        """
        parser = self.get_quality_config()
        preset = normalize_quality_name(preset)
        if not parser.has_section(preset):
            preset = DEFAULT_QUALITY
        return {
            "name": preset,
            "video_bitrate": parser.get(preset, "video_bitrate", fallback=""),
            "max_fps": parser.get(preset, "max_fps", fallback=""),
            "audio_buffer": parser.get(preset, "audio_buffer", fallback=""),
            "resolution": parser.get(preset, "resolution", fallback=""),
        }

    def build_scrcpy_args(
        self,
        *,
        profile: dict[str, str],
        connection: str,
        connection_type: str,
        mode_override: str | None = None,
        extra: Iterable[str] = (),
    ) -> list[str]:
        """Build scrcpy command line arguments from profile settings.

        Args:
            profile: Profile dictionary with device settings
            connection: Connection string (serial or IP:port)
            connection_type: Type of connection (wireless/USB)
            mode_override: Optional mode override
            extra: Additional command line arguments

        Returns:
            List of scrcpy command line arguments
        """
        settings = self.get_quality_settings(profile["quality"])
        args: list[str] = []
        if connection:
            args.extend(["-s", connection])

        mode = (mode_override or profile.get("mode") or DEFAULT_MODE).strip().lower()
        window_type = connection_type.upper() if connection_type else "DEVICE"
        title = f"scrcpy - {profile['nickname']} ({window_type})"
        args.extend(["--window-title", title])

        if settings["video_bitrate"]:
            args.append(f"--video-bit-rate={settings['video_bitrate']}")
        if settings["max_fps"]:
            args.append(f"--max-fps={settings['max_fps']}")
        if settings["audio_buffer"]:
            args.append(f"--audio-output-buffer={settings['audio_buffer']}")
        if settings["resolution"]:
            args.append(f"--max-size={resolution_to_max_size(settings['resolution'])}")
        if mode == "otg":
            args.append("--otg")
        if profile.get("keep_active", "").lower() in {"__yes__", "yes", "y", "true"}:
            args.append("--keep-active")
        if profile.get("background_color", ""):
            args.append(f"--background-color={profile['background_color']}")

        args.extend(extra)
        return args

    def connect_wireless(self, ipport: str) -> tuple[bool, str, str | None]:
        """Connect to a wireless device via ADB.

        Args:
            ipport: IP address and port (e.g., "192.168.1.1:5555")

        Returns:
            Tuple of (success: bool, message: str, serial: str | None)
            - success: True if connection succeeded
            - message: Human-readable status message
            - serial: Device serial if connected, None otherwise
        """
        # Validate IP:port format
        if ":" not in ipport:
            return False, f"Invalid format: {ipport} (expected IP:PORT)", None

        ip, port = ipport.rsplit(":", 1)
        if not is_valid_ipv4(ip):
            return False, f"Invalid IP address: {ip}", None
        if not is_valid_port(port):
            return False, f"Invalid port number: {port}", None

        logger.debug(f"Attempting to connect to {ipport}")
        completed = self.adb("connect", ipport)
        output = "\n".join(part for part in [completed.stdout, completed.stderr] if part).strip()
        if output:
            print(output)

        if completed.returncode != 0:
            error_msg = output or "Connection failed with unknown error"
            logger.error(f"Failed to connect to {ipport}: {error_msg}")
            return False, error_msg, None

        # Wait for device to be ready
        time.sleep(1)

        # Try to find the connected device
        try:
            for device in self.list_devices():
                if device.serial == ipport or device.serial.startswith(ipport.split(":")[0]):
                    logger.info(f"Successfully connected to {device.serial}")
                    return True, f"Connected to {device.serial}", device.serial
        except Exception as exc:
            logger.error(f"Error listing devices after connection: {exc}")
            return False, f"Connection succeeded but failed to list devices: {exc}", None

        # Fallback: return the original ipport if device not found in list
        logger.warning(f"Connected to {ipport} but device not found in list")
        return True, f"Connected to {ipport}", ipport

    def launch_profile(
        self,
        profile_name: str,
        *,
        connection: str | None = None,
        connection_type: str | None = None,
        extra: Iterable[str] = (),
        mode_override: str | None = None,
        detach: bool = False,
    ) -> int | subprocess.Popen:
        """Launch scrcpy for a saved profile.

        Args:
            profile_name: Name of the profile to launch
            connection: Optional connection string to override profile
            connection_type: Optional connection type to override profile
            extra: Additional scrcpy arguments
            mode_override: Optional mode override
            detach: If True, launch in background without blocking

        Returns:
            Scrcpy process exit code (blocking) or Popen handle (detached)

        Raises:
            ValueError: If profile does not exist
            RuntimeError: If device cannot be reached
        """
        profile = self.get_profile(profile_name)

        resolved_connection = connection
        resolved_type = connection_type

        if not resolved_connection:
            ip = profile.get("ip", "")
            serial = profile.get("serial", "")
            if ip:
                resolved_type = resolved_type or "wireless"
                # Try to discover the actual port via mDNS for Android 11+ devices
                discovered_port = self.discover_device_port(ip)
                if discovered_port:
                    success, message, resolved_connection = self.connect_wireless(discovered_port)
                else:
                    # Fall back to default port for legacy devices
                    success, message, resolved_connection = self.connect_wireless(f"{ip}:{DEFAULT_ADB_PORT}")

                if not success:
                    raise RuntimeError(f"Failed to connect to {ip}: {message}")
            if not resolved_connection and serial:
                connected_serials = {device.serial for device in self.list_devices()}
                if serial in connected_serials:
                    resolved_type = resolved_type or "USB"
                    resolved_connection = serial

        if not resolved_connection:
            raise RuntimeError(
                f"Profile '{profile_name}' is not currently reachable. Connect USB or re-run setup."
            )

        resolved_type = resolved_type or ("WIRELESS" if ":" in resolved_connection else "USB")
        self.set_last_used(profile_name, resolved_type.lower(), resolved_connection)
        args = self.build_scrcpy_args(
            profile=profile,
            connection=resolved_connection,
            connection_type=resolved_type,
            extra=extra,
            mode_override=mode_override,
        )
        if not detach:
            print("\nLaunching scrcpy")
            print(f"Profile:    {profile_name}")
            print(f"Nickname:   {profile['nickname']}")
            print(f"Connection: {resolved_connection}")
            print(f"Type:       {resolved_type}")
            print(f"Quality:    {profile['quality']}")
            print(f"Command:    {quote_command([str(SCRCPY_EXE), *args])}\n")
        return self.scrcpy(args, detach=detach)

    def quick_launch(
        self,
        profile_name: str | None = None,
        detach: bool = False,
    ) -> int | subprocess.Popen:
        """Quick launch a profile or the last used device.

        Args:
            profile_name: Optional profile name to launch. If None, launches last used device.
            detach: If True, launch in background without blocking

        Returns:
            Scrcpy process exit code (blocking) or Popen handle (detached)

        Raises:
            RuntimeError: If no last used profile found or connection fails
        """
        if profile_name:
            return self.launch_profile(profile_name, detach=detach)

        parser = self.get_last_used()
        last_profile = parser.get("lastused", "profile", fallback="").strip()
        last_connection = parser.get("lastused", "last_connection", fallback="").strip()
        last_type = parser.get("lastused", "connection_type", fallback="wireless").strip()
        if not last_profile:
            raise RuntimeError("No last used profile found. Launch a device once first.")

        if last_type.lower() == "wireless" and last_connection:
            success, message, connected = self.connect_wireless(last_connection)
            if success and connected:
                last_connection = connected
            elif not success:
                raise RuntimeError(f"Failed to reconnect to {last_connection}: {message}")
        return self.launch_profile(
            last_profile,
            connection=last_connection,
            connection_type=last_type,
            detach=detach,
        )

    def detect_devices(self) -> int:
        """Detect and display connected ADB devices.

        Returns:
            0 if devices found, 1 otherwise
        """
        devices = self.list_devices()
        print("\nscrcpy Device Detection\n")
        if not devices:
            print("No devices found.")
            print("Connect a device via USB or run wireless setup/discovery.")
            return 1
        usb_count = sum(1 for device in devices if device.kind == "USB")
        wireless_count = sum(1 for device in devices if device.kind == "WIRELESS")
        print(f"Connected devices: {len(devices)}")
        print(f"USB: {usb_count}  Wireless: {wireless_count}\n")
        for index, device in enumerate(devices, start=1):
            print(f"[{index}] {device.kind}  {device.display_name}")
            print(f"    Serial:   {device.serial}")
            if device.model:
                print(f"    Model:    {device.model}")
            if device.android:
                print(f"    Android:  {device.android}")
            print()
        return 0

    def mdns_discover(self) -> list[DiscoveredDevice]:
        """Discover wireless-debuggable devices via mDNS.

        Returns:
            List of discovered devices with name, IP:port, source, and service type
        """
        try:
            completed = self.adb("mdns", "services", timeout=MDNS_TIMEOUT)
        except subprocess.TimeoutExpired:
            logger.warning("mDNS discovery timed out")
            return []

        results: list[DiscoveredDevice] = []
        for line in (completed.stdout or "").splitlines():
            text = line.strip()
            if not text or text.lower().startswith("list"):
                continue
            parts = text.split()
            if len(parts) < 3:
                logger.debug(f"Skipping malformed mDNS line: {text}")
                continue

            # Format: device_name service_type ip:port
            # Example: adb-EXAMPLE123-lzUn3r _adb-tls-connect._tcp. 192.168.0.176:44845
            device_name = parts[0]
            service_type = parts[1].rstrip(".") if len(parts) > 1 else "_adb._tcp"
            ipport = parts[2] if len(parts) > 2 else ""

            # Validate IP:port format
            if not ipport or ":" not in ipport:
                logger.debug(f"Skipping invalid IP:port in mDNS line: {ipport}")
                continue

            # Extract readable name from device identifier
            name_parts = device_name.split("-")
            name = name_parts[1] if len(name_parts) > 1 else device_name

            results.append(DiscoveredDevice(
                name=name,
                ipport=ipport,
                source="mDNS",
                service_type=service_type
            ))
        return results

    def pair_device(self, ipport: str, pairing_code: str) -> tuple[bool, str]:
        """Pair with a device using Android 11+ wireless debugging.

        Args:
            ipport: Device IP and pairing port (e.g., "192.168.1.1:37119")
            pairing_code: 6-digit pairing code from device

        Returns:
            Tuple of (success: bool, message: str)
        """
        logger.debug(f"Attempting to pair with {ipport} using code {pairing_code}")
        completed = self.adb("pair", ipport, pairing_code)
        output = "\n".join(part for part in [completed.stdout, completed.stderr] if part).strip()

        if completed.returncode == 0:
            logger.info(f"Successfully paired with {ipport}")
            return True, f"Successfully paired with {ipport}"

        # adb 37.0.0 sometimes throws protocol fault on first pair attempt.
        # Restarting the server and retrying once often resolves it.
        if "protocol fault" in output.lower() or "couldn't read status message" in output.lower():
            print("ADB protocol fault detected. Restarting ADB server and retrying...")
            logger.info("Restarting ADB server due to protocol fault during pairing")
            self.adb("kill-server")
            time.sleep(2)
            self.adb("start-server")
            time.sleep(2)

            completed = self.adb("pair", ipport, pairing_code)
            output = "\n".join(part for part in [completed.stdout, completed.stderr] if part).strip()

            if completed.returncode == 0:
                logger.info(f"Successfully paired with {ipport} after server restart")
                return True, f"Successfully paired with {ipport}"

        error_msg = output or "Pairing failed with unknown error"
        logger.error(f"Failed to pair with {ipport}: {error_msg}")
        return False, error_msg

    def discover_device_port(self, ip: str) -> str | None:
        """Discover a device's connection port via mDNS by IP address.

        Args:
            ip: Device IP address

        Returns:
            IP:port string if found, None otherwise
        """
        devices = self.mdns_discover()
        for device in devices:
            if device.service_type in ("_adb-tls-connect._tcp", "_adb._tcp"):
                if device.ipport.startswith(ip):
                    logger.debug(f"Found device {ip} at {device.ipport} via mDNS")
                    return device.ipport
        return None

    def select_usb_device(self) -> Device:
        """Select a USB device from connected devices.

        Returns:
            Selected Device object

        Raises:
            RuntimeError: If no USB device found or invalid selection
        """
        usb_devices = [device for device in self.list_devices() if device.kind == "USB"]
        if not usb_devices:
            raise RuntimeError("No USB device detected. Connect one and enable USB debugging first.")
        if len(usb_devices) == 1:
            return usb_devices[0]
        print("\nUSB devices:\n")
        for index, device in enumerate(usb_devices, start=1):
            print(f"[{index}] {device.display_name} ({device.serial})")
        choice = prompt("Select device")
        if not choice.isdigit() or not (1 <= int(choice) <= len(usb_devices)):
            raise RuntimeError("Invalid USB device selection.")
        return usb_devices[int(choice) - 1]

    def detect_device_ip(self, serial: str) -> str:
        """Detect the device's IP address by trying multiple methods and interfaces.

        Args:
            serial: Device serial number

        Returns:
            Detected IP address, or empty string if not found
        """
        # Build commands for different network interfaces
        commands = [["ip", "route"]]
        for interface in NETWORK_INTERFACES:
            commands.extend([
                ["ip", "addr", "show", interface],
                ["ip", "-f", "inet", "addr", "show", interface],
            ])

        candidates: list[str] = []
        for command in commands:
            try:
                output = self.adb_shell(serial, command)
                for token in output.replace("/", " ").split():
                    if token.count(".") == 3:
                        cleaned = token.strip()
                        if is_valid_ipv4(cleaned):
                            candidates.append(cleaned)
            except Exception as exc:
                logger.debug(f"Command {command} failed: {exc}")
                continue

        # Return first valid IP that's not 0.0.0.0
        for ip in candidates:
            if ip != "0.0.0.0":
                logger.debug(f"Detected IP: {ip}")
                return ip

        logger.warning(f"Could not detect IP for device {serial}")
        return ""

    def shutdown(self) -> int:
        """Disconnect all devices and stop ADB server.

        Returns:
            0 on success
        """
        print("\nADB shutdown\n")
        for command in (["disconnect"], ["usb"], ["kill-server"]):
            completed = self.adb(*command)
            output = "\n".join(part for part in [completed.stdout, completed.stderr] if part).strip()
            print(f"adb {' '.join(command)}")
            if output:
                print(output)
        print("\nAll adb connections closed.")
        return 0

    def launch_connected_device(
        self,
        device: Device,
        detach: bool = False,
    ) -> int | subprocess.Popen:
        """Launch scrcpy for a connected device.

        Args:
            device: Device object to launch
            detach: If True, launch in background without blocking

        Returns:
            Scrcpy process exit code (blocking) or Popen handle (detached)
        """
        profile_name = self.profile_name_for_serial(device.serial)
        if profile_name:
            return self.launch_profile(
                profile_name,
                connection=device.serial,
                connection_type=device.kind,
                detach=detach,
            )

        temp_profile_name = sanitize_profile_name(device.model or device.serial)
        profile = {
            "name": temp_profile_name,
            "nickname": device.display_name,
            "ip": "",
            "serial": device.serial,
            "quality": "balanced",
            "mode": "mirror",
            "keep_active": "",
            "background_color": "",
        }
        self.set_last_used(temp_profile_name, device.kind.lower(), device.serial)
        args = self.build_scrcpy_args(
            profile=profile,
            connection=device.serial,
            connection_type=device.kind,
        )
        if not detach:
            print(f"\nCommand: {quote_command([str(SCRCPY_EXE), *args])}\n")
        return self.scrcpy(args, detach=detach)



