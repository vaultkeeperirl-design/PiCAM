import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
import sys
import os

# Add project root to sys.path to import obsbot_capture
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import obsbot_capture

class TestStorageCalculation(unittest.TestCase):
    def setUp(self):
        # Prevent actual file I/O for config loading
        self.mock_exists_patcher = patch.object(Path, 'exists', return_value=False)
        self.mock_exists = self.mock_exists_patcher.start()

        self.mock_read_patcher = patch.object(Path, 'read_text')
        self.mock_read = self.mock_read_patcher.start()

    def tearDown(self):
        self.mock_exists_patcher.stop()
        self.mock_read_patcher.stop()

    @patch('shutil.disk_usage')
    def test_remaining_storage_4k(self, mock_disk_usage):
        """
        Verify storage calculation for 4K resolution.
        """
        # Mock 100GB free space
        # disk_usage returns (total, used, free)
        mock_disk_usage.return_value = (200 * 1024**3, 100 * 1024**3, 100 * 1024**3)

        state = obsbot_capture.CameraState()

        # Override output_dir with a MagicMock that exists
        state.output_dir = MagicMock()
        state.output_dir.exists.return_value = True
        state.output_dir.__str__.return_value = "/tmp/fake_storage"

        state.resolution = "3840x2160"

        # Manually set output format to something predictable (h264_high)
        # Check obsbot_capture.OUTPUT_FORMATS[0] is h264_high (~50Mbps)
        state.output_format_idx = 0

        # Verify assumptions about the format note
        fmt = state.output_format
        self.assertIn("50Mbps", fmt["note"])

        free_gb, mins = state.remaining_storage_info

        # Check free space calculation (100GB)
        self.assertAlmostEqual(free_gb, 100.0)

        # Calculation:
        # mbps = 50 (from note)
        # mins = (100 * 8000 / 50) / 60
        #      = (16000) / 60
        #      = 266.66... -> int(266)
        self.assertEqual(mins, 266)

    @patch('shutil.disk_usage')
    def test_remaining_storage_1080p(self, mock_disk_usage):
        """
        Verify storage calculation for 1080p resolution (halves bitrate).
        """
        # Mock 100GB free space
        mock_disk_usage.return_value = (100 * 1024**3, 0, 100 * 1024**3)

        state = obsbot_capture.CameraState()

        state.output_dir = MagicMock()
        state.output_dir.exists.return_value = True
        state.output_dir.__str__.return_value = "/tmp/fake_storage"

        state.resolution = "1920x1080"
        state.output_format_idx = 0 # 50Mbps base

        # 1080p logic: mbps = max(1, 50 // 2) = 25
        # mins = (100 * 8000 / 25) / 60
        #      = 32000 / 60
        #      = 533.33... -> int(533)

        free_gb, mins = state.remaining_storage_info
        self.assertEqual(mins, 533)

    @patch('shutil.disk_usage')
    def test_disk_usage_error(self, mock_disk_usage):
        """
        Verify graceful failure if disk usage check fails.
        """
        mock_disk_usage.side_effect = OSError("Disk error")

        state = obsbot_capture.CameraState()
        state.output_dir = MagicMock()
        state.output_dir.exists.return_value = True
        state.output_dir.__str__.return_value = "/tmp/fake_storage"

        free_gb, mins = state.remaining_storage_info

        self.assertEqual(free_gb, 0)
        self.assertEqual(mins, 0)

    def test_output_dir_not_exist(self):
        """
        Verify (0,0) is returned if output directory does not exist.
        """
        state = obsbot_capture.CameraState()

        # Explicitly mock output_dir.exists to return False
        state.output_dir = MagicMock()
        state.output_dir.exists.return_value = False

        free_gb, mins = state.remaining_storage_info
        self.assertEqual(free_gb, 0)
        self.assertEqual(mins, 0)

if __name__ == "__main__":
    unittest.main()
