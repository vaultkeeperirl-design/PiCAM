import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
import sys
import os
import shutil

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import obsbot_capture

class TestStorageFragility(unittest.TestCase):

    @patch('shutil.disk_usage')
    @patch.object(Path, 'exists', return_value=True) # Mock Config File existence check
    @patch.object(Path, 'read_text', return_value="{}") # Mock Config File read
    def test_bitrate_parsing_robustness(self, mock_read, mock_exists, mock_disk_usage):
        """
        Demonstrate that changing the note format NO LONGER breaks bitrate estimation.
        """
        # Mock 100GB free space
        mock_disk_usage.return_value = (200 * 1024**3, 100 * 1024**3, 100 * 1024**3)

        state = obsbot_capture.CameraState()
        state.output_dir = MagicMock()
        state.output_dir.exists.return_value = True
        state.resolution = "3840x2160"

        # Force a specific format (h264_high which has est_mbps=50)
        state.output_format_idx = 0
        original_fmt = state.output_format

        # Verify initial state works
        # Expected: ~266 mins (100GB * 8000 / 50Mbps / 60)
        _, mins_ok = state.remaining_storage_info
        self.assertEqual(mins_ok, 266)

        # Store original values to restore later
        original_note = original_fmt.get("note")
        original_est = original_fmt.get("est_mbps")

        try:
            # Change the note to something completely unrelated
            original_fmt["note"] = "High Quality Filmora - No numbers here"

            # Recalculate - should still work because we rely on est_mbps
            _, mins_robust = state.remaining_storage_info
            self.assertEqual(mins_robust, 266)

            # Change est_mbps to 100 to verify it's being used
            original_fmt["est_mbps"] = 100
            _, mins_100 = state.remaining_storage_info
            # 100GB * 8000 / 100 / 60 = 133 mins
            self.assertEqual(mins_133 := 133, mins_100)

        finally:
            # Restore to avoid polluting other tests
            if original_note:
                original_fmt["note"] = original_note
            if original_est:
                original_fmt["est_mbps"] = original_est

if __name__ == "__main__":
    unittest.main()
