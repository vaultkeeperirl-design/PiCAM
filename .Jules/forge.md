## 2025-02-21 - [Missing Dependency Management]

**Learning:** The project relies on ad-hoc `pip install` commands within `install.sh`, leading to potential version conflicts and unreproducible environments. `requirements.txt` is missing.
**Action:** Created `requirements.txt` to standardize Python dependencies and updated `install.sh` to use it. Added `pyproject.toml` and CI for linting to ensure code quality.

## 2025-02-21 - [Undefined Variables in Production Code]

**Learning:** Linting revealed critical runtime errors (`NameError`) in `obsbot_capture.py` where variables (`show_peaking`, `show_histogram`, `AMBER`, `RED`) were used without being defined in the local scope.
**Action:** Fixed the undefined variables by referencing the correct `state` attributes and global constants.
