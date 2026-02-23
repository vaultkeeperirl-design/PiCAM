#!/usr/bin/env python3
"""
hat_ui.py — Waveshare 1.44inch LCD HAT — OBSBOT CineRig viewfinder
ST7735S 128×128 SPI display + 5-way joystick + 3 buttons.

8-page viewfinder — page 0 is a full-screen live camera feed:
  LIVE · STATUS · EXPOSURE · WHITE BAL · FOCUS · AUDIO · FORMAT · STORAGE

Navigation:
  JOY ← / →   Previous / next page
  JOY ↑ / ↓   Adjust active value  (key-repeat when held)
  JOY PRESS    Contextual smart action
  KEY1 (21)    Record / Stop  — works on EVERY page
  KEY2 (20)    Toggle AUTO for current page's primary setting
  KEY3 (16)    On LIVE page: toggle HUD overlay
               On other pages: preset / secondary / fine-step

GPIO (BCM): KEY1=21 KEY2=20 KEY3=16
            JOY_UP=6 JOY_DOWN=19 JOY_LEFT=5 JOY_RIGHT=26 JOY_PRESS=13
            SPI: RST=27 DC=25 CS=CE0 BL=24

Standalone test:  python3 hat_ui.py
With main tool:   python3 obsbot_capture.py --mode headless --hat
"""

__version__ = "0.1.0"

import time
import threading
import os
import sys
import math
from pathlib import Path

# ─────────────────────────────────────────────
#  Optional hardware / library imports
# ─────────────────────────────────────────────
try:
    import RPi.GPIO as GPIO
    GPIO_OK = True
except ImportError:
    GPIO_OK = False

try:
    import spidev
    SPI_OK = True
except ImportError:
    SPI_OK = False

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_OK = True
except ImportError:
    PIL_OK = False

try:
    import cv2
    CV2_OK = True
except ImportError:
    CV2_OK = False

try:
    import numpy as np
    NP_OK = True
except ImportError:
    NP_OK = False

# Import format table from main module (graceful — works standalone too)
try:
    from obsbot_capture import OUTPUT_FORMATS, N_FORMATS
except ImportError:
    OUTPUT_FORMATS = [{"key":"prores_hq","label":"ProRes HQ","ext":"mov",
                       "note":"~220Mbps","est_mbps":220,"cpu_warn":False}]
    N_FORMATS = 1

# ─────────────────────────────────────────────
#  GPIO Pin Definitions (BCM)
# ─────────────────────────────────────────────
PIN_KEY1      = 21    # Record / Stop
PIN_KEY2      = 20    # Toggle AUTO
PIN_KEY3      = 16    # Overlay toggle (LIVE page) / secondary
PIN_JOY_UP    = 6
PIN_JOY_DOWN  = 19
PIN_JOY_LEFT  = 5     # Previous page
PIN_JOY_RIGHT = 26    # Next page
PIN_JOY_PRESS = 13    # Contextual action

ALL_INPUT_PINS = [
    PIN_KEY1, PIN_KEY2, PIN_KEY3,
    PIN_JOY_UP, PIN_JOY_DOWN, PIN_JOY_LEFT, PIN_JOY_RIGHT, PIN_JOY_PRESS,
]

# ─────────────────────────────────────────────
#  ST7735S SPI Display Driver
# ─────────────────────────────────────────────
SWRESET=0x01; SLPOUT=0x11; NORON=0x13; DISPON=0x29
CASET=0x2A;   RASET=0x2B;  RAMWR=0x2C; MADCTL=0x36; COLMOD=0x3A
FRMCTR1=0xB1; FRMCTR2=0xB2; FRMCTR3=0xB3; INVCTR=0xB4
PWCTR1=0xC0;  PWCTR2=0xC1; PWCTR3=0xC2; PWCTR4=0xC3; PWCTR5=0xC4
VMCTR1=0xC5;  GMCTRP1=0xE0; GMCTRN1=0xE1

PIN_RST=27; PIN_DC=25; PIN_BL=24
LCD_W=128; LCD_H=128; COL_OFFSET=2


def _rgb565(r, g, b):
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


class ST7735S:
    def __init__(self):
        if not GPIO_OK: raise RuntimeError("RPi.GPIO not available")
        if not SPI_OK:  raise RuntimeError("spidev not available")
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        for p in [PIN_RST, PIN_DC, PIN_BL]:
            GPIO.setup(p, GPIO.OUT)
        self.spi = spidev.SpiDev()
        self.spi.open(0, 0)
        self.spi.max_speed_hz = 40_000_000
        self.spi.mode = 0
        self._init_display()
        self.backlight(True)

    def _cmd(self, c):
        GPIO.output(PIN_DC, 0); self.spi.writebytes([c])

    def _data(self, d):
        GPIO.output(PIN_DC, 1)
        d = [d] if isinstance(d, int) else list(d)
        for i in range(0, len(d), 4096): self.spi.writebytes(d[i:i+4096])

    def _reset(self):
        GPIO.output(PIN_RST, 1); time.sleep(0.01)
        GPIO.output(PIN_RST, 0); time.sleep(0.01)
        GPIO.output(PIN_RST, 1); time.sleep(0.12)

    def _init_display(self):
        self._reset()
        self._cmd(SWRESET); time.sleep(0.15)
        self._cmd(SLPOUT);  time.sleep(0.5)
        self._cmd(FRMCTR1); self._data([0x01,0x2C,0x2D])
        self._cmd(FRMCTR2); self._data([0x01,0x2C,0x2D])
        self._cmd(FRMCTR3); self._data([0x01,0x2C,0x2D,0x01,0x2C,0x2D])
        self._cmd(INVCTR);  self._data(0x07)
        self._cmd(PWCTR1);  self._data([0xA2,0x02,0x84])
        self._cmd(PWCTR2);  self._data(0xC5)
        self._cmd(PWCTR3);  self._data([0x0A,0x00])
        self._cmd(PWCTR4);  self._data([0x8A,0x2A])
        self._cmd(PWCTR5);  self._data([0x8A,0xEE])
        self._cmd(VMCTR1);  self._data(0x0E)
        self._cmd(MADCTL);  self._data(0xC8)
        self._cmd(COLMOD);  self._data(0x05)
        self._cmd(GMCTRP1)
        self._data([0x02,0x1C,0x07,0x12,0x37,0x32,0x29,0x2D,
                    0x29,0x25,0x2B,0x39,0x00,0x01,0x03,0x10])
        self._cmd(GMCTRN1)
        self._data([0x03,0x1D,0x07,0x06,0x2E,0x2C,0x29,0x2D,
                    0x2E,0x2E,0x37,0x3F,0x00,0x00,0x02,0x10])
        self._cmd(NORON); time.sleep(0.01)
        self._cmd(DISPON); time.sleep(0.1)

    def backlight(self, on):
        GPIO.output(PIN_BL, 1 if on else 0)

    def set_window(self, x0, y0, x1, y1):
        x0+=COL_OFFSET; x1+=COL_OFFSET
        self._cmd(CASET); self._data([0x00,x0,0x00,x1])
        self._cmd(RASET); self._data([0x00,y0,0x00,y1])
        self._cmd(RAMWR)

    def display_image(self, img):
        if img.size != (LCD_W, LCD_H):
            img = img.resize((LCD_W, LCD_H))
        self.set_window(0, 0, LCD_W-1, LCD_H-1)
        px  = img.convert("RGB").tobytes()

        if NP_OK:
            # Vectorized numpy implementation (approx 100x faster)
            arr = np.frombuffer(px, dtype=np.uint8).reshape(-1, 3)
            r = arr[:, 0].astype(np.uint16)
            g = arr[:, 1].astype(np.uint16)
            b = arr[:, 2].astype(np.uint16)
            v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            # Big Endian: High byte first
            res = np.empty((arr.shape[0], 2), dtype=np.uint8)
            res[:, 0] = (v >> 8).astype(np.uint8)
            res[:, 1] = (v & 0xFF).astype(np.uint8)
            buf = res.tobytes()
        else:
            buf = bytearray(LCD_W * LCD_H * 2)
            for i in range(LCD_W * LCD_H):
                r=px[i*3]; g=px[i*3+1]; b=px[i*3+2]
                v=_rgb565(r,g,b)
                buf[i*2]=(v>>8)&0xFF; buf[i*2+1]=v&0xFF

        GPIO.output(PIN_DC, 1)
        for i in range(0, len(buf), 4096):
            self.spi.writebytes(list(buf[i:i+4096]))

    def fill(self, color=(0,0,0)):
        self.display_image(Image.new("RGB",(LCD_W,LCD_H),color))

    def close(self):
        self.backlight(False); self.spi.close()


# ─────────────────────────────────────────────
#  Colour palette
# ─────────────────────────────────────────────
C_BLACK   = (0,   0,   0)
C_WHITE   = (255, 255, 255)
C_RED     = (220, 40,  40)
C_RED_DIM = (80,  10,  10)
C_GREEN   = (40,  210, 80)
C_AMBER   = (230, 160, 0)
C_CYAN    = (0,   200, 220)
C_MAGENTA = (200, 50,  200)
C_DGRAY   = (28,  28,  38)
C_MGRAY   = (85,  85,  100)
C_LGRAY   = (160, 160, 175)
C_BG      = (8,   8,   16)
C_BAR_BG  = (25,  25,  40)
C_TOPBAR  = (18,  18,  30)
C_OVERLAY = (0,   0,   0,  160)   # RGBA — used for semi-transparent overlay panels

PAGES = ["LIVE", "STATUS", "EXPOSURE", "WHITE BAL", "FOCUS", "DISPLAY", "AUDIO", "FORMAT", "STORAGE"]
N_PAGES = len(PAGES)
PAGE_COLORS = [C_RED, C_WHITE, C_AMBER, C_CYAN, C_GREEN, C_CYAN, C_GREEN, C_MAGENTA, C_LGRAY]


# ─────────────────────────────────────────────
#  Frame Grabber — live camera feed for HAT
# ─────────────────────────────────────────────
class FrameGrabber:
    """
    Provides 128x128 PIL frames for the HAT live view.

    In GUI mode:  GUI calls feed_frame(bgr) each loop — no second V4L2 open.
    In headless:  Opens the camera itself at low res after a delay.
    """
    PREVIEW_W = 320
    PREVIEW_H = 240

    def __init__(self, device: str):
        self.device      = device
        self._lock       = threading.Lock()
        self._stop       = threading.Event()
        self._thread     = None
        self._frame      = None
        self._ok         = False
        self._fed        = False
        self._placeholder = self._make_placeholder()

    def _make_placeholder(self):
        img  = Image.new("RGB", (LCD_W, LCD_H), C_BG)
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, LCD_W-1, LCD_H-1], outline=C_MGRAY)
        draw.line([0, 0, LCD_W, LCD_H], fill=(40,40,60), width=1)
        draw.line([LCD_W, 0, 0, LCD_H], fill=(40,40,60), width=1)
        draw.rectangle([20, 52, 108, 68], fill=C_TOPBAR)
        draw.text((24, 54), "STARTING...", fill=C_MGRAY)
        return img

    def feed_frame(self, bgr_frame):
        """Called by the GUI each frame — converts and stores as PIL 128x128."""
        if bgr_frame is None or not CV2_OK:
            return
        try:
            rgb  = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
            h, w = rgb.shape[:2]
            sq   = min(h, w)
            y0   = (h - sq) // 2
            x0   = (w - sq) // 2
            pil  = Image.fromarray(
                rgb[y0:y0+sq, x0:x0+sq]
            ).resize((LCD_W, LCD_H), Image.BILINEAR)
            with self._lock:
                self._frame = pil
                self._ok    = True
                self._fed   = True
        except Exception:
            pass

    def start(self):
        """Start background thread — it waits for feed_frame() before opening camera."""
        if not CV2_OK:
            print("[HAT] cv2 not found — live preview disabled")
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="FrameGrabber")
        self._thread.start()

    def _run(self):
        # Wait up to 15s for GUI to call feed_frame() first
        deadline = time.time() + 15.0
        while time.time() < deadline and not self._stop.is_set():
            with self._lock:
                if self._fed:
                    # GUI is feeding us — just idle, feed_frame() does the work
                    while not self._stop.is_set():
                        time.sleep(0.1)
                    return
            time.sleep(0.1)

        if self._stop.is_set():
            return

        # Headless mode — open camera ourselves
        print(f"[HAT] Headless: opening {self.device} @ {self.PREVIEW_W}x{self.PREVIEW_H}")
        cap = cv2.VideoCapture(self.device, cv2.CAP_V4L2)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  self.PREVIEW_W)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.PREVIEW_H)
        cap.set(cv2.CAP_PROP_FPS, 15)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not cap.isOpened():
            print(f"[HAT] Cannot open {self.device} — placeholder only")
            cap.release()
            return
        while not self._stop.is_set():
            ret, frame = cap.read()
            if ret:
                self.feed_frame(frame)
            else:
                time.sleep(0.05)
        cap.release()

    def get(self) -> "Image.Image":
        with self._lock:
            return self._frame.copy() if self._frame is not None else self._placeholder.copy()

    @property
    def ready(self) -> bool:
        return self._ok

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)


# ─────────────────────────────────────────────
#  GPIO Input Handler
# ─────────────────────────────────────────────
class HatInput:
    DEBOUNCE_MS    = 70
    HOLD_DELAY_MS  = 400
    HOLD_REPEAT_MS = 110

    def __init__(self):
        if not GPIO_OK: raise RuntimeError("RPi.GPIO not available")
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        for pin in ALL_INPUT_PINS:
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        self._last  = {p: True for p in ALL_INPUT_PINS}
        self._ptime = {p: 0.0  for p in ALL_INPUT_PINS}
        self._rtime = {p: 0.0  for p in ALL_INPUT_PINS}
        self._etime = {p: 0.0  for p in ALL_INPUT_PINS}

    def get_events(self):
        now    = time.time()
        events = []
        repeat_pins = {PIN_JOY_UP, PIN_JOY_DOWN}

        for pin in ALL_INPUT_PINS:
            pressed = (GPIO.input(pin) == GPIO.LOW)
            was     = not self._last[pin]
            if pressed and not was:
                if (now - self._etime[pin]) * 1000 > self.DEBOUNCE_MS:
                    events.append((pin, 'press'))
                    self._ptime[pin] = self._rtime[pin] = self._etime[pin] = now
            elif pressed and was and pin in repeat_pins:
                held_ms   = (now - self._ptime[pin]) * 1000
                repeat_ms = (now - self._rtime[pin]) * 1000
                if held_ms > self.HOLD_DELAY_MS and repeat_ms > self.HOLD_REPEAT_MS:
                    events.append((pin, 'repeat'))
                    self._rtime[pin] = now
            self._last[pin] = (not pressed)  # True=released
        return events


# ─────────────────────────────────────────────
#  Drawing helpers
# ─────────────────────────────────────────────
def _bar(draw, x, y, w, h, frac, fg, bg=C_BAR_BG, outline=None):
    frac = max(0.0, min(1.0, frac))
    draw.rectangle([x, y, x+w, y+h], fill=bg)
    filled = int(frac * w)
    if filled > 0:
        draw.rectangle([x, y, x+filled, y+h], fill=fg)
    if outline:
        draw.rectangle([x, y, x+w, y+h], outline=outline)


def _db_bar(draw, x, y, w, h, level):
    """Three-zone dBFS audio level bar."""
    if level <= 0:
        draw.rectangle([x, y, x+w, y+h], fill=C_BAR_BG); return
    db   = max(-60, min(0, 20*math.log10(max(level, 1e-6))))
    frac = (db+60)/60
    fill = int(frac*w)
    g_e  = int(w*0.60); a_e = int(w*0.80)
    draw.rectangle([x, y, x+w, y+h], fill=C_BAR_BG)
    if fill > 0:
        draw.rectangle([x, y, x+min(fill,g_e), y+h], fill=C_GREEN)
    if fill > g_e:
        draw.rectangle([x+g_e, y, x+min(fill,a_e), y+h], fill=C_AMBER)
    if fill > a_e:
        draw.rectangle([x+a_e, y, x+fill, y+h], fill=C_RED)
    if 0 < fill < w:
        draw.line([x+fill, y, x+fill, y+h], fill=C_WHITE, width=1)


def _dark_box(img, x, y, w, h, alpha=180):
    """
    Composite a dark semi-transparent rectangle onto a PIL image.
    Used for overlay panels on top of live video.
    """
    overlay = Image.new("RGBA", img.size, (0,0,0,0))
    draw    = ImageDraw.Draw(overlay)
    draw.rectangle([x, y, x+w, y+h], fill=(0,0,0,alpha))
    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


# ─────────────────────────────────────────────
#  HAT UI  — main class
# ─────────────────────────────────────────────
class HatUI:
    """
    8-page cinema viewfinder.

    Page 0 (LIVE) shows a full 128×128 live camera feed.
    KEY3 on the LIVE page toggles the HUD overlay on/off:
      - Overlay ON:  timecode, REC dot, audio meters, focus bar, page strip
      - Overlay OFF: clean unobstructed video (one tiny corner REC dot remains)

    All other pages show the HUD content with a small live thumbnail
    in the bottom-right corner so you always have eyes on the shot.
    """

    def __init__(self, state):
        self.state    = state
        self.display  = None
        self.inp      = None
        self.grabber  = None
        self._stop    = threading.Event()
        self._thread  = None
        self._page    = 1       # start on STATUS; navigate left for LIVE
        self._sub     = 0       # sub-cursor within a page

        # Live view HUD overlay toggle
        self._show_hud = True   # KEY3 on LIVE page toggles this

        # Flash message
        self._flash_msg = ""
        self._flash_t   = 0.0
        self._flash_col = C_WHITE

        # Fonts
        self._font_lg = self._font_md = self._font_sm = self._font_xs = None

    # ─── Lifecycle ────────────────────────────────────────────────────
    def _load_fonts(self):
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeMonoBold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeMono.ttf",
        ]
        path = next((p for p in candidates if os.path.exists(p)), None)
        try:
            if path:
                self._font_lg = ImageFont.truetype(path, 16)
                self._font_md = ImageFont.truetype(path, 12)
                self._font_sm = ImageFont.truetype(path, 10)
                self._font_xs = ImageFont.truetype(path, 8)
                return
        except Exception:
            pass
        d = ImageFont.load_default()
        self._font_lg = self._font_md = self._font_sm = self._font_xs = d

    def start(self):
        missing = [n for n, ok in [("RPi.GPIO",GPIO_OK),("spidev",SPI_OK),("Pillow",PIL_OK)] if not ok]
        if missing:
            print(f"[HAT] Disabled — install: pip3 install {' '.join(missing)}")
            return False
        try:
            self.display = ST7735S()
            self.inp     = HatInput()
            self._load_fonts()
            self.display.fill(C_BG)

            # Reusable PIL buffers to avoid allocation loop
            self._canvas = Image.new("RGB", (LCD_W, LCD_H), C_BG)
            self._draw   = ImageDraw.Draw(self._canvas)
            self._thumb_border = Image.new("RGB", (42, 32), C_MGRAY)

            # Grabber created here but NOT started — the GUI calls
            # grabber.start() after it has its first frame, avoiding conflict
            self.grabber = FrameGrabber(self.state.device)

            print("[HAT] Display online")
            print("      JOY ←/→ = pages  |  KEY3 on LIVE page = overlay toggle")
        except Exception as e:
            print(f"[HAT] Init failed: {e}")
            print("      Check: SPI enabled? sudo raspi-config → Interfaces → SPI")
            return False

        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="HatUI")
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()
        if self._thread: self._thread.join(timeout=3)
        if self.grabber: self.grabber.stop()
        if self.display:
            try:
                self.display.fill(C_BLACK)
                self.display.backlight(False)
                self.display.close()
            except Exception: pass
        try: GPIO.cleanup()
        except Exception: pass

    def flash(self, msg, color=C_WHITE):
        self._flash_msg = msg
        self._flash_t   = time.time()
        self._flash_col = color

    # ─── V4L2 / main module lazy import ───────────────────────────────
    def _oc(self):
        try:
            import obsbot_capture as oc
            return oc
        except ImportError:
            return None

    # ─── Input dispatch ───────────────────────────────────────────────
    def _handle_input(self):
        s   = self.state
        oc  = self._oc()
        dev = s.device

        events = self.inp.get_events()
        for pin, etype in events:

            # KEY1 — Record / Stop — sets trigger, GUI loop acts on it
            if pin == PIN_KEY1 and etype == 'press':
                print(f"[HAT] KEY1 — toggling record (currently {s.recording})")
                s.record_trigger = True
                self.flash("■  STOP" if s.recording else "●  REC",
                           C_WHITE if s.recording else C_RED)

            # JOY LEFT — previous page
            elif pin == PIN_JOY_LEFT and etype == 'press':
                self._page = (self._page - 1) % N_PAGES
                self._sub  = 0
                print(f"[HAT] JOY LEFT → page {self._page} ({PAGES[self._page]})")
                self.flash(f"◀  {PAGES[self._page]}", PAGE_COLORS[self._page])

            # JOY RIGHT — next page
            elif pin == PIN_JOY_RIGHT and etype == 'press':
                self._page = (self._page + 1) % N_PAGES
                self._sub  = 0
                print(f"[HAT] JOY RIGHT → page {self._page} ({PAGES[self._page]})")
                self.flash(f"▶  {PAGES[self._page]}", PAGE_COLORS[self._page])

            # KEY2 — toggle AUTO
            elif pin == PIN_KEY2 and etype == 'press':
                self._toggle_auto(s, oc, dev)

            # KEY3 — overlay toggle on LIVE, secondary elsewhere
            elif pin == PIN_KEY3 and etype == 'press':
                if PAGES[self._page] == "LIVE":
                    self._show_hud = not self._show_hud
                    self.flash("HUD ON" if self._show_hud else "CLEAN", C_WHITE)
                else:
                    self._key3(s, oc, dev)

            # JOY UP/DOWN — adjust value (with repeat)
            elif pin == PIN_JOY_UP:
                self._adjust(s, oc, dev, +1)
            elif pin == PIN_JOY_DOWN:
                self._adjust(s, oc, dev, -1)

            # JOY PRESS — contextual smart action
            elif pin == PIN_JOY_PRESS and etype == 'press':
                self._joy_press(s, oc, dev)

    # ─── KEY2: toggle AUTO ────────────────────────────────────────────
    def _toggle_auto(self, s, oc, dev):
        page = PAGES[self._page]
        if page in ("LIVE", "STATUS"):
            # On LIVE/STATUS, KEY2 = quick AE toggle
            s.auto_exp = not s.auto_exp
            if oc: oc.v4l2_set(dev, oc.V4L2_EXPOSURE_AUTO, 3 if s.auto_exp else 1)
            self.flash("AE  ON" if s.auto_exp else "AE  MAN", C_AMBER)
        elif page == "EXPOSURE":
            s.auto_exp = not s.auto_exp
            if oc: oc.v4l2_set(dev, oc.V4L2_EXPOSURE_AUTO, 3 if s.auto_exp else 1)
            self.flash("AE  ON" if s.auto_exp else "AE  MAN", C_AMBER)
        elif page == "WHITE BAL":
            s.auto_wb = not s.auto_wb
            if oc: oc.v4l2_set(dev, oc.V4L2_WB_AUTO, 1 if s.auto_wb else 0)
            self.flash("AWB ON" if s.auto_wb else "WB  MAN", C_CYAN)
        elif page == "FOCUS":
            s.auto_focus = not s.auto_focus
            if oc:
                oc.v4l2_set(dev, oc.V4L2_FOCUS_AUTO, 1 if s.auto_focus else 0)
                if not s.auto_focus:
                    cur = oc.v4l2_get(dev, oc.V4L2_FOCUS_ABS)
                    if cur is not None: s.focus = cur
            self.flash("AF  ON" if s.auto_focus else "MF", C_GREEN)
        elif page == "DISPLAY":
            # KEY2 on DISPLAY page toggles the selected item
            if self._sub == 0:
                s.show_guides = not getattr(s, 'show_guides', True)
                self.flash("GUIDES " + ("ON" if s.show_guides else "OFF"), C_CYAN)
            elif self._sub == 1:
                s.show_histogram = not getattr(s, 'show_histogram', False)
                self.flash("HISTO " + ("ON" if s.show_histogram else "OFF"), C_CYAN)
            elif self._sub == 2:
                s.focus_peaking = not getattr(s, 'focus_peaking', False)
                self.flash("PEAK " + ("ON" if s.focus_peaking else "OFF"), C_CYAN)
        elif page == "AUDIO":
            s.audio_muted = not s.audio_muted
            self.flash("MUTED" if s.audio_muted else "MIC ON",
                       C_RED if s.audio_muted else C_GREEN)
        elif page == "FORMAT":
            s.output_format_idx = (s.output_format_idx + 1) % N_FORMATS
            self.flash(OUTPUT_FORMATS[s.output_format_idx]["label"], C_MAGENTA)

    # ─── KEY3: secondary ──────────────────────────────────────────────
    def _key3(self, s, oc, dev):
        page = PAGES[self._page]
        if page == "STATUS":
            # Cycle format from overview
            s.output_format_idx = (s.output_format_idx + 1) % N_FORMATS
            self.flash(OUTPUT_FORMATS[s.output_format_idx]["label"], C_MAGENTA)
        elif page == "EXPOSURE":
            self._sub = 1 - self._sub
            self.flash("→  ISO" if self._sub else "→  Shutter", C_AMBER)
        elif page == "WHITE BAL":
            presets = [3200, 4300, 5600, 6500, 7500]
            names   = {3200:"Tungsten",4300:"Shade",5600:"Daylight",
                       6500:"Overcast",7500:"Open sky"}
            dists   = [abs(p - s.wb_temp) for p in presets]
            idx     = (dists.index(min(dists)) + 1) % len(presets)
            s.wb_temp = presets[idx]
            if not s.auto_wb and oc: oc.v4l2_set(dev, oc.V4L2_WB_TEMP, s.wb_temp)
            self.flash(names[s.wb_temp], C_CYAN)
        elif page == "FOCUS":
            s.focus_peaking = not getattr(s, 'focus_peaking', False)
            self.flash("PEAK ON" if s.focus_peaking else "PEAK OFF", C_GREEN)
        elif page == "DISPLAY":
            # KEY3 cycles selection
            self._sub = (self._sub + 1) % 3
        elif page == "AUDIO":
            s.mic_gain_db = 0
            self.flash("GAIN  0dB", C_GREEN)
        elif page == "FORMAT":
            # KEY3 on FORMAT cycles resolution
            res_list = ["3840x2160","1920x1080","1280x720"]
            try:    idx = res_list.index(s.resolution)
            except: idx = 0
            s.resolution = res_list[(idx+1) % len(res_list)]
            label = s.resolution.replace("3840x2160","4K").replace("1920x1080","1080p").replace("1280x720","720p")
            self.flash(label, C_MAGENTA)
        elif page == "FORMAT_FPS":  # internal placeholder (not reached)
            pass
        elif page == "STORAGE":
            s.clip_number = 1
            self.flash("Clip → 0001", C_LGRAY)

    # ─── JOY UP/DOWN: adjust ──────────────────────────────────────────
    def _adjust(self, s, oc, dev, direction):
        page = PAGES[self._page]
        if page == "EXPOSURE":
            if self._sub == 0 and not s.auto_exp:
                step = 50 if s.exposure < 2000 else 200
                s.exposure = max(50, min(10000, s.exposure + direction*step))
                if oc: oc.v4l2_set(dev, oc.V4L2_EXPOSURE, s.exposure)
            elif self._sub == 1:
                s.gain = max(0, min(500, s.gain + direction*10))
                if oc: oc.v4l2_set(dev, oc.V4L2_GAIN, s.gain)
        elif page == "WHITE BAL" and not s.auto_wb:
            s.wb_temp = max(2000, min(10000, s.wb_temp + direction*100))
            if oc: oc.v4l2_set(dev, oc.V4L2_WB_TEMP, s.wb_temp)
        elif page == "FOCUS" and not s.auto_focus and oc:
            step = oc.FOCUS_STEP_COARSE
            s.focus = max(oc.FOCUS_MIN, min(s.focus_max, s.focus + direction*step))
            oc.v4l2_set(dev, oc.V4L2_FOCUS_ABS, s.focus)
        elif page == "DISPLAY":
            # JOY UP/DOWN changes selection
            if direction > 0: self._sub = (self._sub + 1) % 3
            else:             self._sub = (self._sub - 1) % 3
        elif page == "AUDIO":
            s.mic_gain_db = max(-20, min(20, s.mic_gain_db + direction*3))
        elif page == "FORMAT":
            # Up/down cycles through all output formats
            s.output_format_idx = (s.output_format_idx + direction) % N_FORMATS
            self.flash(OUTPUT_FORMATS[s.output_format_idx]["label"], C_MAGENTA)

    # ─── JOY PRESS: contextual ────────────────────────────────────────
    def _joy_press(self, s, oc, dev):
        page = PAGES[self._page]
        if page in ("LIVE", "STATUS"):
            s.output_format_idx = (s.output_format_idx + 1) % N_FORMATS
            self.flash(OUTPUT_FORMATS[s.output_format_idx]["label"], C_MAGENTA)
        elif page == "WHITE BAL":
            if oc:
                oc.v4l2_set(dev, oc.V4L2_WB_AUTO, 1)
                time.sleep(0.8)
                oc.v4l2_set(dev, oc.V4L2_WB_AUTO, 0)
                cur = oc.v4l2_get(dev, oc.V4L2_WB_TEMP)
                if cur: s.wb_temp = cur
                s.auto_wb = False
            self.flash(f"WB LOCK\n{s.wb_temp}K", C_CYAN)
        elif page == "FOCUS":
            if oc:
                oc.v4l2_set(dev, oc.V4L2_FOCUS_AUTO, 1)
                self.flash("FOCUSING…", C_GREEN)
                time.sleep(1.5)
                oc.v4l2_set(dev, oc.V4L2_FOCUS_AUTO, 0)
                cur = oc.v4l2_get(dev, oc.V4L2_FOCUS_ABS)
                if cur: s.focus = cur
                s.auto_focus = False
            self.flash("FOCUS LOCK", C_GREEN)
        elif page == "DISPLAY":
             # JOY PRESS toggles selected item
            if self._sub == 0:
                s.show_guides = not getattr(s, 'show_guides', True)
                self.flash("GUIDES " + ("ON" if s.show_guides else "OFF"), C_CYAN)
            elif self._sub == 1:
                s.show_histogram = not getattr(s, 'show_histogram', False)
                self.flash("HISTO " + ("ON" if s.show_histogram else "OFF"), C_CYAN)
            elif self._sub == 2:
                s.focus_peaking = not getattr(s, 'focus_peaking', False)
                self.flash("PEAK " + ("ON" if s.focus_peaking else "OFF"), C_CYAN)
        elif page == "AUDIO":
            s.audio_muted = not s.audio_muted
            self.flash("MUTED" if s.audio_muted else "MIC ON",
                       C_RED if s.audio_muted else C_GREEN)
        elif page == "STORAGE":
            self.flash(f"Clip #{s.clip_number:04d}", C_LGRAY)

    # ─── Main render loop ─────────────────────────────────────────────
    def _run(self):
        import traceback
        INTERVAL = 1.0 / 15
        while not self._stop.is_set():
            t0 = time.time()
            try:
                self._handle_input()
                self.display.display_image(self._render())
            except Exception as e:
                print(f"[HAT] Error: {e}")
                traceback.print_exc()
            time.sleep(max(0, INTERVAL - (time.time() - t0)))

    # ─── Top-level renderer ───────────────────────────────────────────
    def _render(self):
        s    = self.state
        page = PAGES[self._page]
        acc  = PAGE_COLORS[self._page]

        if page == "LIVE":
            return self._render_live(s, acc)
        else:
            return self._render_page(s, page, acc)

    # ─────────────────────────────────────────────────────────────────
    #  LIVE PAGE — full 128×128 camera feed + optional HUD overlay
    # ─────────────────────────────────────────────────────────────────
    def _render_live(self, s, acc):
        # Show waiting screen until first frame arrives
        if not (self.grabber and self.grabber.ready):
            img  = Image.new("RGB", (LCD_W, LCD_H), C_BG)
            draw = ImageDraw.Draw(img)
            draw.rectangle([0, 0, LCD_W-1, LCD_H-1], outline=C_MGRAY)
            draw.line([0, 0, LCD_W, LCD_H], fill=(40,40,60), width=1)
            draw.line([LCD_W, 0, 0, LCD_H], fill=(40,40,60), width=1)
            draw.text((28, 44), "LIVE FEED", fill=C_MGRAY, font=self._font_sm)
            draw.text((18, 58), "WARMING UP", fill=C_MGRAY, font=self._font_sm)
            self._nav_dots_only(draw, acc)
            return img
        # Live frame available
        img = self.grabber.get()

        if not self._show_hud:
            # ── CLEAN MODE: just the video + a tiny REC dot ──────────
            draw = ImageDraw.Draw(img)
            if s.recording:
                blink = int(time.time()*2)%2==0
                if blink:
                    draw.ellipse([LCD_W-12, 2, LCD_W-3, 11], fill=C_RED)
            return img

        # ── HUD OVERLAY MODE ─────────────────────────────────────────
        # Darken the top and bottom strips for readability
        img = _dark_box(img, 0,  0, LCD_W, 18,  alpha=160)   # top strip
        img = _dark_box(img, 0, LCD_H-38, LCD_W, 38, alpha=150)  # bottom strip

        draw = ImageDraw.Draw(img)

        # ── TOP BAR: REC + timecode ───────────────────────────────
        if s.recording:
            blink = int(time.time()*2)%2==0
            draw.rectangle([0,0,LCD_W,16], fill=(*C_RED, 200) if blink else (*C_RED_DIM, 200))
            draw.text((3, 2),  "●", fill=C_WHITE, font=self._font_sm)
            draw.text((14, 2), s.rec_timecode, fill=C_WHITE, font=self._font_sm)
        else:
            draw.text((3, 3), "○  STANDBY", fill=C_LGRAY, font=self._font_sm)

        clip_str = f"#{s.clip_number:04d}"
        draw.text((LCD_W - len(clip_str)*6 - 2, 3), clip_str, fill=acc, font=self._font_sm)

        # ── FOCUS BAR: thin horizontal bar at top of bottom strip ──
        pct      = s.focus_pct
        bar_y    = LCD_H - 37
        bar_col  = C_GREEN if not s.auto_focus else C_MGRAY
        af_label = "AF" if s.auto_focus else f"MF {pct}%"
        draw.text((3, bar_y), af_label, fill=bar_col, font=self._font_xs)
        _bar(draw, 28, bar_y+1, LCD_W-32, 6, pct/100, bar_col)

        # ── AUDIO METERS: dual bars ───────────────────────────────
        levels = s.audio_levels if s.audio_levels else [0.0, 0.0]
        lv = levels[0] if len(levels)>0 else 0.0
        rv = levels[1] if len(levels)>1 else 0.0
        ay = LCD_H - 27
        if s.audio_enabled and not s.audio_muted:
            draw.text((3, ay), "L", fill=C_MGRAY, font=self._font_xs)
            _db_bar(draw, 14, ay, LCD_W-17, 7, lv)
            ay += 9
            draw.text((3, ay), "R", fill=C_MGRAY, font=self._font_xs)
            _db_bar(draw, 14, ay, LCD_W-17, 7, rv)
        else:
            mute_str = "MIC MUTED" if s.audio_muted else "No mic"
            draw.text((3, ay+2), mute_str, fill=C_RED if s.audio_muted else C_MGRAY, font=self._font_xs)

        # ── BOTTOM STRIP: key settings summary ───────────────────
        by = LCD_H - 14
        ae_str = "AE" if s.auto_exp else f"{s.shutter_angle:.0f}°"
        wb_str = "AWB" if s.auto_wb else f"{s.wb_temp}K"
        n = {0:"Proxy",1:"LT",2:"Standard",3:"HQ"}
        draw.text((3,  by), ae_str,                         fill=C_AMBER,   font=self._font_xs)
        draw.text((36, by), wb_str,                         fill=C_CYAN,    font=self._font_xs)
        draw.text((76, by), s.format_label[:10],            fill=C_MAGENTA, font=self._font_xs)

        # ── Page dots at very bottom ─────────────────────────────
        self._nav_dots_only(draw, acc)

        # ── Flash message on top ─────────────────────────────────
        if self._flash_msg and (time.time() - self._flash_t) < 1.5:
            self._draw_flash(draw)
        else:
            self._flash_msg = ""

        return img

    # ─────────────────────────────────────────────────────────────────
    #  All other pages — HUD page with small live thumbnail
    # ─────────────────────────────────────────────────────────────────
    def _render_page(self, s, page, acc):
        # Reuse persistent canvas
        self._draw.rectangle((0, 0, LCD_W, LCD_H), fill=C_BG)
        img  = self._canvas
        draw = self._draw

        # ── Live thumbnail: bottom-right 40×30 ───────────────────
        self._paste_thumbnail(img, LCD_W-42, LCD_H-32, 40, 30)
        # No need to recreate draw object, it remains attached to img

        self._top_bar(draw, s, acc)

        {
            "STATUS":   self._pg_status,
            "EXPOSURE": self._pg_exposure,
            "WHITE BAL":self._pg_wb,
            "FOCUS":    self._pg_focus,
            "DISPLAY":  self._pg_display,
            "AUDIO":    self._pg_audio,
            "FORMAT":   self._pg_format,
            "STORAGE":  self._pg_storage,
        }.get(page, lambda d, s: None)(draw, s)

        self._nav_strip(draw, acc)

        if self._flash_msg and (time.time() - self._flash_t) < 1.5:
            self._draw_flash(draw)
        else:
            self._flash_msg = ""

        return img

    def _paste_thumbnail(self, img, x, y, w, h):
        """Paste a small live camera thumbnail onto the page image."""
        if not self.grabber: return
        frame = self.grabber.get()
        thumb = frame.resize((w, h), Image.BILINEAR)
        # Thin border
        if w == 40 and h == 30:
            # Reuse persistent border buffer for standard size
            self._thumb_border.paste(thumb, (1, 1))
            img.paste(self._thumb_border, (x-1, y-1))
        else:
            border = Image.new("RGB", (w+2, h+2), C_MGRAY)
            border.paste(thumb, (1, 1))
            img.paste(border, (x-1, y-1))

    # ─── Chrome for non-LIVE pages ────────────────────────────────────
    def _top_bar(self, draw, s, acc):
        if s.recording:
            blink = int(time.time()*2)%2==0
            draw.rectangle([0,0,LCD_W,16], fill=C_RED if blink else C_RED_DIM)
            draw.text((3,2), "●", fill=C_WHITE, font=self._font_sm)
            draw.text((14,2), s.rec_timecode, fill=C_WHITE, font=self._font_sm)
        else:
            draw.rectangle([0,0,LCD_W,16], fill=C_TOPBAR)
            draw.line([0,0,LCD_W,0], fill=acc, width=2)
            draw.text((3,3), "○  STANDBY", fill=C_MGRAY, font=self._font_sm)
        clip_str = f"#{s.clip_number:04d}"
        draw.text((LCD_W-len(clip_str)*6-2, 3), clip_str, fill=acc, font=self._font_sm)

    def _nav_strip(self, draw, acc):
        y = LCD_H - 11
        draw.rectangle([0, y, LCD_W, LCD_H], fill=C_TOPBAR)
        name = PAGES[self._page]
        tx   = max(2, (LCD_W - len(name)*6)//2)
        draw.text((tx, y+1), name, fill=acc, font=self._font_xs)
        self._nav_dots_only(draw, acc)

    def _nav_dots_only(self, draw, acc):
        dot_y   = LCD_H - 3
        x_start = (LCD_W - N_PAGES*8)//2
        for i in range(N_PAGES):
            cx  = x_start + i*8 + 3
            col = acc if i==self._page else C_MGRAY
            r   = 2 if i==self._page else 1
            draw.ellipse([cx-r, dot_y-r, cx+r, dot_y+r], fill=col)

    def _draw_flash(self, draw):
        lines  = self._flash_msg.split("\n")
        lh     = 13
        box_h  = len(lines)*lh + 10
        box_w  = max(len(l) for l in lines)*7 + 16
        bx = (LCD_W-box_w)//2
        by = (LCD_H-box_h)//2
        draw.rectangle([bx-1,by-1,bx+box_w+1,by+box_h+1],
                       fill=C_BG, outline=self._flash_col)
        for i, line in enumerate(lines):
            draw.text((bx+8, by+5+i*lh), line, fill=self._flash_col, font=self._font_sm)

    # ─── Page renderers ───────────────────────────────────────────────
    def _pg_status(self, draw, s):
        y  = 20; xs = self._font_xs; sm = self._font_sm
        res = s.resolution.replace("3840x2160","4K").replace("1920x1080","1080p").replace("1280x720","720p")
        draw.text((3,y), f"{res}  {s.fps}fps", fill=C_WHITE, font=sm); y+=14
        draw.text((3,y), s.format_label, fill=C_MAGENTA, font=sm); y+=13
        ae = "AE" if s.auto_exp else f"{s.shutter_angle:.0f}°"
        draw.text((3,y), f"EXP  {ae}   ISO~{s.gain*10}", fill=C_AMBER, font=xs); y+=12
        wb = "AWB" if s.auto_wb else f"{s.wb_temp}K"
        draw.text((3,y), f"WB   {wb}", fill=C_CYAN, font=xs); y+=12
        af = "AF" if s.auto_focus else f"MF {s.focus_pct}%"
        pk = "  PKG" if getattr(s,'focus_peaking',False) else ""
        draw.text((3,y), f"FOC  {af}{pk}", fill=C_GREEN, font=xs); y+=12
        if not s.audio_enabled:   aud, ac = "No mic", C_MGRAY
        elif s.audio_muted:       aud, ac = "MUTED",  C_RED
        else:
            sign = "+" if s.mic_gain_db >= 0 else ""
            aud, ac = f"Mic  {sign}{s.mic_gain_db}dB", C_GREEN
        draw.text((3,y), aud, fill=ac, font=xs)
        draw.text((3, LCD_H-22), "K1=REC  K3=format", fill=C_MGRAY, font=xs)

    def _pg_exposure(self, draw, s):
        y  = 20; xs = self._font_xs; sm = self._font_sm
        sel_exp  = self._sub == 0; sel_gain = self._sub == 1
        sh_col   = C_AMBER if sel_exp  else C_LGRAY
        g_col    = C_CYAN  if sel_gain else C_LGRAY
        draw.text((3,y), "SHUTTER", fill=sh_col, font=xs); y+=10
        draw.text((3,y), "AUTO" if s.auto_exp else f"{s.shutter_angle:.0f}°", fill=sh_col, font=self._font_lg); y+=20
        _bar(draw, 3, y, LCD_W-48, 8, s.shutter_angle/360,
             C_AMBER if not s.auto_exp else C_MGRAY, outline=C_AMBER if sel_exp else None)
        m = 3+int(0.5*(LCD_W-48)); draw.line([m,y,m,y+8], fill=C_WHITE, width=1)
        y += 12
        draw.text((3,y), f"ISO  ~{s.gain*10}", fill=g_col, font=sm); y+=12
        _bar(draw, 3, y, LCD_W-48, 7, s.gain/500,
             C_CYAN if sel_gain else C_MGRAY, outline=C_CYAN if sel_gain else None)
        cursor = "▲▼ Shutter" if sel_exp else "▲▼ ISO"
        draw.text((3, LCD_H-22), cursor, fill=C_AMBER if sel_exp else C_CYAN, font=xs)
        draw.text((3, LCD_H-13), "K2=AE  K3=switch", fill=C_MGRAY, font=xs)

    def _pg_wb(self, draw, s):
        y  = 20; xs = self._font_xs; sm = self._font_sm
        draw.text((3,y), "AUTO" if s.auto_wb else "MANUAL",
                  fill=C_GREEN if s.auto_wb else C_WHITE, font=sm); y+=14
        draw.text((3,y), f"{s.wb_temp} K", fill=C_CYAN, font=self._font_lg); y+=20
        _bar(draw, 3, y, LCD_W-48, 10, (s.wb_temp-2000)/8000, C_CYAN); y+=11
        for k, lbl in [(3200,"3.2"),(5600,"D"),(6500,"6.5")]:
            mx = 3+int(((k-2000)/8000)*(LCD_W-48))
            draw.line([mx,y-11,mx,y-1], fill=C_WHITE, width=1)
            draw.text((mx-4,y), lbl, fill=C_MGRAY, font=xs)
        y+=11
        draw.text((3,y), "2K", fill=C_MGRAY, font=xs)
        draw.text((3, LCD_H-22), "▲▼ = Kelvin", fill=C_CYAN, font=xs)
        draw.text((3, LCD_H-13), "K2=AWB  K3=preset  ●=lock", fill=C_MGRAY, font=xs)

    def _pg_focus(self, draw, s):
        y  = 20; xs = self._font_xs; sm = self._font_sm
        draw.text((3,y), "AUTO FOCUS" if s.auto_focus else "MANUAL FOCUS",
                  fill=C_GREEN if s.auto_focus else C_AMBER, font=sm); y+=14
        draw.text((3,y), "NEAR", fill=C_MGRAY, font=xs)
        draw.text((LCD_W-70,y), "FAR", fill=C_MGRAY, font=xs); y+=10
        pct = s.focus_pct
        _bar(draw, 3, y, LCD_W-48, 14, pct/100, C_GREEN if not s.auto_focus else C_MGRAY)
        draw.text((LCD_W//2-28, y+2), f"{pct:3d}%", fill=C_WHITE, font=xs)
        for frac in [0.25,0.5,0.75]:
            tx = 3+int(frac*(LCD_W-48))
            draw.line([tx,y+14,tx,y+18], fill=C_MGRAY, width=1)
        y+=22
        draw.text((3,y), f"val {s.focus}/{s.focus_max}", fill=C_MGRAY, font=xs); y+=12
        pk_on = getattr(s,'focus_peaking',False)
        draw.text((3,y), f"Peaking  {'ON ●' if pk_on else 'OFF'}",
                  fill=C_GREEN if pk_on else C_MGRAY, font=xs)
        draw.text((3, LCD_H-22), "▲▼ = pull focus", fill=C_GREEN if not s.auto_focus else C_MGRAY, font=xs)
        draw.text((3, LCD_H-13), "K2=AF  K3=peak  ●=AF lock", fill=C_MGRAY, font=xs)

    def _pg_display(self, draw, s):
        y  = 20; xs = self._font_xs; sm = self._font_sm
        draw.text((3,y), "GUI DISPLAY", fill=C_CYAN, font=sm); y+=16

        items = [
            ("Guides",    getattr(s, 'show_guides', True)),
            ("Histogram", getattr(s, 'show_histogram', False)),
            ("Peaking",   getattr(s, 'focus_peaking', False))
        ]

        for i, (label, val) in enumerate(items):
            selected = (i == self._sub)
            col = C_WHITE if selected else C_MGRAY
            prefix = "▶ " if selected else "  "
            status = "ON" if val else "OFF"
            stat_col = C_GREEN if val else C_RED_DIM
            if selected: stat_col = C_GREEN if val else C_RED

            draw.text((3, y), f"{prefix}{label}", fill=col, font=sm)
            draw.text((LCD_W-36, y), status, fill=stat_col, font=sm)
            y += 16

        draw.text((3, LCD_H-22), "▲▼ = select", fill=C_MGRAY, font=xs)
        draw.text((3, LCD_H-13), "K2/● = toggle  K3=next", fill=C_MGRAY, font=xs)

    def _pg_audio(self, draw, s):
        y  = 20; xs = self._font_xs; sm = self._font_sm
        if not s.audio_enabled:
            draw.text((3,y+10), "No mic detected", fill=C_MGRAY, font=sm); return
        if s.audio_muted:
            draw.rectangle([3,y,LCD_W-48,y+14], fill=(50,0,0))
            draw.text((6,y+1), "MIC  MUTED", fill=C_RED, font=sm)
        else:
            draw.text((3,y), "MIC  LIVE", fill=C_GREEN, font=sm)
        y+=18
        levels = s.audio_levels if s.audio_levels else [0.0,0.0]
        lv = levels[0] if len(levels)>0 else 0.0
        rv = levels[1] if len(levels)>1 else 0.0
        draw.text((3,y), "L", fill=C_LGRAY, font=xs)
        _db_bar(draw, 14, y, LCD_W-60, 9, lv); y+=12
        draw.text((3,y), "R", fill=C_LGRAY, font=xs)
        _db_bar(draw, 14, y, LCD_W-60, 9, rv); y+=13
        draw.text((14,y),"-60",fill=C_MGRAY,font=xs)
        draw.text((45,y),"-12",fill=C_MGRAY,font=xs)
        draw.text((60,y),"-6", fill=C_MGRAY,font=xs); y+=11
        sign = "+" if s.mic_gain_db >= 0 else ""
        draw.text((3,y), f"Gain  {sign}{s.mic_gain_db} dB", fill=C_WHITE, font=sm); y+=12
        mid = (LCD_W-50)//2
        draw.rectangle([3,y,LCD_W-48,y+8], fill=C_BAR_BG)
        draw.line([3+mid,y,3+mid,y+8], fill=C_MGRAY, width=1)
        norm   = (s.mic_gain_db+20)/40
        fill_x = int(norm*(LCD_W-50))
        if norm >= 0.5:
            draw.rectangle([3+mid,y,3+fill_x,y+8], fill=C_GREEN)
        else:
            draw.rectangle([3+fill_x,y,3+mid,y+8], fill=C_AMBER)
        draw.text((3, LCD_H-22), "▲▼ = gain ±3dB", fill=C_MGRAY, font=xs)
        draw.text((3, LCD_H-13), "K2=mute  K3=reset  ●=mute", fill=C_MGRAY, font=xs)

    def _pg_format(self, draw, s):
        y  = 20; xs = self._font_xs; sm = self._font_sm
        fmt = OUTPUT_FORMATS[s.output_format_idx]

        draw.text((3,y), "FORMAT", fill=C_LGRAY, font=xs); y+=10
        draw.text((3,y), fmt["label"], fill=C_MAGENTA, font=sm); y+=13
        draw.text((3,y), fmt["note"],  fill=C_LGRAY,   font=xs); y+=11
        ext_col = C_CYAN if fmt["ext"]=="mp4" else (C_AMBER if fmt["ext"]=="mov" else C_GREEN)
        draw.text((3,y), f".{fmt['ext'].upper()}", fill=ext_col, font=sm)
        if fmt.get("cpu_warn") and "3840" in s.resolution:
            draw.text((34,y), "! 4K slow", fill=C_RED, font=xs)
        y+=14

        # Format selection strip
        total   = N_FORMATS
        strip_w = max(1, (LCD_W - 50) // total)
        for i, f in enumerate(OUTPUT_FORMATS):
            sx     = 3 + i * strip_w
            active = (i == s.output_format_idx)
            draw.rectangle([sx, y, sx+strip_w-2, y+10],
                           fill=C_MAGENTA if active else C_BAR_BG)
            lbl = f["key"][:3].upper()
            draw.text((sx+1, y+1), lbl,
                      fill=C_WHITE if active else C_MGRAY, font=xs)
        y+=14

        draw.text((3,y), "FPS", fill=C_LGRAY, font=xs)
        draw.text((28,y), str(s.fps), fill=C_WHITE, font=sm); y+=14
        res = s.resolution.replace("3840x2160","4K").replace("1920x1080","1080p").replace("1280x720","720p")
        draw.text((3,y), "RES", fill=C_LGRAY, font=xs)
        draw.text((28,y), res, fill=C_WHITE, font=sm)

        draw.text((3, LCD_H-22), "▲▼=format  K2=cycle", fill=C_MGRAY, font=xs)
        draw.text((3, LCD_H-13), "K3=res  ●=fps", fill=C_MGRAY, font=xs)

    def _pg_storage(self, draw, s):
        y  = 20; xs = self._font_xs; sm = self._font_sm
        draw.text((3,y), "CLIP  NUM", fill=C_LGRAY, font=xs)
        draw.text((65,y), f"{s.clip_number:04d}", fill=C_CYAN, font=sm); y+=14
        draw.text((3,y), "FILE", fill=C_LGRAY, font=xs); y+=10
        draw.text((3,y), s.clip_name[:18], fill=C_WHITE, font=xs); y+=12
        draw.text((3,y), "PATH", fill=C_LGRAY, font=xs); y+=10
        out = str(s.output_dir)
        if len(out) > 18: out = "…"+out[-17:]
        draw.text((3,y), out, fill=C_LGRAY, font=xs); y+=14
        try:
            stat     = os.statvfs(str(s.output_dir))
            free_gb  = (stat.f_bavail*stat.f_frsize)/(1024**3)
            total_gb = (stat.f_blocks*stat.f_frsize)/(1024**3)
            used_pct = 1.0-(stat.f_bavail/max(stat.f_blocks,1))
            draw.text((3,y), f"FREE  {free_gb:.1f}/{total_gb:.0f} GB", fill=C_WHITE, font=xs); y+=11
            _bar(draw, 3, y, LCD_W-50, 7, used_pct,
                 C_RED if used_pct>0.9 else (C_AMBER if used_pct>0.7 else C_GREEN)); y+=10

            # Use centralized logic if available
            if hasattr(s, "remaining_storage_info"):
                _, mins = s.remaining_storage_info
            else:
                # Robust fallback logic
                fmt  = OUTPUT_FORMATS[s.output_format_idx]
                mbps = fmt.get("est_mbps")
                # Fallback to note parsing only if est_mbps is missing
                if not mbps:
                    note = fmt.get("note", "")
                    try:
                        mbps = int([w for w in note.replace("~","").split() if "Mbps" in w][0].replace("Mbps",""))
                    except Exception:
                        mbps = 50

                if "720" in str(s.resolution): mbps = max(1, mbps//3)
                elif "1080" in str(s.resolution): mbps = max(1, mbps//2)

                mins = int((free_gb*8000/mbps)/60) if mbps else 0

            h,m  = divmod(mins,60)
            draw.text((3,y), f"{h}h {m:02d}m remaining", fill=C_MGRAY, font=xs)
        except Exception:
            draw.text((3,y), "Disk info N/A", fill=C_MGRAY, font=xs)
        draw.text((3, LCD_H-13), "K3=reset clip#", fill=C_MGRAY, font=xs)


# ─────────────────────────────────────────────
#  Standalone test
# ─────────────────────────────────────────────
class _MockState:
    device="/dev/video0"; resolution="3840x2160"; fps=30
    exposure=500; gain=100; wb_temp=5600
    auto_wb=False; auto_exp=False; auto_focus=True
    focus=128; focus_max=255; focus_peaking=False
    output_format_idx=0; recording=False; rec_start=None; clip_number=1
    record_trigger=False
    audio_enabled=True; audio_muted=False; mic_gain_db=0
    audio_levels=[0.20, 0.18]; audio_peaks=[0.25, 0.22]

    @property
    def output_format(self): return OUTPUT_FORMATS[self.output_format_idx]
    @property
    def format_label(self): return self.output_format["label"]

    @property
    def output_dir(self): return Path.home()/"obsbot_footage"
    @property
    def rec_timecode(self):
        e=time.time()%3600; return f"{int(e//60):02d}:{int(e%60):02d}:{int((e%1)*30):02d}"
    @property
    def clip_name(self):
        ext = self.output_format.get("ext", "mp4")
        return f"CLIP_20250220_0001.{ext}"
    @property
    def shutter_angle(self):
        return min(360, max(1, (self.exposure/10000)*self.fps*360))
    @property
    def focus_pct(self):
        return int((self.focus/max(self.focus_max,1))*100)


if __name__ == "__main__":
    print("HAT UI standalone test")
    print(f"  GPIO={GPIO_OK}  SPI={SPI_OK}  PIL={PIL_OK}  CV2={CV2_OK}")
    missing = [n for n,ok in [("RPi.GPIO",GPIO_OK),("spidev",SPI_OK),("Pillow",PIL_OK)] if not ok]
    if missing:
        print(f"\nInstall: pip3 install {' '.join(missing)}")
        sys.exit(1)

    state = _MockState()
    ui    = HatUI(state)
    if not ui.start():
        print("\nInit failed — check SPI is enabled:")
        print("  sudo raspi-config → Interfaces → SPI → Enable  then reboot")
        sys.exit(1)

    print(f"\n{N_PAGES} pages — JOY ←/→ to navigate")
    print("Page 0 (LIVE): KEY3 toggles HUD overlay on/off")
    print("Ctrl+C to exit\n")
    try:
        while True: time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nStopping…")
        ui.stop()
