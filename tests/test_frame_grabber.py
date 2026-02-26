import unittest
from unittest.mock import MagicMock, patch
import sys
import os
import threading
import time

# 1. Mock hardware/library modules BEFORE importing hat_ui
sys.modules['RPi'] = MagicMock()
sys.modules['RPi.GPIO'] = MagicMock()
sys.modules['spidev'] = MagicMock()
sys.modules['cv2'] = MagicMock()
sys.modules['numpy'] = MagicMock()

# Mock PIL
mock_pil = MagicMock()
sys.modules['PIL'] = mock_pil
sys.modules['PIL.Image'] = mock_pil.Image
sys.modules['PIL.ImageDraw'] = mock_pil.ImageDraw
sys.modules['PIL.ImageFont'] = mock_pil.ImageFont

# Configure PIL mocks
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
    import hat_ui
    from hat_ui import FrameGrabber
except ImportError:
    FrameGrabber = None
    hat_ui = None

class TestFrameGrabber(unittest.TestCase):
    def setUp(self):
        if FrameGrabber is None:
            self.skipTest("hat_ui could not be imported")

        # Explicitly set PIL objects in hat_ui namespace if they are missing
        # This fixes NameError: name 'Image' is not defined inside hat_ui methods
        if not hasattr(hat_ui, 'Image'):
            hat_ui.Image = mock_pil.Image
        if not hasattr(hat_ui, 'ImageDraw'):
            hat_ui.ImageDraw = mock_pil.ImageDraw
        if not hasattr(hat_ui, 'ImageFont'):
            hat_ui.ImageFont = mock_pil.ImageFont

        # Configure font.getmask2 return value to fix unpack error
        # ImageDraw.text calls draw_text -> font.getmask2 which expects (mask, offset)
        mock_font = MagicMock()
        mock_font.getmask2.return_value = (MagicMock(), (0, 0))
        mock_pil.ImageFont.load_default.return_value = mock_font
        mock_pil.ImageFont.truetype.return_value = mock_font

        # Explicitly inject cv2 and force CV2_OK to True
        # This ensures FrameGrabber logic (which checks CV2_OK) runs
        hat_ui.cv2 = sys.modules['cv2']
        hat_ui.CV2_OK = True

        # Reset CV2 mock for each test
        self.mock_cv2 = sys.modules['cv2']
        self.mock_cv2.reset_mock()

        # Mock constants usually found in cv2
        self.mock_cv2.CAP_V4L2 = 200
        self.mock_cv2.CAP_PROP_FRAME_WIDTH = 3
        self.mock_cv2.CAP_PROP_FRAME_HEIGHT = 4
        self.mock_cv2.CAP_PROP_FPS = 5
        self.mock_cv2.CAP_PROP_BUFFERSIZE = 38
        self.mock_cv2.COLOR_BGR2RGB = 4
        self.mock_cv2.VideoWriter_fourcc.return_value = 12345

    def test_init_state(self):
        fg = FrameGrabber("/dev/video0")
        self.assertFalse(fg._fed)
        self.assertFalse(fg._ok)
        self.assertIsNotNone(fg._placeholder)

    def test_feed_frame_gui_mode(self):
        """
        Verify that feeding a frame externally (GUI mode) updates state
        and converts the image.
        """
        fg = FrameGrabber("/dev/video0")

        mock_frame = MagicMock() # numpy array mock
        # mock cvtColor to return something valid (dummy numpy array behavior)
        self.mock_cv2.cvtColor.return_value = MagicMock(shape=(100, 100, 3))

        fg.feed_frame(mock_frame)

        self.assertTrue(fg._fed, "Should be marked as fed")
        self.assertTrue(fg._ok, "Should be marked as OK")
        self.assertIsNotNone(fg._frame, "Frame should be stored")

        # Verify conversions happened
        self.mock_cv2.cvtColor.assert_called_once()
        # Ensure we are checking calls on the EXACT object hat_ui is using
        hat_ui.Image.fromarray.assert_called_once()

    @patch('time.time')
    @patch('time.sleep')
    def test_run_gui_mode_passive(self, mock_sleep, mock_time):
        """
        If _fed is True, _run should loop idly and NOT open VideoCapture.
        """
        fg = FrameGrabber("/dev/video0")
        fg._fed = True

        # Setup time.time to be within deadline initially
        mock_time.return_value = 1000.0

        # Side effect for sleep: stop the thread to break the infinite loop
        # The loop we want to break is: while not self._stop.is_set(): time.sleep(0.1)
        def sleep_side_effect(seconds):
            fg._stop.set()

        mock_sleep.side_effect = sleep_side_effect

        # Run the method (not in a separate thread, blocking call)
        fg._run()

        # Verify VideoCapture was NOT called
        self.mock_cv2.VideoCapture.assert_not_called()

    @patch('time.time')
    @patch('time.sleep')
    def test_run_headless_mode_active(self, mock_sleep, mock_time):
        """
        If _fed is False and timeout expires, _run should open VideoCapture.
        """
        fg = FrameGrabber("/dev/video0")
        fg._fed = False

        # Make time.time return start + 20s to simulate timeout expiration immediately
        # 1. deadline calc: time.time() (1000) -> deadline = 1015
        # 2. while check: time.time() (1020) -> loop terminates
        mock_time.side_effect = [1000.0, 1020.0, 1021.0, 1022.0]

        # Mock VideoCapture
        mock_cap = MagicMock()
        self.mock_cv2.VideoCapture.return_value = mock_cap
        mock_cap.isOpened.return_value = True

        # Mock read() to stop the loop after one frame
        def read_side_effect():
            fg._stop.set() # Stop after first read
            return True, MagicMock()

        mock_cap.read.side_effect = read_side_effect

        # Run
        fg._run()

        # Verify VideoCapture WAS called
        self.mock_cv2.VideoCapture.assert_called_with("/dev/video0", self.mock_cv2.CAP_V4L2)

        # Verify settings applied
        mock_cap.set.assert_any_call(self.mock_cv2.CAP_PROP_FRAME_WIDTH, 320)

        # Verify cleanup
        mock_cap.release.assert_called()

if __name__ == '__main__':
    unittest.main()
