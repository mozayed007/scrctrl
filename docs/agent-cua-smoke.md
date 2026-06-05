# ScrCtrl Android CUA Smoke Workflow

Use this workflow to validate the local AX/CUA surface against a real Android device.

## Prerequisites

- Run `python scrcpy_cli.py update` if `bin\adb.exe` or `bin\scrcpy.exe` is missing.
- Ensure the target device is visible in `python scrcpy_cli.py agent devices --json`.
- Use a saved profile when possible, for example `MainPhone`.

## 1. Check Readiness

```powershell
python scrcpy_cli.py agent doctor --json
```

Expected:

- `adb_binary`, `scrcpy_binary`, `artifact_dir`, and `session_dir` are `ok: true`
- `mcp_tools_list` reports a non-zero `tool_count`
- `connected_devices.count` is at least `1` when a device is connected

## 2. Start an Observe-Only Session

Before controlling a device, inspect the scrcpy-native knowledge surface:

```powershell
python scrcpy_cli.py agent scrcpy-version --json
python scrcpy_cli.py agent scrcpy-shortcuts --json
python scrcpy_cli.py agent scrcpy-recipe virtual-app --package org.videolan.vlc --json
python scrcpy_cli.py agent validate-scrcpy-args --json -- --no-control --new-display
```

Expected:

- Shortcuts include `MOD+q`, `MOD+f`, `MOD+h`, `MOD+b`, `MOD+v`, and camera-only `MOD+t`
- The virtual-app recipe returns exact scrcpy args without launching them
- Validation accepts known scrcpy flags and rejects unknown ones

```powershell
python scrcpy_cli.py agent session-start MainPhone "Inspect Settings without touching anything" --allowed-package com.android.settings --observe-only --json
```

Copy the returned `session.session_id`.

```powershell
python scrcpy_cli.py agent screenshot <session_id> --json
python scrcpy_cli.py agent dump-ui <session_id> --json
```

Expected:

- Screenshot and UI dump files are written under `%TEMP%\scrctrl-agent\artifacts`
- Control commands such as `tap` return `status: blocked` because the session is observe-only

## 3. Start a Controlled Session

```powershell
python scrcpy_cli.py agent session-start MainPhone "Open Settings and inspect one screen" --allowed-package com.android.settings --json
python scrcpy_cli.py agent start-app <session_id> com.android.settings --json
python scrcpy_cli.py agent wait <session_id> 1 --json
python scrcpy_cli.py agent screenshot <session_id> --json
```

Then try a small harmless input action:

```powershell
python scrcpy_cli.py agent keyevent <session_id> back --json
```

Expected:

- Actions append to the session log across separate CLI invocations
- The same `session_id` works after the original command exits

## 4. Verify Approval Gates

```powershell
python scrcpy_cli.py agent type-text <session_id> "delete account" --json
```

Expected:

- The command returns `status: approval_required`
- It includes an `approval_id`

To explicitly execute that exact pending action:

```powershell
python scrcpy_cli.py agent approve <session_id> <approval_id> --json
```

## 5. MCP Smoke

```powershell
'{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python scrcpy_mcp.py
'{"jsonrpc":"2.0","id":2,"method":"resources/read","params":{"uri":"scrctrl://agent/capabilities"}}' | python scrcpy_mcp.py
```

Expected:

- Both commands return one JSON-RPC response line
- `tools/list` includes `android_session_start`, `android_screenshot`, and `approve_action`
