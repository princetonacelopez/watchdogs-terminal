#!/usr/bin/env python3
"""
ctos-panel-guard: Watch Dogs ctOS 2.0 Blurred/Static Panel Guard & Fade-In Transition Wrapper.
Wraps any Zellij panel command (e.g. zsh, lazygit, dymus, etc.):
  1. While /tmp/ctos_faceid_state.json is "LOCKED" or "FAILED" (during FaceID modal scan),
     renders an animated Watch Dogs blurred/static noise matrix beneath the modal.
  2. As soon as FaceID succeeds ("UNLOCKED"), plays a smooth 12-frame TrueColor Fade-In /
     Digital Dissolve transition before exec-ing the target panel command!
"""

import os
import sys
import time
import json
import math
import random
import shutil
import signal
import re
import unicodedata

STATE_FILE = "/tmp/ctos_faceid_state.json"

R = "\033[0m"
B = "\033[1m"
C_CYAN    = "\033[38;2;0;240;255m"
C_MINT    = "\033[38;2;0;255;156m"
C_CRIMSON = "\033[38;2;255;0;85m"
C_SLATE   = "\033[38;2;90;116;142m"
BG_SCAN   = "\033[48;2;0;55;75m"


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


def get_faceid_info():
    if not os.path.exists(STATE_FILE):
        return "UNLOCKED", 0.0
    try:
        with open(STATE_FILE, "r") as f:
            data = json.load(f)
        # Expire stale lock after 45 seconds
        if time.time() - data.get("ts", 0) > 45:
            return "UNLOCKED", 0.0
        return data.get("state", "UNLOCKED"), float(data.get("unlock_ts", 0.0))
    except Exception:
        return "UNLOCKED", 0.0


def render_static_frame(tick, failed=False, fade_out=0.0):
    """
    Render Watch Dogs blurred/static effect across the panel.
    fade_out in [0.0 .. 1.0]: 0.0 = full static/blur, 1.0 = fully faded into clean ctOS panel.
    """
    cols, rows = shutil.get_terminal_size((60, 18))
    cols = max(16, cols)
    rows = max(6, rows)

    # Characters ordered from dense blurred blocks to sparse dots to empty space
    if fade_out <= 0.0:
        chars = "░▒▓▒░·:∷"
    elif fade_out < 0.35:
        chars = "░▒░·:·  "
    elif fade_out < 0.70:
        chars = "░·.     "
    else:
        chars = "·       "

    reveal_row = int(fade_out * rows)
    buf = []

    for y in range(rows):
        if fade_out == 0.0 and y == rows // 2:
            if failed:
                tag = f"{C_CRIMSON}{B} ✖ [ctOS // ACCESS_DENIED :: BIOMETRIC LOCKED] {R}"
            else:
                tag = f"\033[38;2;0;165;200m{B}  [ctOS // ENCRYPTED_PANEL :: SCANNING FACE_ID] {R}"
            buf.append(center_ansi(tag, cols) + "\033[K")
            continue

        if fade_out > 0.0 and y == reveal_row:
            # Glowing cyan/emerald transition beam wiping down the panel
            beam = f"{BG_SCAN}{C_MINT}{B}{'━' * cols}{R}"
            buf.append(beam + "\033[K")
            continue
        elif fade_out > 0.0 and y < reveal_row:
            # Already faded-in region above the decrypt curtain: subtle fading phosphor glow
            glow = max(0.0, 1.0 - (reveal_row - y) / max(1.0, rows * 0.45))
            br = int(7 + 0 * glow)
            bg_c = int(9 + 36 * glow)
            bb = int(14 + 52 * glow)
            buf.append(f"\033[48;2;{br};{bg_c};{bb}m{' ' * cols}{R}\033[K")
            continue

        # Blurred wave + static noise
        row_s = []
        # Step by 2 columns for faster, chunkier "blurred" blocks
        for x in range(0, cols, 2):
            wave = math.sin(x * 0.18 + tick * 0.55) + math.cos(y * 0.35 - tick * 0.45)
            idx = int((wave + 2.0) / 4.0 * (len(chars) - 1) + random.randint(0, 1)) % len(chars)
            ch = chars[idx]
            pair = ch * min(2, cols - x)
            fade_mult = max(0.15, 1.0 - fade_out * 0.85)
            if failed:
                r = int((38 + idx * 14) * fade_mult)
                g = int(10 * fade_mult)
                b = int(24 * fade_mult)
            else:
                r = int(12 * fade_mult)
                g = int((26 + idx * 9) * fade_mult)
                b = int((40 + idx * 13) * fade_mult)
            row_s.append(f"\033[38;2;{r};{g};{b}m{pair}")
        buf.append("".join(row_s) + f"{R}\033[K")

    sys.stdout.write("\033[H\033[?25l" + "\n".join(buf[:rows]) + "\033[J")
    sys.stdout.flush()


def main():
    # Ensure ~/.local/bin is in PATH for Zellij child processes
    local_bin = os.path.expanduser("~/.local/bin")
    cur_path = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    if local_bin not in cur_path.split(":"):
        os.environ["PATH"] = f"{local_bin}:{cur_path}"

    target_cmd = sys.argv[1:]
    default_shell = os.environ.get("SHELL", "/bin/bash")
    if not os.path.exists(default_shell):
        default_shell = "/bin/bash"

    if not target_cmd or not shutil.which(target_cmd[0]):
        target_cmd = [default_shell]

    # Wait while FaceID modal is active; only run transition AFTER modal exits (time >= unlock_ts)
    tick = 0
    st, unlock_ts = get_faceid_info()
    if st in ("LOCKED", "FAILED") or (unlock_ts > time.time()):
        sys.stdout.write("\033[?1049h\033[?7l\033[3J\033[?1000h\033[?1006h")
        sys.stdout.flush()
        while st in ("LOCKED", "FAILED") or (unlock_ts > time.time()):
            render_static_frame(tick, failed=(st == "FAILED"), fade_out=0.0)
            time.sleep(0.06)
            tick += 1
            st, unlock_ts = get_faceid_info()

        # FaceID Modal has exited! Run 15-frame smooth Fade-In / Decrypt Transition
        steps = 15
        for i in range(1, steps + 1):
            render_static_frame(tick + i, failed=False, fade_out=i / float(steps))
            time.sleep(0.045)

    # Clear screen, clear scrollback, and restore terminal before handing over to the real panel
    sys.stdout.write("\033[?1000l\033[?1006l\033[?7h\033[?25h\033[0m\033[?1049l\033[2J\033[3J\033[H")
    sys.stdout.flush()
    if "--inline" in sys.argv:
        return
    os.execvp(target_cmd[0], target_cmd)


if __name__ == "__main__":
    main()
