#!/usr/bin/env python3
"""
OBSBOT Meet 2 — CinePi-style capture tool for Raspberry Pi 5
Shoots ProRes (via FFmpeg), supports GUI and headless modes.

Usage:
    python3 obsbot_capture.py --mode gui
    python3 obsbot_capture.py --mode headless
    python3 obsbot_capture.py --mode gui --device /dev/video2 --fps 24
"""

__version__ = "0.1.0"

import argparse
import subprocess
import threading
import time
import os
import sys
import signal
import json
import datetime
import shutil
from pathlib import Path

# ─────────────────────────────────────────────
#  Try optional imports gracefully
# ─────────────────────────────────────────────
try:
    import cv2
    CV2_OK = True
except ImportError:
    CV2_OK = False

try:
    from rich.console import Console
    from rich.live import Live
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    from rich.layout import Layout
    from rich.columns import Columns
    from rich import box
    RICH_OK = True
except ImportError:
    RICH_OK = False

try:
    import numpy as np
    NP_OK = True
except ImportError:
    NP_OK = False

try:
    import sounddevice as sd
    SD_OK = True
except ImportError:
    SD_OK = False

try:
    from hat_ui import HatUI
    HAT_OK = True
except ImportError:
    HAT_OK = False

# ─────────────────────────────────────────────
#  Constants & Defaults
# ─────────────────────────────────────────────
DEFAULT_DEVICE   = "/dev/video0"
DEFAULT_FPS      = 30
DEFAULT_RES      = "3840x2160"       # 4K
OUTPUT_DIR       = Path.home() / "obsbot_footage"
CONFIG_FILE      = Path.home() / ".obsbot_cinepi.json"

# V4L2 control names as reported by v4l2-ctl
V4L2_EXPOSURE      = "exposure_time_absolute"
V4L2_GAIN          = "gain"
V4L2_WB_TEMP       = "white_balance_temperature"
V4L2_WB_AUTO       = "white_balance_temperature_auto"
V4L2_EXPOSURE_AUTO = "exposure_auto"      # 1=manual, 3=auto
V4L2_FOCUS_AUTO    = "focus_automatic_continuous"  # 0=manual, 1=auto
V4L2_FOCUS_ABS     = "focus_absolute"    # typical range 0–255 or 0–1023

FOCUS_STEP_COARSE  = 10    # [ ] keys
FOCUS_STEP_FINE    = 2     # , . keys
FOCUS_MIN          = 0
FOCUS_MAX          = 255   # adjusted at runtime if camera reports higher

# UI Colors
COLOR_RED    = (0, 0, 220)
COLOR_WHITE  = (255, 255, 255)
COLOR_BLACK  = (0, 0, 0)
COLOR_GREEN  = (50, 220, 50)
COLOR_AMBER  = (0, 165, 255)

# ─────────────────────────────────────────────
#  Output Format Presets
#  Each entry is the full FFmpeg recipe for that format.
#  Pi 5 note: H.264/H.265 encoding is software-only (no HW encoder for
#  arbitrary input). At 4K these codecs push the CPU hard — use 1080p
#  if you see dropped frames.  ProRes is I-frame only and encodes easily.
# ─────────────────────────────────────────────
OUTPUT_FORMATS = [
    {
        "key":      "h264_high",
        "label":    "H.264 High",
        "ext":      "mp4",
        "note":     "~50Mbps · Filmora ★",
        "est_mbps": 50,
        "cpu_warn": True,           # flag for 4K CPU warning
        "vcodec":   "libx264",
        "vparams":  ["-crf","18","-preset","faster","-pix_fmt","yuv420p"],
        "acodec":   "aac",
        "abitrate": "256k",
        "mflags":   ["-movflags","+faststart"],
    },
    {
        "key":      "h264_std",
        "label":    "H.264 Std",
        "ext":      "mp4",
        "note":     "~20Mbps · smaller files",
        "est_mbps": 20,
        "cpu_warn": True,
        "vcodec":   "libx264",
        "vparams":  ["-crf","23","-preset","faster","-pix_fmt","yuv420p"],
        "acodec":   "aac",
        "abitrate": "192k",
        "mflags":   ["-movflags","+faststart"],
    },
    {
        "key":      "h265",
        "label":    "H.265 / HEVC",
        "ext":      "mp4",
        "note":     "~25Mbps · efficient 4K",
        "est_mbps": 25,
        "cpu_warn": True,
        "vcodec":   "libx265",
        "vparams":  ["-crf","20","-preset","faster","-pix_fmt","yuv420p"],
        "acodec":   "aac",
        "abitrate": "256k",
        "mflags":   ["-movflags","+faststart"],
    },
    {
        "key":      "mkv_h264",
        "label":    "MKV H.264",
        "ext":      "mkv",
        "note":     "~50Mbps · flexible container",
        "est_mbps": 50,
        "cpu_warn": True,
        "vcodec":   "libx264",
        "vparams":  ["-crf","18","-preset","faster","-pix_fmt","yuv420p"],
        "acodec":   "aac",
        "abitrate": "256k",
        "mflags":   [],
    },
    {
        "key":      "prores_hq",
        "label":    "ProRes HQ",
        "ext":      "mov",
        "note":     "~220Mbps · max quality",
        "est_mbps": 220,
        "cpu_warn": False,
        "vcodec":   "prores_ks",
        "vparams":  ["-profile:v","3","-vendor","ap10","-pix_fmt","yuv422p10le"],
        "acodec":   "pcm_s24le",
        "abitrate": None,           # PCM has no bitrate flag
        "mflags":   ["-movflags","+faststart"],
    },
    {
        "key":      "prores_lt",
        "label":    "ProRes LT",
        "ext":      "mov",
        "note":     "~100Mbps · edit-ready",
        "est_mbps": 100,
        "cpu_warn": False,
        "vcodec":   "prores_ks",
        "vparams":  ["-profile:v","1","-vendor","ap10","-pix_fmt","yuv422p10le"],
        "acodec":   "pcm_s24le",
        "abitrate": None,
        "mflags":   ["-movflags","+faststart"],
    },
    {
        "key":      "prores_proxy",
        "label":    "ProRes Proxy",
        "ext":      "mov",
        "note":     "~40Mbps · offline / rough cut",
        "est_mbps": 40,
        "cpu_warn": False,
        "vcodec":   "prores_ks",
        "vparams":  ["-profile:v","0","-vendor","ap10","-pix_fmt","yuv422p10le"],
        "acodec":   "pcm_s24le",
        "abitrate": None,
        "mflags":   ["-movflags","+faststart"],
    },
]
N_FORMATS = len(OUTPUT_FORMATS)

# Quick lookup by key
FORMAT_BY_KEY = {f["key"]: f for f in OUTPUT_FORMATS}
DEFAULT_FORMAT_IDX = 0   # h264_high — best for Filmora out of the box

# ─────────────────────────────────────────────
#  Audio constants
# ─────────────────────────────────────────────
AUDIO_SAMPLE_RATE  = 48000   # 48kHz — broadcast standard
AUDIO_CHANNELS     = 2       # stereo
AUDIO_METER_DECAY  = 0.85    # peak hold decay per frame (0–1)
OBSBOT_USB_NAMES   = ["obsbot", "meet", "usb audio"]  # substrings to match

# ─────────────────────────────────────────────
#  Camera State
# ─────────────────────────────────────────────
class CameraState:
    def __init__(self):
        self.device      = DEFAULT_DEVICE
        self.resolution  = DEFAULT_RES
        self.fps         = DEFAULT_FPS
        self.exposure    = 500          # absolute value (~1/200s at 100fps clock)
        self.gain        = 100          # 0–1000+ depending on camera
        self.wb_temp     = 5600         # Kelvin
        self.auto_wb     = False
        self.auto_exp    = False
        self.auto_focus  = True           # start with AF on
        self.focus       = 128            # mid-point default
        self.focus_max   = FOCUS_MAX      # updated at runtime
        self.focus_peaking = False        # highlight in-focus edges
        self.show_guides = True           # framing guides toggle
        self.show_histogram = False       # live histogram toggle
        self.output_format_idx = DEFAULT_FORMAT_IDX  # index into OUTPUT_FORMATS
        self.recording   = False
        self.rec_start   = None
        self.clip_number = 1
        self.output_dir  = OUTPUT_DIR
        self.ffmpeg_proc = None
        self.record_trigger = False  # HAT sets this; GUI loop acts on it
        # ── Audio ──────────────────────────────
        self.audio_device   = None    # ALSA hw: string, detected at startup
        self.audio_device_sd = None   # sounddevice index for metering
        self.audio_enabled  = True    # False if no mic found
        self.audio_muted    = False
        self.mic_gain_db    = 0       # software gain offset in dB (-20 to +20)
        self.audio_levels   = [0.0, 0.0]   # live RMS L/R (0–1)
        self.audio_peaks    = [0.0, 0.0]   # peak hold L/R
        self.load_config()

    def load_config(self):
        if CONFIG_FILE.exists():
            try:
                d = json.loads(CONFIG_FILE.read_text())
                self.exposure       = d.get("exposure", self.exposure)
                self.gain           = d.get("gain", self.gain)
                self.wb_temp        = d.get("wb_temp", self.wb_temp)
                self.fps            = d.get("fps", self.fps)
                self.focus          = d.get("focus", self.focus)
                self.auto_focus     = d.get("auto_focus", self.auto_focus)
                self.mic_gain_db    = d.get("mic_gain_db", self.mic_gain_db)
                self.output_format_idx = d.get("output_format_idx",
                                   d.get("prores_profile", self.output_format_idx))  # legacy compat
            except (OSError, json.JSONDecodeError) as e:
                print(f"[WARN] Failed to load config: {e}")

    def save_config(self):
        data = {
            "exposure":          self.exposure,
            "gain":              self.gain,
            "wb_temp":           self.wb_temp,
            "fps":               self.fps,
            "output_format_idx": self.output_format_idx,
            "focus":             self.focus,
            "auto_focus":        self.auto_focus,
            "mic_gain_db":       self.mic_gain_db,
        }
        try:
            # Atomic write pattern with restrictive permissions (0o600)
            tmp_path = str(CONFIG_FILE) + ".tmp"
            fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'w') as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(fd)
            os.replace(tmp_path, CONFIG_FILE)
        except OSError as e:
            print(f"[WARN] Failed to save config: {e}")

    @property
    def rec_timecode(self):
        if self.rec_start is None:
            return "00:00:00:00"
        elapsed = time.time() - self.rec_start
        h  = int(elapsed // 3600)
        m  = int((elapsed % 3600) // 60)
        s  = int(elapsed % 60)
        fr = int((elapsed % 1) * self.fps)
        return f"{h:02d}:{m:02d}:{s:02d}:{fr:02d}"

    @property
    def output_format(self) -> dict:
        """Return the current output format dict from OUTPUT_FORMATS."""
        idx = max(0, min(self.output_format_idx, N_FORMATS - 1))
        return OUTPUT_FORMATS[idx]

    @property
    def format_label(self) -> str:
        return self.output_format["label"]

    @property
    def clip_name(self):
        ts  = datetime.datetime.now().strftime("%Y%m%d")
        ext = self.output_format["ext"]
        return f"CLIP_{ts}_{self.clip_number:04d}.{ext}"

    @property
    def shutter_angle(self):
        """Convert exposure value to approximate shutter angle at current fps."""
        # exposure_time_absolute is in 100µs units for most UVC cams
        exp_sec = self.exposure / 10000.0
        angle = exp_sec * self.fps * 360
        return min(360, max(1, angle))

    @property
    def focus_pct(self):
        """Focus position as 0–100 percentage of range."""
        return int((self.focus / max(self.focus_max, 1)) * 100)

    @property
    def remaining_storage_info(self):
        """Returns tuple (free_gb, remaining_minutes) or (0, 0) on error."""
        try:
            if not self.output_dir.exists():
                return (0, 0)

            # Use shutil for cross-platform disk usage
            total, used, free = shutil.disk_usage(str(self.output_dir))
            free_gb = free / (1024**3)

            # Estimate bitrate from format definition
            fmt  = self.output_format
            mbps = fmt.get("est_mbps", 50)

            # Adjust for resolution (simple heuristic)
            if "1280x720" in str(self.resolution):
                mbps = max(1, mbps // 3)
            elif "1920x1080" in str(self.resolution):
                mbps = max(1, mbps // 2)

            # Calculate minutes: (GB * 8000 / Mbps) / 60
            mins = int((free_gb * 8000 / mbps) / 60) if mbps else 0
            return (free_gb, mins)
        except Exception:
            return (0, 0)

# ─────────────────────────────────────────────
#  V4L2 Control Layer
# ─────────────────────────────────────────────
def v4l2_set(device, control, value):
    """Set a V4L2 control via v4l2-ctl."""
    cmd = ["v4l2-ctl", f"--device={device}", f"--set-ctrl={control}={value}"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0

def v4l2_get(device, control):
    """Get a V4L2 control value. Returns int or None."""
    cmd = ["v4l2-ctl", f"--device={device}", f"--get-ctrl={control}"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        # Output: "exposure_time_absolute: 500"
        try:
            return int(result.stdout.strip().split(":")[1].strip())
        except Exception:
            return None
    return None

def v4l2_list_controls(device):
    """Return raw output of all controls for debugging."""
    result = subprocess.run(
        ["v4l2-ctl", f"--device={device}", "--list-ctrls-menus"],
        capture_output=True, text=True
    )
    return result.stdout

def detect_focus_range(state: CameraState):
    """Query the camera for its focus_absolute min/max and update state."""
    result = subprocess.run(
        ["v4l2-ctl", f"--device={state.device}", "--list-ctrls"],
        capture_output=True, text=True
    )
    for line in result.stdout.splitlines():
        if "focus_absolute" in line and "max=" in line:
            try:
                parts = {k: int(v) for k, v in
                         (p.split("=") for p in line.split() if "=" in p)}
                state.focus_max = parts.get("max", FOCUS_MAX)
                # Clamp current focus value to detected range
                state.focus = max(parts.get("min", 0),
                                  min(state.focus, state.focus_max))
            except Exception:
                pass
            break

def apply_camera_settings(state: CameraState):
    """Push current state to camera via V4L2."""
    dev = state.device

    # Exposure mode first
    exp_auto_val = 3 if state.auto_exp else 1
    v4l2_set(dev, V4L2_EXPOSURE_AUTO, exp_auto_val)

    if not state.auto_exp:
        v4l2_set(dev, V4L2_EXPOSURE, state.exposure)

    # Gain
    v4l2_set(dev, V4L2_GAIN, state.gain)

    # White balance
    v4l2_set(dev, V4L2_WB_AUTO, 1 if state.auto_wb else 0)
    if not state.auto_wb:
        v4l2_set(dev, V4L2_WB_TEMP, state.wb_temp)

    # Focus
    v4l2_set(dev, V4L2_FOCUS_AUTO, 1 if state.auto_focus else 0)
    if not state.auto_focus:
        v4l2_set(dev, V4L2_FOCUS_ABS, state.focus)

# ─────────────────────────────────────────────
#  Audio Detection & Metering Engine
# ─────────────────────────────────────────────
def detect_audio_device(state: CameraState):
    """
    Find the OBSBOT's ALSA audio device by scanning arecord -l output.
    Sets state.audio_device (ALSA hw:X,0 string) and state.audio_device_sd
    (sounddevice index).  Falls back to default input if not found.
    """
    # ── ALSA device string for FFmpeg ──
    result = subprocess.run(["arecord", "-l"], capture_output=True, text=True)
    alsa_card = None
    for line in result.stdout.splitlines():
        low = line.lower()
        if any(name in low for name in OBSBOT_USB_NAMES):
            # Line looks like: "card 2: OBSBOT_Meet2 [OBSBOT Meet2], device 0: ..."
            try:
                card_num = int(line.split("card")[1].split(":")[0].strip())
                alsa_card = f"hw:{card_num},0"
                print(f"[AUDIO] Found OBSBOT mic → ALSA {alsa_card}")
            except Exception:
                pass
            break

    if alsa_card is None:
        print("[AUDIO] No mic found — recording video-only")
        print("        Run --mode diag to see devices, or pass --audio-device hw:X,0")
        state.audio_device  = None
        state.audio_enabled = False
        return

    state.audio_device = alsa_card

    # ── sounddevice index for live metering ──
    if SD_OK:
        try:
            devices = sd.query_devices()
            for i, dev in enumerate(devices):
                if dev["max_input_channels"] > 0:
                    low = dev["name"].lower()
                    if any(name in low for name in OBSBOT_USB_NAMES):
                        state.audio_device_sd = i
                        print(f"[AUDIO] Meter device → [{i}] {dev['name']}")
                        return
            # Fallback: use default input
            state.audio_device_sd = sd.default.device[0]
        except Exception as e:
            print(f"[AUDIO] sounddevice probe failed: {e}")
            state.audio_device_sd = None


class AudioMeter:
    """
    Background thread that reads from the mic via sounddevice and
    updates state.audio_levels / state.audio_peaks in real time.
    Runs independently of FFmpeg — purely for the visual meters.
    """
    def __init__(self, state: CameraState):
        self.state   = state
        self._stop   = threading.Event()
        self._thread = None

    def start(self):
        if not SD_OK:
            return
        if self.state.audio_device_sd is None or self.state.audio_device_sd < 0:
            print("[AUDIO] No meter device — levels will show 0")
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        BLOCK = 1024  # samples per callback
        try:
            with sd.InputStream(
                device=self.state.audio_device_sd,
                channels=min(AUDIO_CHANNELS,
                             sd.query_devices(self.state.audio_device_sd)["max_input_channels"]),
                samplerate=AUDIO_SAMPLE_RATE,
                blocksize=BLOCK,
                dtype="float32",
            ) as stream:
                while not self._stop.is_set():
                    data, _ = stream.read(BLOCK)
                    # RMS per channel
                    for ch in range(data.shape[1]):
                        rms = float(np.sqrt(np.mean(data[:, ch] ** 2)))
                        self.state.audio_levels[ch] = rms
                        # Peak hold with decay
                        if rms > self.state.audio_peaks[ch]:
                            self.state.audio_peaks[ch] = rms
                        else:
                            self.state.audio_peaks[ch] *= AUDIO_METER_DECAY
        except Exception as e:
            print(f"[AUDIO] Meter error: {e}")


def audio_gain_linear(state: CameraState) -> float:
    """Convert mic_gain_db to linear multiplier for FFmpeg volume filter."""
    return 10 ** (state.mic_gain_db / 20.0)


def list_audio_devices():
    """Print all ALSA capture devices for diagnostics."""
    result = subprocess.run(["arecord", "-l"], capture_output=True, text=True)
    return result.stdout
# ─────────────────────────────────────────────
#  FFmpeg Recording Engine
# ─────────────────────────────────────────────
def build_ffmpeg_cmd(state: CameraState, output_path: str) -> list:
    """
    Build the FFmpeg command. FFmpeg always opens the V4L2 device directly —
    the GUI releases the camera first, FFmpeg records, then GUI reopens.
    This avoids the 700MB/s pipe bottleneck of passing raw 4K frames.
    """
    fmt = state.output_format

    cmd = [
        "ffmpeg", "-y",
        # ── Video input via V4L2 ─────────────────────────────────────
        "-f", "v4l2",
        "-input_format", "mjpeg",
        "-video_size", state.resolution,
        "-framerate", str(state.fps),
        "-i", state.device,
    ]

    # ── Audio input ──────────────────────────────────────────────────
    has_audio = (state.audio_enabled and state.audio_device
                 and not state.audio_muted)
    if has_audio:
        cmd += [
            "-f", "alsa",
            "-channels", str(AUDIO_CHANNELS),
            "-sample_rate", str(AUDIO_SAMPLE_RATE),
            "-i", state.audio_device,
        ]

    # ── Video encode ─────────────────────────────────────────────────
    cmd += ["-vcodec", fmt["vcodec"]] + fmt["vparams"]
    cmd += [
        "-colorspace",      "bt709",
        "-color_primaries", "bt709",
        "-color_trc",       "bt709",
    ]

    # ── Audio encode ─────────────────────────────────────────────────
    if has_audio:
        cmd += ["-acodec", fmt["acodec"]]
        if fmt["abitrate"]:
            cmd += ["-b:a", fmt["abitrate"]]
        cmd += ["-ar", str(AUDIO_SAMPLE_RATE), "-ac", str(AUDIO_CHANNELS)]
        if abs(state.mic_gain_db) > 0.1:
            gain = audio_gain_linear(state)
            cmd += ["-af", f"volume={gain:.4f}"]
    else:
        cmd += ["-an"]

    # ── Container flags + metadata ───────────────────────────────────
    cmd += fmt["mflags"]
    cmd += [
        "-metadata", f"creation_time={datetime.datetime.now().isoformat()}",
        "-metadata", "artist=OBSBOT Meet 2 / Pi5 CineRig",
        "-metadata", f"comment=Format:{fmt['label']}",
        output_path,
    ]
    return cmd

def start_recording(state: CameraState, cap=None) -> bool:
    """
    Start FFmpeg recording.
    cap: the OpenCV VideoCapture — we release it so FFmpeg can open the device.
    Returns True on success.
    """
    if state.recording:
        return False

    state.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = str(state.output_dir / state.clip_name)

    # Release OpenCV's hold on the camera so FFmpeg can open it
    if cap is not None:
        cap.release()
        time.sleep(0.3)   # give the driver a moment to fully release

    cmd = build_ffmpeg_cmd(state, output_path)
    print(f"[REC] Starting: {output_path}")
    print(f"[REC] Format: {state.format_label}  codec: {state.output_format['vcodec']}")

    try:
        state.ffmpeg_proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=None,    # show FFmpeg errors in terminal
        )
        time.sleep(0.8)
        if state.ffmpeg_proc.poll() is not None:
            print(f"[ERROR] FFmpeg exited immediately (code {state.ffmpeg_proc.returncode})")
            state.ffmpeg_proc = None
            return False

        state.recording  = True
        state.rec_start  = time.time()
        print(f"[REC] ● Recording → {output_path}")
        return True
    except FileNotFoundError:
        print("[ERROR] ffmpeg not found. Run: sudo apt install ffmpeg")
        return False
    except Exception as e:
        print(f"[ERROR] Failed to start recording: {e}")
        return False


def stop_recording(state: CameraState, cap=None, cap_w=3840, cap_h=2160, cap_fps=30) -> None:
    """
    Stop FFmpeg gracefully then reopen the camera for the GUI preview.
    cap: pass the OpenCV VideoCapture object to reopen after FFmpeg releases the device.
    """
    if not state.recording or state.ffmpeg_proc is None:
        return

    if state.ffmpeg_proc.poll() is None:
        try:
            state.ffmpeg_proc.stdin.write(b"q")
            state.ffmpeg_proc.stdin.flush()
            state.ffmpeg_proc.wait(timeout=10)
        except BrokenPipeError:
            pass
        except subprocess.TimeoutExpired:
            print("[WARN] FFmpeg timeout — killing")
            state.ffmpeg_proc.kill()
            state.ffmpeg_proc.wait()
        except Exception as e:
            print(f"[WARN] Stop error: {e}")
            try: state.ffmpeg_proc.kill()
            except Exception: pass
    else:
        print(f"[WARN] FFmpeg had already exited (code {state.ffmpeg_proc.returncode})")

    state.recording   = False
    state.rec_start   = None
    state.clip_number += 1
    state.ffmpeg_proc = None
    print("[STOP] ■ Recording stopped.")

    # Reopen camera for GUI preview
    if cap is not None:
        time.sleep(0.5)   # let FFmpeg fully release the device
        cap.open(state.device, cv2.CAP_V4L2)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  cap_w)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cap_h)
        cap.set(cv2.CAP_PROP_FPS, cap_fps)
        print("[GUI] Preview resumed.")

# ─────────────────────────────────────────────
#  GUI Mode (OpenCV)
# ─────────────────────────────────────────────
def run_gui(state: CameraState, hat=None):
    if not CV2_OK:
        print("[ERROR] OpenCV not found. Install: pip3 install opencv-python-headless")
        sys.exit(1)
    if not NP_OK:
        print("[ERROR] NumPy not found. Install: pip3 install numpy")
        sys.exit(1)

    print("[GUI] Opening camera preview… (press H for help)")

    cap = cv2.VideoCapture(state.device, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)       # don't queue stale frames
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  3840)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 2160)
    cap.set(cv2.CAP_PROP_FPS, state.fps)

    if not cap.isOpened():
        print(f"[ERROR] Cannot open camera {state.device}")
        print("        Check: v4l2-ctl --list-devices")
        sys.exit(1)

    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"[GUI] Camera opened: {actual_w}×{actual_h} @ {state.fps}fps")

    # Warmup — drain the initial buffer, camera needs a moment to negotiate MJPEG
    print("[GUI] Warming up camera…")
    for _ in range(10):
        cap.grab()
    # Now do a proper read to confirm frames are coming
    for attempt in range(30):
        ret, frame = cap.read()
        if ret and frame is not None:
            print(f"[GUI] First frame received ({frame.shape[1]}×{frame.shape[0]}) after {attempt+1} attempts")
            break
        time.sleep(0.1)
    else:
        print("[ERROR] Camera opened but no frames received after 3 seconds.")
        print("        Try: v4l2-ctl --device={state.device} --list-formats-ext")
        print("        Try: python3 obsbot_capture.py --mode diag")
        cap.release()
        sys.exit(1)

    # Detect camera focus range before applying settings
    detect_focus_range(state)

    # Detect and start audio
    detect_audio_device(state)
    meter = AudioMeter(state)
    meter.start()

    # Preview at half-res for performance
    PW, PH = actual_w // 2, actual_h // 2

    apply_camera_settings(state)

    FONT   = cv2.FONT_HERSHEY_SIMPLEX

    show_help      = False
    # show_peaking, show_guides, show_histogram are now in state
    format_menu_timer = 0.0
    blink_state    = True
    blink_timer    = time.time()
    storage_timer  = 0.0
    storage_info   = (0, 0)  # free_gb, mins

    # Toast state
    toast_msg = "Press 'H' for Help"
    toast_timer = time.time()
    toast_duration = 5.0
    toast_color = COLOR_WHITE

    def show_toast(msg, color=COLOR_WHITE, duration=2.0):
        nonlocal toast_msg, toast_timer, toast_duration, toast_color
        toast_msg = msg
        toast_color = color
        toast_timer = time.time()
        toast_duration = duration

    cv2.namedWindow("ObsBot CineRig", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("ObsBot CineRig", PW, PH)

    # Start HAT grabber NOW — after we have confirmed the camera is open and streaming
    # This prevents the grabber from trying to open the camera itself
    if hat and hat.grabber:
        hat.grabber.start()
        print("[HAT] Frame grabber started — feeding from GUI")

    fail_count = 0
    last_frame = None
    while True:
        # While recording, FFmpeg owns the camera — don't try to read from it
        if state.recording:
            if state.ffmpeg_proc and state.ffmpeg_proc.poll() is not None:
                print(f"[WARN] FFmpeg died (code {state.ffmpeg_proc.returncode})")
                stop_recording(state, cap=cap, cap_w=actual_w, cap_h=actual_h, cap_fps=state.fps)
            else:
                time.sleep(0.033)
                if last_frame is None:
                    continue
                frame = last_frame
        else:
            ret, frame = cap.read()
            if not ret or frame is None:
                fail_count += 1
                if fail_count % 30 == 1:
                    print(f"[WARN] Frame grab failed (x{fail_count})")
                if fail_count > 100:
                    print("[ERROR] Reopening camera…")
                    cap.release()
                    time.sleep(1.0)
                    cap.open(state.device, cv2.CAP_V4L2)
                    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  actual_w)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, actual_h)
                    cap.set(cv2.CAP_PROP_FPS, state.fps)
                    fail_count = 0
                time.sleep(0.05)
                continue
            fail_count = 0
            last_frame = frame

        # ── HAT record trigger ───────────────────────────────────────
        if state.record_trigger:
            state.record_trigger = False
            if state.recording:
                stop_recording(state, cap=cap,
                               cap_w=actual_w, cap_h=actual_h, cap_fps=state.fps)
            else:
                start_recording(state, cap=cap)

        # ── Feed frame to HAT live view ──────────────────────────────
        if hat and hat.grabber and not state.recording:
            hat.grabber.feed_frame(frame)

        # Scale for display
        display = cv2.resize(frame, (PW, PH), interpolation=cv2.INTER_LINEAR)

        # Compute grayscale once if needed
        gray = None
        if (state.focus_peaking or state.show_histogram) and CV2_OK:
            gray = cv2.cvtColor(display, cv2.COLOR_BGR2GRAY)

        # ── Focus Peaking overlay (before all HUD text) ──
        if state.focus_peaking and NP_OK:
            display = _apply_focus_peaking(display)

        # ── Tally Border (Recording Indicator) ──
        if state.recording:
            cv2.rectangle(display, (0, 0), (PW - 1, PH - 1), COLOR_RED, 10)

        # ── Blink REC dot every 0.5s ──
        if time.time() - blink_timer > 0.5:
            blink_state = not blink_state
            blink_timer = time.time()

        # ── Overlays ──
        # Top-left: device & resolution
        res_str = f"{actual_w}×{actual_h}  {state.fps}fps"
        _shadow_text(display, res_str, (14, 30), FONT, 0.55, COLOR_WHITE)

        # ── Update Storage Info (every 2s) ──
        if time.time() - storage_timer > 2.0:
            storage_info = state.remaining_storage_info
            storage_timer = time.time()

        # Top-right: format label + remaining time
        profile_label = state.format_label
        mins_left = storage_info[1]
        label_col = COLOR_AMBER

        if mins_left > 0:
            h, m = divmod(mins_left, 60)
            time_str = f"{h}h {m:02d}m"
            profile_label = f"{profile_label}  {time_str}"
            if mins_left < 10:
                label_col = COLOR_RED  # Warn low space

        (tw, th), _ = cv2.getTextSize(profile_label, FONT, 0.55, 1)
        # Right-align with 20px margin
        tx = PW - tw - 20
        _shadow_text(display, profile_label, (tx, 30), FONT, 0.55, label_col)

        # Centre-top: REC indicator
        if state.recording:
            tc = state.rec_timecode
            if blink_state:
                cv2.circle(display, (PW // 2 - 70, 22), 9, COLOR_RED, -1)
            _shadow_text(display, f"REC  {tc}", (PW // 2 - 55, 30), FONT, 0.6, COLOR_RED, thickness=2)
        else:
            _shadow_text(display, "STANDBY", (PW // 2 - 40, 30), FONT, 0.6, COLOR_GREEN)

        # Bottom bar: camera settings
        exp_label   = f"EXP {state.exposure}  ({state.shutter_angle:.0f}°)"
        gain_label  = f"ISO ~{state.gain * 10}"
        wb_label    = f"WB {state.wb_temp}K"
        clip_label  = f"Clip {state.clip_number:04d}"

        if state.auto_focus:
            focus_label = "AF  AUTO"
            focus_color = COLOR_GREEN
        else:
            focus_label = f"MF  {state.focus_pct}%"
            focus_color = COLOR_AMBER

        bar_y = PH - 14
        _shadow_text(display, exp_label,   (14,         bar_y), FONT, 0.5, COLOR_WHITE)
        _shadow_text(display, gain_label,  (PW // 4,    bar_y), FONT, 0.5, COLOR_WHITE)
        _shadow_text(display, wb_label,    (PW // 2,    bar_y), FONT, 0.5, COLOR_WHITE)
        _shadow_text(display, focus_label, (PW - 200,   bar_y), FONT, 0.5, focus_color)
        _shadow_text(display, clip_label,  (PW - 110,   bar_y), FONT, 0.5, COLOR_WHITE)

        # Focus pull bar (shown when in manual focus)
        if not state.auto_focus:
            _draw_focus_bar(display, PW, PH, state.focus_pct, state.focus_peaking)

        # Framing guides
        if state.show_guides:
            _draw_guides(display, PW, PH)

        # Live Histogram
        if state.show_histogram:
            _draw_histogram(display, PW, PH)

        # Format Menu
        if time.time() - format_menu_timer < 3.0:
            _draw_format_menu(display, PW, PH, state)

        # Audio meters (left side, vertical)
        if state.audio_enabled:
            _draw_audio_meters(display, PW, PH, state)

        # Help overlay
        if show_help:
            _draw_help(display, PW, PH, FONT)

        # Toast Message
        if time.time() - toast_timer < toast_duration:
            _draw_toast(display, PW, PH, toast_msg, toast_color)

        cv2.imshow("ObsBot CineRig", display)

        key = cv2.waitKey(1) & 0xFF

        if key == ord('q') or key == 27:     # Q / ESC → quit
            break
        elif key == ord('r') or key == ord('R'):
            if state.recording:
                stop_recording(state, cap=cap,
                               cap_w=actual_w, cap_h=actual_h, cap_fps=state.fps)
            else:
                start_recording(state, cap=cap)
        elif key == ord('h') or key == ord('H'):
            show_help = not show_help

        # Exposure
        elif key == ord('e'):                # exposure up
            state.exposure = min(state.exposure + 50, 10000)
            if not state.auto_exp:
                v4l2_set(state.device, V4L2_EXPOSURE, state.exposure)
        elif key == ord('d'):                # exposure down
            state.exposure = max(state.exposure - 50, 50)
            if not state.auto_exp:
                v4l2_set(state.device, V4L2_EXPOSURE, state.exposure)

        # Gain / ISO
        elif key == ord('g'):
            state.gain = min(state.gain + 10, 500)
            v4l2_set(state.device, V4L2_GAIN, state.gain)
        elif key == ord('f'):
            state.gain = max(state.gain - 10, 0)
            v4l2_set(state.device, V4L2_GAIN, state.gain)

        # White balance
        elif key == ord('w'):
            state.wb_temp = min(state.wb_temp + 100, 10000)
            if not state.auto_wb:
                v4l2_set(state.device, V4L2_WB_TEMP, state.wb_temp)
        elif key == ord('s'):
            state.wb_temp = max(state.wb_temp - 100, 2000)
            if not state.auto_wb:
                v4l2_set(state.device, V4L2_WB_TEMP, state.wb_temp)

        # Auto toggles
        elif key == ord('a'):
            state.auto_exp = not state.auto_exp
            val = 3 if state.auto_exp else 1
            v4l2_set(state.device, V4L2_EXPOSURE_AUTO, val)
            show_toast("AUTO EXPOSURE" if state.auto_exp else "MANUAL EXP",
                       COLOR_GREEN if state.auto_exp else COLOR_AMBER)
        elif key == ord('b'):
            state.auto_wb = not state.auto_wb
            v4l2_set(state.device, V4L2_WB_AUTO, 1 if state.auto_wb else 0)
            show_toast("AUTO WB" if state.auto_wb else "MANUAL WB",
                       COLOR_GREEN if state.auto_wb else COLOR_AMBER)

        # Focus
        elif key == ord('t'):                # T = toggle autofocus
            state.auto_focus = not state.auto_focus
            v4l2_set(state.device, V4L2_FOCUS_AUTO, 1 if state.auto_focus else 0)
            show_toast("AUTOFOCUS" if state.auto_focus else "MANUAL FOCUS",
                       COLOR_GREEN if state.auto_focus else COLOR_AMBER)
            if not state.auto_focus:         # seed manual position from camera
                current = v4l2_get(state.device, V4L2_FOCUS_ABS)
                if current is not None:
                    state.focus = current
        elif key == ord(']'):                # ] = focus farther (coarse)
            if not state.auto_focus:
                state.focus = min(state.focus + FOCUS_STEP_COARSE, state.focus_max)
                v4l2_set(state.device, V4L2_FOCUS_ABS, state.focus)
        elif key == ord('['):                # [ = focus closer (coarse)
            if not state.auto_focus:
                state.focus = max(state.focus - FOCUS_STEP_COARSE, FOCUS_MIN)
                v4l2_set(state.device, V4L2_FOCUS_ABS, state.focus)
        elif key == ord('.'):                # . = fine far
            if not state.auto_focus:
                state.focus = min(state.focus + FOCUS_STEP_FINE, state.focus_max)
                v4l2_set(state.device, V4L2_FOCUS_ABS, state.focus)
        elif key == ord(','):                # , = fine near
            if not state.auto_focus:
                state.focus = max(state.focus - FOCUS_STEP_FINE, FOCUS_MIN)
                v4l2_set(state.device, V4L2_FOCUS_ABS, state.focus)
        elif key == ord('k'):                # K = toggle focus peaking
            state.focus_peaking = not state.focus_peaking
            show_toast("PEAKING ON" if state.focus_peaking else "PEAKING OFF",
                       COLOR_GREEN if state.focus_peaking else COLOR_RED)
        elif key == ord('l'):                # L = toggle guides
            state.show_guides = not state.show_guides
            show_toast("GUIDES ON" if state.show_guides else "GUIDES OFF",
                       COLOR_GREEN if state.show_guides else COLOR_RED)
        elif key == ord('j'):                # J = toggle histogram
            state.show_histogram = not state.show_histogram
            show_toast("HISTOGRAM ON" if state.show_histogram else "HISTOGRAM OFF",
                       COLOR_GREEN if state.show_histogram else COLOR_RED)

        # Audio
        elif key == ord('m'):                # M = mute/unmute mic
            state.audio_muted = not state.audio_muted
            show_toast("MIC MUTED" if state.audio_muted else "MIC LIVE",
                       COLOR_RED if state.audio_muted else COLOR_GREEN)
        elif key == ord('+') or key == ord('='):   # + = mic gain up
            state.mic_gain_db = min(state.mic_gain_db + 3, 20)
        elif key == ord('-'):                # - = mic gain down
            state.mic_gain_db = max(state.mic_gain_db - 3, -20)

        # Output format cycle
        elif key == ord('p'):
            state.output_format_idx = (state.output_format_idx + 1) % N_FORMATS
            format_menu_timer = time.time()
            fmt = state.output_format
            print(f"[FORMAT] → {fmt['label']}  ({fmt['note']})")

    if state.recording:
        stop_recording(state, cap=cap, cap_w=actual_w, cap_h=actual_h, cap_fps=state.fps)
    meter.stop()
    state.save_config()
    cap.release()
    cv2.destroyAllWindows()


def _draw_toast(img, w, h, text, color):
    """Draw a temporary message in the center of the screen."""
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 1.0
    thickness = 2
    (tw, th), _ = cv2.getTextSize(text, font, scale, thickness)

    # Center position (slightly above center to avoid covering subject)
    cx, cy = w // 2, h // 2 - 50

    # Background box
    pad_x, pad_y = 30, 15
    x1, y1 = cx - tw // 2 - pad_x, cy - th // 2 - pad_y
    x2, y2 = cx + tw // 2 + pad_x, cy + th // 2 + pad_y

    # Draw semi-transparent background
    overlay = img.copy()
    cv2.rectangle(overlay, (x1, y1), (x2, y2), (20, 20, 20), -1)
    cv2.addWeighted(overlay, 0.7, img, 0.3, 0, img)

    # Draw text
    cv2.putText(img, text, (cx - tw // 2, cy + th // 2), font, scale, color, thickness, cv2.LINE_AA)


def _shadow_text(img, text, pos, font, scale, color, thickness=1):
    """Draw text with a drop-shadow for readability over any background."""
    cv2.putText(img, text, (pos[0]+1, pos[1]+1), font, scale, (0,0,0), thickness+1, cv2.LINE_AA)
    cv2.putText(img, text, pos, font, scale, color, thickness, cv2.LINE_AA)


def _apply_focus_peaking(frame, gray=None):
    """
    Highlight in-focus edges with a red overlay (focus peaking).
    Uses Laplacian edge detection — bright red = sharpest areas.
    """
    if gray is None:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    # Use CV_16S (signed 16-bit) to save memory (vs CV_64F) and convertScaleAbs to handle saturation correctly
    lap     = cv2.Laplacian(gray, cv2.CV_16S)
    lap_abs = cv2.convertScaleAbs(lap)

    # Use Histogram to find percentile (O(N) vs O(N log N) sorting)
    hist = cv2.calcHist([lap_abs], [0], None, [256], [0, 256])

    total_pixels = frame.shape[0] * frame.shape[1]
    target_count = total_pixels * 0.15
    current_count = 0
    threshold = 0

    # Iterate backwards from 255 to find the top 15% threshold
    for i in range(255, -1, -1):
        current_count += hist[i][0]
        if current_count >= target_count:
            threshold = i
            break

    # Apply threshold
    _, mask = cv2.threshold(lap_abs, threshold, 255, cv2.THRESH_BINARY)

    # Dilate slightly so peaking pixels are visible
    kernel = np.ones((2, 2), np.uint8)
    mask   = cv2.dilate(mask, kernel, iterations=1)

    # Blend red highlight onto frame
    peak_layer       = np.zeros_like(frame)
    peak_layer[:, :, 2] = mask   # mask is already 0 or 255 (uint8)

    result = cv2.addWeighted(frame, 1.0, peak_layer, 0.6, 0)
    return result


def _draw_focus_bar(img, w, h, focus_pct, peaking_on):
    """
    Draw a vertical focus pull bar on the right edge of the frame.
    Shows current focus position (0%=near, 100%=far) and peaking status.
    """
    BAR_X   = w - 22
    BAR_TOP = 60
    BAR_BOT = h - 60
    BAR_H   = BAR_BOT - BAR_TOP
    BAR_W   = 8

    # Track background
    cv2.rectangle(img, (BAR_X, BAR_TOP), (BAR_X + BAR_W, BAR_BOT), (40, 40, 40), -1)

    # Filled portion (bottom = near, top = far — same as most cinema cams)
    fill_h   = int(BAR_H * focus_pct / 100)
    fill_top = BAR_BOT - fill_h
    bar_col  = (50, 200, 255) if not peaking_on else (50, 50, 255)
    cv2.rectangle(img, (BAR_X, fill_top), (BAR_X + BAR_W, BAR_BOT), bar_col, -1)

    # Tick marks at 25% intervals
    for pct in [25, 50, 75]:
        tick_y = BAR_BOT - int(BAR_H * pct / 100)
        cv2.line(img, (BAR_X - 4, tick_y), (BAR_X + BAR_W + 4, tick_y), (160, 160, 160), 1)

    # Labels
    FONT = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(img, "FAR",  (BAR_X - 2, BAR_TOP - 6),  FONT, 0.35, (180,180,180), 1, cv2.LINE_AA)
    cv2.putText(img, "NEAR", (BAR_X - 4, BAR_BOT + 14), FONT, 0.35, (180,180,180), 1, cv2.LINE_AA)

    if peaking_on:
        cv2.putText(img, "PKG", (BAR_X - 2, BAR_BOT + 28), FONT, 0.35, (50, 50, 255), 1, cv2.LINE_AA)


def _draw_audio_meters(img, w, h, state):
    """
    Draw dual vertical audio level meters on the left edge.
    Green = safe, Amber = hot, Red = clipping.
    Shows peak hold markers and mute/gain labels.
    """
    FONT    = cv2.FONT_HERSHEY_SIMPLEX
    BAR_W   = 8
    GAP     = 4
    BAR_TOP = 60
    BAR_BOT = h - 60
    BAR_H   = BAR_BOT - BAR_TOP
    X_L     = 14                   # left channel bar x
    X_R     = X_L + BAR_W + GAP   # right channel bar x

    # dBFS scale: map linear RMS (0–1) → display height
    def rms_to_y(rms):
        if rms < 1e-6:
            return BAR_BOT
        db = 20 * np.log10(rms)           # 0 dBFS at full scale
        db = max(-60, min(0, db))
        frac = (db + 60) / 60             # 0=silent, 1=0dBFS
        return int(BAR_BOT - frac * BAR_H)

    def bar_color(rms):
        db = 20 * np.log10(max(rms, 1e-6))
        if db > -6:   return (0, 50, 230)    # red  — clipping zone
        if db > -18:  return (0, 180, 230)   # amber — hot
        return (50, 200, 80)                  # green — safe

    for ch, x in enumerate([X_L, X_R]):
        rms  = state.audio_levels[ch] if ch < len(state.audio_levels) else 0.0
        peak = state.audio_peaks[ch]  if ch < len(state.audio_peaks)  else 0.0

        # Background track
        cv2.rectangle(img, (x, BAR_TOP), (x + BAR_W, BAR_BOT), (30, 30, 30), -1)

        if not state.audio_muted:
            # RMS fill
            fill_y = rms_to_y(rms)
            col    = bar_color(rms)
            if fill_y < BAR_BOT:
                cv2.rectangle(img, (x, fill_y), (x + BAR_W, BAR_BOT), col, -1)

            # Peak hold tick
            peak_y = rms_to_y(peak)
            cv2.line(img, (x, peak_y), (x + BAR_W, peak_y), (255, 255, 255), 2)
        else:
            # MUTE stripe
            cv2.line(img, (x, BAR_TOP + BAR_H//2),
                     (x + BAR_W, BAR_TOP + BAR_H//2), (80, 80, 200), 2)

    # Channel labels
    cv2.putText(img, "L", (X_L + 1, BAR_TOP - 6), FONT, 0.35, (180,180,180), 1, cv2.LINE_AA)
    cv2.putText(img, "R", (X_R + 1, BAR_TOP - 6), FONT, 0.35, (180,180,180), 1, cv2.LINE_AA)

    # dB scale ticks: -48, -24, -12, -6, 0
    for db_mark in [-48, -24, -12, -6, 0]:
        frac  = (db_mark + 60) / 60
        tick_y = int(BAR_BOT - frac * BAR_H)
        col   = (80, 80, 200) if db_mark == 0 else (80, 80, 80)
        cv2.line(img, (X_L - 3, tick_y), (X_R + BAR_W + 3, tick_y), col, 1)

    # Gain / mute label at bottom
    if state.audio_muted:
        label = "MUTE"
        lcol  = (80, 80, 200)
    else:
        sign = "+" if state.mic_gain_db >= 0 else ""
        label = f"{sign}{state.mic_gain_db}dB"
        lcol  = (180, 180, 180)
    cv2.putText(img, label, (X_L - 2, BAR_BOT + 14), FONT, 0.35, lcol, 1, cv2.LINE_AA)


def _draw_guides(img, w, h):
    """Draw rule-of-thirds lines and a centre crosshair."""
    col = (180, 180, 180)
    alpha = 0.2
    overlay = img.copy()
    # Rule of thirds
    for x in [w//3, 2*w//3]:
        cv2.line(overlay, (x, 0), (x, h), col, 1)
    for y in [h//3, 2*h//3]:
        cv2.line(overlay, (0, y), (w, y), col, 1)
    # Centre cross
    cx, cy = w//2, h//2
    cv2.line(overlay, (cx-20, cy), (cx+20, cy), col, 1)
    cv2.line(overlay, (cx, cy-20), (cx, cy+20), col, 1)
    cv2.addWeighted(overlay, alpha, img, 1-alpha, 0, img)


def _draw_histogram(img, w, h, gray=None):
    """Draw a small luminance histogram in the bottom-right corner."""
    # Compute histogram for the whole image (luminance approximation)
    if gray is None:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    hist = cv2.calcHist([gray], [0], None, [256], [0, 256])

    # Normalize to fit in the box height
    hist_h = 100
    cv2.normalize(hist, hist, 0, hist_h, cv2.NORM_MINMAX)

    # Draw parameters
    hist_w = 256
    margin = 20

    # Position: Bottom Right, above the bottom bar
    x_offset = w - hist_w - margin
    y_offset = h - hist_h - 50

    # Create a semi-transparent overlay
    overlay = img.copy()
    cv2.rectangle(overlay, (x_offset, y_offset), (x_offset + hist_w, y_offset + hist_h), (0, 0, 0), -1)

    # Convert histogram points to a polyline for faster drawing
    # Create an array of points (x, y)
    pts = np.column_stack((
        np.arange(x_offset, x_offset + 256),
        y_offset + hist_h - hist.flatten().astype(int)
    )).astype(np.int32)

    # Draw the histogram curve as a polyline
    cv2.polylines(overlay, [pts], isClosed=False, color=(200, 200, 200), thickness=1)

    # Optional: Fill the area under the curve
    # pts_fill = np.vstack([[x_offset, y_offset + hist_h], pts, [x_offset + 255, y_offset + hist_h]])
    # cv2.fillPoly(overlay, [pts_fill], color=(100, 100, 100))

    cv2.addWeighted(overlay, 0.6, img, 0.4, 0, img)


def _draw_format_menu(img, w, h, state):
    """Draw a centered list of formats, highlighting the selected one."""
    menu_w = 300
    menu_h = len(OUTPUT_FORMATS) * 30 + 20
    x = (w - menu_w) // 2
    y = (h - menu_h) // 2

    overlay = img.copy()
    cv2.rectangle(overlay, (x, y), (x + menu_w, y + menu_h), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.8, img, 0.2, 0, img)

    FONT = cv2.FONT_HERSHEY_SIMPLEX
    for i, fmt in enumerate(OUTPUT_FORMATS):
        color = (0, 255, 0) if i == state.output_format_idx else (180, 180, 180)
        thickness = 2 if i == state.output_format_idx else 1
        text = fmt["label"]
        cv2.putText(img, text, (x + 20, y + 30 * (i + 1)), FONT, 0.7, color, thickness, cv2.LINE_AA)


def _draw_help(img, w, h, font):
    """Overlay keyboard shortcut reference."""
    help_lines = [
        "R          Record / Stop",
        "E / D      Exposure +/-",
        "G / F      Gain (ISO) +/-",
        "W / S      White Balance +/-",
        "A          Toggle Auto Exposure",
        "B          Toggle Auto White Balance",
        "T          Toggle Autofocus (AF/MF)",
        "] / [      Focus Far / Near  (coarse)",
        ". / ,      Focus Far / Near  (fine)",
        "K          Toggle Focus Peaking",
        "L          Toggle Framing Guides",
        "J          Toggle Histogram",
        "M          Mute / Unmute mic",
        "+ / -      Mic gain +3 / -3 dB",
        "P          Cycle output format (H.264/H.265/ProRes…)",
        "H          Toggle this help",
        "Q / ESC    Quit",
    ]
    bx, by = 30, h // 2 - (len(help_lines) * 24) // 2
    for i, line in enumerate(help_lines):
        cv2.putText(img, line, (bx, by + i * 26),
                    font, 0.55, (0,0,0), 2, cv2.LINE_AA)
        cv2.putText(img, line, (bx, by + i * 26),
                    font, 0.55, (240,240,240), 1, cv2.LINE_AA)


# ─────────────────────────────────────────────
#  Headless Mode (Rich TUI)
# ─────────────────────────────────────────────
def run_headless(state: CameraState):
    if not RICH_OK:
        print("[ERROR] 'rich' not installed. Run: pip3 install rich")
        sys.exit(1)

    import termios, tty, select

    console = Console()
    detect_focus_range(state)
    detect_audio_device(state)
    meter = AudioMeter(state)
    meter.start()
    apply_camera_settings(state)

    def get_key():
        """Non-blocking single keypress. Returns char or None."""
        if select.select([sys.stdin], [], [], 0)[0]:
            return sys.stdin.read(1)
        return None

    def make_dashboard():
        now = datetime.datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
        rec_color = "bold red" if state.recording else "bold green"
        rec_label = f"● REC  {state.rec_timecode}" if state.recording else "○ STANDBY"

        status_table = Table(box=box.SIMPLE_HEAVY, show_header=False, padding=(0, 2))
        status_table.add_column("Key", style="dim")
        status_table.add_column("Value", style="bold white")
        status_table.add_row("Status",   f"[{rec_color}]{rec_label}[/]")
        status_table.add_row("Clip",     f"[cyan]{state.clip_name}[/]")
        status_table.add_row("Output",   str(state.output_dir))
        status_table.add_row("Time",     now)

        cam_table = Table(box=box.SIMPLE_HEAVY, show_header=False, padding=(0, 2))
        cam_table.add_column("Setting", style="dim")
        cam_table.add_column("Value",   style="bold yellow")
        cam_table.add_row("Resolution", state.resolution)
        cam_table.add_row("FPS",        str(state.fps))
        cam_table.add_row("Exposure",   f"{state.exposure}  ({state.shutter_angle:.0f}°)" +
                                         (" [AUTO]" if state.auto_exp else ""))
        cam_table.add_row("Gain/ISO",   f"~{state.gain * 10}" +
                                         (" [AUTO]" if False else ""))
        cam_table.add_row("White Bal",  f"{state.wb_temp}K" +
                                         (" [AUTO]" if state.auto_wb else ""))
        if state.auto_focus:
            cam_table.add_row("Focus",  "[green]AUTO[/green]")
        else:
            cam_table.add_row("Focus",  f"MANUAL  {state.focus_pct}%  (val {state.focus})")
        cam_table.add_row("Format",     f"{state.format_label}  [dim]({state.output_format['note']})[/dim]")
        cam_table.add_row("Device",     state.device)

        # Audio status with ASCII level meters
        if not state.audio_enabled:
            cam_table.add_row("Audio", "[dim]No mic detected[/dim]")
        else:
            def _ascii_bar(level, width=12):
                filled = int(min(level, 1.0) * width)
                bar    = "█" * filled + "░" * (width - filled)
                db     = 20 * (np.log10(max(level, 1e-6)) if NP_OK else -60)
                col    = "red" if db > -6 else ("yellow" if db > -18 else "green")
                return f"[{col}]{bar}[/]"
            if state.audio_muted:
                audio_str = "[bold red]MUTED[/bold red]"
            else:
                L = _ascii_bar(state.audio_levels[0] if state.audio_levels else 0)
                R = _ascii_bar(state.audio_levels[1] if len(state.audio_levels) > 1 else 0)
                sign = "+" if state.mic_gain_db >= 0 else ""
                audio_str = f"L {L}  R {R}  [{sign}{state.mic_gain_db}dB]"
            cam_table.add_row("Audio", audio_str)

        keys_table = Table(box=box.SIMPLE_HEAVY, show_header=False, padding=(0, 1))
        keys_table.add_column("Key",    style="bold cyan", width=10)
        keys_table.add_column("Action", style="dim white")
        keys_table.add_row("R", "Record / Stop")
        keys_table.add_row("E / D", "Exposure +/-")
        keys_table.add_row("G / F", "Gain (ISO) +/-")
        keys_table.add_row("W / S", "White Balance +/-")
        keys_table.add_row("A", "Auto Exposure")
        keys_table.add_row("B", "Auto WB")
        keys_table.add_row("T", "Toggle AF/MF")
        keys_table.add_row("] / [", "Focus far/near")
        keys_table.add_row(". / ,", "Focus fine")
        keys_table.add_row("M", "Mute mic")
        keys_table.add_row("+ / -", "Mic gain ±3dB")
        keys_table.add_row("P", "Output format")
        keys_table.add_row("Q", "Quit")

        layout = Table.grid(expand=True)
        layout.add_column()
        layout.add_column()
        layout.add_row(
            Panel(status_table, title="[bold]Status[/]", border_style="red" if state.recording else "green"),
            Panel(cam_table,    title="[bold]Camera Settings[/]", border_style="yellow"),
        )
        layout.add_row(
            Panel(keys_table,   title="[bold]Controls[/]", border_style="blue"),
            Panel(Text("OBSBOT Meet 2\nPi5 CineRig\n\nFootage saved to:\n" +
                       str(state.output_dir), justify="center"),
                  title="[bold]Info[/]", border_style="dim"),
        )
        return Panel(layout, title="[bold white on red]  ◉ OBSBOT CINERIG  [/]", border_style="white")

    # Switch terminal to raw mode for single keypress
    old_settings = termios.tcgetattr(sys.stdin)
    try:
        tty.setraw(sys.stdin.fileno())
        with Live(make_dashboard(), console=console, refresh_per_second=4) as live:
            while True:
                time.sleep(0.08)
                key = get_key()
                if key:
                    k = key.lower()
                    if k == 'q':
                        break
                    elif k == 'r':
                        if state.recording:
                            stop_recording(state)
                        else:
                            start_recording(state)
                    elif k == 'e':
                        state.exposure = min(state.exposure + 50, 10000)
                        if not state.auto_exp:
                            v4l2_set(state.device, V4L2_EXPOSURE, state.exposure)
                    elif k == 'd':
                        state.exposure = max(state.exposure - 50, 50)
                        if not state.auto_exp:
                            v4l2_set(state.device, V4L2_EXPOSURE, state.exposure)
                    elif k == 'g':
                        state.gain = min(state.gain + 10, 500)
                        v4l2_set(state.device, V4L2_GAIN, state.gain)
                    elif k == 'f':
                        state.gain = max(state.gain - 10, 0)
                        v4l2_set(state.device, V4L2_GAIN, state.gain)
                    elif k == 'w':
                        state.wb_temp = min(state.wb_temp + 100, 10000)
                        if not state.auto_wb:
                            v4l2_set(state.device, V4L2_WB_TEMP, state.wb_temp)
                    elif k == 's':
                        state.wb_temp = max(state.wb_temp - 100, 2000)
                        if not state.auto_wb:
                            v4l2_set(state.device, V4L2_WB_TEMP, state.wb_temp)
                    elif k == 'a':
                        state.auto_exp = not state.auto_exp
                        v4l2_set(state.device, V4L2_EXPOSURE_AUTO, 3 if state.auto_exp else 1)
                    elif k == 'b':
                        state.auto_wb = not state.auto_wb
                        v4l2_set(state.device, V4L2_WB_AUTO, 1 if state.auto_wb else 0)
                    elif k == 't':
                        state.auto_focus = not state.auto_focus
                        v4l2_set(state.device, V4L2_FOCUS_AUTO, 1 if state.auto_focus else 0)
                        if not state.auto_focus:
                            current = v4l2_get(state.device, V4L2_FOCUS_ABS)
                            if current is not None:
                                state.focus = current
                    elif k == ']':
                        if not state.auto_focus:
                            state.focus = min(state.focus + FOCUS_STEP_COARSE, state.focus_max)
                            v4l2_set(state.device, V4L2_FOCUS_ABS, state.focus)
                    elif k == '[':
                        if not state.auto_focus:
                            state.focus = max(state.focus - FOCUS_STEP_COARSE, FOCUS_MIN)
                            v4l2_set(state.device, V4L2_FOCUS_ABS, state.focus)
                    elif k == '.':
                        if not state.auto_focus:
                            state.focus = min(state.focus + FOCUS_STEP_FINE, state.focus_max)
                            v4l2_set(state.device, V4L2_FOCUS_ABS, state.focus)
                    elif k == ',':
                        if not state.auto_focus:
                            state.focus = max(state.focus - FOCUS_STEP_FINE, FOCUS_MIN)
                            v4l2_set(state.device, V4L2_FOCUS_ABS, state.focus)
                    elif k == 'p':
                        state.output_format_idx = (state.output_format_idx + 1) % N_FORMATS
                    elif k == 'm':
                        state.audio_muted = not state.audio_muted
                    elif k in ('+', '='):
                        state.mic_gain_db = min(state.mic_gain_db + 3, 20)
                    elif k == '-':
                        state.mic_gain_db = max(state.mic_gain_db - 3, -20)

                live.update(make_dashboard())

    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
        meter.stop()
        if state.recording:
            stop_recording(state)
        state.save_config()


# ─────────────────────────────────────────────
#  Diagnostics
# ─────────────────────────────────────────────
def run_diagnostics(state: CameraState):
    print("\n── OBSBOT CineRig Diagnostics ──\n")

    # Check device exists
    if os.path.exists(state.device):
        print(f"✓ Camera device found: {state.device}")
    else:
        print(f"✗ Camera device NOT found: {state.device}")
        print("  Try: ls /dev/video* to find the correct device")

    # Check ffmpeg
    r = subprocess.run(["ffmpeg", "-version"], capture_output=True)
    if r.returncode == 0:
        ver = r.stdout.decode().split('\n')[0]
        print(f"✓ FFmpeg: {ver}")
    else:
        print("✗ FFmpeg not found — install with: sudo apt install ffmpeg")

    # Check v4l2-ctl
    r = subprocess.run(["v4l2-ctl", "--version"], capture_output=True)
    if r.returncode == 0:
        print(f"✓ v4l2-ctl found")
    else:
        print("✗ v4l2-ctl not found — install with: sudo apt install v4l-utils")

    # List controls
    if os.path.exists(state.device):
        print(f"\n── Camera Controls ({state.device}) ──\n")
        raw = v4l2_list_controls(state.device)
        print(raw)

        # Specifically call out focus support
        if "focus_absolute" in raw:
            print("✓ Manual focus (focus_absolute) supported")
        else:
            print("△ focus_absolute not found — manual focus keys will have no effect")
        if "focus_automatic_continuous" in raw:
            print("✓ Autofocus toggle supported")
        else:
            print("△ focus_automatic_continuous not found — try 'focus_auto' in v4l2-ctl output above")

    # Check output dir writable
    try:
        state.output_dir.mkdir(parents=True, exist_ok=True)
        print(f"✓ Output directory OK: {state.output_dir}")
    except Exception as e:
        print(f"✗ Output directory error: {e}")

    # Audio devices
    print(f"\n── Audio Capture Devices ──\n")
    print(list_audio_devices() or "  None found (is 'alsa-utils' installed?)")

    if SD_OK:
        print("── sounddevice input devices ──")
        try:
            for i, dev in enumerate(sd.query_devices()):
                if dev["max_input_channels"] > 0:
                    print(f"  [{i}] {dev['name']}  ({dev['max_input_channels']}ch)")
        except Exception as e:
            print(f"  Error: {e}")
    else:
        print("△ sounddevice not installed — level meters won't work")
        print("  Install: pip3 install sounddevice")

    # Check OpenCV
    print(f"{'✓' if CV2_OK else '✗'} OpenCV (cv2): {'found' if CV2_OK else 'not found  →  pip3 install opencv-python-headless'}")
    print(f"{'✓' if RICH_OK else '✗'} Rich TUI:     {'found' if RICH_OK else 'not found  →  pip3 install rich'}")
    print(f"{'✓' if NP_OK  else '✗'} NumPy:        {'found' if NP_OK else 'not found  →  pip3 install numpy'}")
    print(f"{'✓' if SD_OK  else '✗'} sounddevice:  {'found' if SD_OK else 'not found  →  pip3 install sounddevice'}")
    print()


# ─────────────────────────────────────────────
#  Entry Point
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="OBSBOT Meet 2 — Pi5 CineRig Capture Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 obsbot_capture.py --mode gui
  python3 obsbot_capture.py --mode headless
  python3 obsbot_capture.py --mode diag
  python3 obsbot_capture.py --mode gui --device /dev/video2 --fps 24
  python3 obsbot_capture.py --mode gui --profile 1   (LT)
        """
    )
    parser.add_argument("--mode",    choices=["gui","headless","diag"], default="gui",
                        help="gui=preview+record  headless=TUI only  diag=diagnostics")
    parser.add_argument("--device",  default=DEFAULT_DEVICE,
                        help=f"V4L2 device (default: {DEFAULT_DEVICE})")
    parser.add_argument("--fps",     type=int, default=None,
                        help="Frame rate (default: from saved config or 30)")
    parser.add_argument("--res",     default=None,
                        help="Resolution WxH (default: 3840x2160)")
    parser.add_argument("--profile", type=int, choices=[0,1,2,3], default=None,
                        help="(Legacy) ProRes profile — use --format instead")
    parser.add_argument("--format", default=None,
                        choices=[f["key"] for f in OUTPUT_FORMATS],
                        help="Output format: " + ", ".join(
                            f"{f['key']} ({f['label']})" for f in OUTPUT_FORMATS))
    parser.add_argument("--outdir",  default=None,
                        help="Output directory (default: ~/obsbot_footage)")
    parser.add_argument("--audio-device", default=None,
                        help="ALSA audio device override, e.g. hw:2,0 (default: auto-detect OBSBOT mic)")
    parser.add_argument("--no-audio", action="store_true",
                        help="Disable audio recording entirely")
    parser.add_argument("--hat", action="store_true",
                        help="Enable Waveshare 1.44inch LCD HAT display and controls")

    args = parser.parse_args()

    state = CameraState()
    state.device = args.device
    if args.fps:     state.fps             = args.fps
    if args.res:     state.resolution      = args.res
    if args.profile is not None:
        # Legacy: map old ProRes profile numbers to new format keys
        legacy_map = {0: "prores_proxy", 1: "prores_lt", 2: "prores_lt", 3: "prores_hq"}
        key = legacy_map.get(args.profile, "prores_hq")
        state.output_format_idx = next(
            (i for i, f in enumerate(OUTPUT_FORMATS) if f["key"] == key), 0)
    if args.format:
        state.output_format_idx = next(
            (i for i, f in enumerate(OUTPUT_FORMATS) if f["key"] == args.format), 0)
    if args.outdir:  state.output_dir      = Path(args.outdir)
    if args.audio_device: state.audio_device = args.audio_device
    if args.no_audio:     state.audio_enabled = False

    # Start HAT UI if requested
    hat = None
    if args.hat:
        if HAT_OK:
            hat = HatUI(state)
            hat.start()
        else:
            print("[HAT] hat_ui.py not found — place it alongside obsbot_capture.py")

    def _exit(sig, frame):
        if state.recording:
            stop_recording(state)
        if hat:
            hat.stop()
        state.save_config()
        sys.exit(0)

    signal.signal(signal.SIGINT,  _exit)
    signal.signal(signal.SIGTERM, _exit)

    if args.mode == "diag":
        run_diagnostics(state)
    elif args.mode == "gui":
        run_gui(state, hat=hat)
    elif args.mode == "headless":
        run_headless(state)


if __name__ == "__main__":
    main()
