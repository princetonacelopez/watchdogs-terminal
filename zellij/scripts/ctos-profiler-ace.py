#!/usr/bin/env python3
"""
ctos-profiler-ace: Watch Dogs ctOS 2.0 / DedSec High-Detail 1:1 Full-Panel Biometric Portrait
Top-left Zellij panel displaying:
  1. Ace's high-resolution 1:1 aspect ratio 2x4 sub-pixel Unicode Braille & TrueColor portrait
     shifted down slightly for clean headroom above the cap and a clean torso cutoff at the bottom.
  2. Ace
  3. Fullstack Developer
  4. WebIT | Offsure
  5. ● Online
Also reacts to /tmp/ctos_faceid_state.json (blurred/static during FaceID auth + fade-in transition).
Press 'm' when focused to cycle visual modes (Hologram Braille / TrueColor HD / Mono).
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
from PIL import Image, ImageFilter

ASSET_PATHS = [
    os.path.expanduser("~/.config/zellij/assets/ace_photo.jpg"),
    "/home/princetonacelopez/Documents/antigravity/serene-volta/zellij/assets/ace_photo.jpg",
]
STATE_FILE = "/tmp/ctos_faceid_state.json"

# Watch Dogs ctOS TrueColor ANSI Palette
R          = "\033[0m"
B          = "\033[1m"

C_CYAN     = "\033[38;2;0;240;255m"     # #00F0FF ctOS Electric Cyan
C_CYAN_BRT = "\033[38;2;150;252;255m"   # #96FCFF Scan Beam Highlight
C_BLUE     = "\033[38;2;0;175;255m"     # #00AFFF ctOS Data Link Blue
C_CRIMSON  = "\033[38;2;255;0;85m"      # #FF0055 DedSec Intrusion Red
C_MINT     = "\033[38;2;0;255;156m"     # #00FF9C Access Granted / Online Mint
C_PURPLE   = "\033[38;2;214;0;255m"     # #D600FF DedSec Purple
C_WHITE    = "\033[38;2;226;241;255m"   # #E2F1FF Ice White
C_SLATE    = "\033[38;2;122;147;172m"   # #7A93AC Tactical Slate
C_GRID     = "\033[38;2;22;34;48m"      # #162230 Subtle Background Grid

BG_SCAN    = "\033[48;2;0;55;75m"       # Subtle Cyan Scanline Background Tint
BG_GLITCH  = "\033[48;2;45;0;25m"       # Subtle Crimson Glitch Tint

DOT_BITS = [
    [0x01, 0x08],
    [0x02, 0x10],
    [0x04, 0x20],
    [0x40, 0x80],
]

BAYER = [
    [ 15, 135],
    [195,  75],
    [ 45, 165],
    [225, 105],
]

running = True
original_termios = None
render_mode = 0
last_auth_state = "UNLOCKED"
fade_progress = 1.0  # 0.0 -> 1.0 during fade-in transition


def cleanup(sig=None, frame=None):
    global running, original_termios
    running = False
    if original_termios:
        try:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, original_termios)
        except Exception:
            pass
    if "--once" not in sys.argv:
        sys.stdout.write("\033[?1000l\033[?1006l\033[?7h\033[?25h\033[0m\033[?1049l")
    else:
        sys.stdout.write("\033[?25h\033[0m\n")
    sys.stdout.flush()
    sys.exit(0)


signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)


def get_faceid_state():
    if not os.path.exists(STATE_FILE):
        return "UNLOCKED"
    try:
        with open(STATE_FILE, "r") as f:
            data = json.load(f)
        if time.time() - data.get("ts", 0) > 45:
            return "UNLOCKED"
        st = data.get("state", "UNLOCKED")
        unlock_ts = float(data.get("unlock_ts", 0.0))
        if st == "UNLOCKED" and unlock_ts > time.time():
            return "LOCKED"
        return st
    except Exception:
        return "UNLOCKED"


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


def load_segmented_portrait():
    img_path = next((p for p in ASSET_PATHS if os.path.exists(p)), None)
    if not img_path:
        return None, None, None, None, 0, 0

    im = Image.open(img_path).convert("RGB")
    # Crop from y=0..146 and add 26px of headroom above the head so the portrait shifts down
    # with breathing room above Ace's cap and a clean cutoff across the chest/sweatshirt at the bottom!
    raw_crop = im.crop((440, 0, 616, 162))
    cw, ch = raw_crop.size
    headroom = 14
    sq_size = ch + headroom  # 176 x 176 (true 1:1 square)

    # Sample top background color to fill headroom seamlessly
    top_bg = raw_crop.getpixel((0, 0))
    crop_rgb = Image.new("RGB", (sq_size, sq_size), top_bg)
    crop_rgb.paste(raw_crop, (0, headroom))

    w, h = crop_rgb.size
    px = crop_rgb.load()

    bg_mask = [[False] * w for _ in range(h)]
    q = deque()
    for y in range(h):
        q.append((0, y)); bg_mask[y][0] = True
        q.append((w - 1, y)); bg_mask[y][w - 1] = True
    for x in range(w):
        q.append((x, 0)); bg_mask[0][x] = True

    while q:
        cx, cy = q.popleft()
        br, bg_g, bb = px[0, cy] if cx < w // 2 else px[w - 1, cy]
        for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
            if 0 <= nx < w and 0 <= ny < h and not bg_mask[ny][nx]:
                r1, g1, b1 = px[nx, ny]
                if abs(r1 - br) + abs(g1 - bg_g) + abs(b1 - bb) < 26 and (r1 - b1) > 55:
                    bg_mask[ny][nx] = True
                    q.append((nx, ny))

    gray = crop_rgb.convert("L")
    sharp_gray = gray.filter(ImageFilter.UnsharpMask(radius=2.2, percent=260, threshold=2))
    edges_gray = gray.filter(ImageFilter.FIND_EDGES)
    sharp_rgb = crop_rgb.filter(ImageFilter.UnsharpMask(radius=1.8, percent=180, threshold=2))

    return sharp_rgb, sharp_gray, edges_gray, bg_mask, w, h


SHARP_RGB, SHARP_GRAY, EDGES_GRAY, BG_MASK, SRC_W, SRC_H = load_segmented_portrait()
GRID_CACHE = {}


def map_1to1_coords(u, v, vis_w, vis_h):
    """Map normalized (u, v) in [0, 1] into the 1:1 source square anchored to the bottom edge for clean cutoff."""
    panel_aspect = vis_w / max(0.1, vis_h)
    if panel_aspect > 1.0:
        scale_u = 1.0
        scale_v = 1.0 / panel_aspect
    else:
        scale_u = panel_aspect
        scale_v = 1.0

    su = (u - 0.5) * scale_u + 0.5
    # Anchor bottom (v=1.0 -> sv=1.0) so torso cuts off cleanly at the bottom border and headroom stays above head
    sv = 1.0 - (1.0 - v) * scale_v
    sx = int(su * SRC_W)
    sy = int(sv * SRC_H)
    return sx, sy


def build_portrait_grid(tw, th, mode):
    key = (tw, th, mode)
    if key in GRID_CACHE:
        return GRID_CACHE[key]

    if SHARP_RGB is None:
        GRID_CACHE[key] = []
        return []

    rgb_px = SHARP_RGB.load()
    spx = SHARP_GRAY.load()
    epx = EDGES_GRAY.load()
    rows_data = []

    vis_w = tw / 2.0
    vis_h = float(th)

    if mode in (0, 2):
        for ty in range(th):
            row_cells = []
            for tx in range(tw):
                mask_bits = 0
                fg_dots = 0
                lum_sum = 0
                r_sum = g_sum = b_sum = 0
                any_fg = False

                for dy in range(4):
                    for dx in range(2):
                        u = (tx * 2 + dx + 0.5) / (tw * 2)
                        v = (ty * 4 + dy + 0.5) / (th * 4)
                        sx, sy = map_1to1_coords(u, v, vis_w, vis_h)
                        if 0 <= sx < SRC_W and 0 <= sy < SRC_H and not BG_MASK[sy][sx]:
                            any_fg = True
                            val = spx[sx, sy]
                            ed = epx[sx, sy]
                            r, g, b = rgb_px[sx, sy]
                            lum_sum += val
                            r_sum += r; g_sum += g; b_sum += b
                            fg_dots += 1

                            is_border = any(
                                BG_MASK[max(0, min(SRC_H - 1, sy + oy))][max(0, min(SRC_W - 1, sx + ox))]
                                for ox, oy in ((-1, 0), (1, 0), (0, -1), (0, 1))
                            )
                            if is_border or ed > 42 or val > BAYER[dy][dx]:
                                mask_bits |= DOT_BITS[dy][dx]

                if not any_fg or mask_bits == 0:
                    row_cells.append(None)
                else:
                    ch = chr(0x2800 + mask_bits)
                    avg_lum = lum_sum / max(1, fg_dots)
                    avg_r = r_sum // max(1, fg_dots)
                    avg_g = g_sum // max(1, fg_dots)
                    avg_b = b_sum // max(1, fg_dots)
                    row_cells.append((ch, avg_lum, (avg_r, avg_g, avg_b)))
            rows_data.append(row_cells)
    else:
        for ty in range(th):
            row_cells = []
            v_top = (ty * 2 + 0.5) / (th * 2)
            v_bot = (ty * 2 + 1.5) / (th * 2)
            for tx in range(tw):
                u = (tx + 0.5) / tw
                sx_t, sy_top = map_1to1_coords(u, v_top, vis_w, vis_h)
                sx_b, sy_bot = map_1to1_coords(u, v_bot, vis_w, vis_h)
                bg_t = not (0 <= sx_t < SRC_W and 0 <= sy_top < SRC_H) or BG_MASK[sy_top][sx_t]
                bg_b = not (0 <= sx_b < SRC_W and 0 <= sy_bot < SRC_H) or BG_MASK[sy_bot][sx_b]
                if bg_t and bg_b:
                    row_cells.append(None)
                else:
                    rt, gt, bt = (7, 9, 14) if bg_t else rgb_px[sx_t, sy_top]
                    rb, gb, bb = (7, 9, 14) if bg_b else rgb_px[sx_b, sy_bot]
                    lum = 128 if bg_t else spx[sx_t, sy_top]
                    row_cells.append(("▀", lum, (rt, gt, bt, rb, gb, bb)))
            rows_data.append(row_cells)

    GRID_CACHE[key] = rows_data
    return rows_data


def holo_color_for_lum(lum, fade=1.0):
    if lum < 55:
        r, g, b = 45, 185, 255
    elif lum < 110:
        r, g, b = 0, 215, 245
    elif lum < 165:
        r, g, b = 85, 245, 255
    elif lum < 205:
        r, g, b = 175, 250, 255
    else:
        r, g, b = 230, 245, 255
    r = int(7 + (r - 7) * fade)
    g = int(9 + (g - 9) * fade)
    b = int(14 + (b - 14) * fade)
    return f"\033[38;2;{r};{g};{b}m"


def render_static_blur(cols, rows, tick, failed=False):
    """Render blurred/static ctOS effect while FaceID modal is authenticating."""
    chars = "░▒▓·:∷"
    buf = []
    for y in range(rows):
        if y == rows // 2:
            if failed:
                tag = f"\033[38;2;255;0;85m{B} ✖ BIOMETRIC LOCKED {R}"
            else:
                tag = f"\033[38;2;0;160;190m{B}  SCANNING FACE_ID {R}"
            buf.append(center_ansi(tag, cols) + "\033[K")
            continue
        row_s = []
        for x in range(cols):
            # Coherent blurred noise wave + high-freq static
            v = math.sin(x * 0.25 + tick * 0.6) + math.cos(y * 0.4 - tick * 0.5)
            idx = int((v + 2.0) / 4.0 * (len(chars) - 1) + random.randint(0, 1)) % len(chars)
            ch = chars[idx]
            if failed:
                c = f"\033[38;2;{35 + (idx*12)};10;22m"
            else:
                c = f"\033[38;2;14;{28 + (idx*10)};{42 + (idx*14)}m"
            row_s.append(f"{c}{ch}")
        buf.append("".join(row_s) + f"{R}\033[K")
    sys.stdout.write("\033[H\033[?25l" + "\n".join(buf[:rows]) + "\033[J")
    sys.stdout.flush()


def render_frame(tick, fade=1.0):
    cols, rows = shutil.get_terminal_size((34, 22))
    cols = max(16, cols)
    rows = max(10, rows)

    buf = []

    reserved_bottom = 4
    portrait_h = max(6, rows - reserved_bottom)
    portrait_w = max(12, cols - 2)

    grid = build_portrait_grid(portrait_w, portrait_h, render_mode)
    scan_row = int((tick * 0.45) % (portrait_h + 4)) - 2
    glitch_active = (tick % 31 == 0)
    glitch_row = (tick * 7) % max(1, portrait_h)

    reveal_row = int(fade * portrait_h)
    static_chars = "░▒▓·"

    for ry in range(portrait_h):
        row_cells = grid[ry] if ry < len(grid) else []
        dist_scan = abs(ry - scan_row)
        is_scan_beam = (ry == scan_row)
        is_scan_trail = (dist_scan == 1)
        is_glitch_row = glitch_active and (ry == glitch_row)

        if ry == 0:
            l_brk = f"{C_CYAN}{B}⌜{R}"
            r_brk = f"{C_CYAN}{B}⌝{R}"
        elif ry == portrait_h - 1:
            l_brk = f"{C_CYAN}{B}⌞{R}"
            r_brk = f"{C_CYAN}{B}⌟{R}"
        elif is_scan_beam:
            l_brk = f"{C_CRIMSON}{B}▶{R}"
            r_brk = f"{C_CRIMSON}{B}◀{R}"
        else:
            l_brk = f"{C_GRID}│{R}"
            r_brk = f"{C_GRID}│{R}"

        line_chars = []
        for rx in range(portrait_w):
            if fade < 1.0 and ry > reveal_row:
                # Below fade curtain: dissolving static
                sc = static_chars[(rx + ry + tick) % len(static_chars)]
                line_chars.append(f"\033[38;2;18;38;52m{sc}{R}")
                continue
            elif fade < 1.0 and ry == reveal_row:
                # Active fade transition beam
                line_chars.append(f"{BG_SCAN}{C_MINT}{B}━{R}")
                continue

            cell = row_cells[rx] if rx < len(row_cells) else None
            if cell is None:
                if is_scan_beam:
                    line_chars.append(f"{C_CRIMSON}─{R}" if rx % 4 == 0 else f"{C_GRID}─{R}")
                elif (rx % 6 == 0 and ry % 3 == 0):
                    line_chars.append(f"{C_GRID}·{R}")
                else:
                    line_chars.append(" ")
            else:
                ch, lum, color_info = cell
                if is_scan_beam:
                    line_chars.append(f"{BG_SCAN}{C_MINT}{B}{ch}{R}")
                elif is_scan_trail and render_mode != 1:
                    line_chars.append(f"{C_CYAN_BRT}{B}{ch}{R}")
                elif is_glitch_row:
                    line_chars.append(f"{BG_GLITCH}{C_CRIMSON}{B}{ch}{R}")
                elif render_mode == 0:
                    c_code = holo_color_for_lum(lum, fade)
                    line_chars.append(f"{c_code}{ch}{R}")
                elif render_mode == 1:
                    rt, gt, bt, rb, gb, bb = color_info
                    line_chars.append(f"\033[38;2;{rt};{gt};{bt}m\033[48;2;{rb};{gb};{bb}m▀{R}")
                else:
                    line_chars.append(f"{C_WHITE}{ch}{R}")

        inner_row = "".join(line_chars)
        framed_row = f"{l_brk}{inner_row}{r_brk}"
        buf.append(center_ansi(framed_row, cols) + "\033[K")

    # Identity Block:
    #   Ace
    #   Fullstack Developer
    #   WebIT | Offsure
    #   ● Online
    pulse_dot    = f"{C_MINT}{B}●{R}" if (tick % 6 < 4) else f"{C_CYAN}◉{R}"
    line_name    = center_ansi(f"{C_WHITE}{B}Ace{R}", cols)
    line_role    = center_ansi(f"{C_CYAN}Fullstack Developer{R}", cols)
    line_company = center_ansi(f"{C_SLATE}{B}WebIT {C_CRIMSON}|{C_SLATE}{B} Offsure{R}", cols)
    line_status  = center_ansi(f"{pulse_dot} {C_MINT}{B}Online{R}", cols)

    buf.append(f"{line_name}\033[K")
    buf.append(f"{line_role}\033[K")
    buf.append(f"{line_company}\033[K")
    buf.append(f"{line_status}\033[K")

    sys.stdout.write("\033[H\033[?25l" + "\n".join(buf[:rows]) + "\033[J")
    sys.stdout.flush()


def main():
    global render_mode, original_termios, last_auth_state, fade_progress
    if "--once" in sys.argv:
        render_frame(4, 1.0)
        cleanup()

    if sys.stdin.isatty():
        try:
            original_termios = termios.tcgetattr(sys.stdin.fileno())
            tty.setcbreak(sys.stdin.fileno())
            sys.stdout.write("\033[?1049h\033[?7l\033[3J\033[?1000h\033[?1006h")
            sys.stdout.flush()
        except Exception:
            original_termios = None

    init_mtime = os.path.getmtime(os.path.abspath(__file__)) if os.path.exists(__file__) else 0
    tick = 0
    while running:
        try:
            cur_mtime = os.path.getmtime(os.path.abspath(__file__))
            if init_mtime and cur_mtime != init_mtime:
                if original_termios:
                    termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, original_termios)
                os.execv(sys.executable, [sys.executable] + sys.argv)
        except Exception:
            pass

        st = get_faceid_state()
        if st in ("LOCKED", "FAILED"):
            cols, rows = shutil.get_terminal_size((34, 22))
            render_static_blur(max(16, cols), max(10, rows), tick, failed=(st == "FAILED"))
            last_auth_state = st
            fade_progress = 0.0
        else:
            if last_auth_state in ("LOCKED", "FAILED"):
                last_auth_state = "UNLOCKED"
                fade_progress = 0.07
            elif fade_progress < 1.0:
                fade_progress = min(1.0, fade_progress + 0.08)
            render_frame(tick, fade_progress)

        tick += 1
        if original_termios:
            rlist, _, _ = select.select([sys.stdin], [], [], 0.09)
            if rlist:
                ch = sys.stdin.read(1)
                if ch == "\x1b":
                    while select.select([sys.stdin], [], [], 0.005)[0]:
                        sys.stdin.read(1)
                elif ch in ("m", "M"):
                    render_mode = (render_mode + 1) % 3
        else:
            time.sleep(0.09)


if __name__ == "__main__":
    main()
