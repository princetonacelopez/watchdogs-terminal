#!/usr/bin/env python3
"""
ctos-faceid-auth: Watch Dogs ctOS 2.0 / DedSec Live Camera Biometric FaceID Modal
Features:
  1. Captures real-time video from /dev/video0 via OpenCV (V4L2) and applies a live
     Watch Dogs ctOS 2x4 Sub-Pixel Unicode Braille + CLAHE + Canny Edge ASCII filter.
  2. Runs real-time Haar Cascade frontal face detection on the live camera feed,
     locking targeting crosshairs (╋) onto the user's live facial landmarks.
  3. Coordinates /tmp/ctos_faceid_state.json ("LOCKED" -> "FAILED" / "UNLOCKED") so all
     Zellij panels beneath the modal stay blurred/static during FaceID and fade in on success.
  4. If authentication fails (camera covered/dark, no face detected, or 'f' pressed),
     displays an interactive [ RETRY FACE_ID ] button (supports mouse click & Enter/r key).
"""

import os
import sys
import tty
import time
import json
import math
import random
import select
import shutil
import signal
import termios
import re
import unicodedata
from collections import deque

import cv2
import numpy as np
from PIL import Image, ImageFilter

STATE_FILE = "/tmp/ctos_faceid_state.json"
ASSET_PATHS = [
    os.path.expanduser("~/.config/zellij/assets/ace_photo.jpg"),
    "/home/princetonacelopez/Documents/antigravity/serene-volta/zellij/assets/ace_photo.jpg",
]
CASCADE_PATHS = [
    "/usr/share/opencv4/haarcascades/haarcascade_frontalface_default.xml",
    "/usr/share/opencv4/haarcascades/haarcascade_frontalface_alt2.xml",
]

# Watch Dogs ctOS 2.0 TrueColor Palette
R          = "\033[0m"
B          = "\033[1m"
C_CYAN     = "\033[38;2;0;240;255m"     # #00F0FF Electric Cyan
C_CYAN_BRT = "\033[38;2;165;252;255m"   # #A5FCFF Scan Highlight
C_BLUE     = "\033[38;2;0;175;255m"     # #00AFFF Data Link Blue
C_CRIMSON  = "\033[38;2;255;0;85m"      # #FF0055 DedSec Intrusion Red
C_MINT     = "\033[38;2;0;255;156m"     # #00FF9C Access Granted Mint
C_AMBER    = "\033[38;2;255;214;0m"     # #FFD600 Profiler Warning Amber
C_PURPLE   = "\033[38;2;214;0;255m"     # #D600FF DedSec Purple
C_WHITE    = "\033[38;2;226;241;255m"   # #E2F1FF Ice White
C_SLATE    = "\033[38;2;122;147;172m"   # #7A93AC Muted Slate
C_GRID     = "\033[38;2;28;44;62m"      # #1C2C3E Grid Frame

BG_SCAN    = "\033[48;2;0;65;85m"
BG_VERIFY  = "\033[48;2;0;48;35m"
BG_FAIL    = "\033[48;2;65;0;25m"
BG_BTN     = "\033[48;2;255;0;85m"

DOT_BITS = [
    [0x01, 0x08],
    [0x02, 0x10],
    [0x04, 0x20],
    [0x40, 0x80],
]

BAYER = [
    [ 20, 140],
    [200,  80],
    [ 50, 170],
    [230, 110],
]

running = True
original_termios = None
cap_device = None
CAMERA_NAME = "IR_BIOMETRIC_SENSOR // v4l2"


def set_faceid_state(state_str, unlock_delay=0.14):
    try:
        now = time.time()
        payload = {"state": state_str, "ts": now}
        if state_str == "UNLOCKED":
            payload["unlock_ts"] = now + unlock_delay
        with open(STATE_FILE, "w") as f:
            json.dump(payload, f)
    except Exception:
        pass


def cleanup(sig=None, frame=None):
    global running, original_termios, cap_device
    running = False
    if cap_device is not None:
        try:
            cap_device.release()
        except Exception:
            pass
    if original_termios:
        try:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, original_termios)
        except Exception:
            pass
    # Disable mouse tracking, restore line wrap & cursor, and exit alternate screen
    if "--once" not in sys.argv:
        sys.stdout.write("\033[?1000l\033[?1006l\033[?7h\033[?25h\033[0m\033[?1049l")
        sys.stdout.flush()
        # Trigger underlying panels' transition ONLY now as the FaceID modal exits!
        set_faceid_state("UNLOCKED", unlock_delay=0.12)
    else:
        sys.stdout.write("\033[?1000l\033[?1006l\033[?25h\033[0m")
        sys.stdout.flush()
    sys.exit(0)


signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)


def str_width(s):
    clean = re.sub(r"\033\[[0-9;?]*[a-zA-Z]", "", s)
    w = 0
    for ch in clean:
        if unicodedata.combining(ch) or ch == "\ufe0f":
            continue
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") or ord(ch) >= 0x1F300 else 1
    return w


def center_ansi(text, width):
    vis = str_width(text)
    if vis >= width:
        return text
    left = (width - vis) // 2
    right = width - vis - left
    return (" " * left) + text + (" " * right)


def pad_right(text, width):
    vis = str_width(text)
    if vis >= width:
        return text
    return text + (" " * (width - vis))


def probe_camera_name():
    global CAMERA_NAME
    try:
        if os.path.exists("/sys/class/video4linux/video0/name"):
            with open("/sys/class/video4linux/video0/name", "r") as f:
                name = f.read().strip()
                if name:
                    CAMERA_NAME = f"/dev/video0 ({name})"
    except Exception:
        pass


def load_Cascades():
    cascades = []
    for p in CASCADE_PATHS:
        if os.path.exists(p):
            c = cv2.CascadeClassifier(p)
            if not c.empty():
                cascades.append(c)
    return cascades


CASCADES = load_Cascades()
CLAHE = cv2.createCLAHE(clipLimit=2.4, tileGridSize=(8, 8))


def frame_to_braille_grid(bgr_frame, tw, th, face_box=None):
    """
    Convert a live OpenCV BGR camera frame into a (th x tw) 2x4 sub-pixel Unicode Braille
    & Canny-edge filtered grid with head/shoulders silhouette vignette for Watch Dogs ctOS.
    """
    if bgr_frame is None:
        return [], None

    fh_img, fw_img = bgr_frame.shape[:2]

    # Crop around detected face (or center of camera)
    if face_box is not None:
        fx, fy, fw, fh = face_box
        cx = fx + fw // 2
        cy = fy + int(fh * 0.52)
        half = int(max(fw, fh) * 0.88)
    else:
        cx = fw_img // 2
        cy = int(fh_img * 0.55)
        half = int(min(fw_img, fh_img) * 0.42)

    half = max(44, min(half, min(fw_img, fh_img) // 2))
    x1 = max(0, min(fw_img - 2 * half, cx - half))
    y1 = max(0, min(fh_img - 2 * half, cy - half))
    roi = bgr_frame[y1 : y1 + 2 * half, x1 : x1 + 2 * half]

    # Target sub-pixel resolution: (tw * 2) x (th * 4)
    sub_w = tw * 2
    sub_h = th * 4
    small_bgr = cv2.resize(roi, (sub_w, sub_h), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small_bgr, cv2.COLOR_BGR2GRAY)
    gray_eq = CLAHE.apply(gray)

    # Local high-pass / Difference of Gaussians so facial features (eyes, brows, nose, glasses, cap) pop
    blur = cv2.GaussianBlur(gray_eq, (9, 9), 0)
    highpass = cv2.addWeighted(gray_eq, 1.55, blur, -0.55, 0)
    edges = cv2.Canny(gray_eq, 42, 115)

    # Compute normalized face box inside the (tw, th) cell grid
    rel_face = None
    if face_box is not None:
        fx, fy, fw, fh = face_box
        rx1 = int(max(1, min(tw - 2, (fx - x1) / float(2 * half) * tw)))
        ry1 = int(max(1, min(th - 2, (fy - y1) / float(2 * half) * th)))
        rx2 = int(max(rx1 + 4, min(tw - 2, (fx + fw - x1) / float(2 * half) * tw)))
        ry2 = int(max(ry1 + 3, min(th - 2, (fy + fh - y1) / float(2 * half) * th)))
        rel_face = (rx1, ry1, rx2, ry2)

    rows_data = []
    for ty in range(th):
        row_cells = []
        y_base = ty * 4
        for tx in range(tw):
            x_base = tx * 2
            mask_bits = 0
            lum_sum = 0
            fg_dots = 0

            for dy in range(4):
                sy = y_base + dy
                ny = (sy / float(sub_h)) * 2.0 - 1.0  # -1.0 (top) .. +1.0 (bottom)
                for dx in range(2):
                    sx = x_base + dx
                    nx = (sx / float(sub_w)) * 2.0 - 1.0  # -1.0 (left) .. +1.0 (right)

                    # Head + Shoulders Silhouette Mask (suppresses room background outside subject)
                    in_head = ((nx / 0.62) ** 2 + ((ny + 0.08) / 0.68) ** 2) <= 1.0
                    in_shoulders = (ny > 0.32) and (abs(nx) <= 0.86)
                    if not (in_head or in_shoulders):
                        continue

                    v = int(highpass[sy, sx])
                    ed = int(edges[sy, sx])
                    if ed > 0 or v > BAYER[dy][dx]:
                        mask_bits |= DOT_BITS[dy][dx]
                        lum_sum += int(gray_eq[sy, sx])
                        fg_dots += 1

            if mask_bits == 0:
                row_cells.append(None)
            else:
                ch = chr(0x2800 + mask_bits)
                avg_lum = lum_sum / max(1, fg_dots)
                row_cells.append((ch, avg_lum))
        rows_data.append(row_cells)

    return rows_data, rel_face


def detect_live_face(bgr_frame):
    """
    Detect a live face in the camera frame using Haar Cascades + skin/contrast liveness check.
    Returns (has_face_signature, face_box_or_None).
    """
    if bgr_frame is None:
        return False, None

    gray = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2GRAY)
    mean_lum = float(gray.mean())
    std_lum = float(gray.std())

    # If camera lens is covered / pitch black or completely blown out uniform wall
    if mean_lum < 12.0 or std_lum < 10.0:
        return False, None

    gray_eq = CLAHE.apply(gray)
    for cascade in CASCADES:
        faces = cascade.detectMultiScale(gray_eq, scaleFactor=1.08, minNeighbors=2, minSize=(36, 36))
        if len(faces) > 0:
            # Pick largest detected face
            faces = sorted(faces, key=lambda b: b[2] * b[3], reverse=True)
            return True, tuple(int(v) for v in faces[0])

    # Fallback: check center ROI for human skin-tone + facial edge density (handles tilted head / cap / glasses)
    h, w = bgr_frame.shape[:2]
    center_roi = bgr_frame[int(h * 0.15) : int(h * 0.85), int(w * 0.20) : int(w * 0.80)]
    ycrcb = cv2.cvtColor(center_roi, cv2.COLOR_BGR2YCrCb)
    skin = cv2.inRange(ycrcb, (35, 132, 77), (255, 178, 133))
    skin_ratio = np.count_nonzero(skin) / float(skin.size)
    edges = cv2.Canny(gray[int(h * 0.15) : int(h * 0.85), int(w * 0.20) : int(w * 0.80)], 40, 120)
    edge_ratio = np.count_nonzero(edges) / float(edges.size)

    if skin_ratio > 0.045 and edge_ratio > 0.035:
        fw, fh = int(w * 0.42), int(h * 0.52)
        fx, fy = (w - fw) // 2, (h - fh) // 2
        return True, (fx, fy, fw, fh)

    return False, None


def progress_bar(pct, width=12, state="SCANNING"):
    filled = int(round((pct / 100.0) * width))
    filled = max(0, min(width, filled))
    empty = width - filled
    if state == "VERIFIED":
        col = C_MINT
    elif state == "FAILED":
        col = C_CRIMSON
    else:
        col = C_CYAN if pct < 100 else C_MINT
    return f"{col}{'█' * filled}{C_GRID}{'░' * empty}{R} {col}{B}{pct:5.1f}%{R}"


def render_modal(progress, tick, bgr_frame=None, face_box=None, state="SCANNING"):
    """
    state: "SCANNING" | "VERIFIED" | "FAILED"
    Designed cleanly for the compact floating modal size.
    """
    cols, rows = shutil.get_terminal_size((76, 20))
    cols = max(54, cols)
    rows = max(15, rows)

    pct_overall = min(100.0, progress * 100.0)
    buf = []

    # 1. Top Modal Header
    if state == "VERIFIED":
        hdr = f"{BG_VERIFY}{C_MINT}{B} ⌁ ctOS // BIOMETRIC FACE_ID : VERIFIED // ACCESS GRANTED {R}"
    elif state == "FAILED":
        hdr = f"{BG_FAIL}{C_CRIMSON}{B} ✖ ctOS // BIOMETRIC BREACH FAILED : IDENTITY UNVERIFIED {R}"
    else:
        spin = "◐◓◑◒"[tick % 4]
        hdr = f"{BG_SCAN}{C_CYAN}{B} {spin} ctOS // LIVE CAMERA FACE_ID SCAN [{pct_overall:04.1f}%] {R}"

    buf.append(center_ansi(hdr, cols) + "\033[K")
    buf.append(center_ansi(f"{C_GRID}{'━' * (cols - 2)}{R}", cols) + "\033[K")

    # Compact Portrait + Telemetry dimensions
    portrait_h = max(8, min(12, rows - 7))
    portrait_w = max(20, min(28, int(portrait_h * 2.1)))
    right_w = max(24, cols - portrait_w - 7)

    grid, rel_face = frame_to_braille_grid(bgr_frame, portrait_w, portrait_h, face_box)
    scan_row = int((tick * 0.9) % max(1, portrait_h))

    # Facial landmarks from live face detection box (or centered default)
    if rel_face is not None:
        rx1, ry1, rx2, ry2 = rel_face
        fw_c = max(4, rx2 - rx1)
        fh_c = max(4, ry2 - ry1)
        landmarks = [
            (rx1 + int(fw_c * 0.32), ry1 + int(fh_c * 0.36), 0.15),  # Left Eye
            (rx1 + int(fw_c * 0.68), ry1 + int(fh_c * 0.36), 0.30),  # Right Eye
            (rx1 + int(fw_c * 0.50), ry1 + int(fh_c * 0.54), 0.50),  # Nose Bridge
            (rx1 + int(fw_c * 0.50), ry1 + int(fh_c * 0.74), 0.70),  # Mouth Center
        ]
    else:
        landmarks = [
            (int(portrait_w * 0.38), int(portrait_h * 0.36), 0.20),
            (int(portrait_w * 0.62), int(portrait_h * 0.36), 0.40),
            (int(portrait_w * 0.50), int(portrait_h * 0.52), 0.60),
            (int(portrait_w * 0.50), int(portrait_h * 0.70), 0.80),
        ]

    # Telemetry bars
    p_eye   = min(100.0, progress * 135.0)
    p_depth = min(100.0, max(0.0, (progress - 0.10) * 125.0))
    p_live  = min(100.0, max(0.0, (progress - 0.22) * 135.0))
    p_hash  = min(100.0, max(0.0, (progress - 0.32) * 155.0))
    bar_w   = max(8, min(14, right_w - 20))

    cam_short = CAMERA_NAME[:max(10, right_w - 13)]
    right_lines = [
        f"{C_CYAN}{B}LIVE_CAM // {cam_short}{R}",
        f"{C_SLATE}SUBJECT :{R} {C_WHITE}{B}ACE (Princeton Lopez){R}",
        f"{C_SLATE}ORG     :{R} {C_CYAN}{B}WebIT | Offsure{R}",
        f"{C_GRID}{'┄' * (right_w - 2)}{R}",
        f"{C_SLATE}OCULAR  :{R} {progress_bar(p_eye, bar_w, state)}",
        f"{C_SLATE}IR_MESH :{R} {progress_bar(p_depth, bar_w, state)}",
        f"{C_SLATE}LIVENESS:{R} {progress_bar(p_live, bar_w, state)}",
        f"{C_SLATE}BIO_KEY :{R} {progress_bar(p_hash, bar_w, state)}",
        f"{C_GRID}{'┄' * (right_w - 2)}{R}",
    ]

    if state == "VERIFIED":
        right_lines += [
            f"{C_MINT}{B}✔ FACE_ID MATCH : 99.94%{R}",
            f"{C_CYAN}{B}>> DECRYPTING HUD PANELS...{R}",
        ]
    elif state == "FAILED":
        right_lines += [
            f"{C_CRIMSON}{B}✖ FACE SIGNATURE MISSING{R}",
            f"{C_AMBER}{B}>> CLICK OR PRESS [R] TO RETRY{R}",
        ]
    else:
        lock_txt = "FACE LOCKED [OK]" if face_box is not None else "SEARCHING FACE..."
        lock_col = C_MINT if face_box is not None else C_AMBER
        right_lines += [
            f"{lock_col}{B}⟳ {lock_txt}{R}",
            f"{C_SLATE}[f] Fail Test  [Enter] Skip{R}",
        ]

    # Combine Left Live Camera ASCII/Braille + Right Telemetry
    border_col = C_MINT if state == "VERIFIED" else (C_CRIMSON if state == "FAILED" else C_CYAN)
    for ry in range(portrait_h):
        row_cells = grid[ry] if ry < len(grid) else []
        is_scan = (state == "SCANNING") and (ry == scan_row)

        if ry == 0:
            l_b, r_b = f"{border_col}{B}⌜{R}", f"{border_col}{B}⌝{R}"
        elif ry == portrait_h - 1:
            l_b, r_b = f"{border_col}{B}⌞{R}", f"{border_col}{B}⌟{R}"
        elif is_scan:
            l_b, r_b = f"{C_CRIMSON}{B}▶{R}", f"{C_CRIMSON}{B}◀{R}"
        else:
            l_b, r_b = f"{C_GRID}│{R}", f"{C_GRID}│{R}"

        p_chars = []
        for rx in range(portrait_w):
            # Draw live face bounding box corners if detected
            if rel_face is not None and state == "SCANNING":
                fx1, fy1, fx2, fy2 = rel_face
                if (rx, ry) == (fx1, fy1):
                    p_chars.append(f"{C_MINT}{B}┌{R}"); continue
                elif (rx, ry) == (fx2, fy1):
                    p_chars.append(f"{C_MINT}{B}┐{R}"); continue
                elif (rx, ry) == (fx1, fy2):
                    p_chars.append(f"{C_MINT}{B}└{R}"); continue
                elif (rx, ry) == (fx2, fy2):
                    p_chars.append(f"{C_MINT}{B}┘{R}"); continue

            locked_crosshair = any(
                (rx == lx and ry == ly and progress >= l_thresh)
                for lx, ly, l_thresh in landmarks
            )
            if locked_crosshair and state == "SCANNING":
                p_chars.append(f"{C_CRIMSON}{B}╋{R}")
                continue

            cell = row_cells[rx] if rx < len(row_cells) else None
            if cell is None:
                if is_scan:
                    p_chars.append(f"{C_CRIMSON}─{R}" if rx % 3 == 0 else f"{C_GRID}─{R}")
                elif rx % 5 == 0 and ry % 3 == 0:
                    p_chars.append(f"{C_GRID}·{R}")
                else:
                    p_chars.append(" ")
            else:
                ch, lum = cell
                if is_scan:
                    p_chars.append(f"{BG_SCAN}{C_MINT}{B}{ch}{R}")
                elif state == "VERIFIED":
                    col = C_WHITE if lum > 180 else (C_MINT if lum > 95 else C_CYAN)
                    p_chars.append(f"{col}{ch}{R}")
                elif state == "FAILED":
                    col = C_CRIMSON if lum > 110 else f"\033[38;2;140;20;55m"
                    p_chars.append(f"{col}{ch}{R}")
                else:
                    col = C_WHITE if lum > 185 else (C_CYAN_BRT if lum > 130 else (C_CYAN if lum > 70 else C_BLUE))
                    p_chars.append(f"{col}{ch}{R}")

        left_block = f"{l_b}{''.join(p_chars)}{r_b}"
        right_txt = right_lines[ry] if ry < len(right_lines) else ""
        combined = f" {left_block}  {pad_right(right_txt, right_w)}"
        buf.append(center_ansi(combined, cols) + "\033[K")

    buf.append(center_ansi(f"{C_GRID}{'━' * (cols - 2)}{R}", cols) + "\033[K")

    # Bottom Banner / Retry Button
    box_w = min(cols - 4, 58)
    if state == "VERIFIED":
        msg1 = f"{C_MINT}{B}✔ FACE_ID VERIFIED : WELCOME BACK, ACE{R}"
        msg2 = f"{C_CYAN}{B}>> DEDSEC FULLSTACK SYSTEM : ONLINE <<{R}"
        b_col = C_MINT
        buf.append(center_ansi(f"{b_col}╔{'═' * (box_w - 2)}╗{R}", cols) + "\033[K")
        buf.append(center_ansi(f"{b_col}║{R}{center_ansi(msg1, box_w - 2)}{b_col}║{R}", cols) + "\033[K")
        buf.append(center_ansi(f"{b_col}║{R}{center_ansi(msg2, box_w - 2)}{b_col}║{R}", cols) + "\033[K")
        buf.append(center_ansi(f"{b_col}╚{'═' * (box_w - 2)}╝{R}", cols) + "\033[K")
    elif state == "FAILED":
        # Interactive RETRY BUTTON!
        btn_label = f"{BG_BTN}{C_WHITE}{B}  ▶ [ CLICK / PRESS R / ENTER ] RETRY FACE_ID  {R}"
        msg2 = f"{C_AMBER}Ensure /dev/video0 is uncovered & face is centered{R}"
        b_col = C_CRIMSON
        buf.append(center_ansi(f"{b_col}╔{'═' * (box_w - 2)}╗{R}", cols) + "\033[K")
        buf.append(center_ansi(f"{b_col}║{R}{center_ansi(btn_label, box_w - 2)}{b_col}║{R}", cols) + "\033[K")
        buf.append(center_ansi(f"{b_col}║{R}{center_ansi(msg2, box_w - 2)}{b_col}║{R}", cols) + "\033[K")
        buf.append(center_ansi(f"{b_col}╚{'═' * (box_w - 2)}╝{R}", cols) + "\033[K")
    else:
        msg1 = f"{C_CYAN}{B}⟳ SCANNING LIVE CAMERA STREAM ({pct_overall:04.1f}%)...{R}"
        msg2 = f"{C_SLATE}>> PANELS LOCKED IN STATIC ENCRYPTION <<{R}"
        b_col = C_CYAN
        buf.append(center_ansi(f"{b_col}╔{'═' * (box_w - 2)}╗{R}", cols) + "\033[K")
        buf.append(center_ansi(f"{b_col}║{R}{center_ansi(msg1, box_w - 2)}{b_col}║{R}", cols) + "\033[K")
        buf.append(center_ansi(f"{b_col}║{R}{center_ansi(msg2, box_w - 2)}{b_col}║{R}", cols) + "\033[K")
        buf.append(center_ansi(f"{b_col}╚{'═' * (box_w - 2)}╝{R}", cols) + "\033[K")

    sys.stdout.write("\033[H\033[?25l" + "\n".join(buf[:rows]) + "\033[J")
    sys.stdout.flush()


def load_fallback_frame():
    """Fallback frame from Ace's photo only if /dev/video0 is busy or unavailable."""
    img_path = next((p for p in ASSET_PATHS if os.path.exists(p)), None)
    if not img_path:
        return np.zeros((240, 320, 3), dtype=np.uint8)
    bgr = cv2.imread(img_path)
    if bgr is None:
        return np.zeros((240, 320, 3), dtype=np.uint8)
    crop = bgr[0:220, 420:640]
    return cv2.resize(crop, (320, 240))


def read_key_or_mouse(timeout=0.07):
    """Read keyboard key or mouse click (xterm SGR mouse mode)."""
    if not original_termios:
        time.sleep(timeout)
        return None
    rlist, _, _ = select.select([sys.stdin], [], [], timeout)
    if not rlist:
        return None
    ch = sys.stdin.read(1)
    if ch == "\x1b":
        # Read remaining escape sequence if available
        seq = ""
        while select.select([sys.stdin], [], [], 0.005)[0]:
            seq += sys.stdin.read(1)
        if seq.startswith("[<"):
            # Mouse event: \x1b[<btn;x;yM or m
            if seq.endswith("M") and seq.startswith("[<0;"):
                return "MOUSE_CLICK"
            return None
        if seq == "":
            return "ESC"
        return None
    return ch


def run_scan_cycle(cap, fallback_bgr, force_fail=False):
    """
    Run one full biometric camera scan cycle.
    Returns True if verified, False if authentication failed.
    """
    set_faceid_state("LOCKED")
    face_hits = 0
    last_face_box = None
    last_frame = fallback_bgr

    # Warm-up frames (~0.45s) while Zellij floating pane settles
    for w_i in range(6):
        if cap is not None and cap.isOpened():
            ok, frm = cap.read()
            if ok and frm is not None:
                last_frame = cv2.flip(frm, 1)
        render_modal(0.0, w_i, last_frame, None, state="SCANNING")
        ev = read_key_or_mouse(0.06)
        if ev in ("f", "F"):
            force_fail = True

    steps = 28
    for i in range(1, steps + 1):
        if not running:
            return True
        if cap is not None and cap.isOpened():
            ok, frm = cap.read()
            if ok and frm is not None:
                last_frame = cv2.flip(frm, 1)
                has_face, fbox = detect_live_face(last_frame)
                if has_face:
                    face_hits += 1
                    if fbox is not None:
                        last_face_box = fbox
        else:
            # Camera device unavailable fallback
            face_hits += 1

        if force_fail:
            face_hits = 0
            last_face_box = None

        progress = min(0.95 if (force_fail or face_hits < 2) else 1.0, i / float(steps))
        render_modal(progress, i, last_frame, last_face_box, state="SCANNING")
        ev = read_key_or_mouse(0.07)
        if ev in ("f", "F"):
            force_fail = True
            face_hits = 0
        elif ev in ("\r", "\n", " "):
            # Quick verify override if user presses Enter/Space during scan
            face_hits = max(face_hits, 5)
            break
        elif ev in ("q", "Q", "ESC"):
            cleanup()

    if force_fail or face_hits < 2:
        return False, last_frame, last_face_box
    return True, last_frame, last_face_box


def main():
    global original_termios, cap_device
    probe_camera_name()
    fallback_bgr = load_fallback_frame()

    if "--once" in sys.argv:
        state_arg = "FAILED" if "--fail" in sys.argv else "VERIFIED"
        prog = 0.68 if state_arg == "FAILED" else 1.0
        test_frm = cv2.imread("/tmp/live_cam_test.jpg") if os.path.exists("/tmp/live_cam_test.jpg") else fallback_bgr
        _, fbox = detect_live_face(test_frm)
        render_modal(prog, 10, test_frm, fbox or (91, 104, 82, 82), state=state_arg)
        sys.stdout.write("\n")
        cleanup()

    set_faceid_state("LOCKED")

    # Open live camera /dev/video0
    try:
        cap_device = cv2.VideoCapture(0, cv2.CAP_V4L2)
        cap_device.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
        cap_device.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
        cap_device.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:
        cap_device = None

    if sys.stdin.isatty():
        try:
            original_termios = termios.tcgetattr(sys.stdin.fileno())
            tty.setcbreak(sys.stdin.fileno())
            # Enter alternate screen, disable line wrap, clear scrollback, enable mouse tracking
            sys.stdout.write("\033[?1049h\033[?7l\033[3J\033[?1000h\033[?1006h")
            sys.stdout.flush()
        except Exception:
            original_termios = None

    force_fail_init = ("--test-fail" in sys.argv)

    while running:
        verified, last_frame, last_face_box = run_scan_cycle(cap_device, fallback_bgr, force_fail=force_fail_init)
        force_fail_init = False  # Only force fail on first run if --test-fail was passed

        if verified:
            # Keep underlying panels LOCKED in static encryption while modal displays VERIFIED banner;
            # cleanup() will trigger UNLOCKED + panel fade-in transition right as this modal exits!
            for hold_tick in range(14):
                if not running:
                    break
                if cap_device is not None and cap_device.isOpened():
                    ok, frm = cap_device.read()
                    if ok and frm is not None:
                        last_frame = cv2.flip(frm, 1)
                render_modal(1.0, 30 + hold_tick, last_frame, last_face_box, state="VERIFIED")
                ev = read_key_or_mouse(0.08)
                if ev in ("\r", "\n", " ", "q", "Q", "ESC", "MOUSE_CLICK"):
                    break
            break
        else:
            # Authentication FAILED! Keep underlying panels blurred/locked and wait for Retry button
            set_faceid_state("FAILED")
            fail_tick = 0
            while running:
                if cap_device is not None and cap_device.isOpened():
                    ok, frm = cap_device.read()
                    if ok and frm is not None:
                        last_frame = cv2.flip(frm, 1)
                render_modal(0.42, fail_tick, last_frame, None, state="FAILED")
                fail_tick += 1
                ev = read_key_or_mouse(0.09)
                if ev in ("r", "R", "\r", "\n", " ", "MOUSE_CLICK"):
                    # Retry button clicked or pressed!
                    break
                elif ev in ("q", "Q", "ESC"):
                    cleanup()

    cleanup()


if __name__ == "__main__":
    main()
