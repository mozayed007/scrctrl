# Third-Party Licenses

This project bundles or downloads pre-built binaries from the following
open-source projects. Their respective licenses are reproduced below or
linked.

## scrcpy

- **Homepage:** https://github.com/Genymobile/scrcpy
- **License:** Apache License 2.0
- **Full text:** [licenses/scrcpy-LICENSE](licenses/scrcpy-LICENSE)
- **Copyright:** (C) 2018 Genymobile, (C) 2018-2026 Romain Vimont

scrcpy is an open-source application that provides display and control of
Android devices from a desktop. The `scrcpy.exe`, `scrcpy-server`, and
associated DLLs (SDL3, FFmpeg, etc.) are downloaded automatically by this
manager via the `update` command, or may be placed manually in `bin\`.

## Android SDK Platform Tools (adb)

- **Homepage:** https://developer.android.com/tools/releases/platform-tools
- **License:** Apache License 2.0
- **Copyright:** Google LLC

The `adb.exe` binary is part of the Android SDK Platform Tools and is
bundled inside the scrcpy Windows release archive.

## SDL3

- **Homepage:** https://libsdl.org/
- **License:** zlib License
- **Copyright:** (C) 1997-2024 Sam Lantinga

SDL3 is bundled as a DLL inside the scrcpy Windows release.

## FFmpeg

- **Homepage:** https://ffmpeg.org/
- **License:** LGPL 2.1+ / GPL 2+
- **Copyright:** FFmpeg contributors

FFmpeg libraries (avcodec, avformat, avutil, etc.) are bundled as DLLs
inside the scrcpy Windows release.

## dav1d

- **Homepage:** https://code.videolan.org/videolan/dav1d
- **License:** BSD 2-Clause
- **Copyright:** (C) 2018-2024 VideoLAN and dav1d authors

Bundled as part of the scrcpy Windows release.

---

This manager itself (the Python code) is licensed under the MIT License.
See [LICENSE](LICENSE) for the full text.
