<div align="center">

<!--
  Logo placeholder — replace with a banner image when ready
  e.g. <img src="docs/assets/banner.png" width="700" alt="ScrCtrl Banner">
-->

<pre align="center">
╔══════════════════════════════════════════╗
║                S C R C T R L             ║
║      Scrcpy Device Manager for Windows   ║
╚══════════════════════════════════════════╝
</pre>

<br>

<a href="https://github.com/mozayed007/scrctrl/stargazers"><img src="https://img.shields.io/github/stars/mozayed007/scrctrl?style=for-the-badge&color=yellow" alt="Stars"></a>
<a href="https://github.com/mozayed007/scrctrl/network/members"><img src="https://img.shields.io/github/forks/mozayed007/scrctrl?style=for-the-badge&color=green" alt="Forks"></a>
<a href="./LICENSE"><img src="https://img.shields.io/github/license/mozayed007/scrctrl?style=for-the-badge&color=brightgreen" alt="License"></a>
<a href="https://github.com/mozayed007/scrctrl/issues"><img src="https://img.shields.io/github/issues/mozayed007/scrctrl?style=for-the-badge&color=orange" alt="Issues"></a>
<br>
<a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.9+-blue.svg?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.9+"></a>
<a href="#platform"><img src="https://img.shields.io/badge/platform-Windows-lightgrey.svg?style=for-the-badge&logo=windows&logoColor=white" alt="Windows"></a>
<a href="https://github.com/Genymobile/scrcpy"><img src="https://img.shields.io/badge/powered%20by-scrcpy-green.svg?style=for-the-badge&logo=android&logoColor=white" alt="Powered by scrcpy"></a>

<p align="center">
  <b>A unified Python TUI / CLI manager for scrcpy</b><br>
  <sub>Device discovery · Profiles · Wireless ADB · Auto-updates · Camera mode</sub>
</p>

[Features](#sparkles-features) · [Installation](#rocket-installation) · [Quick Start](#zap-quick-start) · [Usage](#gear-usage) · [Documentation](#book-documentation) · [Contributing](#handshake-contributing) · [License](#scroll-license)

</div>

---

> **Disclaimer:** This is an **unofficial community project**. `scrcpy` is a trademark of [Genymobile](https://github.com/Genymobile). This manager is a separate Python wrapper — it does not modify or distribute scrcpy source code. Pre-built binaries are downloaded directly from official Genymobile/scrcpy GitHub releases under the Apache 2.0 License. See [THIRD-PARTY-LICENSES.md](THIRD-PARTY-LICENSES.md) for full attribution.

---

<!-- You can add a demo GIF / screenshot here:
<p align="center">
  <img src="docs/assets/demo.gif" width="800" alt="ScrCtrl TUI Demo" />
</p>
-->

## :sparkles: Features

| | Feature | Description |
|---|---|---|
| :tv: | **Rich Textual TUI** | Live device list, auto-refresh, modal dialogs, hotkeys — or falls back to a clean terminal menu automatically |
| :satellite: | **Network Auto-Discovery** | mDNS-based discovery across all network interfaces (Android 11+ Wireless Debugging) |
| :calling: | **Wireless ADB Setup Wizard** | One-time USB pairing, then wireless forever — no cables needed after setup |
| :camera: | **Camera Mode** | Launch device cameras as webcam sources directly from the menu |
| :rocket: | **Quick App Launcher** | Start Android apps in mirror or virtual display mode without typing package names |
| :bookmark_tabs: | **Device Profiles** | Save nicknames, IPs, serials, quality presets, and per-device settings across sessions |
| :arrows_counterclockwise: | **Self-Updating Binaries** | Download the latest scrcpy / adb releases from GitHub automatically, with backups |
| :shield: | **Graceful Error Handling** | ADB pairing fault auto-retry, Ctrl+C handling throughout, fault-tolerant mDNS parsing |

---

## :rocket: Installation

### 1. Clone the repository

```bash
git clone https://github.com/mozayed007/scrctrl.git
cd scrctrl
```

### 2. Download scrcpy binaries

```bash
python scrcpy_cli.py update
```

This fetches the latest official Windows release (including `adb.exe`) into `bin\`.

### 3. (Optional) Install Textual for the rich TUI

```bash
pip install textual
```

> Without Textual, the manager automatically falls back to a clean `input()`-based menu — zero hard dependencies.

---

## :zap: Quick Start

```bash
# Open the interactive menu (TUI or legacy fallback)
python scrcpy_cli.py menu

# Quick-launch the last used device
python scrcpy_cli.py quick

# List connected ADB devices
python scrcpy_cli.py detect
```

---

## :gear: Usage

### Interactive TUI

```bash
python scrcpy_cli.py menu
```

| Key | Action |
|-----|--------|
| `Enter` / Click | Launch selected device or profile |
| `L` | Quick Launch last used device |
| `A` | Open Profile Manager |
| `D` | Detect / refresh device list |
| `F` | Discover wireless devices (mDNS) |
| `S` | Setup wireless ADB |
| `C` | Launch Camera Mode |
| `P` | Quick App Launcher |
| `R` | Refresh all data |
| `X` | Shutdown ADB server |
| `Q` | Quit |

### Command-Line

```bash
# Launch a saved profile
python scrcpy_cli.py launch MainPhone

# Find wireless-debuggable devices
python scrcpy_cli.py discover

# Run wireless setup over USB
python scrcpy_cli.py setup

# Launch camera mode
python scrcpy_cli.py camera

# Launch an app
python scrcpy_cli.py quickapp

# Manage profiles
python scrcpy_cli.py profiles

# Disconnect everything
python scrcpy_cli.py shutdown
```

### Convenience Wrappers

Each subcommand has a thin wrapper in `scripts\`:

| Wrapper | Equivalent |
|---------|-----------|
| `python scrcpy-menu.py` | `scrcpy_cli.py menu` |
| `python scripts\scrcpy-quick.py` | `scrcpy_cli.py quick` |
| `python scripts\scrcpy-detect.py` | `scrcpy_cli.py detect` |
| `python scripts\scrcpy-discover.py` | `scrcpy_cli.py discover` |
| `python scripts\scrcpy-setup.py` | `scrcpy_cli.py setup` |
| `python scripts\scrcpy-camera.py` | `scrcpy_cli.py camera` |
| `python scripts\scrcpy-quickapp.py` | `scrcpy_cli.py quickapp` |
| `python scripts\scrcpy-profile.py` | `scrcpy_cli.py profiles` |
| `python scripts\scrcpy-shutdown.py` | `scrcpy_cli.py shutdown` |
| `python scripts\scrcpy-launch.py ProfileName` | `scrcpy_cli.py launch ProfileName` |
| `python scripts\scrcpy-update.py` | `scrcpy_cli.py update` |

### Update Workflow

Automatically download and install the latest scrcpy release from GitHub:

```bash
# Check for updates and install if newer
python scrcpy_cli.py update

# Force reinstall even if already on latest
python scrcpy_cli.py update --force

# Skip backup of current binaries
python scrcpy_cli.py update --no-backup

# Also upgrade Python packages (textual)
python scrcpy_cli.py update --python-deps
```

What it does:
1. Queries the [Genymobile/scrcpy](https://github.com/Genymobile/scrcpy) GitHub API
2. Compares with your current `bin\scrcpy.exe` version
3. Downloads the Windows 64-bit zip (`scrcpy-win64-vX.X.X.zip`)
4. Backs up `bin\` to `legacy\bin-v{version}-backup\`
5. Extracts and replaces all binaries
6. Preserves custom files like `bin\icon.png`
7. Verifies the new installation

### Programmatic API

Use `ScrcpyManager` directly in your own scripts:

```python
from scrcpy_manager import ScrcpyManager

manager = ScrcpyManager()

# List connected devices
devices = manager.list_devices()
for d in devices:
    print(d.display_name, d.serial, d.kind)

# Launch a saved profile
manager.launch_profile("MainPhone")

# Save a new profile
manager.save_profile(
    profile_name="Tablet",
    nickname="Galaxy Tab",
    ip="192.168.1.45",
    quality="high",
    keep_active="__YES__",
)
```

---

## :book: Documentation

### First-Time Setup

#### USB Connection (Simplest)

1. Enable **USB Debugging** on your Android device:
   - Settings → About Phone → Tap "Build Number" 7 times
   - Settings → Developer Options → **USB Debugging** → ON

2. Connect via USB, then run:
   ```bash
   python scrcpy_cli.py detect
   ```
   You should see your device listed.

3. Launch it:
   ```bash
   python scrcpy_cli.py menu
   # Press the number next to your device
   ```

#### Wireless Connection (One-Time Setup)

1. Connect via USB first (required for initial pairing)
2. Run the setup wizard:
   ```bash
   python scrcpy_cli.py setup
   ```
3. The wizard will:
   - Detect your device IP automatically
   - Switch ADB to TCP/IP mode
   - Connect wirelessly
   - Offer to save the device as a profile

After setup, disconnect the USB cable. The device remains reachable wirelessly.

#### Android 11+ Wireless Debugging (No USB Needed)

1. Enable **Wireless Debugging** on your device:
   - Settings → Developer Options → **Wireless Debugging** → ON

2. On your PC, run:
   ```bash
   python scrcpy_cli.py menu
   # Press [F] to discover
   ```

3. Select your device, enter the 6-digit pairing code when prompted, and connect.

### Device Profiles

Profiles persist device settings across sessions. Stored in `config\devices.ini`.

#### Example Profile

```ini
[MainPhone]
nickname=Main Phone
ip=192.168.1.31
serial=EXAMPLE1234
quality=balanced
mode=mirror
keep_active=__YES__
background_color=#234567
```

#### Fields

| Field | Description |
|-------|-------------|
| `nickname` | Display name shown in menus |
| `ip` | IP address for wireless connections |
| `serial` | USB serial number |
| `quality` | Preset: `low`, `balanced`, `high`, `ultra` |
| `mode` | `mirror`, `otg`, or `camera` |
| `keep_active` | `__YES__` to prevent sleep during scrcpy |
| `background_color` | Hex color for window background |

### Network Auto-Discovery

When Android devices have **Wireless Debugging** enabled, they advertise themselves via mDNS. The `[F] Find/Discover` feature finds them instantly across **all connected network interfaces**.

```
Network Device Discovery

Devices requiring pairing (Android 11+):
[1] Pixel-8
    Address: 192.168.1.45:42047
    Type:    Pairing required

Already paired devices:
[2] Galaxy-Tab-S9
    Address: 10.0.0.52:5555
    Type:    Ready to connect
```

**Requirements:** Android 11+, device and PC on the same network.

### Keyboard Shortcuts

#### Textual TUI

| Key | Action |
|-----|--------|
| `Enter` / Click | Launch selected device or profile |
| `L` | Quick Launch |
| `A` | Profile Manager |
| `D` | Detect devices |
| `F` | Discover wireless devices |
| `S` | Setup wireless |
| `C` | Camera mode |
| `P` | Quick App Launcher |
| `R` | Refresh |
| `X` | Shutdown ADB |
| `Q` | Quit |

#### Legacy Terminal Menu

| Key | Action |
|-----|--------|
| `[1-9]` | Select device or profile directly |
| `L` | Quick Launch (last device) |
| `A` | Profile Manager |
| `D` | Detect devices |
| `F` | Discover devices (mDNS) |
| `S` | Setup wireless |
| `C` | Camera mode |
| `R` | Refresh |
| `Q` | Quit |

### Quality Presets

| Preset | Bitrate | FPS | Buffer | Resolution |
|--------|---------|-----|--------|------------|
| `low` | 2M | 30 | 60 | native |
| `balanced` | 8M | 60 | 40 | native |
| `high` | 12M | 60 | 30 | 1920x1080 |
| `ultra` | 32M | 120 | 20 | 2560x1440 |
| `camera_low` | 2M | 30 | 60 | 640x480 |
| `camera_balanced` | 4M | 30 | 40 | 1280x720 |
| `camera_high` | 8M | 30 | 30 | 1920x1080 |

### Configuration

User-specific config lives in `config\` and is **not** tracked by git:

| File | Purpose |
|------|---------|
| `devices.ini` | Saved device profiles |
| `quality.ini` | Quality preset definitions |
| `lastused.ini` | Recently used device for Quick Launch |
| `userprefs.ini` | User preferences (timeouts, defaults) |

Example `userprefs.ini`:

```ini
[preferences]
quick_launch_timeout=3
```

Set `quick_launch_timeout=0` to disable the quick-launch prompt at startup.

### Architecture

The codebase is split into four clean layers:

```
┌─────────────────────────────────────────┐
│  scrcpy_cli.py   │  CLI entry point    │
│  scrcpy_tui.py   │  Textual TUI        │
│  scrcpy_legacy_menu.py │ Terminal menus │
├─────────────────────────────────────────┤
│  scrcpy_manager.py │  Pure library      │
│  · ScrcpyManager, Device, ADB wrappers │
│  · INI persistence, auto-updates         │
└─────────────────────────────────────────┘
```

This separation means:
- The TUI imports only the library, never menu code
- The CLI decides between TUI and legacy menu at runtime
- Your own scripts can import `ScrcpyManager` without dragging in UI code

### Directory Structure

```
scrctrl/
├── scrcpy_cli.py              # CLI entry point
├── scrcpy_manager.py          # Pure library
├── scrcpy_legacy_menu.py      # Terminal menus
├── scrcpy_tui.py              # Textual TUI
├── scrcpy-menu.py             # Convenience wrapper
├── README.md
├── LICENSE                    # MIT
├── .gitignore
├── bin/
│   ├── .gitkeep               # Preserves directory in git
│   ├── icon.png               # Custom icon (preserved on update)
│   └── scrcpy.exe, adb.exe, *.dll  # Downloaded via update
├── scripts/
│   ├── scrcpy-menu.py
│   ├── scrcpy-quick.py
│   ├── scrcpy-detect.py
│   ├── scrcpy-discover.py
│   ├── scrcpy-setup.py
│   ├── scrcpy-camera.py
│   ├── scrcpy-profile.py
│   ├── scrcpy-shutdown.py
│   ├── scrcpy-launch.py
│   ├── scrcpy-quickapp.py
│   └── scrcpy-update.py
├── config/                    # User data (gitignored)
│   ├── devices.ini
│   ├── quality.ini
│   ├── lastused.ini
│   └── userprefs.ini
└── legacy/                    # Backups & old scripts (gitignored)
    └── bin-vX.X-backup/
```

### Troubleshooting

| Issue | Solution |
|-------|----------|
| **Device not found** | Run `python scrcpy_cli.py detect`. Check USB debugging is enabled. |
| **Wireless fails** | Re-run `python scrcpy_cli.py setup` to re-enable TCP/IP mode. |
| **Camera mode fails** | Requires Android 12+. Run `bin\scrcpy --list-cameras` to verify. |
| **Quick Launch timeout** | Edit `config\userprefs.ini`: `quick_launch_timeout=0` |
| **Pairing protocol fault** | Manager auto-restarts ADB server and retries once. |
| **TUI looks plain / won't start** | Install Textual: `pip install textual`. Falls back to text menu without it. |
| **No scrcpy.exe found** | Run `python scrcpy_cli.py update` to download binaries. |
| **Legacy menu stuck** | Press `Ctrl+C` — all interactive paths handle `KeyboardInterrupt`. |

---

## :wrench: Built With

- [scrcpy](https://github.com/Genymobile/scrcpy) — Android screen mirroring & control
- [Textual](https://github.com/Textualize/textual) — Python TUI framework
- [adb](https://developer.android.com/studio/releases/platform-tools) — Android Debug Bridge
- Python 3.9+

---

## :handshake: Contributing

Contributions are welcome! Whether it's bug reports, feature ideas, or pull requests — feel free to open an [issue](https://github.com/mozayed007/scrctrl/issues) or submit a PR.

1. Fork the repository
2. Create a feature branch: `git checkout -b feat/my-feature`
3. Commit your changes: `git commit -m "feat: add awesome feature"`
4. Push to the branch: `git push origin feat/my-feature`
5. Open a Pull Request

Please keep code style consistent with the existing codebase and add comments for non-trivial logic.

---

## :star: Show Your Support

If you find this project useful, please consider giving it a :star: on GitHub — it helps others discover it!

<a href="https://github.com/mozayed007/scrctrl/stargazers">
  <img src="https://reporanger.com/badge/mozayed007/scrctrl" alt="Stargazers" />
</a>

---

## :scroll: License

This manager (Python code) is licensed under the **MIT License** — see [LICENSE](LICENSE).

Third-party binaries (`scrcpy.exe`, `adb.exe`, SDL3, FFmpeg, dav1d) are downloaded from the official [Genymobile/scrcpy](https://github.com/Genymobile/scrcpy) releases and are licensed under their respective terms. See [THIRD-PARTY-LICENSES.md](THIRD-PARTY-LICENSES.md) and [NOTICE](NOTICE) for full attribution.

| Component | License | File |
|-----------|---------|------|
| scrcpy & adb | Apache 2.0 | [licenses/scrcpy-LICENSE](licenses/scrcpy-LICENSE) |
| SDL3 | zlib License | — |
| FFmpeg | LGPL 2.1+ / GPL 2+ | — |
| dav1d | BSD 2-Clause | — |

Copyright (c) 2026 Scrcpy Device Manager Contributors.

---

<div align="center">
  <sub>Built with :heart: by <a href="https://github.com/mozayed007">mozayed007</a>, Kilo (Kimi K2.6 Turbo — Fireworks AI), & <a href="https://github.com/mozayed007/scrctrl/graphs/contributors">contributors</a></sub>
</div>
