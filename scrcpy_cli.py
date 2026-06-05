#!/usr/bin/env python3
"""CLI entry point for scrcpy Device Manager.

Routes subcommands to the appropriate handler (Textual TUI, legacy menus,
or direct manager operations). Also provides the update workflow.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from collections.abc import Sequence
from pathlib import Path

from scrcpy_legacy_menu import LegacyMenu
from scrcpy_manager import (
    AUDIO_CODECS,
    AUDIO_SOURCES,
    BIN_DIR,
    ORIENTATIONS,
    QUALITY_PRESETS,
    RECORD_FORMATS,
    RENDER_FITS,
    ROOT,
    SCRCPY_EXE,
    VIDEO_CODECS,
    logger,
    prompt_yes_no,
)


def get_current_scrcpy_version() -> str:
    """Get installed scrcpy version from bundled binary."""
    try:
        completed = subprocess.run(
            [str(SCRCPY_EXE), "--version"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if completed.returncode == 0:
            for line in (completed.stdout or "").splitlines():
                lowered = line.lower()
                if "scrcpy" in lowered:
                    parts = line.split()
                    for part in parts:
                        # Accept "v4.0" or "4.0"
                        clean = part.lstrip("v")
                        if clean.replace(".", "").isdigit() and len(clean) >= 1:
                            return f"v{clean}"
            # Fallback: any version-like token on any line
            for line in (completed.stdout or "").splitlines():
                for token in line.split():
                    clean = token.lstrip("v")
                    if clean.replace(".", "").isdigit() and len(clean) >= 1:
                        return f"v{clean}"
    except Exception as exc:
        logger.debug(f"Could not detect current scrcpy version: {exc}")
    return "unknown"


def parse_version_tag(tag: str) -> tuple[int, ...]:
    """Parse a version tag like 'v4.0' or 'v3.3.4' into a tuple."""
    cleaned = tag.lstrip("v").split("-")[0]
    result: list[int] = []
    for part in cleaned.split("."):
        try:
            result.append(int(part))
        except ValueError:
            break
    return tuple(result)


def update_scrcpy(
    *,
    force: bool = False,
    no_backup: bool = False,
    update_python_deps: bool = False,
) -> int:
    """Update scrcpy and adb binaries from the latest GitHub release.

    Args:
        force: Reinstall even if already on latest version
        no_backup: Skip creating a backup of current binaries
        update_python_deps: Also upgrade Python packages (textual)

    Returns:
        0 on success, 1 on failure
    """
    print("Checking for scrcpy updates...")
    BIN_DIR.mkdir(exist_ok=True)
    current_version = get_current_scrcpy_version()
    print(f"Current version: {current_version}")

    # Query GitHub API for latest release
    api_url = "https://api.github.com/repos/Genymobile/scrcpy/releases/latest"
    req = urllib.request.Request(api_url, headers={"User-Agent": "scrcpy-manager-updater"})
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            release = json.load(response)
    except Exception as exc:
        logger.error(f"Failed to fetch release info: {exc}")
        print(f"Error: Could not reach GitHub API ({exc})")
        return 1

    tag_name = release.get("tag_name", "")
    if not tag_name:
        print("Error: Could not determine latest version from GitHub.")
        return 1

    print(f"Latest version:  {tag_name}")

    if not force and current_version != "unknown":
        current_tuple = parse_version_tag(current_version)
        latest_tuple = parse_version_tag(tag_name)
        if current_tuple and latest_tuple and current_tuple >= latest_tuple:
            print("You are already on the latest version. Use --force to reinstall.")
            return 0

    # Find the win64 zip asset
    asset_url: str | None = None
    asset_name: str | None = None
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        if name.startswith("scrcpy-win64-") and name.endswith(".zip"):
            asset_url = asset.get("browser_download_url")
            asset_name = name
            break

    if not asset_url or not asset_name:
        print("Error: No Windows 64-bit zip asset found in the latest release.")
        return 1

    print(f"Download asset:  {asset_name}")

    # Download to a temp file
    try:
        with tempfile.TemporaryDirectory(prefix="scrcpy_update_") as tmpdir:
            tmpdir_path = Path(tmpdir)
            zip_path = tmpdir_path / asset_name

            print(f"Downloading to {zip_path} ...")
            download_req = urllib.request.Request(asset_url, headers={"User-Agent": "scrcpy-manager-updater"})
            with urllib.request.urlopen(download_req, timeout=120) as dl_resp, zip_path.open("wb") as f:
                while True:
                    chunk = dl_resp.read(8192)
                    if not chunk:
                        break
                    f.write(chunk)

            print("Download complete.")

            # Extract
            extract_dir = tmpdir_path / "extracted"
            extract_dir.mkdir()
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(path=extract_dir)

            # Find the extracted root folder (e.g., scrcpy-win64-v4.0)
            extracted_roots = [p for p in extract_dir.iterdir() if p.is_dir()]
            if not extracted_roots:
                print("Error: Archive extracted but no root folder found.")
                return 1
            source_dir = extracted_roots[0]

            # Preserve custom files that may not be in the archive
            preserve_files: list[str] = []
            for fname in ("icon.png",):
                if (BIN_DIR / fname).exists() and not (source_dir / fname).exists():
                    preserve_files.append(fname)

            # Backup current bin/
            if not no_backup:
                backup_tag = current_version.lstrip("v") if current_version != "unknown" else "backup"
                backup_dir = ROOT / "legacy" / f"bin-v{backup_tag}-backup"
                # Avoid collision
                counter = 1
                original_backup_dir = backup_dir
                while backup_dir.exists():
                    backup_dir = Path(str(original_backup_dir) + f"-{counter}")
                    counter += 1
                try:
                    shutil.copytree(BIN_DIR, backup_dir)
                    print(f"Backup created: {backup_dir}")
                except Exception as exc:
                    logger.warning(f"Backup failed: {exc}")
                    print(f"Warning: Could not create backup ({exc})")

            # Replace files in bin/
            print("Updating binaries...")
            for src_file in source_dir.iterdir():
                dest = BIN_DIR / src_file.name
                try:
                    if dest.exists() and dest.is_dir():
                        shutil.rmtree(dest)
                    elif dest.exists():
                        dest.unlink()
                    if src_file.is_dir():
                        shutil.copytree(src_file, dest)
                    else:
                        shutil.copy2(src_file, dest)
                except Exception as exc:
                    logger.error(f"Failed to copy {src_file.name}: {exc}")
                    print(f"Error updating {src_file.name}: {exc}")
                    return 1

            # Restore preserved custom files
            for fname in preserve_files:
                src = backup_dir / fname if "backup_dir" in locals() else BIN_DIR / fname
                if src.exists():
                    shutil.copy2(src, BIN_DIR / fname)
                    print(f"Preserved custom file: {fname}")

            print("Binaries updated.")
    except Exception as exc:
        logger.error(f"Update failed: {exc}")
        print(f"Error: Update failed ({exc})")
        return 1

    # Verify
    new_version = get_current_scrcpy_version()
    print(f"Installed version: {new_version}")
    if new_version == "unknown":
        print("Warning: Could not verify installed version, but files were replaced.")
    else:
        print("Update successful.")

    # Update Python deps
    if update_python_deps:
        print("Checking Python dependencies...")
        for package in ("textual",):
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "install", "--upgrade", package],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if result.returncode == 0:
                    print(f"Updated Python package: {package}")
                else:
                    print(f"Could not update {package}: {result.stderr.strip()}")
            except Exception as exc:
                print(f"Could not update {package}: {exc}")

    return 0


def check_updates_silent() -> str | None:
    """Silently check GitHub for a newer scrcpy release.

    Returns:
        Newer version tag (e.g. 'v4.1') if available, else None.
    """
    try:
        api_url = "https://api.github.com/repos/Genymobile/scrcpy/releases/latest"
        req = urllib.request.Request(api_url, headers={"User-Agent": "scrcpy-manager-updater"})
        with urllib.request.urlopen(req, timeout=8) as response:
            release = json.load(response)
        tag_name = release.get("tag_name", "")
        if not tag_name:
            return None
        current_version = get_current_scrcpy_version()
        if current_version != "unknown":
            current_tuple = parse_version_tag(current_version)
            latest_tuple = parse_version_tag(tag_name)
            if current_tuple and latest_tuple and current_tuple >= latest_tuple:
                return None
        return str(tag_name)
    except Exception:
        return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Python scrcpy terminal manager")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("menu", help="Open the interactive terminal menu")
    subparsers.add_parser("mcp", help="Run the ScrCtrl MCP stdio server")
    subparsers.add_parser("detect", help="List connected adb devices")
    subparsers.add_parser("discover", help="Discover wireless-debuggable devices")
    subparsers.add_parser("setup", help="Run wireless adb setup")
    subparsers.add_parser("camera", help="Open camera mode launcher")
    subparsers.add_parser("quickapp", help="Launch an app with scrcpy")
    subparsers.add_parser("shutdown", help="Disconnect devices and stop adb")
    subparsers.add_parser("profiles", help="Open profile manager")

    def add_launch_overrides(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument(
            "--quality", choices=QUALITY_PRESETS, help="Override quality preset for this launch"
        )
        command_parser.add_argument("--video-codec", choices=VIDEO_CODECS, help="Override video codec")
        command_parser.add_argument("--audio-codec", choices=AUDIO_CODECS, help="Override audio codec")
        command_parser.add_argument("--audio-source", choices=AUDIO_SOURCES, help="Override audio source")
        command_parser.add_argument("--render-fit", choices=RENDER_FITS, help="Override render fit mode")
        command_parser.add_argument(
            "--no-window-aspect-ratio-lock",
            action="store_true",
            help="Disable window aspect ratio lock",
        )
        command_parser.add_argument("--orientation", choices=ORIENTATIONS, help="Override orientation")
        command_parser.add_argument("--no-control", action="store_true", help="Disable device control")
        command_parser.add_argument("--power-off-on-close", action="store_true", help="Turn device screen off on close")
        command_parser.add_argument("--flex-display", action="store_true", help="Enable flex display")
        command_parser.add_argument("--new-display", help="Create new display (e.g. 1920x1080/160)")
        command_parser.add_argument("--record", help="Record to file path")
        command_parser.add_argument("--record-format", choices=RECORD_FORMATS, help="Force recording format")

    quick = subparsers.add_parser("quick", help="Quick-launch last or selected profile")
    quick.add_argument("profile", nargs="?", help="Optional profile name")
    add_launch_overrides(quick)

    launch = subparsers.add_parser("launch", help="Launch a saved profile")
    launch.add_argument("profile", help="Profile name to launch")
    add_launch_overrides(launch)

    update = subparsers.add_parser("update", help="Update scrcpy/adb binaries from GitHub releases")
    update.add_argument("--force", action="store_true", help="Reinstall even if already on latest version")
    update.add_argument("--no-backup", action="store_true", help="Skip backing up current binaries")
    update.add_argument("--python-deps", action="store_true", help="Also upgrade Python packages (textual)")

    agent = subparsers.add_parser("agent", help="Machine-readable agent and CUA commands")
    agent_subparsers = agent.add_subparsers(dest="agent_command")

    def add_json_flag(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument("--json", action="store_true", help="Emit JSON output (agent commands always use JSON)")

    add_json_flag(agent_subparsers.add_parser("capabilities", help="Describe agent capabilities"))
    add_json_flag(agent_subparsers.add_parser("devices", help="List connected devices"))
    add_json_flag(agent_subparsers.add_parser("profiles", help="List saved profiles"))
    profile = agent_subparsers.add_parser("profile", help="Read one profile")
    profile.add_argument("profile_name")
    add_json_flag(profile)
    add_json_flag(agent_subparsers.add_parser("quality-presets", help="List quality presets"))
    add_json_flag(agent_subparsers.add_parser("last-used", help="Read last-used profile metadata"))

    build_command = agent_subparsers.add_parser("build-command", help="Build a scrcpy command without launching")
    build_command.add_argument("profile_name")
    build_command.add_argument("--connection")
    build_command.add_argument("--connection-type")
    build_command.add_argument("--mode")
    build_command.add_argument("--quality", choices=QUALITY_PRESETS)
    build_command.add_argument("--extra", action="append", default=[], help="Extra scrcpy arg; repeat for multiple args")
    add_json_flag(build_command)

    session_start = agent_subparsers.add_parser("session-start", help="Start an Android CUA session")
    session_start.add_argument("profile_or_serial")
    session_start.add_argument("goal")
    session_start.add_argument("--allowed-package", action="append", default=[])
    session_start.add_argument("--observe-only", action="store_true")
    add_json_flag(session_start)

    return parser


# Mapping from CLI argument name to (scrcpy_flag, is_bool)
CLI_OVERRIDE_FLAGS: list[tuple[str, str, bool]] = [
    ("video_codec", "--video-codec", False),
    ("audio_codec", "--audio-codec", False),
    ("audio_source", "--audio-source", False),
    ("render_fit", "--render-fit", False),
    ("no_window_aspect_ratio_lock", "--no-window-aspect-ratio-lock", True),
    ("orientation", "--orientation", False),
    ("no_control", "--no-control", True),
    ("power_off_on_close", "--power-off-on-close", True),
    ("flex_display", "--flex-display", True),
    ("new_display", "--new-display", False),
    ("record", "--record", False),
    ("record_format", "--record-format", False),
]


def _build_extra_from_args(args: argparse.Namespace) -> list[str]:
    """Build extra scrcpy arguments from CLI overrides."""
    extra: list[str] = []
    for attr_name, flag, is_bool in CLI_OVERRIDE_FLAGS:
        value = getattr(args, attr_name, None)
        if not value:
            continue
        if is_bool:
            extra.append(flag)
        else:
            extra.append(f"{flag}={value}")
    return extra


def _print_agent_json(payload: dict[str, object]) -> int:
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def run_agent_command(args: argparse.Namespace) -> int:
    """Run prompt-free agent CLI commands."""
    from scrcpy_agent import AgentService

    service = AgentService()
    agent_command = args.agent_command or "capabilities"
    if agent_command == "capabilities":
        return _print_agent_json(service.capabilities())
    if agent_command == "devices":
        return _print_agent_json(service.list_devices())
    if agent_command == "profiles":
        return _print_agent_json(service.list_profiles())
    if agent_command == "profile":
        return _print_agent_json(service.get_profile(args.profile_name))
    if agent_command == "quality-presets":
        return _print_agent_json(service.get_quality_presets())
    if agent_command == "last-used":
        return _print_agent_json(service.get_last_used())
    if agent_command == "build-command":
        return _print_agent_json(
            service.build_scrcpy_command(
                args.profile_name,
                connection=args.connection,
                connection_type=args.connection_type,
                mode_override=args.mode,
                quality_override=args.quality,
                extra=args.extra,
            )
        )
    if agent_command == "session-start":
        return _print_agent_json(
            service.android_session_start(
                args.profile_or_serial,
                args.goal,
                allowed_packages=args.allowed_package,
                observe_only=args.observe_only,
            )
        )
    raise RuntimeError(f"Unknown agent command: {agent_command}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "menu"

    if command == "update":
        return update_scrcpy(
            force=args.force,
            no_backup=args.no_backup,
            update_python_deps=args.python_deps,
        )
    if command == "mcp":
        from scrcpy_mcp import main as mcp_main

        return mcp_main()
    if command == "agent":
        return run_agent_command(args)

    try:
        manager = LegacyMenu()
    except SystemExit as exc:
        if command == "menu":
            print(exc)
            print("Run 'python scrcpy_cli.py update' to download the bundled scrcpy/adb binaries.")
            return 1
        raise

    if command == "menu":
        # Auto-reconnect saved wireless profiles before showing UI
        try:
            reconnected = manager.auto_connect_profiles()
            if reconnected:
                print(f"Auto-reconnected: {', '.join(reconnected)}")
        except Exception:
            pass

        # Background update check with optional auto-install prompt
        if manager.get_pref_bool("auto_check_updates", True):
            newer = check_updates_silent()
            if newer:
                print(f"\nUpdate available: {newer}")
                if manager.get_pref_bool("auto_install_updates", True):
                    if prompt_yes_no("Install now", default=True):
                        update_result = update_scrcpy()
                        if update_result == 0:
                            print("\nUpdate installed. Restarting menu...\n")
                        else:
                            print("\nUpdate failed or was cancelled. Continuing with current version.\n")
                    else:
                        print("Skipping update. You can run it later with: python scrcpy_cli.py update\n")
                else:
                    print("Run 'python scrcpy_cli.py update' to install.\n")

        # Try Textual TUI first, fall back to legacy terminal menu
        try:
            from scrcpy_tui import run_tui

            run_tui(manager)
            return 0
        except ImportError as exc:
            logger.warning(f"Textual TUI not available: {exc}. Falling back to legacy menu.")
            return manager.main_menu()
        except Exception as exc:
            logger.error(f"TUI error: {exc}. Falling back to legacy menu.")
            return manager.main_menu()
    if command == "detect":
        return manager.detect_devices()
    if command == "discover":
        return manager.discover_menu()
    if command == "setup":
        return manager.setup_wireless()
    if command == "camera":
        return manager.camera_mode()
    if command == "quickapp":
        return manager.quick_app()
    if command == "shutdown":
        return manager.shutdown()
    if command == "profiles":
        return manager.profiles_menu()
    if command == "quick":
        extra = _build_extra_from_args(args)
        return manager.quick_launch(args.profile, extra=extra, quality_override=args.quality)  # type: ignore[return-value]
    if command == "launch":
        extra = _build_extra_from_args(args)
        return manager.launch_profile(args.profile, extra=extra, quality_override=args.quality)  # type: ignore[return-value]
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
