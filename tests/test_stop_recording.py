import unittest
from unittest.mock import MagicMock, patch
import subprocess
import sys
import os

# Mock modules that might not be available or need hardware
mock_cv2 = MagicMock()
sys.modules["cv2"] = mock_cv2
sys.modules["hat_ui"] = MagicMock()
sys.modules["rich"] = MagicMock()
sys.modules["rich.console"] = MagicMock()
sys.modules["rich.live"] = MagicMock()
sys.modules["rich.table"] = MagicMock()
sys.modules["rich.panel"] = MagicMock()
sys.modules["rich.text"] = MagicMock()
sys.modules["rich.layout"] = MagicMock()
sys.modules["rich.columns"] = MagicMock()
sys.modules["rich.box"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()

import obsbot_capture

class TestStopRecording(unittest.TestCase):
    def setUp(self):
        self.state = MagicMock(spec=obsbot_capture.CameraState)
        self.state.recording = True
        self.mock_ffmpeg = MagicMock()
        self.state.ffmpeg_proc = self.mock_ffmpeg
        self.state.clip_number = 1
        self.state.device = "/dev/video0"

    @patch('time.sleep', return_value=None)
    @patch('builtins.print')
    def test_stop_recording_graceful(self, mock_print, mock_sleep):
        # Setup: FFmpeg is running and exits gracefully
        self.mock_ffmpeg.poll.return_value = None # Running

        obsbot_capture.stop_recording(self.state)

        self.mock_ffmpeg.stdin.write.assert_called_with(b"q")
        self.mock_ffmpeg.stdin.flush.assert_called()
        self.mock_ffmpeg.wait.assert_called_with(timeout=10)
        self.assertFalse(self.state.recording)
        self.assertEqual(self.state.clip_number, 2)
        self.assertIsNone(self.state.ffmpeg_proc)
        mock_print.assert_any_call("[STOP] ■ Recording stopped.")

    @patch('time.sleep', return_value=None)
    @patch('builtins.print')
    def test_stop_recording_broken_pipe(self, mock_print, mock_sleep):
        # Setup: BrokenPipeError when writing 'q'
        self.mock_ffmpeg.poll.return_value = None
        self.mock_ffmpeg.stdin.write.side_effect = BrokenPipeError()

        obsbot_capture.stop_recording(self.state)

        # Should now log the warning
        mock_print.assert_any_call("[WARN] FFmpeg stdin broken (already exited?)")
        # Should still proceed to wait and eventually stop
        self.mock_ffmpeg.wait.assert_called_with(timeout=10)
        self.assertFalse(self.state.recording)
        mock_print.assert_any_call("[STOP] ■ Recording stopped.")

    @patch('time.sleep', return_value=None)
    @patch('builtins.print')
    def test_stop_recording_timeout(self, mock_print, mock_sleep):
        # Setup: TimeoutExpired when waiting (first time)
        self.mock_ffmpeg.poll.return_value = None
        self.mock_ffmpeg.wait.side_effect = [subprocess.TimeoutExpired(cmd="ffmpeg", timeout=10), 0]

        obsbot_capture.stop_recording(self.state)

        self.mock_ffmpeg.kill.assert_called()
        # It should call wait() again after kill()
        self.assertEqual(self.mock_ffmpeg.wait.call_count, 2)
        mock_print.assert_any_call("[WARN] FFmpeg timeout — killing")

    @patch('time.sleep', return_value=None)
    @patch('builtins.print')
    def test_stop_recording_exception_on_wait(self, mock_print, mock_sleep):
        # Setup: Generic Exception when waiting
        self.mock_ffmpeg.poll.return_value = None
        self.mock_ffmpeg.wait.side_effect = Exception("Some error")

        obsbot_capture.stop_recording(self.state)

        mock_print.assert_any_call("[WARN] Stop error: Some error")
        self.mock_ffmpeg.kill.assert_called()

    @patch('time.sleep', return_value=None)
    @patch('builtins.print')
    def test_stop_recording_exception_on_kill_logged(self, mock_print, mock_sleep):
        # Setup: Exception when killing after another exception
        self.mock_ffmpeg.poll.return_value = None
        self.mock_ffmpeg.wait.side_effect = Exception("First error")
        self.mock_ffmpeg.kill.side_effect = Exception("Kill error")

        obsbot_capture.stop_recording(self.state)

        mock_print.assert_any_call("[WARN] Stop error: First error")
        # Kill error should NOT be silenced anymore
        mock_print.assert_any_call("[ERROR] Failed to kill FFmpeg after stop error: Kill error")
        self.assertFalse(self.state.recording)

if __name__ == "__main__":
    unittest.main()
