import unittest
from unittest.mock import MagicMock, patch
import os
import sys
from pathlib import Path

# Add project root to sys.path to import obsbot_capture
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import obsbot_capture

class TestFFmpegCmd(unittest.TestCase):
    def setUp(self):
        # Patch load_config to prevent file I/O during CameraState init
        self.load_config_patcher = patch.object(obsbot_capture.CameraState, 'load_config')
        self.mock_load_config = self.load_config_patcher.start()

        # Instantiate CameraState
        self.state = obsbot_capture.CameraState()

        # Set default values for tests
        self.state.device = "/dev/video0"
        self.state.resolution = "3840x2160"
        self.state.fps = 30
        self.state.audio_enabled = True
        self.state.audio_device = "hw:1,0"
        self.state.audio_muted = False
        self.state.mic_gain_db = 0
        self.state.output_format_idx = 0 # h264_high default
        self.state.output_dir = Path("/tmp/obsbot_footage")

    def tearDown(self):
        self.load_config_patcher.stop()

    def test_video_only(self):
        """Test command when audio is disabled."""
        self.state.audio_enabled = False
        cmd = obsbot_capture.build_ffmpeg_cmd(self.state, "output.mp4")

        self.assertIn("-an", cmd)
        # Should only have one -f (v4l2), no alsa
        self.assertEqual(cmd.count("-f"), 1)
        self.assertNotIn("alsa", cmd)

    def test_video_audio(self):
        """Test command with audio enabled."""
        self.state.audio_enabled = True
        self.state.audio_device = "hw:2,0"
        cmd = obsbot_capture.build_ffmpeg_cmd(self.state, "output.mp4")

        self.assertNotIn("-an", cmd)
        self.assertIn("alsa", cmd)
        self.assertIn("hw:2,0", cmd)
        self.assertIn("-ac", cmd)
        # Should have two -f flags (v4l2 and alsa)
        self.assertEqual(cmd.count("-f"), 2)

    def test_muted(self):
        """Test command when audio is muted (should be no audio track)."""
        self.state.audio_muted = True
        cmd = obsbot_capture.build_ffmpeg_cmd(self.state, "output.mp4")

        self.assertIn("-an", cmd)
        self.assertNotIn("alsa", cmd)

    def test_gain_positive(self):
        """Test volume filter application."""
        self.state.mic_gain_db = 6.0
        cmd = obsbot_capture.build_ffmpeg_cmd(self.state, "output.mp4")

        # 6dB is approx 1.9953 linear
        # We look for -af volume=...
        self.assertIn("-af", cmd)
        af_idx = cmd.index("-af")
        volume_arg = cmd[af_idx + 1]
        self.assertTrue(volume_arg.startswith("volume="))
        val = float(volume_arg.split("=")[1])
        self.assertAlmostEqual(val, 1.9953, places=3)

    def test_prores_format(self):
        """Test ProRes codec selection."""
        # Find index for prores_hq
        idx = next(i for i, f in enumerate(obsbot_capture.OUTPUT_FORMATS) if f["key"] == "prores_hq")
        self.state.output_format_idx = idx

        cmd = obsbot_capture.build_ffmpeg_cmd(self.state, "output.mov")

        self.assertIn("prores_ks", cmd)
        self.assertIn("pcm_s24le", cmd)
        self.assertNotIn("libx264", cmd)

    def test_h264_format(self):
        """Test H.264 codec selection."""
        # Find index for h264_high
        idx = next(i for i, f in enumerate(obsbot_capture.OUTPUT_FORMATS) if f["key"] == "h264_high")
        self.state.output_format_idx = idx

        cmd = obsbot_capture.build_ffmpeg_cmd(self.state, "output.mp4")

        self.assertIn("libx264", cmd)
        self.assertIn("aac", cmd)
        self.assertNotIn("prores_ks", cmd)

if __name__ == "__main__":
    unittest.main()
