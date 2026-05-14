# Scrcpy Device Manager v4.0

A unified, menu-driven Python interface for managing Android devices with scrcpy v4.0.

## Quick Start

1. **Main TUI**: Run `python scrcpy_cli.py menu` — launches the rich Textual interface
2. **Quick Launch**: Run `python scrcpy_cli.py quick` (connects to last device)
3. **Auto-Discover**: Press `[F]` in the TUI to find devices automatically across all networks
4. **Setup Wireless**: Run `python scrcpy_cli.py setup` to enable wireless ADB

## Requirements

- **Python 3** on Windows
- **Android device** with USB debugging or Wireless Debugging enabled
- **Textual** (optional, for TUI): `pip install textual`

## Python Interface

### Main entry point (`scrcpy_cli.py`)

- `python scrcpy_cli.py` - opens the interactive menu (TUI or legacy fallback)
- `python scrcpy_cli.py menu` - same as above
- `python scrcpy_cli.py quick` - quick-launch last used device
- `python scrcpy_cli.py quick [ProfileName]` - quick-launch a specific profile
- `python scrcpy_cli.py launch MainPhone` - launch a saved profile directly
- `python scrcpy_cli.py detect` - list connected devices
- `python scrcpy_cli.py discover` - find wireless-debuggable devices via mDNS
- `python scrcpy_cli.py setup` - run wireless setup over USB
- `python scrcpy_cli.py camera` - launch camera mode
- `python scrcpy_cli.py quickapp` - launch an app with scrcpy
- `python scrcpy_cli.py profiles` - manage saved profiles
- `python scrcpy_cli.py shutdown` - disconnect devices and stop adb
- `python scrcpy_cli.py update` - update scrcpy/adb from latest GitHub release

### Convenience wrappers

- `python scrcpy-menu.py` — same as `scrcpy_cli.py menu`
- `python scripts\scrcpy-menu.py`
- `python scripts\scrcpy-quick.py`
- `python scripts\scrcpy-setup.py`
- `python scripts\scrcpy-detect.py`
- `python scripts\scrcpy-discover.py`
- `python scripts\scrcpy-camera.py`
- `python scripts\scrcpy-profile.py`
- `python scripts\scrcpy-quickapp.py`
- `python scripts\scrcpy-shutdown.py`
- `python scripts\scrcpy-launch.py <ProfileName>`
- `python scripts\scrcpy-update.py` — check for and install scrcpy updates

### Notes

- Uses the same `config\devices.ini`, `config\quality.ini`, `config\lastused.ini`, and `config\userprefs.ini`
- Uses the bundled `bin\adb.exe` and `bin\scrcpy.exe`
- Requires Python 3 on Windows

## Textual TUI (Rich Terminal Interface)

The manager now includes a **Textual**-powered TUI when you run `python scrcpy_cli.py menu` (or `python scrcpy-menu.py`).

### TUI Features

- **Live device list** — Auto-refreshes every 3 seconds
- **Saved profiles panel** — Browse and launch profiles with Enter or click
- **Action buttons** — All major features accessible via buttons or hotkeys
- **Modal dialogs** — Profile editor, pairing, camera setup, quick app launcher
- **Keyboard shortcuts** — `L` quick launch, `F` discover, `S` setup, `C` camera, `P` quick app, `A` profiles, `R` refresh, `X` shutdown, `Q` quit

### Installing Textual

```bash
pip install textual
```

If Textual is not installed, the manager falls back to the legacy `input()` terminal menu automatically.

## Network Auto-Discovery (Android 11+)

**No need to type IP addresses! Works across ALL your networks!**

When your Android devices have **Wireless Debugging** enabled, they advertise themselves on the network. The `[F] Find/Discover` feature uses **mDNS** to find them instantly - across **all connected networks** (Ethernet, WiFi, multiple adapters).

### How to Use

1. Enable **Wireless Debugging** on your tablet/phone:
   - Settings → Developer Options → **Wireless Debugging** → ON
   - (Android 11+ required)

2. On PC, run `python scrcpy_cli.py menu` and press **`[F]`**

3. You'll see discovered devices from ALL networks:
   ```
   Scanning across 2 network interfaces...

   FOUND 2 DEVICE(s)

   [1] Pixel-8
       Address: 192.168.1.45:42047
       Source: mDNS

   [2] Galaxy-Tab-S9
       Address: 10.0.0.52:5555
       Source: Scan
   ```

4. Press **`[1]`** or **`[2]`** to connect, or **`[S]`** to save to profiles

### Multi-Network Support

**Works with your setup (Ethernet + Ethernet 2):**
- Automatically scans ALL active network interfaces
- Finds devices on any connected subnet
- Shows which network each device was found on
- No configuration needed - detects your networks automatically

### Discovery Methods

| Method | Speed | Networks | When Used |
|--------|-------|----------|-----------|
| **mDNS** | Instant (<1s) | All | Primary - Android 11+ devices advertise automatically |
| **Network Scan** | ~3 seconds | All detected | Fallback - scans common ports on all subnets |

### Requirements
- **Android 11 or newer** (your Android 13-16 devices work perfectly)
- Device and PC on **same network** (any Ethernet or WiFi)
- **Wireless Debugging** enabled on device

### Manual Alternative
If auto-discovery doesn't find your device:
- **`[S]` Setup Wireless** - Manual IP entry with USB first time
- Run `python scrcpy_cli.py discover` for dedicated discovery window
- Or manually: `bin\adb connect 192.168.1.XX:5555`

## Directory Structure

```
F:\utils\scrcpy\
├── scrcpy_cli.py         ← CLI entry point (argparse + main())
├── scrcpy_manager.py     ← Pure library (ScrcpyManager, Device, ADB/INI helpers)
├── scrcpy_legacy_menu.py ← Legacy terminal menus (input()-based)
├── scrcpy_tui.py         ← Textual TUI (rich terminal interface)
├── scrcpy-menu.py        ← Wrapper: opens interactive menu
├── README.md             ← This file
├── bin\                  ← Executables and DLLs (scrcpy v4.0)
│   ├── scrcpy.exe, adb.exe
│   ├── SDL3.dll, *.dll
│   └── scrcpy-server
├── scripts\              ← Python script wrappers
│   ├── scrcpy-menu.py
│   ├── scrcpy-quick.py
│   ├── scrcpy-discover.py
│   ├── scrcpy-setup.py
│   ├── scrcpy-camera.py
│   ├── scrcpy-profile.py
│   ├── scrcpy-detect.py
│   ├── scrcpy-shutdown.py
│   ├── scrcpy-launch.py
│   ├── scrcpy-quickapp.py
│   └── scrcpy-update.py
├── config\               ← Configuration files
│   ├── devices.ini
│   ├── quality.ini
│   ├── lastused.ini
│   └── userprefs.ini
├── legacy\               ← Old scripts and backups
│   ├── scrcpy-wireless-setup.bat
│   ├── camera-*.bat
│   └── bin-v3.3.4-backup\  ← Previous scrcpy binaries
└── .vscode\              (if using VS Code)
```

## Update scrcpy / adb

The manager can automatically download and install the latest scrcpy release (which includes adb) from GitHub:

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

**What it does:**
1. Queries the [Genymobile/scrcpy](https://github.com/Genymobile/scrcpy) GitHub API for the latest release
2. Compares with your current `bin\scrcpy.exe` version
3. Downloads the Windows 64-bit zip (`scrcpy-win64-vX.X.X.zip`)
4. Backs up your current `bin\` folder to `legacy\bin-v{version}-backup\`
5. Extracts and replaces all binaries
6. Preserves custom files like `bin\icon.png`
7. Verifies the new installation

## Main Scripts (in scripts\ folder)

| Script | Purpose |
|--------|---------|
| `scripts\scrcpy-menu.py` | Main TUI with device selection, profiles, and all features |
| `scripts\scrcpy-quick.py` | Direct quick-launch to last used device |
| `scripts\scrcpy-quickapp.py` | Launch specific apps directly (v4.0 feature) |
| `scripts\scrcpy-discover.py` | **Auto-discover Android devices on network (mDNS)** |
| `scripts\scrcpy-setup.py` | Wireless ADB setup wizard with profile saving |
| `scripts\scrcpy-camera.py` | Unified camera mode launcher |
| `scripts\scrcpy-profile.py` | Manage device profiles (add/edit/delete) |
| `scripts\scrcpy-detect.py` | Scan and display connected devices |
| `scripts\scrcpy-shutdown.py` | Disconnect all and kill ADB server |
| `scripts\scrcpy-launch.py` | Internal: Launch scrcpy with profile settings |
| `scripts\scrcpy-update.py` | Update scrcpy / adb from GitHub releases |

## Keyboard Shortcuts (Textual TUI)

When running `python scrcpy_cli.py menu` with Textual installed:

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

## Keyboard Shortcuts (Legacy Terminal Menu)

When running without Textual (fallback mode):

```
[1-9]  Select device or profile directly
[L]    Quick Launch (last device, 3s timeout)
[A]    Add/Edit Device Profile
[D]    Detect connected devices
[F]    Find/Discover network devices (mDNS auto-discovery)
[S]    Setup wireless device
[C]    Camera mode
[R]    Refresh list
[Q]    Quit
```

## Configuration Files

Located in `config\` folder:

- `devices.ini` - Saved device profiles with nicknames, IPs, quality settings
- `quality.ini` - Quality presets (low/balanced/high/ultra, camera variants)
- `lastused.ini` - Tracks recently used device for Quick Launch
- `userprefs.ini` - User preferences (timeouts, defaults)

## Device Profile Format

```ini
[ProfileID]
nickname=Display Name
ip=192.168.1.31
serial=aff170d0
quality=balanced
mode=mirror
keep_active=__YES__
background_color=#234567
```

## Quality Presets

| Preset | Bitrate | FPS | Buffer | Resolution |
|--------|---------|-----|--------|------------|
| low | 2M | 30 | 60 | native |
| balanced | 8M | 60 | 40 | native |
| high | 12M | 60 | 30 | 1920x1080 |
| ultra | 32M | 120 | 20 | 2560x1440 |
| camera_low | 2M | 30 | 60 | 640x480 |
| camera_balanced | 4M | 30 | 40 | 1280x720 |
| camera_high | 8M | 30 | 30 | 1920x1080 |

## Window Titles

scrcpy windows now show: `scrcpy - Nickname (Connection Type)`
- Example: `scrcpy - Main Phone (Wireless)`
- Example: `scrcpy - Work Phone (USB)`
- Example: `scrcpy - Tablet (Camera Mode)`

## New Features in v4.0

- **Textual TUI**: Rich terminal interface with live device list, profile management, and modal dialogs (optional `pip install textual`)
- **SDL3 Upgrade**: Faster, smoother rendering with SDL3 (was SDL2)
- **Flex Display**: Dynamic virtual display resizing with `--flex-display`
- **Keep Active**: Prevent device sleep during scrcpy with `--keep-active`
- **Background Color**: Customize window background via `--background-color`
- **Camera Torch**: Turn on camera flashlight at startup with `--camera-torch`
- **Camera Zoom**: Set initial camera zoom level with `--camera-zoom`
- **Aspect Ratio Lock**: Disable with `--no-window-aspect-ratio-lock` for free resizing
- **F11 / Mod+q Shortcuts**: Improved fullscreen and quit shortcuts
- **ADB 37.0.0**: Latest platform-tools bundled
- **FFmpeg 8.1.1**: Updated codec support

## Legacy Files

Old scripts are backed up in `legacy\` folder:
- Original batch scripts (`*.bat`)
- Original `scrcpy-wireless-setup.bat`
- Original `scrcpy-wireless-connect.bat`
- Original camera scripts
- Original `config.txt` (migrated to `devices.ini`)
- `bin-v3.3.4-backup\` - Previous scrcpy binaries (rollback available)

## Troubleshooting

1. **Device not found**: Run `python scrcpy_cli.py detect` to check ADB connection
2. **Wireless fails**: Re-run `python scrcpy_cli.py setup` to re-enable TCP/IP mode
3. **Camera mode fails**: Requires Android 12+; use `bin\scrcpy --list-cameras` to verify
4. **Quick Launch timeout**: Edit `config\userprefs.ini` and set `quick_launch_timeout=0` to disable
5. **Pairing fails with protocol fault**: The manager now auto-restarts ADB server and retries once
6. **TUI won't start / looks plain**: Install Textual with `pip install textual`. Without it, the manager falls back to a simple text menu automatically.

## Migration from Old Scripts

Your old `config.txt` is automatically migrated on first run:
- IP address → MainPhone profile
- Quality settings → Proper presets (legacy Y/N mapped to balanced/high)

After migration, `config.txt` is renamed to `config.txt.migrated`.
