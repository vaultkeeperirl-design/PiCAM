## 2025-02-20 - [Insecure and Non-Atomic Config Saving]

**Learning:** The configuration file `~/.obsbot_cinepi.json` was being written using `Path.write_text`, which is not atomic and does not set restrictive permissions. This poses a risk of data corruption (if power fails during write) and potential information leakage.
**Action:** Implemented an atomic write pattern using `os.open` (with `O_CREAT | O_TRUNC | O_WRONLY` and mode `0o600`), `os.fdopen`, `json.dump`, `f.flush()`, `os.fsync()`, and `os.replace`. This ensures the file is fully written to disk before replacing the old one, and has correct permissions from the start. Added a unit test `tests/test_save_config.py` to verify this behavior using mocks.
