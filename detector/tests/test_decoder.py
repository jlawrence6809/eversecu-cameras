"""Exercise pipe saturation and a stalled decoder using real child processes."""

import subprocess
import sys
import unittest
from unittest.mock import patch

from coyote_watch import FRAME_BYTES, FFmpegCamera


class DecoderTests(unittest.TestCase):
    def test_stderr_saturation_does_not_block_frame(self):
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import os; os.write(2, b'error\\n' * 30000); "
                f"os.write(1, bytes({FRAME_BYTES}))",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        with (
            patch("coyote_watch.shutil.which", return_value="ffmpeg"),
            patch("coyote_watch.subprocess.Popen", return_value=process),
        ):
            camera = FFmpegCamera("rtsp://example.test")
        try:
            ok, frame = camera.read()
            self.assertTrue(ok)
            self.assertEqual(frame.shape, (360, 640, 3))
        finally:
            camera.release()
        self.assertIsNotNone(process.poll())

    def test_stall_returns_and_release_reaps_process(self):
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        with (
            patch("coyote_watch.shutil.which", return_value="ffmpeg"),
            patch("coyote_watch.subprocess.Popen", return_value=process),
        ):
            camera = FFmpegCamera("rtsp://example.test")
        try:
            with patch("coyote_watch.select.select", return_value=([], [], [])):
                self.assertEqual(camera.read(), (False, None))
        finally:
            camera.release()
        self.assertIsNotNone(process.poll())
