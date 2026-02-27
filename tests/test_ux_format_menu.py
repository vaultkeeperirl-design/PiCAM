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

class TestUXFormatMenu(unittest.TestCase):
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

        # Mock image
        self.img = MagicMock()
        self.w = 1920
        self.h = 1080

        # State setup
        self.state = obsbot_capture.CameraState()
        self.state.output_format_idx = 0 # Select first item

    def tearDown(self):
        obsbot_capture.CV2_OK = self.original_cv2_ok
        self.cv2_patcher.stop()

    def test_format_menu_draws_items(self):
        """Test that format menu draws all items."""
        obsbot_capture._draw_format_menu(self.img, self.w, self.h, self.state)

        # Check that putText was called for each format label
        labels_found = 0
        for call in self.mock_cv2.putText.call_args_list:
            args, _ = call
            text = args[1]
            if text in [fmt["label"] for fmt in obsbot_capture.OUTPUT_FORMATS]:
                labels_found += 1

        self.assertEqual(labels_found, len(obsbot_capture.OUTPUT_FORMATS),
                         "Should draw all format labels")

    def test_format_menu_selection_highlight(self):
        """Test that the selection indicator '>' is GONE and we use a highlight bar instead."""
        # Select the second item
        self.state.output_format_idx = 1

        obsbot_capture._draw_format_menu(self.img, self.w, self.h, self.state)

        # Check that '>' is NOT drawn
        indicator_found = False
        for call in self.mock_cv2.putText.call_args_list:
            args, _ = call
            text = args[1]
            if text == ">":
                indicator_found = True
                break

        self.assertFalse(indicator_found, "Should NOT draw '>' selection indicator anymore")

        # Verify we draw 3 rectangles: Background, Highlight Bar, Border
        # (Original code drew 2)
        rect_calls = self.mock_cv2.rectangle.call_count
        self.assertEqual(rect_calls, 3, "Should draw 3 rectangles (bg, highlight, border)")

if __name__ == "__main__":
    unittest.main()
