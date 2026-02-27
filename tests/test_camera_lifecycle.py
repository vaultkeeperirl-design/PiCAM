import unittest
from unittest.mock import patch, MagicMock
import os
import sys
import subprocess
from pathlib import Path

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import obsbot_capture

class TestCameraLifecycle(unittest.TestCase):
    def setUp(self):
        # Patch CameraState dependencies
        self.load_config_patcher = patch.object(obsbot_capture.CameraState, 'load_config')
        self.mock_load_config = self.load_config_patcher.start()

        # Mock cv2 in obsbot_capture module
        self.cv2_patcher = patch.object(obsbot_capture, 'cv2', create=True)
        self.mock_cv2 = self.cv2_patcher.start()
        self.mock_cv2.CAP_V4L2 = 200  # Mock constant

        self.cv2_ok_patcher = patch.object(obsbot_capture, 'CV2_OK', True)
        self.cv2_ok_patcher.start()

        # Create CameraState instance
        self.state = obsbot_capture.CameraState()
        self.state.device = "/dev/video0"
        self.state.output_dir = MagicMock(spec=Path)
        self.state.output_dir.exists.return_value = True
        self.state.output_dir.__truediv__.return_value = Path("/tmp/obsbot_footage/clip.mp4")
        self.state.output_dir.mkdir = MagicMock()

        # Mock dependencies for start/stop_recording
        self.mock_cap = MagicMock()

    def tearDown(self):
        self.cv2_ok_patcher.stop()
        self.cv2_patcher.stop()
        self.load_config_patcher.stop()

    @patch("obsbot_capture.subprocess.Popen")
    def test_start_recording_success(self, mock_popen):
        """Test successful recording start."""
        # Setup mock process
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # Process running
        mock_popen.return_value = mock_proc

        # Call start_recording
        result = obsbot_capture.start_recording(self.state, cap=self.mock_cap)

        # Verify
        self.assertTrue(result)
        self.assertTrue(self.state.recording)
        self.assertIsNotNone(self.state.rec_start)
        self.assertEqual(self.state.ffmpeg_proc, mock_proc)

        # Verify cap release
        self.mock_cap.release.assert_called_once()

        # Verify output directory created
        self.state.output_dir.mkdir.assert_called_with(parents=True, exist_ok=True)

    @patch("obsbot_capture.subprocess.Popen")
    def test_start_recording_failure_immediate_exit(self, mock_popen):
        """Test recording start failure (process exits immediately)."""
        # Setup mock process that exits immediately
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1  # Process exited with error
        mock_proc.returncode = 1
        mock_popen.return_value = mock_proc

        # Call start_recording
        result = obsbot_capture.start_recording(self.state, cap=self.mock_cap)

        # Verify
        self.assertFalse(result)
        self.assertFalse(self.state.recording)
        self.assertIsNone(self.state.ffmpeg_proc)

    @patch("obsbot_capture.subprocess.Popen")
    def test_double_start_prevention(self, mock_popen):
        """Test that start_recording returns False if already recording."""
        self.state.recording = True

        result = obsbot_capture.start_recording(self.state, cap=self.mock_cap)

        self.assertFalse(result)
        mock_popen.assert_not_called()

    def test_stop_recording_success(self):
        """Test successful recording stop."""
        # Setup state as if recording
        self.state.recording = True
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None # Running
        self.state.ffmpeg_proc = mock_proc
        self.state.rec_start = 12345.0
        initial_clip = self.state.clip_number

        # Call stop_recording
        obsbot_capture.stop_recording(self.state, cap=self.mock_cap)

        # Verify process interaction
        mock_proc.stdin.write.assert_called_with(b"q")
        mock_proc.stdin.flush.assert_called()
        mock_proc.wait.assert_called()

        # Verify state update
        self.assertFalse(self.state.recording)
        self.assertIsNone(self.state.rec_start)
        self.assertEqual(self.state.clip_number, initial_clip + 1)
        self.assertIsNone(self.state.ffmpeg_proc)

        # Verify cap reopen
        self.mock_cap.open.assert_called_with(self.state.device, obsbot_capture.cv2.CAP_V4L2)

    def test_stop_recording_not_recording(self):
        """Test stop_recording does nothing if not recording."""
        self.state.recording = False
        self.state.ffmpeg_proc = None

        obsbot_capture.stop_recording(self.state, cap=self.mock_cap)

        self.mock_cap.open.assert_not_called()

    def test_stop_recording_process_already_dead(self):
        """Test stop_recording handles process already dead."""
        self.state.recording = True
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1 # Dead
        mock_proc.returncode = 1
        self.state.ffmpeg_proc = mock_proc

        obsbot_capture.stop_recording(self.state, cap=self.mock_cap)

        # Verify no attempt to write to stdin
        mock_proc.stdin.write.assert_not_called()

        # State should still clean up
        self.assertFalse(self.state.recording)
        self.assertIsNone(self.state.ffmpeg_proc)
        self.mock_cap.open.assert_called()

    @patch("obsbot_capture.subprocess.Popen")
    @patch("obsbot_capture.open")
    def test_start_recording_headless(self, mock_open, mock_popen):
        """Test recording start in headless mode (redirect stderr to file)."""
        # Setup headless mode
        self.state.mode = "headless"

        # Mock successful file open
        mock_file = MagicMock()
        mock_open.return_value = mock_file

        # Mock successful process
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        # Call start_recording
        result = obsbot_capture.start_recording(self.state, cap=self.mock_cap)

        # Verify
        self.assertTrue(result)

        # Verify log file opened
        log_path = self.state.output_dir / "ffmpeg.log"
        mock_open.assert_called_with(log_path, "a")

        # Verify log written
        mock_file.write.assert_called()
        mock_file.flush.assert_called()

        # Verify Popen called with file as stderr
        mock_popen.assert_called()
        args, kwargs = mock_popen.call_args
        self.assertEqual(kwargs['stderr'], mock_file)

        # Verify file closed
        mock_file.close.assert_called()

if __name__ == "__main__":
    unittest.main()
