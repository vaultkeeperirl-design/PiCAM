import unittest
from unittest.mock import patch
import json
from pathlib import Path

# Add project root to sys.path to import obsbot_capture
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import obsbot_capture

class TestConfigLoading(unittest.TestCase):
    def setUp(self):
        # Prevent actual file I/O
        self.mock_exists_patcher = patch.object(Path, 'exists', return_value=True)
        self.mock_exists = self.mock_exists_patcher.start()

        self.mock_read_patcher = patch.object(Path, 'read_text')
        self.mock_read = self.mock_read_patcher.start()

    def tearDown(self):
        self.mock_exists_patcher.stop()
        self.mock_read_patcher.stop()

    def test_json_decode_error(self):
        """
        Verify that a JSONDecodeError (corrupt config) is caught gracefully,
        preventing a crash, and allowing the application to use defaults.
        """
        self.mock_read.side_effect = json.JSONDecodeError("Expecting value", "doc", 0)

        # Should not raise exception
        try:
            obsbot_capture.CameraState()
        except json.JSONDecodeError:
            self.fail("CameraState() raised JSONDecodeError unexpectedly!")
        except Exception as e:
            self.fail(f"CameraState() raised unexpected exception: {e}")

    def test_os_error(self):
        """
        Verify that an OSError (e.g. PermissionError) is caught gracefully,
        allowing the application to use defaults.
        """
        self.mock_read.side_effect = PermissionError("Permission denied")

        # Should not raise exception
        try:
            obsbot_capture.CameraState()
        except PermissionError:
            self.fail("CameraState() raised PermissionError unexpectedly!")
        except Exception as e:
            self.fail(f"CameraState() raised unexpected exception: {e}")

    def test_unexpected_error(self):
        """
        Verify that an unexpected error (e.g. RuntimeError) is NOT caught.
        This confirms we are no longer using a bare 'except:' clause.
        """
        self.mock_read.side_effect = RuntimeError("Something bad happened")

        with self.assertRaises(RuntimeError):
            obsbot_capture.CameraState()

if __name__ == "__main__":
    unittest.main()
