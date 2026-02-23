# PiCAM (OBSBOT Meet 2 — Pi5 CineRig)

**Current Version: v0.1.0**

CinePi-inspired capture tool for the **OBSBOT Meet 2 4K** on **Raspberry Pi 5**.
Records to **MP4, MKV or ProRes MOV** via FFmpeg with full manual camera controls,
live audio metering, and a **Waveshare 1.44" LCD HAT** viewfinder.

---

## Hardware Requirements

- **Raspberry Pi 5** (Required for 4K encoding performance)
- **OBSBOT Meet 2** (4K Webcam)
- **Waveshare 1.44" LCD HAT** (GPIO/SPI Interface)

---

## Files

| File | Purpose |
|---|---|
| `obsbot_capture.py` | Main capture tool — GUI, headless, diagnostics |
| `hat_ui.py` | Waveshare HAT viewfinder — 8-page cinema monitor + live feed |
| `install.sh` | One-time dependency installer |
| `README.md` | This file |

## Architecture

- **`obsbot_capture.py`**: The main application controller. It manages:
  - **Main Thread**: Handles OpenCV GUI (HDMI preview), keyboard input, and the FFmpeg recording process.
  - **`CameraState`**: A shared data class acting as the source of truth for all settings (exposure, focus, format).
- **`hat_ui.py`**: Run as a daemon thread. It manages:
  - **SPI Display**: Renders the 128x128 UI at ~15fps.
  - **GPIO Input**: Polls joystick and buttons for interaction.
  - **`FrameGrabber`**: A helper that safely extracts frames from the main OpenCV loop for the HAT's live preview.
- **`install.sh`**: One-time setup script that configures system boot parameters (USB bandwidth, SPI, GPIO) and installs dependencies.

**Data Flow:** `CameraState` is the single source of truth. The GUI loop (OpenCV) and HAT loop (daemon) both read/write to it independently. FFmpeg is launched as a subprocess reading from `CameraState` config, while the GUI temporarily releases the camera resource.

---

## Quick Start

```bash
# 1. Install everything (once, then reboot)
bash install.sh
sudo reboot

# 2. Check everything is detected
python3 obsbot_capture.py --mode diag

# 3. Launch (pick one)
python3 obsbot_capture.py --mode gui                      # HDMI preview
python3 obsbot_capture.py --mode headless --hat           # HAT-only (no monitor)
python3 obsbot_capture.py --mode gui --hat                # Both

# 4. Test HAT display standalone
python3 hat_ui.py
```

### Installation Details

The `install.sh` script performs the following critical system changes:

1. **USB Bandwidth:** Adds `usbcore.usbfs_memory_mb=512` to `/boot/firmware/cmdline.txt` (Required for 4K video).
2. **SPI Interface:** Enables SPI (`dtparam=spi=on`) in `/boot/firmware/config.txt`.
3. **GPIO Pull-ups:** Configures pull-ups for the HAT buttons and joystick in `/boot/firmware/config.txt`.
4. **Dependencies:** Installs `ffmpeg`, `v4l-utils`, and Python libraries (`rich`, `spidev`, `sounddevice`, `lgpio`, `Pillow`).

---

## Output Formats

Press **P** (keyboard) or use the **FORMAT page** on the HAT to cycle between:

| # | Format | Container | ~Bitrate 4K | Notes |
|---|---|---|---|---|
| 1 | **H.264 High** | `.mp4` | ~50 Mbps | ★ Best for Filmora — just drag & drop |
| 2 | **H.264 Std** | `.mp4` | ~20 Mbps | Filmora, smaller files |
| 3 | **H.265 / HEVC** | `.mp4` | ~25 Mbps | Efficient 4K, Filmora compatible |
| 4 | **MKV H.264** | `.mkv` | ~50 Mbps | Flexible container, Filmora compatible |
| 5 | **ProRes HQ** | `.mov` | ~220 Mbps | Maximum quality, large files |
| 6 | **ProRes LT** | `.mov` | ~100 Mbps | Edit-ready, reasonable size |
| 7 | **ProRes Proxy** | `.mov` | ~40 Mbps | Offline / rough cut |

> **Pi 5 note:** H.264 and H.265 are software-encoded (no hardware encoder for
> arbitrary V4L2 input). At 4K they push the CPU hard — if you see dropped frames,
> switch to 1080p (`--res 1920x1080`) or use ProRes which encodes easily.
> ProRes is I-frame only and is the most reliable choice for 4K 30fps recording.

Set format on the command line:

```bash
python3 obsbot_capture.py --format h264_high     # MP4 H.264 — Filmora default
python3 obsbot_capture.py --format h265          # MP4 HEVC
python3 obsbot_capture.py --format prores_hq     # ProRes HQ .mov
```

Available `--format` values: `h264_high`, `h264_std`, `h265`, `mkv_h264`,
`prores_hq`, `prores_lt`, `prores_proxy`

---

## Keyboard Controls

| Key | Action |
|---|---|
| **R** | Record / Stop |
| **P** | Cycle output format (H.264 → H.265 → ProRes…) |
| **E / D** | Exposure +/- |
| **G / F** | Gain (ISO) +/- |
| **W / S** | White balance Kelvin +/- |
| **A** | Toggle auto exposure |
| **B** | Toggle auto white balance |
| **T** | Toggle autofocus AF/MF |
| **] / [** | Focus far / near (coarse) |
| **. / ,** | Focus far / near (fine) |
| **K** | Toggle focus peaking |
| **L** | Toggle framing guides |
| **J** | Toggle live histogram |
| **M** | Mute / unmute mic |
| **+ / -** | Mic gain ±3 dB |
| **H** | Toggle help overlay (GUI only) |
| **Q / ESC** | Quit |

---

## HAT Viewfinder — 9 Pages

**JOY ←/→** navigates pages. **JOY ↑/↓** adjusts. **KEY1** always records.

| Page | JOY ↑↓ adjusts | KEY2 | KEY3 | JOY PRESS |
|---|---|---|---|---|
| **LIVE** | — | Toggle AE | Toggle HUD overlay | Cycle format |
| **STATUS** | — | Toggle AE | Cycle format | Cycle format |
| **EXPOSURE** | Shutter or ISO | Toggle AE | Switch shutter↔ISO | — |
| **WHITE BAL** | Kelvin ±100 | Toggle AWB | Jump WB preset | One-shot AWB lock |
| **FOCUS** | Pull focus | Toggle AF/MF | Toggle peaking | One-shot AF lock |
| **DISPLAY** | Select item | Toggle item | Cycle selection | Toggle item |
| **AUDIO** | Mic gain ±3dB | Mute | Reset gain to 0 | Mute toggle |
| **FORMAT** | Cycle all formats | Cycle format | Cycle resolution | Cycle FPS |
| **STORAGE** | — | — | Reset clip # | Clip info |

### DISPLAY Page
Use this page to toggle HDMI/GUI overlays:
- **Guides:** Rule-of-thirds & crosshair
- **Histogram:** Live luminance histogram
- **Peaking:** Focus peaking (red edges)

### LIVE Page — KEY3 toggles HUD
- **HUD ON:** timecode · REC dot · focus bar · L/R audio meters · settings summary
- **CLEAN:** pure video — only a tiny REC dot remains so you know you're rolling

On all other pages a **40×30 live thumbnail** sits in the bottom-right corner.

### FORMAT Page — HAT
The FORMAT page shows the current format name, container extension, approximate
bitrate, and a **"! 4K slow"** warning when a software codec (H.264/H.265) is
selected with 4K resolution. The STORAGE page calculates remaining record time
automatically using the bitrate of the selected format.

---

## CLI Reference

```bash
python3 obsbot_capture.py [OPTIONS]

  --mode        gui | headless | diag      (default: gui)
  --hat                                    Enable HAT viewfinder
  --device      /dev/videoN                (default: /dev/video0)
  --fps         24|25|30|50|60             (default: 30)
  --res         3840x2160|1920x1080|1280x720
  --format      h264_high|h264_std|h265|mkv_h264|prores_hq|prores_lt|prores_proxy
  --outdir      /path/to/footage           (default: ~/obsbot_footage)
  --audio-device  hw:X,0                   (default: auto-detect OBSBOT mic)
  --no-audio                               Disable audio recording
```

### Examples

```bash
# Best for Filmora, 1080p to stay comfortable on Pi CPU
python3 obsbot_capture.py --mode gui --format h264_high --res 1920x1080

# 4K H.265 (watch for dropped frames)
python3 obsbot_capture.py --mode gui --format h265

# HAT-only rig, ProRes HQ to USB SSD
python3 obsbot_capture.py --mode headless --hat --format prores_hq --outdir /mnt/ssd/footage

# Cinema 24fps, Filmora MP4
python3 obsbot_capture.py --mode gui --fps 24 --format h264_high

# External mic on Scarlett interface
python3 obsbot_capture.py --mode gui --audio-device hw:2,0 --format h264_high

# Diagnose camera, audio, and disk
python3 obsbot_capture.py --mode diag
```

---

## Audio

OBSBOT's built-in USB mic is auto-detected and recorded as **24-bit PCM** (ProRes)
or **AAC 256k** (MP4/MKV), baked into the same file as the video.

For better audio use any USB mic or audio interface with `--audio-device hw:X,0`
(find the card number with `--mode diag` or `arecord -l`).

---

## Troubleshooting

**General Diagnostics**
Run the built-in diagnostic tool to check camera, audio, and dependencies:
```bash
python3 obsbot_capture.py --mode diag
```

**H.264/H.265 dropped frames at 4K**
Switch to 1080p: `--res 1920x1080`, or use ProRes which the Pi handles easily.

**Camera not found**
```bash
v4l2-ctl --list-devices
python3 obsbot_capture.py --mode diag --device /dev/video2
```

**4K stream failing (USB bandwidth)**
Make sure you rebooted after `install.sh` (adds `usbfs_memory_mb=512`).
Use the **blue USB 3 port** on the Pi 5.

**HAT not working**
```bash
ls /dev/spidev*          # should show spidev0.0
sudo raspi-config        # Interfaces → SPI → Enable → reboot
python3 hat_ui.py        # standalone HAT test
```

**HAT preview shows NO SIGNAL**
Some cameras only allow one V4L2 handle at a time. Recording still works fine —
use `--mode gui` on HDMI for preview instead.

**Can't open MP4 in Filmora**
Filmora needs H.264 or H.265 — use `--format h264_high` or `--format h265`.
If Filmora can't find the file make sure you're pointing it at your `outdir`.

---

## Output Files

```
~/obsbot_footage/
  CLIP_20250220_0001.mp4    ← H.264 High
  CLIP_20250220_0002.mov    ← ProRes HQ
  CLIP_20250220_0003.mkv    ← MKV H.264
```

Settings (exposure, WB, focus, gain, selected format) persist between sessions
in `~/.obsbot_cinepi.json`.

---

## 🛠️ Development & Contributing

We welcome contributions! Please follow these steps to set up your development environment.

### Development Setup (Raspberry Pi)

1.  **Install System Dependencies** (Raspberry Pi OS Bookworm):
    ```bash
    sudo apt install ffmpeg v4l-utils python3-opencv libopenblas-dev
    ```

2.  **Install Python Dependencies**:
    ```bash
    pip3 install -r requirements.txt
    ```

### Development Setup (Local / Non-Pi)

You can run unit tests and linting on macOS, Windows, or standard Linux without the camera hardware.

1.  **System Dependencies (Linux Only):**
    If developing on Linux, install audio libraries required by `sounddevice`:
    ```bash
    sudo apt install libasound2-dev portaudio19-dev
    ```
    *(macOS/Windows users can skip this step as binaries are included in the wheel)*

2.  **Create a virtual environment:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    pip install pylint  # For linting
    ```
    *Note: `spidev` is Linux-only and will be skipped automatically on macOS/Windows.*

### Running Tests

Run the unit test suite to verify changes (works without hardware):

```bash
python3 -m unittest discover tests
```

### Code Style

-   Keep logic simple and readable.
-   `obsbot_capture.py` is the single-file entry point to minimize import complexity.
-   Use `black` or similar for formatting if possible.

### Static Analysis

Ensure code quality by running pylint (enforced in CI):

```bash
pylint obsbot_capture.py hat_ui.py
```
