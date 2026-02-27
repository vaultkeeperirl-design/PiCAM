import sys
import unittest
import importlib
from unittest.mock import MagicMock

# Define mocks globally so they persist
mock_cv2 = MagicMock()
mock_numpy = MagicMock()
mock_sd = MagicMock()
mock_hat = MagicMock()

sys.modules["cv2"] = mock_cv2
sys.modules["numpy"] = mock_numpy
sys.modules["sounddevice"] = mock_sd
sys.modules["hat_ui"] = mock_hat

# We must import obsbot_capture AFTER mocking
# If it was already imported, we must reload it to ensure it sees the mocks and sets CV2_OK = True
try:
    import obsbot_capture
    importlib.reload(obsbot_capture)
except ImportError:
    # If not in path, try adding current dir
    sys.path.append(".")
    import obsbot_capture
    importlib.reload(obsbot_capture)

class TestPerfOpt(unittest.TestCase):
    def setUp(self):
        # Reset mocks
        obsbot_capture.cv2.reset_mock()
        obsbot_capture.cv2.cvtColor.side_effect = None

        # 1. Mock calcHist for _apply_focus_peaking
        mock_hist = MagicMock()
        mock_hist.__getitem__.side_effect = lambda i: [10]
        # Ensure flatten().astype(int) returns a Mock
        mock_hist.flatten.return_value.astype.return_value = MagicMock()

        obsbot_capture.cv2.calcHist.return_value = mock_hist

        # 2. Mock threshold for _apply_focus_peaking
        obsbot_capture.cv2.threshold.return_value = (None, MagicMock())

    def test_apply_focus_peaking_calls_cvtColor_when_gray_is_none(self):
        frame = MagicMock()
        frame.shape = (1080, 1920, 3)
        obsbot_capture._apply_focus_peaking(frame, gray=None)
        obsbot_capture.cv2.cvtColor.assert_called_once()

    def test_apply_focus_peaking_skips_cvtColor_when_gray_is_provided(self):
        frame = MagicMock()
        frame.shape = (1080, 1920, 3)
        gray = MagicMock()
        obsbot_capture._apply_focus_peaking(frame, gray=gray)
        obsbot_capture.cv2.cvtColor.assert_not_called()

    def test_draw_histogram_calls_cvtColor_when_gray_is_none(self):
        img = MagicMock()
        img.shape = (1080, 1920, 3)
        w, h = 1920, 1080
        obsbot_capture._draw_histogram(img, w, h, gray=None)
        obsbot_capture.cv2.cvtColor.assert_called_once()

    def test_draw_histogram_skips_cvtColor_when_gray_is_provided(self):
        img = MagicMock()
        img.shape = (1080, 1920, 3)
        gray = MagicMock()
        w, h = 1920, 1080
        obsbot_capture._draw_histogram(img, w, h, gray=gray)
        obsbot_capture.cv2.cvtColor.assert_not_called()

if __name__ == '__main__':
    unittest.main()
