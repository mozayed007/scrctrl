from __future__ import annotations

import unittest
from collections.abc import Iterable

from scrcpy_cli import build_parser
from scrcpy_manager import ScrcpyManager


def quality(name: str) -> dict[str, str]:
    presets = {
        "balanced": {
            "name": "balanced",
            "video_bitrate": "8M",
            "max_fps": "60",
            "audio_buffer": "10",
            "audio_delay": "40",
            "video_buffer": "30",
            "resolution": "",
            "video_codec": "h264",
            "audio_codec": "opus",
            "audio_source": "output",
        },
        "high": {
            "name": "high",
            "video_bitrate": "12M",
            "max_fps": "60",
            "audio_buffer": "10",
            "audio_delay": "30",
            "video_buffer": "20",
            "resolution": "1920x1080",
            "video_codec": "h265",
            "audio_codec": "opus",
            "audio_source": "output",
        },
    }
    return presets[name]


class DummyManager(ScrcpyManager):
    def __init__(self) -> None:
        pass

    def get_quality_settings(self, preset: str) -> dict[str, str]:
        return quality(preset)


class RecordingManager(DummyManager):
    def __init__(self) -> None:
        self.launch_call: dict[str, object] = {}

    def launch_profile(
        self,
        profile_name: str,
        *,
        connection: str | None = None,
        connection_type: str | None = None,
        extra: Iterable[str] = (),
        mode_override: str | None = None,
        quality_override: str | None = None,
        detach: bool = False,
    ) -> int:
        self.launch_call = {
            "profile_name": profile_name,
            "connection": connection,
            "connection_type": connection_type,
            "extra": list(extra),
            "mode_override": mode_override,
            "quality_override": quality_override,
            "detach": detach,
        }
        return 0


class CliManagerTests(unittest.TestCase):
    def test_quick_parser_accepts_launch_overrides(self) -> None:
        args = build_parser().parse_args(
            [
                "quick",
                "MainPhone",
                "--quality",
                "high",
                "--record-format",
                "raw",
                "--render-fit",
                "stretch",
            ]
        )

        self.assertEqual(args.command, "quick")
        self.assertEqual(args.profile, "MainPhone")
        self.assertEqual(args.quality, "high")
        self.assertEqual(args.record_format, "raw")
        self.assertEqual(args.render_fit, "stretch")

    def test_quick_launch_forwards_extra_and_quality_override(self) -> None:
        manager = RecordingManager()

        result = manager.quick_launch(
            "MainPhone",
            extra=["--no-control"],
            quality_override="high",
            detach=True,
        )

        self.assertEqual(result, 0)
        self.assertEqual(manager.launch_call["profile_name"], "MainPhone")
        self.assertEqual(manager.launch_call["extra"], ["--no-control"])
        self.assertEqual(manager.launch_call["quality_override"], "high")
        self.assertEqual(manager.launch_call["detach"], True)

    def test_quality_override_uses_override_preset_but_keeps_profile_codec_precedence(self) -> None:
        manager = DummyManager()
        profile = {
            "name": "MainPhone",
            "nickname": "Main Phone",
            "quality": "balanced",
            "mode": "mirror",
            "video_codec": "h264",
        }

        args = manager.build_scrcpy_args(
            profile=profile,
            connection="USB123",
            connection_type="USB",
            quality_override="high",
        )

        self.assertIn("--video-bit-rate=12M", args)
        self.assertIn("--max-size=1920", args)
        self.assertIn("--video-codec=h264", args)
        self.assertNotIn("--video-bit-rate=8M", args)
        self.assertNotIn("--video-codec=h265", args)


if __name__ == "__main__":
    unittest.main()
