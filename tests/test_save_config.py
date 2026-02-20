import unittest
from unittest.mock import patch, MagicMock, mock_open
import os
import sys
import json
from pathlib import Path

# Add project root to sys.path to import obsbot_capture
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import obsbot_capture

class TestSaveConfig(unittest.TestCase):
    def setUp(self):
        # Create a mock CameraState instance
        # We need to mock CONFIG_FILE.exists() and read_text() to initialize CameraState without errors
        with patch("pathlib.Path.exists", return_value=False):
            self.camera_state = obsbot_capture.CameraState()

    @patch("obsbot_capture.os.replace")
    @patch("obsbot_capture.os.fsync")
    @patch("obsbot_capture.os.fdopen")
    @patch("obsbot_capture.os.open")
    def test_save_config_atomic_secure(self, mock_os_open, mock_os_fdopen, mock_os_fsync, mock_os_replace):
        """
        Verify that save_config uses atomic write with secure permissions.
        """
        # Setup mocks
        mock_fd = 123
        mock_os_open.return_value = mock_fd

        mock_file_obj = MagicMock()
        mock_os_fdopen.return_value.__enter__.return_value = mock_file_obj

        # Call the method under test
        self.camera_state.save_config()

        # Verify os.open called with correct path, flags, and permissions (0o600)
        expected_temp_path = str(obsbot_capture.CONFIG_FILE) + ".tmp"
        mock_os_open.assert_called_once()
        args, kwargs = mock_os_open.call_args
        self.assertEqual(args[0], expected_temp_path)
        self.assertTrue(args[1] & os.O_WRONLY)
        self.assertTrue(args[1] & os.O_CREAT)
        self.assertEqual(args[2], 0o600)

        # Verify os.fdopen called with the file descriptor
        mock_os_fdopen.assert_called_once_with(mock_fd, 'w')

        # Verify data was written to the file object
        # json.dump writes to the file object. We can check write calls on the mock file object.
        self.assertTrue(mock_file_obj.write.called)

        # Verify flush and fsync were called
        mock_file_obj.flush.assert_called_once()
        mock_os_fsync.assert_called_once_with(mock_fd)

        # Verify atomic rename
        mock_os_replace.assert_called_once_with(expected_temp_path, obsbot_capture.CONFIG_FILE)

    @patch("builtins.print")
    @patch("obsbot_capture.os.open")
    def test_save_config_exception_handling(self, mock_os_open, mock_print):
        """
        Verify that exceptions during save are caught and logged.
        """
        # Simulate an OSError during open
        mock_os_open.side_effect = OSError("Disk full")

        # Call save_config, should not raise exception
        try:
            self.camera_state.save_config()
        except Exception as e:
            self.fail(f"save_config raised exception unexpectedly: {e}")

        # Verify error was logged
        mock_print.assert_called_with("[WARN] Failed to save config: Disk full")

if __name__ == "__main__":
    unittest.main()
