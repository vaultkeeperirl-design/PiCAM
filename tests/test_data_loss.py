import unittest
import tempfile
import shutil
import os
import datetime
from pathlib import Path
import sys

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from obsbot_capture import CameraState

class TestDataLoss(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.state = CameraState()
        self.state.output_dir = Path(self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_clip_number_collision(self):
        # 1. Create a dummy file that simulates an existing recording from today
        today_str = datetime.datetime.now().strftime("%Y%m%d")
        existing_file = Path(self.test_dir) / f"CLIP_{today_str}_0001.mp4"
        existing_file.touch()

        # 2. Call the new method to refresh clip number
        self.state.refresh_clip_number()

        # 3. Verify that CameraState now safely starts at 2
        self.assertEqual(self.state.clip_number, 2, "CameraState should increment to 2 to avoid collision")

if __name__ == '__main__':
    unittest.main()
