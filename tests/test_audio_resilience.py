
import unittest
from unittest.mock import patch
from obsbot_capture import detect_audio_device, CameraState, list_audio_devices

class TestAudioResilience(unittest.TestCase):
    @patch('subprocess.run')
    def test_detect_audio_device_missing_arecord(self, mock_run):
        mock_run.side_effect = FileNotFoundError("arecord not found")
        state = CameraState()

        # Should not raise exception
        detect_audio_device(state)

        self.assertIsNone(state.audio_device)
        self.assertFalse(state.audio_enabled)

    @patch('subprocess.run')
    def test_list_audio_devices_missing_arecord(self, mock_run):
        mock_run.side_effect = FileNotFoundError("arecord not found")

        # Should not raise exception
        result = list_audio_devices()

        self.assertIn("'arecord' not found", result)

if __name__ == '__main__':
    unittest.main()
