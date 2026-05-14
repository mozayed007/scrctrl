#!/usr/bin/env python3
"""CLI entry point for scrcpy Device Manager.

Routes subcommands to the appropriate handler (Textual TUI, legacy menus,
or direct manager operations). Also provides the update workflow.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Sequence

from scrcpy_manager import (
    BIN_DIR,
    ROOT,
    SCRCPY_EXE,
    logger,
)
from scrcpy_legacy_menu import LegacyMenu


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
            with urllib.request.urlopen(download_req, timeout=120) as dl_resp:
                with zip_path.open("wb") as f:
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Python scrcpy terminal manager")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("menu", help="Open the interactive terminal menu")
    subparsers.add_parser("detect", help="List connected adb devices")
    subparsers.add_parser("discover", help="Discover wireless-debuggable devices")
    subparsers.add_parser("setup", help="Run wireless adb setup")
    subparsers.add_parser("camera", help="Open camera mode launcher")
    subparsers.add_parser("quickapp", help="Launch an app with scrcpy")
    subparsers.add_parser("shutdown", help="Disconnect devices and stop adb")
    subparsers.add_parser("profiles", help="Open profile manager")

    quick = subparsers.add_parser("quick", help="Quick-launch last or selected profile")
    quick.add_argument("profile", nargs="?", help="Optional profile name")

    launch = subparsers.add_parser("launch", help="Launch a saved profile")
    launch.add_argument("profile", help="Profile name to launch")

    update = subparsers.add_parser("update", help="Update scrcpy/adb binaries from GitHub releases")
    update.add_argument("--force", action="store_true", help="Reinstall even if already on latest version")
    update.add_argument("--no-backup", action="store_true", help="Skip backing up current binaries")
    update.add_argument("--python-deps", action="store_true", help="Also upgrade Python packages (textual)")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "menu"
    manager = LegacyMenu()

    if command == "menu":
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
        return manager.quick_launch(args.profile)
    if command == "launch":
        return manager.launch_profile(args.profile)
    if command == "update":
        return update_scrcpy(
            force=args.force,
            no_backup=args.no_backup,
            update_python_deps=args.python_deps,
        )
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
