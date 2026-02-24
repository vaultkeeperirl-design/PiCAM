import unittest
from unittest.mock import MagicMock, patch
import sys
import os
import math

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock cv2 before importing obsbot_capture to avoid ImportError if not installed
if "cv2" not in sys.modules:
    sys.modules["cv2"] = MagicMock()

# Ensure numpy is mocked if missing, and configure it
if "numpy" not in sys.modules:
    sys.modules["numpy"] = MagicMock()

# Configure the numpy mock (whether newly created or from another test)
mock_np = sys.modules["numpy"]
if isinstance(mock_np, MagicMock):
    def log10_side_effect(x):
        if isinstance(x, (int, float)):
            return math.log10(x)
        return [math.log10(v) for v in x]
    mock_np.log10.side_effect = log10_side_effect

import obsbot_capture

class TestUXAudio(unittest.TestCase):
    def setUp(self):
        # Force CV2_OK to True
        self.original_cv2_ok = obsbot_capture.CV2_OK
        obsbot_capture.CV2_OK = True

        # Patch cv2 inside obsbot_capture to capture calls
        self.cv2_patcher = patch('obsbot_capture.cv2')
        self.mock_cv2 = self.cv2_patcher.start()

        # Set constants
        self.mock_cv2.FONT_HERSHEY_SIMPLEX = 0
        self.mock_cv2.LINE_AA = 16

        # Ensure NP_OK is True
        self.original_np_ok = obsbot_capture.NP_OK
        obsbot_capture.NP_OK = True

        # If obsbot_capture didn't import numpy (because it wasn't there),
        # it won't have 'np' attribute. We need to set it if missing.
        if not hasattr(obsbot_capture, 'np'):
            obsbot_capture.np = sys.modules["numpy"]

        # Also ensure the np used by obsbot_capture is configured correctly
        # In case obsbot_capture imported a DIFFERENT mock object (unlikely if sys.modules used)
        if isinstance(obsbot_capture.np, MagicMock):
             obsbot_capture.np.log10.side_effect = log10_side_effect

        self.state = obsbot_capture.CameraState()
        self.state.audio_levels = [0.0, 0.0]
        self.state.audio_peaks = [0.0, 0.0]
        self.state.audio_muted = False

        self.img = MagicMock()
        self.w = 100
        self.h = 100

    def tearDown(self):
        obsbot_capture.CV2_OK = self.original_cv2_ok
        obsbot_capture.NP_OK = self.original_np_ok
        self.cv2_patcher.stop()

    def test_audio_meter_no_clip(self):
        """Test that normal audio levels do NOT trigger 'CLIP' text."""
        # 0.1 linear ~= -20dB. Should be green/safe.
        self.state.audio_levels = [0.1, 0.1]

        obsbot_capture._draw_audio_meters(self.img, self.w, self.h, self.state)

        # Iterate over calls to putText
        for call in self.mock_cv2.putText.call_args_list:
            args, _ = call
            text = args[1]
            self.assertNotEqual(text, "CLIP", f"Found unexpected 'CLIP' text in putText call: {args}")

    def test_audio_meter_clip(self):
        """Test that high audio levels trigger 'CLIP' text."""
        # 0.8 linear ~= -1.9dB. Should be red/clipping.
        self.state.audio_levels = [0.8, 0.8]

        obsbot_capture._draw_audio_meters(self.img, self.w, self.h, self.state)

        found_clip = False
        for call in self.mock_cv2.putText.call_args_list:
            args, _ = call
            text = args[1]
            if text == "CLIP":
                found_clip = True
                break

        self.assertTrue(found_clip, "Expected 'CLIP' text to be drawn for high audio levels")

if __name__ == "__main__":
    unittest.main()
