# Archivist Journal

## 2025-02-21 - Contributor Onboarding Gaps

**Learning:** The project lacked clear instructions for new contributors on how to set up the environment and run tests, potentially stalling community involvement.
**Action:** Added a `Contributing` section to `README.md` detailing dependencies, test execution, and code style. Also clarified the `Architecture` section to better explain the threading model.

## 2026-02-22 - Non-Pi Development Friction

**Learning:** New contributors on non-Pi platforms (macOS/Windows) were blocked by strict hardware requirements (Raspberry Pi, HAT) in the setup guide, unaware they could run unit tests locally.
**Action:** Split setup instructions into "Raspberry Pi" (Production) and "Local / Non-Pi" (Development) sections, clarified `install.sh` vs `requirements.txt`, and added "General Diagnostics" to troubleshooting.
