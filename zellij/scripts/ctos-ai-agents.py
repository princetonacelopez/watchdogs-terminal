#!/usr/bin/env python3
"""
ctos-ai-agents: Watch Dogs ctOS 2.0 // DedSec AI Agents Squad Monitor & Character Avatar Preview
Powered by open-source character avatar & pixel art libraries:
  • DiceBear Open-Source Pixel-Art & Bottts Character Avatars (MIT License)
  • pixelart-py (PyPI open-source programmatic pixel-art sprite generator)
  • psutil real-time process & memory telemetry
  • Native Kitty Graphics Protocol (\033_G...) character avatar rendering in Ghostty + Zellij 0.45.1

Monitors active and available AI coding agents on this machine:
  1. Antigravity (Google DeepMind `agy` / `antigravity-ide`) — Character: NOVA // AGY-01
  2. Cursor (`cursor` / `cursor-agent`)                      — Character: VORTEX // CUR-02
  3. OpenCode (`opencode`)                                   — Character: WRENCH // OPC-03
  4. GitHub Copilot (`copilot`)                              — Character: AERO // COP-04
  5. LM Studio (`lmstudio` / `lms`)                          — Character: FORGE // LMS-05

Controls:
  [j / k] or [↑ / ↓] or Mouse Wheel : Select AI Agent
  [Enter / o]                       : Launch selected AI Agent in current workspace
  [r]                               : Refresh live agent telemetry
"""

import base64
import io
import json
import os
import random
import re
import select
import shutil
import signal
import subprocess
import sys
import termios
import time
import tty
import unicodedata

import psutil
from PIL import Image, ImageDraw

try:
    import pixelart_py
    HAS_PIXELART_PY = True
except ImportError:
    HAS_PIXELART_PY = False

# Watch Dogs ctOS 2.0 TrueColor ANSI Palette
R         = "\033[0m"
B         = "\033[1m"
C_CYAN    = "\033[38;2;0;240;255m"      # #00F0FF Electric Cyan
C_BLUE    = "\033[38;2;0;168;255m"      # #00A8FF Data Link Blue
C_MINT    = "\033[38;2;0;255;156m"      # #00FF9C Access Granted Mint
C_CRIMSON = "\033[38;2;255;0;85m"       # #FF0055 DedSec Intrusion Red
C_AMBER   = "\033[38;2;255;214;0m"      # #FFD600 Profiler Warning Amber
C_PURPLE  = "\033[38;2;214;0;255m"      # #D600FF DedSec Purple
C_WHITE   = "\033[38;2;226;241;255m"    # #E2F1FF Ice White
C_SILVER  = "\033[38;2;175;200;225m"    # #AFC8E1 Soft Silver
C_SLATE   = "\033[38;2;105;130;155m"    # #69829B Muted Slate
C_GRID    = "\033[38;2;28;44;64m"       # #1C2C40 Grid Frame

BG_CARD   = "\033[48;2;12;18;28m"
BG_SEL    = "\033[48;2;0;48;70m"
BG_BADGE  = "\033[48;2;0;240;255m\033[38;2;7;9;14m"

ASSETS_DIR = os.path.expanduser("~/.config/zellij/assets/agents")
os.makedirs(ASSETS_DIR, exist_ok=True)

AGENTS_CATALOG = [
    {
        "id": "antigravity",
        "name": "Antigravity",
        "codename": "NOVA // AGY-01",
        "role": "DeepMind Agentic IDE & CLI",
        "color": C_CYAN,
        "border_rgb": (0, 240, 255),
        "avatar_file": os.path.join(ASSETS_DIR, "antigravity.png"),
        "binaries": [
            os.path.expanduser("~/.local/bin/agy"),
            os.path.expanduser("~/.local/bin/antigravity"),
            os.path.expanduser("~/.local/bin/antigravity-ide"),
        ],
        "proc_patterns": ["antigravity", "agy", "language_server_linux_x64"],
        "launch_cmd": [os.path.expanduser("~/.local/bin/antigravity"), "."],
        "sprite_face": "⌜◉_◉⌝",
    },
    {
        "id": "cursor",
        "name": "Cursor AI",
        "codename": "VORTEX // CUR-02",
        "role": "AI Code Editor & Spec-Ops Agent",
        "color": C_PURPLE,
        "border_rgb": (214, 0, 255),
        "avatar_file": os.path.join(ASSETS_DIR, "cursor.png"),
        "binaries": [
            "/usr/bin/cursor",
            os.path.expanduser("~/.local/bin/cursor-agent"),
            os.path.expanduser("~/.local/bin/agent"),
        ],
        "proc_patterns": ["/usr/share/cursor/cursor", "cursor-agent"],
        "launch_cmd": ["/usr/bin/cursor", "."],
        "sprite_face": "╭▀_▀╮",
    },
    {
        "id": "opencode",
        "name": "OpenCode",
        "codename": "WRENCH // OPC-03",
        "role": "DedSec Terminal Coding Agent",
        "color": C_MINT,
        "border_rgb": (0, 255, 156),
        "avatar_file": os.path.join(ASSETS_DIR, "opencode.png"),
        "binaries": [
            os.path.expanduser("~/.opencode/bin/opencode"),
        ],
        "proc_patterns": ["opencode"],
        "launch_cmd": [os.path.expanduser("~/.opencode/bin/opencode")],
        "sprite_face": "⟦^‿^⟧",
    },
    {
        "id": "copilot",
        "name": "GitHub Copilot",
        "codename": "AERO // COP-04",
        "role": "Tactical Pair-Programmer Droid",
        "color": C_AMBER,
        "border_rgb": (255, 214, 0),
        "avatar_file": os.path.join(ASSETS_DIR, "copilot.png"),
        "binaries": [
            os.path.expanduser("~/.local/bin/copilot"),
        ],
        "proc_patterns": ["copilot"],
        "launch_cmd": [os.path.expanduser("~/.local/bin/copilot")],
        "sprite_face": "⟅◕_◕⟆",
    },
    {
        "id": "lmstudio",
        "name": "LM Studio",
        "codename": "FORGE // LMS-05",
        "role": "Local LLM Runtime & Agent Core",
        "color": C_CRIMSON,
        "border_rgb": (255, 0, 85),
        "avatar_file": os.path.join(ASSETS_DIR, "lmstudio.png"),
        "binaries": [
            os.path.expanduser("~/.lmstudio/bin/lms"),
            os.path.expanduser("~/.local/bin/lmstudio"),
        ],
        "proc_patterns": ["lmstudio", "LM-Studio", "/lms"],
        "launch_cmd": [os.path.expanduser("~/.local/bin/lmstudio")],
        "sprite_face": "⦗■_■⦘",
    },
]

running = True
original_termios = None
selected_idx = 0
kitty_avatar_cache = {}
telemetry_cache = []
last_telemetry_ts = 0.0


def cleanup(sig=None, frame=None):
    global running, original_termios
    running = False
    if original_termios:
        try:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, original_termios)
        except Exception:
            pass
    if "--once" not in sys.argv:
        sys.stdout.write("\033_Ga=d,d=A,q=2\033\\\033[?1000l\033[?1006l\033[?7h\033[?25h\033[0m\033[?1049l")
    else:
        sys.stdout.write("\033[?25h\033[0m\n")
    sys.stdout.flush()
    sys.exit(0)


signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)


def char_width(ch: str) -> int:
    if unicodedata.combining(ch) or ch in ("\ufe0f", "\u200d"):
        return 0
    if unicodedata.east_asian_width(ch) in ("W", "F") or ord(ch) >= 0x1F300:
        return 2
    return 1


def str_width(s: str) -> int:
    clean = re.sub(r"\033\[[0-9;?]*[a-zA-Z]", "", s or "")
    return sum(char_width(ch) for ch in clean)


def clip_plain(s: str, max_w: int) -> str:
    s = " ".join((s or "").replace("\n", " ").split())
    if max_w <= 1:
        return ""
    if str_width(s) <= max_w:
        return s
    out = []
    w = 0
    for ch in s:
        cw = char_width(ch)
        if w + cw > max_w - 1:
            break
        out.append(ch)
        w += cw
    return "".join(out) + "…"


def pad_ansi(s: str, width: int) -> str:
    w = str_width(s)
    if w >= width:
        return s
    return s + (" " * (width - w))


def ensure_pixelart_fallback(agent: dict):
    """If the DiceBear PNG is missing, generate a crisp 16x16 character sprite via pixelart-py."""
    path = agent["avatar_file"]
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return
    r, g, b = agent["border_rgb"]
    if HAS_PIXELART_PY:
        try:
            canvas = pixelart_py.Canvas(16, 16)
            bg_hex = f"#{r//8:02x}{g//8:02x}{b//8:02x}"
            fg_hex = f"#{r:02x}{g:02x}{b:02x}"
            canvas.fill(bg_hex)
            canvas.rect(3, 2, 12, 11, fg_hex, filled=True)
            canvas.rect(4, 5, 11, 7, "#07090e", filled=True)
            canvas.set_pixel(5, 6, "#00ff9c")
            canvas.set_pixel(10, 6, "#00ff9c")
            canvas.rect(2, 12, 13, 15, fg_hex, filled=True)
            pixelart_py.save_png(canvas, path, scale=8)
            return
        except Exception:
            pass
    img = Image.new("RGB", (128, 128), (12, 18, 28))
    drw = ImageDraw.Draw(img)
    drw.rectangle([20, 16, 108, 92], fill=(r, g, b))
    drw.rectangle([30, 38, 98, 58], fill=(7, 9, 14))
    img.save(path, format="PNG")


def get_kitty_avatar(agent: dict, is_active: bool, w_cells: int, h_cells: int) -> str:
    """Build framed character avatar PNG and encode as Kitty Graphics Protocol sequence."""
    ensure_pixelart_fallback(agent)
    path = agent["avatar_file"]
    cache_key = (agent["id"], is_active, w_cells, h_cells)
    if cache_key in kitty_avatar_cache:
        return kitty_avatar_cache[cache_key]

    try:
        base_img = Image.open(path).convert("RGBA")
        size_px = 144
        base_img = base_img.resize((size_px, size_px), resample=Image.Resampling.NEAREST)

        # Add Watch Dogs tactical corner frame + active status indicator dot
        framed = Image.new("RGBA", (size_px + 8, size_px + 8), (12, 18, 28, 255))
        framed.paste(base_img, (4, 4), base_img)
        drw = ImageDraw.Draw(framed)
        br, bg, bb = agent["border_rgb"] if is_active else (70, 95, 120)
        drw.rectangle([0, 0, size_px + 7, size_px + 7], outline=(br, bg, bb, 255), width=3)
        # Status LED in bottom-right corner
        led_col = (0, 255, 156, 255) if is_active else (255, 214, 0, 255)
        drw.ellipse([size_px - 18, size_px - 18, size_px + 2, size_px + 2], fill=led_col, outline=(7, 9, 14, 255), width=2)

        bio = io.BytesIO()
        framed.convert("RGB").save(bio, format="PNG", optimize=True)
        b64 = base64.b64encode(bio.getvalue()).decode("ascii")

        chunks = []
        chunk_size = 4096
        for i in range(0, len(b64), chunk_size):
            part = b64[i : i + chunk_size]
            more = 1 if (i + chunk_size < len(b64)) else 0
            if i == 0:
                chunks.append(
                    f"\033_Ga=T,f=100,t=d,i=22,p=1,c={w_cells},r={h_cells},C=1,q=2,m={more};{part}\033\\"
                )
            else:
                chunks.append(f"\033_Gm={more};{part}\033\\")
        esc = "".join(chunks)
        kitty_avatar_cache[cache_key] = esc
        return esc
    except Exception:
        return ""


def scan_agents_telemetry(force: bool = False) -> list:
    global telemetry_cache, last_telemetry_ts
    now = time.time()
    if not force and telemetry_cache and (now - last_telemetry_ts < 2.5):
        return telemetry_cache

    proc_snapshots = []
    for p in psutil.process_iter(["pid", "name", "cmdline", "memory_info", "cpu_percent"]):
        try:
            info = p.info
            cmd_str = " ".join(info.get("cmdline") or [])
            name_str = info.get("name") or ""
            if not cmd_str and not name_str:
                continue
            # Ignore our own monitor script
            if "ctos-ai-agents" in cmd_str:
                continue
            rss_mb = (info.get("memory_info").rss / (1024 * 1024)) if info.get("memory_info") else 0.0
            cpu_p = float(info.get("cpu_percent") or 0.0)
            proc_snapshots.append((name_str, cmd_str, rss_mb, cpu_p))
        except Exception:
            continue

    results = []
    for ag in AGENTS_CATALOG:
        installed = any(os.path.exists(b) or shutil.which(os.path.basename(b)) for b in ag["binaries"])
        proc_cnt = 0
        mem_mb = 0.0
        cpu_total = 0.0
        for name_s, cmd_s, rss, cpu in proc_snapshots:
            hay = f"{name_s} {cmd_s}"
            if any(pat in hay for pat in ag["proc_patterns"]):
                proc_cnt += 1
                mem_mb += rss
                cpu_total += cpu

        active = proc_cnt > 0
        if active:
            status = "ACTIVE"
            activity = "⚡ WORKING" if cpu_total > 1.5 else "● ONLINE"
        elif installed:
            status = "STANDBY"
            activity = "◉ READY"
        else:
            status = "OFFLINE"
            activity = "○ N/A"

        entry = dict(ag)
        entry.update({
            "installed": installed,
            "active": active,
            "status": status,
            "activity": activity,
            "procs": proc_cnt,
            "mem_mb": int(round(mem_mb)),
            "cpu_pct": round(cpu_total, 1),
        })
        results.append(entry)

    telemetry_cache = results
    last_telemetry_ts = now
    return results


def launch_selected_agent(agents: list):
    if not agents or not (0 <= selected_idx < len(agents)):
        return
    ag = agents[selected_idx]
    cmd = ag.get("launch_cmd") or []
    if not cmd:
        return
    exe = cmd[0]
    if not os.path.exists(exe) and not shutil.which(exe):
        return
    try:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        pass


def render(force_redraw: bool = False):
    global selected_idx

    cols, rows = shutil.get_terminal_size((48, 12))
    cols = max(24, cols)
    rows = max(7, rows)
    inner_w = max(20, cols - 2)

    agents = scan_agents_telemetry()
    selected_idx = max(0, min(selected_idx, len(agents) - 1))
    cur = agents[selected_idx]

    active_total = sum(1 for a in agents if a["active"])
    installed_total = sum(1 for a in agents if a["installed"])

    buf = []

    # 1. Top Header Bar
    hdr_left = f" {C_CYAN}{B}⌁ [ctOS // AI_AGENTS_SQUAD]{R}"
    hdr_right = f"{C_MINT}{B}● {active_total} ACTIVE{R} {C_SLATE}/{installed_total} AVAIL{R}"
    pad_h = max(1, cols - str_width(hdr_left) - str_width(hdr_right) - 1)
    buf.append(f"{hdr_left}{' ' * pad_h}{hdr_right}\033[K")

    # 2. Featured Character Avatar Card (Left: Kitty Graphics Pixel Character Avatar | Right: Agent Details)
    av_h = max(4, min(6, rows - 5))
    av_w = av_h * 2
    card_start_row = len(buf) + 1
    av_start_col = 3

    st_col = C_MINT if cur["active"] else (C_AMBER if cur["installed"] else C_SLATE)
    mem_str = f"{cur['mem_mb']}MB · {cur['procs']} procs" if cur["active"] else ("Installed · CLI/IDE Ready" if cur["installed"] else "Not Installed")

    info_w = max(10, inner_w - av_w - 3)
    card_right_lines = [
        f"{ cur['color'] }{B}{clip_plain(cur['name'], info_w - 10)}{R}{BG_CARD} {st_col}{B}{cur['activity']}{R}",
        f"{C_WHITE}{B}{clip_plain(cur['codename'], info_w)}{R}",
        f"{C_SILVER}{clip_plain(cur['role'], info_w)}{R}",
        f"{C_BLUE}Telemetry:{R}{BG_CARD} {C_WHITE}{clip_plain(mem_str, info_w - 11)}{R}",
        f"{C_SLATE}Avatar:{R}{BG_CARD} {C_PURPLE}DiceBear + pixelart-py{R}",
        f"{C_MINT}[Enter] Launch {cur['name']}{R}",
    ]

    for r_i in range(av_h):
        r_txt = card_right_lines[r_i] if r_i < len(card_right_lines) else ""
        buf.append(f"{BG_CARD} {' ' * av_w}  {pad_ansi(r_txt, info_w)}{R}\033[K")

    buf.append(f" {C_GRID}{'━' * inner_w}{R}\033[K")

    # 3. Roster Strip / List of All Installed & Active AI Agents with Character Faces
    rem_rows = rows - len(buf) - 1
    if rem_rows >= 1:
        # Show compact rows for agents
        start_a = max(0, min(selected_idx - rem_rows // 2, max(0, len(agents) - rem_rows)))
        for a_i in range(start_a, min(len(agents), start_a + rem_rows)):
            ag = agents[a_i]
            is_sel = (a_i == selected_idx)
            bg = BG_SEL if is_sel else ""
            ptr = f"{C_CYAN}{B}❯{R}{bg}" if is_sel else " "
            face = f"{ag['color']}{B}{ag['sprite_face']}{R}{bg}"
            st_dot = f"{C_MINT}{B}● ACTIVE{R}{bg}" if ag["active"] else (f"{C_AMBER}◉ READY {R}{bg}" if ag["installed"] else f"{C_SLATE}○ OFF   {R}{bg}")
            ram_tag = f"{C_SILVER}{ag['mem_mb']:>4}M{R}{bg}" if ag["active"] else f"{C_SLATE}  -- {R}{bg}"

            right_meta_w = 15
            nm_w = max(8, inner_w - right_meta_w - 9)
            nm_s = clip_plain(ag["name"], nm_w)
            pad_m = max(1, inner_w - str_width(nm_s) - right_meta_w - 8)
            row_s = f" {bg}{ptr} {face} {C_WHITE if is_sel else C_SILVER}{B if is_sel else ''}{nm_s}{R}{bg}{' ' * pad_m}{st_dot} {ram_tag}{R}"
            buf.append(f"{row_s}\033[K")

    while len(buf) < rows - 1:
        buf.append("\033[K")

    hint = clip_plain(" [j/k]Agent [Enter/o]Launch [r]Sync", cols - 1)
    buf.append(f"{C_SLATE}{hint}{R}\033[K")

    # Check FaceID state lock & post-modal transition
    st_file = "/tmp/ctos_faceid_state.json"
    st_mode = "UNLOCKED"
    if os.path.exists(st_file) and "--once" not in sys.argv:
        try:
            with open(st_file, "r", encoding="utf-8") as sf:
                sd = json.load(sf)
            if time.time() - sd.get("ts", 0) < 45:
                st_mode = sd.get("state", "UNLOCKED")
                unlock_ts = float(sd.get("unlock_ts", 0.0))
                if st_mode == "UNLOCKED" and unlock_ts > time.time():
                    st_mode = "LOCKED"
        except Exception:
            pass

    if st_mode in ("LOCKED", "FAILED"):
        render._was_locked = True
        render._fade_step = 0
        render._last_sig = None
        s_chars = "░▒▓▒░·:∷"
        s_buf = []
        t_now = int(time.time() * 12)
        for sy in range(rows):
            if sy == rows // 2:
                lbl = (
                    f"{C_CRIMSON}{B} ✖ AI_AGENTS LOCKED {R}"
                    if st_mode == "FAILED"
                    else f"\033[38;2;0;165;200m{B}  SCANNING FACE_ID {R}"
                )
                pad_l = max(0, (cols - 22) // 2)
                s_buf.append((" " * pad_l) + lbl + "\033[K")
                continue
            r_ch = []
            for sx in range(cols):
                idx = (sx + sy * 2 + t_now + random.randint(0, 1)) % len(s_chars)
                col = (
                    f"\033[38;2;{40 + idx*12};10;22m"
                    if st_mode == "FAILED"
                    else f"\033[38;2;12;{26 + idx*9};{40 + idx*13}m"
                )
                r_ch.append(f"{col}{s_chars[idx]}")
            s_buf.append("".join(r_ch) + f"{R}\033[K")
        sys.stdout.write("\033_Ga=d,d=A,q=2\033\\\033[H\033[?25l" + "\n".join(s_buf[:rows]) + "\033[J")
        sys.stdout.flush()
        return

    if getattr(render, "_was_locked", False):
        f_step = getattr(render, "_fade_step", 0) + 1
        render._fade_step = f_step
        render._last_sig = None
        if f_step <= 14:
            rev = int((f_step / 14.0) * rows)
            for ry in range(rev, rows):
                if ry == rev:
                    buf[ry] = f"\033[48;2;0;55;75m{C_MINT}{B}{'━' * cols}{R}\033[K"
                else:
                    buf[ry] = f"\033[38;2;18;38;52m{'░' * cols}{R}\033[K"
            sys.stdout.write("\033_Ga=d,d=A,q=2\033\\\033[H\033[?25l" + "\n".join(buf[:rows]) + "\033[J")
            sys.stdout.flush()
            return
        else:
            render._was_locked = False

    frame_sig = (
        cols,
        rows,
        selected_idx,
        cur["id"],
        cur["active"],
        cur["procs"],
        cur["mem_mb"] // 16,
        active_total,
    )
    if not force_redraw and getattr(render, "_last_sig", None) == frame_sig and "--once" not in sys.argv:
        return
    render._last_sig = frame_sig

    kitty_esc = get_kitty_avatar(cur, cur["active"], av_w, av_h)
    out_str = "\033_Ga=d,d=A,q=2\033\\\033[H\033[?25l" + "\n".join(buf[:rows]) + "\033[J"
    if kitty_esc and "--no-kitty" not in sys.argv:
        out_str += f"\033[{card_start_row};{av_start_col}H{kitty_esc}"
    sys.stdout.write(out_str)
    sys.stdout.flush()


def main():
    global selected_idx, original_termios

    if "--once" in sys.argv:
        render(force_redraw=True)
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
    render(force_redraw=True)

    while running:
        try:
            cur_mtime = os.path.getmtime(os.path.abspath(__file__))
            if init_mtime and cur_mtime != init_mtime:
                if original_termios:
                    termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, original_termios)
                os.execv(sys.executable, [sys.executable] + sys.argv)
        except Exception:
            pass

        if original_termios:
            wait_t = 0.05 if getattr(render, "_was_locked", False) else 0.8
            rlist, _, _ = select.select([sys.stdin], [], [], wait_t)
            if rlist:
                ch = sys.stdin.read(1)
                if ch == "\x1b":
                    seq = ""
                    while select.select([sys.stdin], [], [], 0.005)[0]:
                        seq += sys.stdin.read(1)
                    if seq in ("[A", "OA") or (seq.startswith("[<64;") and seq.endswith("M")):
                        selected_idx = max(0, selected_idx - 1)
                    elif seq in ("[B", "OB") or (seq.startswith("[<65;") and seq.endswith("M")):
                        selected_idx = max(0, min(len(AGENTS_CATALOG) - 1, selected_idx + 1))
                elif ch in ("k", "K"):
                    selected_idx = max(0, selected_idx - 1)
                elif ch in ("j", "J"):
                    selected_idx = max(0, min(len(AGENTS_CATALOG) - 1, selected_idx + 1))
                elif ch in ("\r", "\n", "o", "O"):
                    launch_selected_agent(scan_agents_telemetry())
                elif ch in ("r", "R"):
                    scan_agents_telemetry(force=True)
                    render(force_redraw=True)
                    continue
                render()
            else:
                render()
        else:
            time.sleep(2.0)
            render()


if __name__ == "__main__":
    main()
