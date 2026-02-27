import unittest
from unittest.mock import MagicMock, patch
import subprocess
import os
import sys

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import obsbot_capture

class TestStopRecordingResilience(unittest.TestCase):
    def setUp(self):
        # Patch CameraState dependencies to avoid side effects
        self.load_config_patcher = patch.object(obsbot_capture.CameraState, 'load_config')
        self.mock_load_config = self.load_config_patcher.start()

        # Mock cv2 to avoid ImportError handling issues and to supply constants
        self.cv2_patcher = patch.object(obsbot_capture, 'cv2', create=True)
        self.mock_cv2 = self.cv2_patcher.start()
        self.mock_cv2.CAP_V4L2 = 200

        # Ensure CV2_OK is True so code paths using cv2 are taken
        self.cv2_ok_patcher = patch.object(obsbot_capture, 'CV2_OK', True)
        self.cv2_ok_patcher.start()

        self.state = obsbot_capture.CameraState()
        self.state.recording = True
        self.state.ffmpeg_proc = MagicMock()
        self.state.ffmpeg_proc.poll.return_value = None  # Process is running

        # Mock dependencies
        self.mock_cap = MagicMock()

    def tearDown(self):
        self.cv2_ok_patcher.stop()
        self.cv2_patcher.stop()
        self.load_config_patcher.stop()

    def test_stop_recording_handles_timeout(self):
        """
        Verify that if FFmpeg does not exit gracefully within the timeout,
        it is forcibly killed.
        """
        # Arrange
        # First call to wait() raises TimeoutExpired, second call returns None
        self.state.ffmpeg_proc.wait.side_effect = [
            subprocess.TimeoutExpired(cmd='ffmpeg', timeout=10),
            None
        ]

        # Keep a reference to the mock process before it's cleared from state
        mock_proc = self.state.ffmpeg_proc

        # Act
        obsbot_capture.stop_recording(self.state, cap=self.mock_cap)

        # Assert
        # 1. Graceful quit attempted
        mock_proc.stdin.write.assert_called_with(b"q")

        # 2. wait() called with timeout first
        mock_proc.wait.assert_any_call(timeout=10)

        # 3. kill() called
        mock_proc.kill.assert_called_once()

        # 4. State cleanup happened
        self.assertFalse(self.state.recording)
        self.assertIsNone(self.state.ffmpeg_proc)

        # 5. Camera reopened
        self.mock_cap.open.assert_called()

    def test_stop_recording_handles_generic_exception(self):
        """
        Verify that if an unexpected error occurs during stop (e.g. pipe error),
        the process is forcibly killed to ensure cleanup.
        """
        # Arrange
        # Simulate an error during the graceful shutdown attempt
        self.state.ffmpeg_proc.stdin.write.side_effect = OSError("Pipe error")

        # Keep a reference to the mock process before it's cleared from state
        mock_proc = self.state.ffmpeg_proc

        # Act
        obsbot_capture.stop_recording(self.state, cap=self.mock_cap)

        # Assert
        # kill() should be called in the except block
        mock_proc.kill.assert_called_once()

        # State cleanup should still happen
        self.assertFalse(self.state.recording)
        self.assertIsNone(self.state.ffmpeg_proc)

        # Camera reopened
        self.mock_cap.open.assert_called()

if __name__ == "__main__":
    unittest.main()
