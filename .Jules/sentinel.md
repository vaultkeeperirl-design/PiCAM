## 2026-02-20 - [Risky Storage Estimation Logic]

**Learning:** Critical storage estimation logic in `CameraState.remaining_storage_info` relies on parsing unstructured text from `OUTPUT_FORMATS` "note" fields (e.g., extracting "50Mbps" from a string). This creates a hidden dependency where changing a UI label could break recording duration estimates.
**Action:** Added unit tests that verify this parsing logic holds for current format definitions, ensuring that changes to format descriptions will trigger test failures if they break the bitrate extraction heuristic.
