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

    @patch('shutil.disk_usage')
    def test_output_dir_fallback(self, mock_disk_usage):
        """
        Verify storage info is calculated using parent directory if output_dir missing.
        """
        # 50GB free
        mock_disk_usage.return_value = (100 * 1024**3, 50 * 1024**3, 50 * 1024**3)

        state = obsbot_capture.CameraState()

        # We need output_dir.exists() -> False
        # But output_dir.parent.exists() -> True
        mock_out = MagicMock()
        mock_out.exists.return_value = False
        mock_out.__str__.return_value = "/tmp/missing"

        mock_parent = MagicMock()
        mock_parent.exists.return_value = True
        mock_parent.__str__.return_value = "/tmp"
        # Prevent infinite recursion in parent traversal
        mock_parent.parent = mock_parent

        mock_out.parent = mock_parent
        state.output_dir = mock_out

        # Use 50Mbps format
        state.output_format_idx = 0

        free_gb, mins = state.remaining_storage_info

        # Should use parent's disk usage (50GB free)
        self.assertEqual(free_gb, 50.0)
        # 50GB * 8000 / 50Mbps / 60 = 133.33 -> 133
        self.assertEqual(mins, 133)
        # Verify it checked the parent path
        mock_disk_usage.assert_called_with("/tmp")

    def test_storage_fails_if_no_parent_exists(self):
        """
        Verify (0,0) is returned if neither output dir nor parents exist.
        """
        state = obsbot_capture.CameraState()

        # output_dir and its parent both fail exists()
        mock_out = MagicMock()
        mock_out.exists.return_value = False
        mock_out.parent = mock_out # simulating root that doesn't exist
        state.output_dir = mock_out

        free_gb, mins = state.remaining_storage_info
        self.assertEqual(free_gb, 0)
        self.assertEqual(mins, 0)

if __name__ == "__main__":
    unittest.main()
