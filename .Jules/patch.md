## 2026-02-22 - Storage Calculation Bug on First Run

**Learning:** The application initialized `output_dir` to a non-existent directory on first run, causing `shutil.disk_usage` to fail or logic to return (0, 0) immediately. This resulted in the UI showing "0 mins remaining" even when disk space was ample, which is a confusing user experience.
**Action:** Implemented a recursive parent directory check in `CameraState.remaining_storage_info`. If the target directory doesn't exist, the logic now walks up the directory tree to find the nearest existing ancestor (likely the mount point or user home) to estimate available space correctly. Added `tests/test_storage.py` validation for this fallback behavior.
