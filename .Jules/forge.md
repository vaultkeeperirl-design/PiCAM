## 2025-02-21 - [Missing Dependency Management]

**Learning:** The project relies on ad-hoc `pip install` commands within `install.sh`, leading to potential version conflicts and unreproducible environments. `requirements.txt` is missing.
**Action:** Created `requirements.txt` to standardize Python dependencies and updated `install.sh` to use it. Added `pyproject.toml` and CI for linting to ensure code quality.

## 2025-02-21 - [Undefined Variables in Production Code]

**Learning:** Linting revealed critical runtime errors (`NameError`) in `obsbot_capture.py` where variables (`show_peaking`, `show_histogram`, `AMBER`, `RED`) were used without being defined in the local scope.
**Action:** Fixed the undefined variables by referencing the correct `state` attributes and global constants.

## 2025-02-21 - [Build Safety & Platform Compatibility]

**Learning:** `install.sh` was hardcoded for Raspberry Pi 5, performing potentially destructive system modifications (/boot/firmware) on non-Pi platforms. `requirements.txt` also lacked platform markers for `spidev`.
**Action:** Added rigorous platform detection to `install.sh` to skip Pi-specific config on other systems. Added `sys_platform == 'linux'` marker to `spidev` in `requirements.txt`.

## 2026-02-22 - [CI Pipeline Hardening]

**Learning:** The CI pipeline (`ci.yml`) only performed linting, leaving logic errors undetected until release.
**Action:** Added a unit test step (`python3 -m unittest discover tests`) to the CI workflow to ensure tests pass on every push and pull request.
