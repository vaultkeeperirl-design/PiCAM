## 2026-02-20 - [Risky Storage Estimation Logic]

**Learning:** Critical storage estimation logic in `CameraState.remaining_storage_info` relies on parsing unstructured text from `OUTPUT_FORMATS` "note" fields (e.g., extracting "50Mbps" from a string). This creates a hidden dependency where changing a UI label could break recording duration estimates.
**Action:** Added unit tests that verify this parsing logic holds for current format definitions, ensuring that changes to format descriptions will trigger test failures if they break the bitrate extraction heuristic.

## 2026-02-23 - [Zombie Process Risk in Recording Stop]

**Learning:** The `stop_recording` function handles critical process termination logic, including timeouts and pipe errors. If this fails, the camera device remains locked by a zombie FFmpeg process, requiring a system reboot. This complex error handling path was previously untested.
**Action:** Added `tests/test_stop_recording_resilience.py` to simulate `subprocess.TimeoutExpired` and generic exceptions, verifying that `kill()` is always called to release hardware resources.

## 2026-02-23 - [UI Crash from Invalid Config State]

**Learning:** The `HatUI` daemon thread relied on `CameraState` properties being strictly valid (non-None, correct types). A corrupted config file or initialization race condition could inject `None` values, causing the UI thread to crash silently while the main process continued, leaving the user without feedback.
**Action:** Added `tests/test_hat_ui_robustness.py` which mocks invalid state to verify rendering safety. Hardened both `obsbot_capture.py` (load_config validation) and `hat_ui.py` (safe accessors) to ensure the UI can recover from bad data.
