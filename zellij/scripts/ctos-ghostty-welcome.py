#!/usr/bin/env python3
"""
ctos-ghostty-welcome: Watch Dogs ctOS 2.0 // DedSec Ghostty Terminal Startup Launcher
Interactive startup screen displayed when opening a fresh Ghostty window (or running `welcome`):
  • Left Column  : RECENTLY OPENED FOLDERS (from zdev history, zoxide, Antigravity & Cursor workspaces)
  • Right Column : PROJECT FOLDERS (from ~/Projects and ~/Documents/antigravity with Jira keys & Git branches)
  • Live search (/), Mouse click/wheel support, and one-key launch into `zdev`, plain `cd`, Antigravity, or Cursor.
"""

import json
import os
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
import urllib.parse

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

BG_DARK   = "\033[48;2;10;15;24m"
BG_SEL    = "\033[48;2;0;52;76m"
BG_HDR    = "\033[48;2;0;240;255m\033[38;2;7;9;14m"
BG_TAB_IN = "\033[48;2;17;25;38m"

RECENT_FILE = os.path.expanduser("~/.config/zellij/recent_folders.json")
PROJECTS_DIRS = [
    os.path.expanduser("~/Projects"),
    os.path.expanduser("~/Documents/antigravity"),
]

FOLDER_KEY_MAP = [
    ("buxton",        "BUX"),
    ("areal",         "AREAL"),
    ("highland",      "HP"),
    ("hodges",        "HRE"),
    ("dataonce",      "DATA"),
    ("listonce",      "LO"),
    ("nelson",        "NA"),
    ("noel",          "NJ"),
    ("property-pass", "PASS"),
    ("rt-edgar",      "RTE"),
    ("prd",           "PRD"),
    ("education",     "EDU"),
    ("serene-volta",  "AGY"),
]

running = True
original_termios = None
tty_fd = None
tty_out = None


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


def center_ansi(s: str, width: int) -> str:
    w = str_width(s)
    if w >= width:
        return s
    left = (width - w) // 2
    right = width - w - left
    return (" " * left) + s + (" " * right)


def short_path(p: str) -> str:
    home = os.path.expanduser("~")
    if p == home:
        return "~"
    if p.startswith(home + "/"):
        return "~/" + p[len(home) + 1 :]
    return p


def infer_jira_key(folder_path: str) -> str:
    jp = os.path.join(folder_path, ".jira-project")
    if os.path.isfile(jp):
        try:
            with open(jp, "r", encoding="utf-8") as f:
                val = f.read().strip()
                if val:
                    return val[:8]
        except Exception:
            pass
    base = os.path.basename(folder_path).lower()
    for sub, k in FOLDER_KEY_MAP:
        if sub in base:
            return k
    if "/antigravity/" in folder_path:
        return "AGY"
    return "DEV"


def get_git_branch(folder_path: str) -> str:
    head_file = os.path.join(folder_path, ".git", "HEAD")
    if os.path.isfile(head_file):
        try:
            with open(head_file, "r", encoding="utf-8") as f:
                raw = f.read().strip()
            if raw.startswith("ref: refs/heads/"):
                return raw[len("ref: refs/heads/") :]
            return raw[:7]
        except Exception:
            pass
    return ""


def get_live_zellij_sessions() -> set:
    live = set()
    try:
        res = subprocess.run(
            ["zellij", "list-sessions", "--no-formatting"],
            capture_output=True,
            text=True,
            timeout=1.5,
        )
        if res.returncode == 0:
            for ln in res.stdout.splitlines():
                if ln.strip() and "EXITED" not in ln:
                    sname = ln.strip().split()[0]
                    live.add(sname)
    except Exception:
        pass
    return live


def session_name_for_dir(path: str) -> str:
    base = os.path.basename(path.rstrip("/")) or "root"
    return re.sub(r"[^a-zA-Z0-9_-]", "-", base)


def record_recent_folder(path: str):
    real = os.path.realpath(os.path.expanduser(path))
    if not os.path.isdir(real):
        return
    os.makedirs(os.path.dirname(RECENT_FILE), exist_ok=True)
    items = []
    if os.path.exists(RECENT_FILE):
        try:
            with open(RECENT_FILE, "r", encoding="utf-8") as f:
                items = json.load(f)
        except Exception:
            items = []
    now = int(time.time())
    filtered = [it for it in items if isinstance(it, dict) and os.path.realpath(it.get("path", "")) != real]
    filtered.insert(0, {"path": real, "ts": now})
    try:
        with open(RECENT_FILE, "w", encoding="utf-8") as f:
            json.dump(filtered[:30], f, indent=2)
    except Exception:
        pass
    try:
        subprocess.run(["zoxide", "add", real], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1.0)
    except Exception:
        pass


def gather_recent_folders(live_sessions: set) -> list:
    seen = set()
    out = []
    home = os.path.realpath(os.path.expanduser("~"))

    def add_candidate(p: str, source_tag: str = ""):
        if not p:
            return
        real = os.path.realpath(os.path.expanduser(p))
        if real in seen or real == home or not os.path.isdir(real):
            return
        # Skip noisy root parent directories if they are just containers
        if real in (
            os.path.realpath(os.path.expanduser("~/Projects")),
            os.path.realpath(os.path.expanduser("~/projects")),
        ):
            return
        seen.add(real)
        sname = session_name_for_dir(real)
        out.append({
            "name": os.path.basename(real),
            "path": real,
            "short": short_path(real),
            "branch": get_git_branch(real),
            "key": infer_jira_key(real),
            "live": sname in live_sessions,
            "source": source_tag,
        })

    # 1. Explicit recent_folders.json history
    if os.path.exists(RECENT_FILE):
        try:
            with open(RECENT_FILE, "r", encoding="utf-8") as f:
                for item in json.load(f):
                    if isinstance(item, dict):
                        add_candidate(item.get("path", ""), "zdev")
        except Exception:
            pass

    # 2. zoxide most recent / frequent directories
    try:
        res = subprocess.run(["zoxide", "query", "-l"], capture_output=True, text=True, timeout=1.5)
        if res.returncode == 0:
            for ln in res.stdout.splitlines()[:20]:
                add_candidate(ln.strip(), "shell")
    except Exception:
        pass

    # 3. Antigravity & Cursor recent IDE workspaces
    for ide_name, storage_path in [
        ("agy", os.path.expanduser("~/.config/Antigravity/User/globalStorage/storage.json")),
        ("cursor", os.path.expanduser("~/.config/Cursor/User/globalStorage/storage.json")),
    ]:
        if os.path.exists(storage_path):
            try:
                with open(storage_path, "r", encoding="utf-8") as f:
                    raw = f.read()
                for m in re.finditer(r"file://(/[^\"'\s]+)", raw):
                    decoded = urllib.parse.unquote(m.group(1))
                    if os.path.isdir(decoded):
                        add_candidate(decoded, ide_name)
            except Exception:
                pass

    # Sort live sessions to top of recent list while preserving recency order
    out.sort(key=lambda x: (0 if x["live"] else 1))
    return out[:18]


def gather_project_folders(live_sessions: set) -> list:
    seen = set()
    out = []
    for root in PROJECTS_DIRS:
        if not os.path.isdir(root):
            continue
        try:
            entries = sorted(os.listdir(root))
        except Exception:
            continue
        for entry in entries:
            if entry.startswith("."):
                continue
            full = os.path.abspath(os.path.join(root, entry))
            if not os.path.isdir(full) or full in seen:
                continue
            seen.add(full)
            sname = session_name_for_dir(full)
            try:
                mtime = os.path.getmtime(full)
            except Exception:
                mtime = 0
            out.append({
                "name": entry,
                "path": full,
                "short": short_path(full),
                "branch": get_git_branch(full),
                "key": infer_jira_key(full),
                "live": sname in live_sessions,
                "mtime": mtime,
            })

    # Sort: live sessions first, then main ~/Projects before workspaces, then alphabetical
    out.sort(key=lambda x: (0 if x["live"] else 1, 0 if "/Projects/" in x["path"] else 1, x["name"].lower()))
    return out


def restore_tty():
    global original_termios, tty_fd, tty_out
    if original_termios and tty_fd is not None:
        try:
            termios.tcsetattr(tty_fd, termios.TCSADRAIN, original_termios)
        except Exception:
            pass
    if tty_out:
        try:
            tty_out.write("\033[?1000l\033[?1006l\033[?7h\033[?25h\033[0m\033[?1049l")
            tty_out.flush()
        except Exception:
            pass


def write_action_and_exit(action: str, target_path: str, out_file: str):
    if target_path and action in ("zdev", "cd", "antigravity", "cursor"):
        record_recent_folder(target_path)
    if out_file:
        try:
            with open(out_file, "w", encoding="utf-8") as f:
                f.write(f"{action}|{target_path}\n")
        except Exception:
            pass
    restore_tty()
    sys.exit(0)


def render_screen(
    out_stream,
    recents: list,
    projects: list,
    active_col: int,
    sel_recent: int,
    sel_project: int,
    search_query: str,
    search_mode: bool,
    live_sessions: set,
):
    cols, rows = shutil.get_terminal_size((110, 32))
    cols = max(68, cols)
    rows = max(18, rows)

    buf = []

    # 1. Watch Dogs ctOS 2.0 Top Telemetry Banner
    now_str = time.strftime("%H:%M:%S")
    live_cnt = len(live_sessions)
    hdr_left = f"{BG_HDR}{B} ⌁ ctOS 2.0 // GHOSTTY_TERMINAL_LAUNCHER {R}"
    hdr_right = f"{C_MINT}{B}● {live_cnt} LIVE SESSIONS{R}  {C_CYAN}{B}⌚ {now_str}{R} "
    pad_hdr = max(1, cols - str_width(hdr_left) - str_width(hdr_right))
    buf.append(f"{hdr_left}{' ' * pad_hdr}{hdr_right}\033[K")

    # 2. ASCII Watch Dogs Sub-Header & Search Filter Bar
    sub_banner = (
        f" {C_CYAN}{B}⌜ DEDSEC WORKSPACE MATRIX ⌝{R}  "
        f"{C_SLATE}Select a Recent Folder or Project Directory to launch {C_CYAN}{B}zdev{R}{C_SLATE} or shell{R}"
    )
    buf.append(f"{clip_plain(sub_banner, cols)}\033[K")

    if search_mode or search_query:
        cursor_ch = f"{C_CYAN}█{R}" if search_mode else ""
        s_bar = f" {C_AMBER}{B}⌕ FILTER QUERY :{R} {C_WHITE}{B}{search_query}{cursor_ch}{R}  {C_SLATE}([Esc] clear filter){R}"
    else:
        s_bar = f" {C_GRID}{'━' * (cols - 2)}{R}"
    buf.append(f"{s_bar}\033[K")

    # 3. Two-Column Matrix (Left: RECENT FOLDERS | Right: PROJECT FOLDERS)
    col_gap = 3
    col_w = max(30, (cols - col_gap - 4) // 2)
    right_w = max(30, cols - col_w - col_gap - 3)

    l_active = (active_col == 0)
    r_active = (active_col == 1)

    l_hdr_bg = BG_HDR if l_active else BG_TAB_IN
    r_hdr_bg = BG_HDR if r_active else BG_TAB_IN
    l_hdr_fg = "" if l_active else C_CYAN
    r_hdr_fg = "" if r_active else C_CYAN

    l_title = pad_ansi(f"{l_hdr_bg}{l_hdr_fg}{B} ⌁ [1] RECENT FOLDERS ({len(recents)}) {R}", col_w)
    r_title = pad_ansi(f"{r_hdr_bg}{r_hdr_fg}{B} ⌁ [2] PROJECT FOLDERS ({len(projects)}) {R}", right_w)
    buf.append(f" {l_title} {C_GRID}┃{R} {r_title}\033[K")
    buf.append(f" {C_CYAN if l_active else C_GRID}{'━' * col_w}{R} {C_GRID}╋{R} {C_CYAN if r_active else C_GRID}{'━' * right_w}{R}\033[K")

    # Available list rows (each item is 2 lines: Title+Badges on line 1, Path+Branch on line 2)
    avail_rows = max(6, rows - len(buf) - 5)
    slots = max(3, avail_rows // 2)

    # Compute scroll offsets (strictly clamped >= 0)
    r_off = max(0, min(sel_recent - slots // 2, max(0, len(recents) - slots)))
    p_off = max(0, min(sel_project - slots // 2, max(0, len(projects) - slots)))

    def format_slot(items: list, idx: int, is_col_active: bool, sel_idx: int, width: int) -> tuple:
        if idx >= len(items):
            return (" " * width, " " * width)
        it = items[idx]
        is_sel = is_col_active and (idx == sel_idx)
        bg = BG_SEL if is_sel else ""
        pointer = f"{C_CYAN}{B}❯ {R}{bg}" if is_sel else "  "
        name_col = f"{C_WHITE}{B}" if is_sel else (f"{C_CYAN}{B}" if it.get("live") else f"{C_SILVER}")

        live_badge = f" {C_MINT}{B}● LIVE{R}{bg}" if it.get("live") else ""
        key_badge = f"{C_PURPLE}[{it.get('key', 'DEV')}]{R}{bg}"
        badge_vis = str_width(live_badge) + str_width(key_badge) + 1

        name_str = clip_plain(it["name"], max(8, width - badge_vis - 4))
        pad_1 = max(1, width - 2 - str_width(name_str) - badge_vis)
        line1 = f"{bg}{pointer}{name_col}{name_str}{R}{bg}{' ' * pad_1}{key_badge}{live_badge}{R}"
        line1 = pad_ansi(line1, width)

        branch = it.get("branch")
        br_str = f"{C_MINT}⎇ {clip_plain(branch, 16)}{R}{bg} · " if branch else ""
        br_w = (str_width(f"⎇ {clip_plain(branch, 16)} · ") if branch else 0)
        path_str = clip_plain(it["short"], max(8, width - 4 - br_w))
        line2 = f"{bg}    {br_str}{C_SLATE}{path_str}{R}"
        line2 = pad_ansi(line2, width)
        return (line1, line2)

    for s_i in range(slots):
        l1, l2 = format_slot(recents, r_off + s_i, l_active, sel_recent, col_w)
        r1, r2 = format_slot(projects, p_off + s_i, r_active, sel_project, right_w)
        buf.append(f" {l1} {C_GRID}│{R} {r1}\033[K")
        buf.append(f" {l2} {C_GRID}│{R} {r2}\033[K")

    while len(buf) < rows - 4:
        buf.append(f" {' ' * col_w} {C_GRID}│{R} {' ' * right_w}\033[K")

    # 4. Selected Folder Telemetry Preview Bar
    cur_list = recents if l_active else projects
    cur_idx = sel_recent if l_active else sel_project
    cur_item = cur_list[cur_idx] if (cur_list and 0 <= cur_idx < len(cur_list)) else None

    buf.append(f" {C_GRID}{'━' * (cols - 2)}{R}\033[K")
    if cur_item:
        st_lbl = f"{C_MINT}{B}ATTACH LIVE ZDEV SESSION{R}" if cur_item.get("live") else f"{C_CYAN}{B}LAUNCH NEW ZDEV HUD{R}"
        sel_bar = (
            f" {C_CYAN}{B}TARGET >>{R} {C_WHITE}{B}{cur_item['name']}{R} "
            f"{C_SLATE}({cur_item['path']}){R}  {C_CRIMSON}│{R}  {st_lbl}"
        )
    else:
        sel_bar = f" {C_SLATE}No matching folder selected{R}"
    buf.append(f"{ sel_bar }\033[K")

    # 5. Bottom Controls Legend
    controls = (
        f" {BG_TAB_IN}{C_CYAN}{B} [Enter] {R} {C_WHITE}Open zdev HUD{R}  "
        f"{BG_TAB_IN}{C_MINT}{B} [c] {R} {C_WHITE}cd in Shell{R}  "
        f"{BG_TAB_IN}{C_PURPLE}{B} [Tab/h/l] {R} {C_WHITE}Switch Column{R}  "
        f"{BG_TAB_IN}{C_AMBER}{B} [/] {R} {C_WHITE}Search{R}  "
        f"{BG_TAB_IN}{C_BLUE}{B} [a/u] {R} {C_WHITE}Antigravity/Cursor{R}  "
        f"{BG_TAB_IN}{C_CRIMSON}{B} [q/Esc] {R} {C_SLATE}Shell{R}"
    )
    buf.append(f"{controls}\033[K")

    out_stream.write("\033[H\033[?25l" + "\n".join(buf[:rows]) + "\033[J")
    out_stream.flush()


def main():
    global original_termios, tty_fd, tty_out

    out_file = ""
    if "--out-file" in sys.argv:
        idx = sys.argv.index("--out-file")
        if idx + 1 < len(sys.argv):
            out_file = sys.argv[idx + 1]

    if "--record" in sys.argv:
        idx = sys.argv.index("--record")
        if idx + 1 < len(sys.argv):
            record_recent_folder(sys.argv[idx + 1])
        sys.exit(0)

    live_sessions = get_live_zellij_sessions()
    all_recents = gather_recent_folders(live_sessions)
    all_projects = gather_project_folders(live_sessions)

    if "--once" in sys.argv:
        render_screen(sys.stdout, all_recents, all_projects, 0, 0, 0, "", False, live_sessions)
        sys.stdout.write("\033[?25h\033[0m\n")
        sys.exit(0)

    try:
        tty_file = open("/dev/tty", "r+b", buffering=0)
        tty_fd = tty_file.fileno()
        tty_out = open("/dev/tty", "w", encoding="utf-8")
    except Exception:
        sys.exit(0)

    signal.signal(signal.SIGINT, lambda *_: write_action_and_exit("none", "", out_file))
    signal.signal(signal.SIGTERM, lambda *_: write_action_and_exit("none", "", out_file))

    try:
        original_termios = termios.tcgetattr(tty_fd)
        tty.setcbreak(tty_fd)
        tty_out.write("\033[?1049h\033[?7l\033[3J\033[?1000h\033[?1006h")
        tty_out.flush()
    except Exception:
        sys.exit(0)

    active_col = 0 if all_recents else 1
    sel_recent = 0
    sel_project = 0
    search_query = ""
    search_mode = False

    while running:
        if search_query:
            q = search_query.lower()
            recents = [r for r in all_recents if q in r["name"].lower() or q in r["short"].lower() or q in r["key"].lower()]
            projects = [p for p in all_projects if q in p["name"].lower() or q in p["short"].lower() or q in p["key"].lower()]
        else:
            recents = all_recents
            projects = all_projects

        sel_recent = max(0, min(sel_recent, max(0, len(recents) - 1)))
        sel_project = max(0, min(sel_project, max(0, len(projects) - 1)))

        render_screen(
            tty_out,
            recents,
            projects,
            active_col,
            sel_recent,
            sel_project,
            search_query,
            search_mode,
            live_sessions,
        )

        rlist, _, _ = select.select([tty_fd], [], [], 0.5)
        if not rlist:
            continue

        ch_b = os.read(tty_fd, 1)
        if not ch_b:
            break
        ch = ch_b.decode("utf-8", errors="ignore")

        if ch == "\x1b":
            seq = ""
            while select.select([tty_fd], [], [], 0.008)[0]:
                seq += os.read(tty_fd, 1).decode("utf-8", errors="ignore")
            if seq == "":
                if search_mode or search_query:
                    search_mode = False
                    search_query = ""
                else:
                    write_action_and_exit("none", "", out_file)
            elif seq in ("[A", "OA") or (seq.startswith("[<64;") and seq.endswith("M")):
                if active_col == 0:
                    sel_recent = max(0, sel_recent - 1)
                else:
                    sel_project = max(0, sel_project - 1)
            elif seq in ("[B", "OB") or (seq.startswith("[<65;") and seq.endswith("M")):
                if active_col == 0:
                    sel_recent = max(0, min(max(0, len(recents) - 1), sel_recent + 1))
                else:
                    sel_project = max(0, min(max(0, len(projects) - 1), sel_project + 1))
            elif seq in ("[C", "OC"):
                active_col = 1
            elif seq in ("[D", "OD"):
                active_col = 0
            elif seq.startswith("[<0;") and seq.endswith("M"):
                # Mouse click switches column based on X coordinate
                try:
                    parts = seq[2:-1].split(";")
                    mx = int(parts[1])
                    cols_now, _ = shutil.get_terminal_size((110, 32))
                    active_col = 0 if mx < (cols_now // 2) else 1
                except Exception:
                    pass
            continue

        if search_mode:
            if ch in ("\r", "\n"):
                search_mode = False
            elif ch in ("\x7f", "\x08"):
                search_query = search_query[:-1]
                if not search_query:
                    search_mode = False
            elif ch == "\t":
                active_col = 1 - active_col
            elif ch.isprintable():
                search_query += ch
            continue

        if ch in ("q", "Q"):
            write_action_and_exit("none", "", out_file)
        elif ch == "/":
            search_mode = True
        elif ch == "\t":
            active_col = 1 - active_col
        elif ch in ("h", "H", "1"):
            active_col = 0
        elif ch in ("l", "L", "2"):
            active_col = 1
        elif ch in ("k", "K"):
            if active_col == 0:
                sel_recent = max(0, sel_recent - 1)
            else:
                sel_project = max(0, sel_project - 1)
        elif ch in ("j", "J"):
            if active_col == 0:
                sel_recent = max(0, min(max(0, len(recents) - 1), sel_recent + 1))
            else:
                sel_project = max(0, min(max(0, len(projects) - 1), sel_project + 1))
        elif ch in ("\r", "\n"):
            cur_list = recents if active_col == 0 else projects
            cur_idx = sel_recent if active_col == 0 else sel_project
            if cur_list and 0 <= cur_idx < len(cur_list):
                write_action_and_exit("zdev", cur_list[cur_idx]["path"], out_file)
        elif ch in ("c", "C"):
            cur_list = recents if active_col == 0 else projects
            cur_idx = sel_recent if active_col == 0 else sel_project
            if cur_list and 0 <= cur_idx < len(cur_list):
                write_action_and_exit("cd", cur_list[cur_idx]["path"], out_file)
        elif ch in ("a", "A"):
            cur_list = recents if active_col == 0 else projects
            cur_idx = sel_recent if active_col == 0 else sel_project
            if cur_list and 0 <= cur_idx < len(cur_list):
                write_action_and_exit("antigravity", cur_list[cur_idx]["path"], out_file)
        elif ch in ("u", "U"):
            cur_list = recents if active_col == 0 else projects
            cur_idx = sel_recent if active_col == 0 else sel_project
            if cur_list and 0 <= cur_idx < len(cur_list):
                write_action_and_exit("cursor", cur_list[cur_idx]["path"], out_file)


if __name__ == "__main__":
    main()
