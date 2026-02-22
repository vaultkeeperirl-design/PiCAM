# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-02-22

### Added
- Initial release of OBSBOT Meet 2 CineRig capture tool.
- `obsbot_capture.py`: Core capture logic, FFmpeg recording (ProRes, H.264, H.265), and OpenCV GUI.
- `hat_ui.py`: Waveshare 1.44" LCD HAT viewfinder interface with 8 pages of controls.
- `install.sh`: Automated dependency installation script.
- Support for 4K recording on Raspberry Pi 5 via `usbcore.usbfs_memory_mb=512`.
- Audio metering and recording via ALSA/sounddevice.
