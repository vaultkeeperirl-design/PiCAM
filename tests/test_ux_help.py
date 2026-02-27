import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock cv2 before importing obsbot_capture
if "cv2" not in sys.modules:
    sys.modules["cv2"] = MagicMock()

# Ensure numpy is mocked if missing
if "numpy" not in sys.modules:
    sys.modules["numpy"] = MagicMock()

import obsbot_capture

class TestUXHelp(unittest.TestCase):
    def setUp(self):
        # Force CV2_OK to True
        self.original_cv2_ok = obsbot_capture.CV2_OK
        obsbot_capture.CV2_OK = True

        # Patch cv2 inside obsbot_capture
        self.cv2_patcher = patch('obsbot_capture.cv2')
        self.mock_cv2 = self.cv2_patcher.start()

        # Set constants
        self.mock_cv2.FONT_HERSHEY_SIMPLEX = 0
        self.mock_cv2.LINE_AA = 16

        # Configure getTextSize to return a dummy size (width, height) + baseline
        self.mock_cv2.getTextSize.return_value = ((100, 20), 5)
        # Mock addWeighted to just return the first image (simplified)
        self.mock_cv2.addWeighted.return_value = MagicMock()

        # Mock image
        self.img = MagicMock()
        self.img.copy.return_value = MagicMock()
        self.img.shape = (1080, 1920, 3)
        self.w = 1920
        self.h = 1080

        # State setup
        self.state = obsbot_capture.CameraState()

    def tearDown(self):
        obsbot_capture.CV2_OK = self.original_cv2_ok
        self.cv2_patcher.stop()

    def test_help_overlay_calls_drawing_functions(self):
        """Test that _draw_help calls cv2 drawing functions."""
        font = MagicMock()
        obsbot_capture._draw_help(self.img, self.w, self.h, font)

        # Check that rectangle is called (for background and border)
        self.assertTrue(self.mock_cv2.rectangle.called, "Should call rectangle")
        # Check that addWeighted is called (for transparency)
        self.assertTrue(self.mock_cv2.addWeighted.called, "Should call addWeighted")

    def test_help_overlay_content(self):
        """Test that new help text elements are drawn."""
        font = MagicMock()
        obsbot_capture._draw_help(self.img, self.w, self.h, font)

        # Collect all text passed to putText
        drawn_text = []
        for call in self.mock_cv2.putText.call_args_list:
            args, _ = call
            drawn_text.append(args[1])

        # Verify specific new elements
        self.assertIn("KEYBOARD SHORTCUTS", drawn_text, "Should display title")
        self.assertIn("CAMERA CONTROL", drawn_text, "Should display left header")
        self.assertIn("SYSTEM & TOOLS", drawn_text, "Should display right header")
        self.assertIn("Record / Stop", drawn_text, "Should display Record help text")
        self.assertIn("Press H to close", drawn_text, "Should display footer hint")

    def test_help_overlay_scaling(self):
        """Test that overlay scales for smaller screens."""
        font = MagicMock()
        # Test with 720p height (half res preview of 720p is 360, but let's test a case where scaling kicks in)
        # base_h is 540. If h is 270 (half of 540), scale should be 0.5.

        small_h = 270
        obsbot_capture._draw_help(self.img, 480, small_h, font)

        # We can't easily verify the scale factor directly without inspecting internal variables,
        # but we can verify that it runs without error.
        # Ideally we would check that the font size in putText calls is smaller.

        # In setup, font_head is 0.7 * scale. If scale is 0.5, font_head is 0.35.
        # Let's check the font scale of the title "KEYBOARD SHORTCUTS"

        found_title = False
        for call in self.mock_cv2.putText.call_args_list:
            args, _ = call
            text = args[1]
            font_scale = args[4]
            if text == "KEYBOARD SHORTCUTS":
                found_title = True
                self.assertLess(font_scale, 0.7, "Font scale should be reduced for small screen")
                break

        self.assertTrue(found_title, "Title should be drawn even on small screen")

if __name__ == "__main__":
    unittest.main()
