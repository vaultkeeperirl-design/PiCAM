import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# 1. Mock hardware/library modules BEFORE importing hat_ui
# We need to mock these to run the test on non-Pi hardware
sys.modules['RPi'] = MagicMock()
sys.modules['RPi.GPIO'] = MagicMock()
sys.modules['spidev'] = MagicMock()
sys.modules['cv2'] = MagicMock()
sys.modules['numpy'] = MagicMock()

# Mock PIL with enough structure to support Image.new, ImageDraw, etc.
mock_pil = MagicMock()
sys.modules['PIL'] = mock_pil
sys.modules['PIL.Image'] = mock_pil.Image
sys.modules['PIL.ImageDraw'] = mock_pil.ImageDraw
sys.modules['PIL.ImageFont'] = mock_pil.ImageFont

# Configure PIL mocks to return usable objects
mock_image = MagicMock()
mock_pil.Image.new.return_value = mock_image
mock_pil.Image.fromarray.return_value = mock_image
mock_image.resize.return_value = mock_image
mock_image.convert.return_value = mock_image
mock_image.copy.return_value = mock_image

# 2. Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 3. Import hat_ui (mocks active)
try:
    from hat_ui import HatUI, PAGES, OUTPUT_FORMATS
except ImportError:
    # Handle case where imports might fail during discovery if mocks aren't perfect
    HatUI = None

class TestHatUIRobustness(unittest.TestCase):
    def setUp(self):
        if HatUI is None:
            self.skipTest("hat_ui could not be imported")

        # Setup a mock state with "dangerous" None values
        self.state = MagicMock()
        self.state.device = "/dev/video0"
        self.state.recording = False
        self.state.clip_number = 1
        self.state.rec_timecode = "00:00:00:00"
        self.state.resolution = "3840x2160"
        self.state.fps = 30
        self.state.output_format_idx = 0
        self.state.format_label = "H.264 High"

        # Properties that might be None from bad config
        self.state.gain = None
        self.state.exposure = None
        self.state.wb_temp = None
        self.state.focus = None
        self.state.focus_max = 100
        self.state.focus_pct = 0 # Property usually handles None, but let's see
        self.state.shutter_angle = 180 # Property
        self.state.mic_gain_db = None

        self.state.audio_enabled = True
        self.state.audio_muted = False
        self.state.audio_levels = [0.0, 0.0]

        # Instantiate HatUI
        self.ui = HatUI(self.state)
        # Mock internal display/draw objects to avoid calls to real hardware methods
        self.ui.display = MagicMock()
        self.ui._draw = MagicMock()
        self.ui._canvas = MagicMock()

    def test_render_status_page_no_crash_on_none_values(self):
        """
        Verify that rendering the STATUS page does not crash if state values are None.
        This simulates a corrupted config file or initialization race condition.
        """
        # Set page to STATUS (index 1)
        self.ui._page = 1

        try:
            # This triggers _render_page -> _pg_status
            self.ui._render()
        except TypeError as e:
            self.fail(f"HatUI crashed on STATUS page with None values: {e}")
        except Exception as e:
            self.fail(f"HatUI crashed on STATUS page with unexpected error: {e}")

    def test_render_exposure_page_no_crash_on_none_values(self):
        """Verify EXPOSURE page robustness."""
        self.ui._page = 2 # EXPOSURE
        try:
            self.ui._render()
        except TypeError as e:
            self.fail(f"HatUI crashed on EXPOSURE page with None values: {e}")

    def test_render_audio_page_no_crash_on_none_values(self):
        """Verify AUDIO page robustness."""
        self.ui._page = 6 # AUDIO
        self.state.mic_gain_db = None # Explicitly set None
        try:
            self.ui._render()
        except TypeError as e:
            self.fail(f"HatUI crashed on AUDIO page with None values: {e}")

if __name__ == '__main__':
    unittest.main()
