# AGENTS.md

## Project: ScrCtrl — scrcpy Device Manager for Windows

## Quick Reference

- **Language**: Python 3.9+
- **Entry points**: `scrcpy_cli.py` (CLI), `scrcpy_tui.py` (Textual TUI), `scrcpy_legacy_menu.py` (fallback menu)
- **Core library**: `scrcpy_manager.py` (pure Python, no UI deps)
- **Binaries**: `bin\scrcpy.exe`, `bin\adb.exe` (downloaded from official Genymobile releases)
- **Config**: `config\devices.ini`, `config\quality.ini`, `config\lastused.ini`, `config\userprefs.ini`
- **Key dependency**: `textual` (optional, for TUI)

## Architecture

```
scrcpy_cli.py   →  argparse routing, update workflow, CLI entry
scrcpy_tui.py   →  Textual App / MainScreen (imports screens + manager)
scrcpy_tui_screens.py  →  Modal screens (ProfileEdit, Help, LaunchOptions, etc.)
scrcpy_legacy_menu.py  →  input()-based menus (extends ScrcpyManager)
scrcpy_manager.py  →  ScrcpyManager, Device, ADB wrappers, INI I/O, ProfileField schema
```

The manager is the single source of truth for all scrcpy argument building.

## Profile Schema (config/devices.ini)

### Connection & Identity
- `nickname` — Display name
- `ip` — Wireless IP address
- `serial` — USB serial number
- `quality` — Preset name from `quality.ini`
- `mode` — `mirror` | `otg` | `camera`

### Streaming & Quality
- `video_codec` — `h264` | `h265` | `av1` | empty (uses quality preset)
- `audio_codec` — `opus` | `aac` | `flac` | `raw` | empty
- `audio_source` — `output` | `playback` | `mic` | `mic-unprocessed` | ... | empty
- `render_fit` — `auto` | `stretch` | `crop` | `letterbox` | empty
- `orientation` — `0` | `90` | `180` | `270` | `flip0` | `flip90` | `flip180` | `flip270` | empty
- `window_aspect_ratio_lock` — `yes` (default) | `no`

### Display & Behavior
- `keep_active` — `__YES__` / `yes` / `true` / `1` / `on` → `--keep-active`
- `background_color` — Hex color, e.g. `#234567`
- `flex_display` — `yes` → `--flex-display` (only meaningful with `new_display` or `mode=mirror`)
- `new_display` — Virtual display spec, e.g. `1920x1080/160` → `--new-display=1920x1080/160`
- `no_control` — `yes` → `--no-control`
- `power_off_on_close` — `yes` → `--power-off-on-close`

### Recording
- `record` — File path → `--record=<path>`
- `record_format` — `mp4` | `mkv` | `m4a` | `mka` | `opus` | `aac` | `flac` | `wav` | `raw` → `--record-format=<fmt>`

### Boolean Normalization
Profile booleans use `is_profile_bool_yes(value)` which accepts:
- `__YES__`, `yes`, `y`, `true`, `1`, `on` → True
- Everything else (including empty string) → False

## Quality Preset Schema (config/quality.ini)

Each section is a preset name used by profiles.

- `video_bitrate` — e.g. `12M` → `--video-bit-rate=12M`
- `max_fps` — e.g. `60` → `--max-fps=60`
- `audio_buffer` — e.g. `10` → `--audio-output-buffer=10` (SDL buffer, default 10ms)
- `audio_delay` — e.g. `30` → `--audio-buffer=30` (target delay, default 50ms)
- `video_buffer` — e.g. `20` → `--video-buffer=20` (jitter compensation, default 0ms)
- `resolution` — e.g. `1920x1080` → `--max-size=1920`
- `video_codec` — e.g. `h265` → `--video-codec=h265`
- `audio_codec` — e.g. `opus` → `--audio-codec=opus`
- `audio_source` — e.g. `output` → `--audio-source=output`

**Precedence rule**: Profile-level `video_codec`/`audio_codec`/`audio_source` override the quality preset values.

## Default Presets (Optimized for Modern Hardware)

| Preset | Bitrate | FPS | Audio Delay | Video Buffer | Resolution | Video Codec | Audio |
|--------|---------|-----|-------------|--------------|------------|-------------|-------|
| low | 2M | 30 | 60ms | 50ms | native | h264 | opus |
| balanced | 8M | 60 | 40ms | 30ms | native | h264 | opus |
| high | 12M | 60 | 30ms | 20ms | 1920x1080 | h265 | opus |
| ultra | 32M | 120 | 20ms | 0ms | 2560x1440 | h265 | opus |

- Use `high` or `ultra` for modern devices and laptops (H265 decoding is efficient on modern hardware).
- `audio_delay` is `--audio-buffer`. Lower = more responsive; higher = smoother.
- `video_buffer` is `--video-buffer`. `0` on `ultra` minimizes latency.
- `audio_buffer` (SDL output) is kept at `10ms` (default) for all presets.

## scrcpy Argument Building (build_scrcpy_args)

The canonical place where CLI flags are generated from profile + quality settings.

Key logic:
1. `-s <connection>` always first
2. `--window-title` is auto-generated
3. Quality settings are applied (bitrate, fps, buffers, resolution, codecs, source)
4. Mode flags: `--otg`, `--video-source=camera`
5. New display: `--new-display=<spec>` (if `mode != otg`)
6. Flex display: `--flex-display` (if `mode != otg`)
7. Window/rendering: `--keep-active`, `--background-color`, `--render-fit`, `--no-window-aspect-ratio-lock`, `--orientation`
8. Behavior: `--no-control`, `--power-off-on-close`
9. Recording: `--record`, `--record-format`
10. Profile-level codec overrides (take final precedence over quality presets)
11. `extra` args from CLI are appended last

## Validation Helpers

- `is_valid_video_codec` — checks against `VIDEO_CODECS` list
- `is_valid_audio_codec` — checks against `AUDIO_CODECS` list
- `is_valid_audio_source` — checks against `AUDIO_SOURCES` list
- `is_valid_render_fit` — checks against `RENDER_FITS` list
- `is_valid_orientation` — checks against `ORIENTATIONS` list
- `is_valid_record_format` — checks against `RECORD_FORMATS` list
- `is_valid_new_display` — validates `WIDTHxHEIGHT` or `WIDTHxHEIGHT/DPI`
- `is_profile_bool_yes` — normalizes boolean strings

## Coding Conventions

- Use `str | None` for optional strings, not `Optional[str]`
- Use `list[str]` instead of `List[str]`
- Use `configparser.ConfigParser(interpolation=None)` and `parser.optionxform = str` to preserve case
- Always create `.bak` backup before overwriting INI files
- All UI code lives in `scrcpy_tui.py` or `scrcpy_legacy_menu.py`; `scrcpy_manager.py` is pure library
- TUI widgets are created inside `try: ... except ImportError:` so the module remains importable without Textual
- Use `logger = logging.getLogger(__name__)` for debug output; enable with `SCRCPY_DEBUG=1`

## Adding New scrcpy Flags

1. Add the constant list (e.g., `NEW_OPTIONS = [...]`) to `scrcpy_manager.py`
2. Add a validation helper if needed
3. Add the field to `get_profile`, `list_profiles`, `save_profile`
4. Add the flag to `build_scrcpy_args`
5. Add the field to `ProfileEditScreen` (TUI) and `_prompt_profile_fields` (legacy menu)
6. Add CLI argument to `build_parser` in `scrcpy_cli.py`
7. Add to `_build_extra_from_args` in `scrcpy_cli.py`
8. Update `config/quality.ini` if the preset should include it
9. Update `scrcpy_agent.py` JSON-safe service methods if the flag should be agent-addressable
10. Update `scrcpy_mcp.py` tool/resource schemas if the flag should be exposed to MCP clients
11. Update `README.md`, `AGENTS.md`, and tests

## Agent Experience / Android CUA

- `scrcpy_agent.py` is the prompt-free agent service layer; keep it JSON-safe and non-interactive
- `scrcpy_mcp.py` is the local MCP stdio server; keep tool schemas explicit and avoid arbitrary `adb shell`
- Android CUA sessions require `session_id` for control actions and should use direct ADB screenshots (`exec-out screencap -p`)
- Risky actions should return `approval_required` or `blocked`, not silently execute
- Scrcpy remains the watch/recording surface; ADB remains the reliable state/action surface
