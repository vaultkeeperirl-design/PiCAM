#!/bin/bash
# ─────────────────────────────────────────────────────────────
#  OBSBOT Meet 2 — CineRig setup script for Raspberry Pi 5
#  Run once: bash install.sh
# ─────────────────────────────────────────────────────────────

set -e
BOLD="\033[1m"
RED="\033[0;31m"
GREEN="\033[0;32m"
YELLOW="\033[1;33m"
CYAN="\033[0;36m"
RESET="\033[0m"

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║   OBSBOT Meet 2 — Pi5 CineRig Setup      ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════════╝${RESET}"
echo ""

# ── System dependencies ──────────────────────────────────────
echo -e "${CYAN}[1/4] Installing system packages…${RESET}"
sudo apt-get update -qq
sudo apt-get install -y \
    ffmpeg \
    libx264-dev \
    libx265-dev \
    v4l-utils \
    python3-pip \
    python3-dev \
    libopencv-dev \
    python3-opencv \
    python3-numpy

# ── Python packages ──────────────────────────────────────────
echo -e "${CYAN}[2/4] Installing Python packages…${RESET}"
# RPi.GPIO does not work on Pi 5 — replace with the drop-in lgpio shim
sudo apt-get remove -y python3-rpi.gpio 2>/dev/null || true
sudo apt-get install -y python3-rpi-lgpio python3-lgpio

pip3 install --break-system-packages rich sounddevice spidev Pillow

# If system opencv didn't work, also try pip
python3 -c "import cv2" 2>/dev/null || \
    pip3 install --break-system-packages opencv-python-headless

# ── USB bandwidth for 4K UVC ─────────────────────────────────
echo -e "${CYAN}[3/4] Configuring USB and SPI…${RESET}"

# Increase usbfs memory limit (needed for 4K webcam streams)
if ! grep -q "usbcore.usbfs_memory_mb" /boot/firmware/cmdline.txt 2>/dev/null; then
    echo -e "${YELLOW}  Adding usbfs_memory_mb=512 to boot cmdline…${RESET}"
    sudo sed -i 's/$/ usbcore.usbfs_memory_mb=512/' /boot/firmware/cmdline.txt
    echo -e "${GREEN}  ✓ Added (will take effect after reboot)${RESET}"
else
    echo -e "${GREEN}  ✓ USB memory already set${RESET}"
fi

# Enable SPI for the LCD HAT
CONFIG=/boot/firmware/config.txt
if ! grep -q "dtparam=spi=on" "$CONFIG" 2>/dev/null; then
    echo -e "${YELLOW}  Enabling SPI in /boot/firmware/config.txt…${RESET}"
    echo "dtparam=spi=on" | sudo tee -a "$CONFIG" > /dev/null
    echo -e "${GREEN}  ✓ SPI enabled${RESET}"
else
    echo -e "${GREEN}  ✓ SPI already enabled${RESET}"
fi

# GPIO pull-ups for HAT buttons and joystick (KEY1/2/3 + joystick 5-way)
# Pins: KEY1=21 KEY2=20 KEY3=16  Joy: UP=6 DOWN=19 LEFT=5 RIGHT=26 PRESS=13
if ! grep -q "gpio=6,19,5,26,13,21,20,16=pu" "$CONFIG" 2>/dev/null; then
    echo -e "${YELLOW}  Adding HAT GPIO pull-ups to config.txt…${RESET}"
    echo "gpio=6,19,5,26,13,21,20,16=pu" | sudo tee -a "$CONFIG" > /dev/null
    echo -e "${GREEN}  ✓ GPIO pull-ups set${RESET}"
else
    echo -e "${GREEN}  ✓ GPIO pull-ups already set${RESET}"
fi

# ── Detect camera ────────────────────────────────────────────
echo -e "${CYAN}[4/4] Detecting OBSBOT Meet 2…${RESET}"
echo ""
echo "Video devices found:"
ls /dev/video* 2>/dev/null || echo "  None found — is the camera plugged in?"
echo ""

# Show which device is the OBSBOT
if command -v v4l2-ctl &>/dev/null; then
    for dev in /dev/video*; do
        name=$(v4l2-ctl --device="$dev" --info 2>/dev/null | grep "Card type" | cut -d: -f2 | xargs)
        if [ -n "$name" ]; then
            echo "  $dev → $name"
        fi
    done
fi

echo ""
echo -e "${GREEN}${BOLD}✓ Setup complete!${RESET}"
echo ""
echo -e "Run a quick diagnostic first:"
echo -e "  ${CYAN}python3 obsbot_capture.py --mode diag${RESET}"
echo ""
echo -e "Then launch with GUI preview + HAT controls:"
echo -e "  ${CYAN}python3 obsbot_capture.py --mode gui --hat${RESET}"
echo ""
echo -e "Or headless (no screen, rig use) with HAT as your only UI:"
echo -e "  ${CYAN}python3 obsbot_capture.py --mode headless --hat${RESET}"
echo ""
echo -e "Test the HAT display on its own:"
echo -e "  ${CYAN}python3 hat_ui.py${RESET}"
echo ""
echo -e "${YELLOW}NOTE: If the camera appears as /dev/video2 etc., pass --device /dev/video2${RESET}"
echo ""
