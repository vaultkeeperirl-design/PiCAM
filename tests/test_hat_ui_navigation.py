import unittest
from unittest.mock import MagicMock
import sys
import os

# 1. Mock hardware/library modules BEFORE importing hat_ui
sys.modules['RPi'] = MagicMock()
sys.modules['RPi.GPIO'] = MagicMock()
sys.modules['spidev'] = MagicMock()
sys.modules['cv2'] = MagicMock()
sys.modules['numpy'] = MagicMock()
sys.modules['PIL'] = MagicMock()
sys.modules['PIL.Image'] = MagicMock()
sys.modules['PIL.ImageDraw'] = MagicMock()
sys.modules['PIL.ImageFont'] = MagicMock()

# 2. Add project root to path so we can import hat_ui
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 3. Import hat_ui (now using mocks)
from hat_ui import HatUI, PIN_JOY_RIGHT

class TestHatUINavigation(unittest.TestCase):
    def test_joy_right_increments_page(self):
        """Verify JOY_RIGHT moves to the next page."""
        # Setup mock state
        state = MagicMock()
        state.device = "/dev/video0"

        # Instantiate HatUI
        # Note: __init__ relies on imports which are now mocked
        ui = HatUI(state)

        # Inject a mock input handler (bypass real GPIO init)
        ui.inp = MagicMock()

        # Initial page is 1 (STATUS)
        ui._page = 1

        # Mock input to return JOY_RIGHT press
        ui.inp.get_events.return_value = [(PIN_JOY_RIGHT, 'press')]

        # Trigger input handling manually
        ui._handle_input()

        # Assert page incremented to 2
        self.assertEqual(ui._page, 2, "JOY_RIGHT should increment page index")

if __name__ == '__main__':
    unittest.main()
