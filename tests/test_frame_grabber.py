import unittest
from unittest.mock import MagicMock, patch
import sys
import os
import threading
import time

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import hat_ui (might be already imported by other tests, so we can't rely on sys.modules blocking)
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

        # Create mocks
        self.mock_image_cls = MagicMock()
        self.mock_draw_cls = MagicMock()
        self.mock_font_cls = MagicMock()
        self.mock_cv2 = MagicMock()

        # Setup standard mock behaviors
        self.mock_image = MagicMock()
        self.mock_image_cls.new.return_value = self.mock_image
        self.mock_image_cls.fromarray.return_value = self.mock_image
        self.mock_image.resize.return_value = self.mock_image
        self.mock_image.convert.return_value = self.mock_image
        self.mock_image.copy.return_value = self.mock_image

        self.mock_draw_instance = MagicMock()
        self.mock_draw_cls.Draw.return_value = self.mock_draw_instance

        # Mock cv2 constants and behaviors
        self.mock_cv2.CAP_V4L2 = 200
        self.mock_cv2.CAP_PROP_FRAME_WIDTH = 3
        self.mock_cv2.CAP_PROP_FRAME_HEIGHT = 4
        self.mock_cv2.CAP_PROP_FPS = 5
        self.mock_cv2.CAP_PROP_BUFFERSIZE = 38
        self.mock_cv2.COLOR_BGR2RGB = 4
        self.mock_cv2.VideoWriter_fourcc.return_value = 12345
        self.mock_cv2.cvtColor.return_value = MagicMock(shape=(100, 100, 3))

        # Patch dependencies directly in hat_ui module
        # create=True handles cases where the module failed to import optional deps originally
        self.patchers = [
            patch.object(hat_ui, 'Image', self.mock_image_cls, create=True),
            patch.object(hat_ui, 'ImageDraw', self.mock_draw_cls, create=True),
            patch.object(hat_ui, 'ImageFont', self.mock_font_cls, create=True),
            patch.object(hat_ui, 'cv2', self.mock_cv2, create=True),
            patch.object(hat_ui, 'CV2_OK', True, create=True),
            patch.object(hat_ui, 'PIL_OK', True, create=True),
        ]

        for p in self.patchers:
            p.start()

    def tearDown(self):
        for p in self.patchers:
            p.stop()

    def test_init_state(self):
        fg = FrameGrabber("/dev/video0")
        self.assertFalse(fg._fed)
        self.assertFalse(fg._ok)
        self.assertIsNotNone(fg._placeholder)

        # Verify placeholder creation used our mocks
        self.mock_image_cls.new.assert_called()
        self.mock_draw_cls.Draw.assert_called()
        self.mock_draw_instance.text.assert_called()

    def test_feed_frame_gui_mode(self):
        """
        Verify that feeding a frame externally (GUI mode) updates state
        and converts the image.
        """
        fg = FrameGrabber("/dev/video0")

        mock_frame = MagicMock()
        fg.feed_frame(mock_frame)

        self.assertTrue(fg._fed, "Should be marked as fed")
        self.assertTrue(fg._ok, "Should be marked as OK")
        self.assertIsNotNone(fg._frame, "Frame should be stored")

        # Verify conversions happened
        self.mock_cv2.cvtColor.assert_called_once()
        self.mock_image_cls.fromarray.assert_called_once()

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
        def sleep_side_effect(seconds):
            fg._stop.set()

        mock_sleep.side_effect = sleep_side_effect

        # Run the method
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

        # Make time.time return start + 20s to simulate timeout expiration
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
