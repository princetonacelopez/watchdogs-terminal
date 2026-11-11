#!/usr/bin/env python3
"""
jira-project-board: Watch Dogs ctOS 2.0 / DedSec TrueColor TUI for WebIT Jira Sprint Tickets.
Auto-detects the active WebIT project from .jira-project, git branch, git log, or directory name,
and renders active Jira tickets with ctOS color-coded status/priority badges and browser launch.
"""

import os
import sys
import tty
import time
import json
import re
import select
import shutil
import signal
import termios
import subprocess
import threading
import unicodedata

# Watch Dogs ctOS 2.0 / DedSec TrueColor ANSI Palette (#00F0FF / #FF0055)
C_RESET   = "\033[0m"
C_BOLD    = "\033[1m"
C_DIM     = "\033[2m"

C_BLUE    = "\033[38;2;0;168;255m"    # ctOS Data Link Blue (#00A8FF)
C_CYAN    = "\033[38;2;0;240;255m"    # Signature ctOS Electric Cyan (#00F0FF)
C_PURPLE  = "\033[38;2;214;0;255m"    # DedSec Glitch Purple (#D600FF)
C_GREEN   = "\033[38;2;0;255;156m"    # Access Granted Neon Mint (#00FF9C)
C_RED     = "\033[38;2;255;0;85m"     # DedSec Intrusion Crimson (#FF0055)
C_ORANGE  = "\033[38;2;255;85;0m"     # Breach Alert Orange (#FF5500)
C_YELLOW  = "\033[38;2;255;214;0m"    # ctOS Profiler Warning Amber (#FFD600)
C_MUTED   = "\033[38;2;122;147;172m"  # Tactical Slate (#7A93AC)
C_TEXT    = "\033[38;2;226;241;255m"  # Crisp ctOS Ice White (#E2F1FF)
C_GRAY    = "\033[38;2;75;98;122m"    # Grid Dim (#4B627A)
C_BG_SEL  = "\033[48;2;17;25;38m"     # Selected Row Tactical Navy (#111926)

JIRA_BASE_URL = "https://webitau.atlassian.net/browse"
STATUS_FILTER = "status NOT IN (Deployed, Resolved, Closed)"
CACHE_TTL     = 180

FOLDER_KEY_MAP = [
    ("buxton",        "BUX"),
    ("areal",         "AREAL"),
    ("highland",      "HP"),
    ("hodges",        "HRE"),
    ("dataonce",      "BUXDATA"),
    ("listonce",      "LO"),
    ("nelson",        "NA"),
    ("noel",          "NJ"),
    ("property-pass", "PASS"),
    ("rt-edgar",      "RTE"),
    ("prd",           "PRD"),
]

issues_lock      = threading.Lock()
cached_issues    = []
project_key      = ""
filter_mine      = True
selected_idx     = 0
scroll_offset    = 0
is_refreshing    = False
last_status_msg  = ""
running          = True
original_termios = None


def detect_project_key(proj_dir):
    try:
        os.chdir(proj_dir)
    except Exception:
        pass

    # A. Explicit .jira-project file
    if os.path.isfile(".jira-project"):
        try:
            with open(".jira-project", "r") as f:
                val = f.read().strip()
                if val:
                    return val
        except Exception:
            pass

    # B. Current Git branch (e.g. bugfix/AREAL-146 -> AREAL)
    try:
        branch = subprocess.check_output(
            ["git", "branch", "--show-current"],
            stderr=subprocess.DEVNULL, text=True, timeout=2
        ).strip()
        m = re.search(r"([A-Z]{2,10})(?=-\d+)", branch)
        if m:
            return m.group(1)
    except Exception:
        pass

    # C. Recent Git commits
    try:
        logs = subprocess.check_output(
            ["git", "log", "-n", "10", "--oneline"],
            stderr=subprocess.DEVNULL, text=True, timeout=2
        )
        m = re.search(r"([A-Z]{2,10})(?=-\d+)", logs)
        if m:
            return m.group(1)
    except Exception:
        pass

    # D. Folder name mapping fallback
    base = os.path.basename(os.getcwd()).lower()
    for substr, key in FOLDER_KEY_MAP:
        if substr in base:
            return key

    return ""


def cache_path_for(key, mine):
    scope = "mine" if mine else "all"
    k = key or "GLOBAL"
    return f"/tmp/zdev_jira_board_{k}_{scope}.json"


def parse_jira_tsv(raw_output):
    items = []
    for line in raw_output.splitlines():
        if not line.strip():
            continue
        cols = [c.strip() for c in re.split(r"\t+", line.strip())]
        if len(cols) < 4:
            continue
        issue_type = cols[0]
        key = cols[1]
        summary = cols[2]
        status = cols[3]
        assignee = cols[4] if len(cols) > 4 else ""
        reporter = cols[5] if len(cols) > 5 else ""
        priority = cols[6] if len(cols) > 6 else "Standard"
        labels = cols[-1] if len(cols) > 7 and not re.match(r"^\d{4}-\d{2}-\d{2}", cols[-1]) else ""
        items.append({
            "type": issue_type,
            "key": key,
            "summary": summary,
            "status": status,
            "assignee": assignee,
            "reporter": reporter,
            "priority": priority,
            "labels": labels,
            "url": f"{JIRA_BASE_URL}/{key}",
        })
    return items


def run_jira_query(key, mine_only):
    cmd = ["jira", "issue", "list", "--plain", "--no-headers", "--no-truncate"]
    if key:
        cmd.extend(["-p", key])
    if mine_only:
        jql = f"assignee = currentUser() AND {STATUS_FILTER}"
    else:
        jql = STATUS_FILTER
    cmd.extend(["-q", jql])

    res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    if res.returncode == 0 and res.stdout.strip():
        return parse_jira_tsv(res.stdout)
    return []


def refresh_issues_worker():
    global cached_issues, is_refreshing, last_status_msg, filter_mine
    is_refreshing = True
    try:
        items = run_jira_query(project_key, filter_mine)
        if not items and filter_mine and project_key:
            # Fallback to all active project issues if user has 0 assigned in this project
            items = run_jira_query(project_key, False)
            scope_note = "Project"
        else:
            scope_note = "Assigned" if filter_mine else "Project"

        # Sort: In Progress first, then Blocked/Major, then In QA/UAT, then Open
        def status_rank(st):
            s = st.lower()
            if "progress" in s:
                return 0
            if "block" in s:
                return 1
            if "qa" in s:
                return 2
            if "uat" in s:
                return 3
            return 4

        items.sort(key=lambda x: (status_rank(x["status"]), x["key"]))

        with issues_lock:
            if items or not cached_issues:
                cached_issues = items
                try:
                    with open(cache_path_for(project_key, filter_mine), "w") as f:
                        json.dump({"timestamp": time.time(), "issues": items}, f)
                except Exception:
                    pass
            last_status_msg = f"Synced {time.strftime('%H:%M:%S')} · {len(cached_issues)} {scope_note} tickets"
    except Exception as e:
        last_status_msg = f"Jira sync error: {e}"
    finally:
        is_refreshing = False


def load_cached_issues():
    global cached_issues, last_status_msg
    cpath = cache_path_for(project_key, filter_mine)
    if os.path.exists(cpath):
        try:
            with open(cpath, "r") as f:
                data = json.load(f)
                cached_issues = data.get("issues", [])
                age = int(time.time() - data.get("timestamp", 0))
                last_status_msg = f"Cached ({age}s ago) · {len(cached_issues)} tickets"
        except Exception:
            pass


def str_width(s):
    clean = re.sub(r"\033\[[0-9;?]*[a-zA-Z]", "", s)
    w = 0
    for ch in clean:
        if unicodedata.combining(ch) or ch == "\ufe0f":
            continue
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") or ord(ch) >= 0x1F300 else 1
    return w


def format_status_badge(st):
    s = st.lower()
    if "progress" in s:
        return f"{C_CYAN}{C_BOLD}IN_PROG{C_RESET}"
    if "qa" in s:
        return f"{C_PURPLE}{C_BOLD}IN_QA  {C_RESET}"
    if "uat" in s:
        return f"{C_GREEN}{C_BOLD}IN_UAT {C_RESET}"
    if "block" in s:
        return f"{C_RED}{C_BOLD}BLOCKED{C_RESET}"
    if "review" in s:
        return f"{C_YELLOW}{C_BOLD}REVIEW {C_RESET}"
    return f"{C_BLUE}OPEN   {C_RESET}"


def format_prio_badge(prio):
    p = prio.lower()
    if p in ("critical", "blocker", "highest"):
        return f"{C_RED}{C_BOLD}CRIT{C_RESET}"
    if p in ("major", "high"):
        return f"{C_ORANGE}{C_BOLD}MAJR{C_RESET}"
    if p in ("minor", "low", "lowest"):
        return f"{C_GRAY}MINR{C_RESET}"
    return f"{C_MUTED}STD {C_RESET}"


def format_type_badge(t):
    tl = t.lower()
    if "bug" in tl:
        return f"{C_RED}BUG {C_RESET}"
    if "sub" in tl:
        return f"{C_PURPLE}SUB {C_RESET}"
    if "story" in tl or "feat" in tl:
        return f"{C_GREEN}STRY{C_RESET}"
    return f"{C_CYAN}TASK{C_RESET}"


def render():
    global scroll_offset, selected_idx
    cols, rows = shutil.get_terminal_size((70, 12))
    cols = max(30, cols)
    rows = max(6, rows)

    with issues_lock:
        issues = list(cached_issues)
        stat = last_status_msg
        refreshing = is_refreshing

    if issues:
        selected_idx = max(0, min(selected_idx, len(issues) - 1))
    else:
        selected_idx = 0

    header_rows = 2
    footer_rows = 2
    visible_h = max(1, rows - header_rows - footer_rows)

    if selected_idx < scroll_offset:
        scroll_offset = selected_idx
    elif selected_idx >= scroll_offset + visible_h:
        scroll_offset = selected_idx - visible_h + 1

    buf = ["\033[H\033[?25l"]

    # 1. Top ctOS Header Bar
    spin = " ⟳" if refreshing else ""
    proj_tag = project_key if project_key else "ALL_WEBIT"
    scope_tag = "MINE" if filter_mine else "ALL"
    title_line = (
        f" {C_CYAN}{C_BOLD}⌁ [ctOS // JIRA_SPRINT_MATRIX :: {proj_tag}]{C_RESET}"
        f"{C_RED}{C_BOLD} [{len(issues)}]{C_RESET} "
        f"{C_GRAY}[{scope_tag}]{C_YELLOW}{spin}{C_RESET}"
    )
    buf.append(f"{title_line}\033[K")

    # 2. Column Headers
    c_key_w = 10
    c_stat_w = 7
    c_prio_w = 4
    c_type_w = 4
    c_sum_w = max(12, cols - (c_key_w + c_stat_w + c_prio_w + c_type_w + 10))

    hdr = f"  {C_MUTED}{'KEY':<{c_key_w}} {'STATUS':<{c_stat_w}} {'PRIO':<{c_prio_w}} {'TYPE':<{c_type_w}} {'SUMMARY'}{C_RESET}"
    buf.append(f"{hdr}\033[K")

    # 3. Rows
    if not issues:
        msg = "  Scanning WebIT Jira sprint telemetry..." if refreshing else f"  No active Jira issues found for {proj_tag}"
        buf.append(f"{C_YELLOW}{msg}{C_RESET}\033[K")
        for _ in range(visible_h - 1):
            buf.append("\033[K")
    else:
        vis_slice = issues[scroll_offset : scroll_offset + visible_h]
        for rel_i, item in enumerate(vis_slice):
            act_i = scroll_offset + rel_i
            is_sel = (act_i == selected_idx)
            cursor = "❯ " if is_sel else "  "

            key_str = f"{item['key']:<{c_key_w}}"[:c_key_w]
            st_badge = format_status_badge(item["status"])
            pr_badge = format_prio_badge(item["priority"])
            ty_badge = format_type_badge(item["type"])

            summary = item["summary"]
            if len(summary) > c_sum_w:
                sum_str = summary[:c_sum_w - 1] + "…"
            else:
                sum_str = summary + (" " * (c_sum_w - len(summary)))

            if is_sel:
                row_s = (
                    f"{C_BG_SEL}{C_CYAN}{C_BOLD}{cursor}{C_CYAN}{C_BOLD}{key_str}{C_RESET}{C_BG_SEL} "
                    f"{st_badge}{C_BG_SEL} {pr_badge}{C_BG_SEL} {ty_badge}{C_BG_SEL} "
                    f"{C_TEXT}{C_BOLD}{sum_str}{C_RESET}"
                )
            else:
                row_s = (
                    f"{cursor}{C_CYAN}{key_str}{C_RESET} "
                    f"{st_badge} {pr_badge} {ty_badge} "
                    f"{C_TEXT}{sum_str}{C_RESET}"
                )
            buf.append(f"{row_s}\033[K")

        for _ in range(visible_h - len(vis_slice)):
            buf.append("\033[K")

    # 4. Detail Bar
    if issues and 0 <= selected_idx < len(issues):
        sel = issues[selected_idx]
        lbl = f" · 🏷 {sel['labels']}" if sel.get("labels") else ""
        detail = f" {sel['key']} [{sel['status']} / {sel['priority']}] {sel['summary']} · Assignee: {sel['assignee'] or 'Unassigned'}{lbl}"
    else:
        detail = f" {stat}" if stat else " WebIT Jira Sprint Feed"

    if str_width(detail) > cols - 1:
        detail = detail[:cols - 4] + "..."
    buf.append(f"{C_MUTED}{detail}{C_RESET}\033[K")

    # 5. Footer Hints
    hint = " [↑/↓/j/k] Select  [Enter/o] Open Jira  [a] Mine/All  [r] Refresh"
    if str_width(hint) > cols - 1:
        hint = " [j/k] Nav  [Enter] Open  [a] Scope  [r] Sync"
    buf.append(f"{C_GRAY}{hint}{C_RESET}\033[K")

    st_file = "/tmp/ctos_faceid_state.json"
    st_mode = "UNLOCKED"
    if os.path.exists(st_file) and "--once" not in sys.argv:
        try:
            with open(st_file, "r") as sf:
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
        s_chars = "░▒▓▒░·:∷"
        s_buf = ["\033[H\033[?25l"]
        t_now = int(time.time() * 12)
        for sy in range(rows):
            if sy == rows // 2:
                lbl = f"{C_RED}{C_BOLD} ✖ [ctOS // JIRA_MATRIX :: LOCKED] {C_RESET}" if st_mode == "FAILED" else f"\033[38;2;0;165;200m{C_BOLD}  [ctOS // JIRA_MATRIX :: SCANNING FACE_ID] {C_RESET}"
                pad_l = max(0, (cols - 44) // 2)
                s_buf.append((" " * pad_l) + lbl + "\033[K")
                continue
            r_ch = []
            for sx in range(0, cols, 2):
                idx = (sx + sy * 2 + t_now) % len(s_chars)
                col = f"\033[38;2;{40 + idx*12};10;22m" if st_mode == "FAILED" else f"\033[38;2;12;{26 + idx*9};{40 + idx*13}m"
                r_ch.append(f"{col}{s_chars[idx] * min(2, cols - sx)}")
            s_buf.append("".join(r_ch) + f"{C_RESET}\033[K")
        sys.stdout.write("\n".join(s_buf[:rows + 1]) + "\033[J")
        sys.stdout.flush()
        return

    if getattr(render, "_was_locked", False):
        f_step = getattr(render, "_fade_step", 0) + 1
        render._fade_step = f_step
        if f_step <= 14:
            rev = int((f_step / 14.0) * rows)
            for ry in range(rev + 1, len(buf)):
                if ry == rev + 1:
                    buf[ry] = f"\033[48;2;0;55;75m{C_GREEN}{C_BOLD}{'━' * cols}{C_RESET}\033[K"
                else:
                    buf[ry] = f"\033[38;2;18;38;52m{'░' * cols}{C_RESET}\033[K"
        else:
            render._was_locked = False

    sys.stdout.write("\n".join(buf[:rows]) + "\033[J")
    sys.stdout.flush()


def open_selected():
    with issues_lock:
        if cached_issues and 0 <= selected_idx < len(cached_issues):
            url = cached_issues[selected_idx].get("url")
            if url:
                try:
                    subprocess.Popen(
                        ["xdg-open", url],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                except Exception:
                    pass


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


def main():
    global project_key, selected_idx, scroll_offset, filter_mine, running, original_termios
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    proj_dir = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else os.getcwd()
    project_key = detect_project_key(proj_dir)
    load_cached_issues()

    if "--once" in sys.argv:
        if not cached_issues:
            refresh_issues_worker()
        render()
        cleanup()

    def auto_refresh_loop():
        while running:
            refresh_issues_worker()
            for _ in range(CACHE_TTL):
                if not running:
                    break
                time.sleep(1)

    t_worker = threading.Thread(target=auto_refresh_loop, daemon=True)
    t_worker.start()

    if not sys.stdin.isatty():
        while running:
            render()
            time.sleep(2)
        return

    original_termios = termios.tcgetattr(sys.stdin.fileno())
    tty.setcbreak(sys.stdin.fileno())
    sys.stdout.write("\033[?1049h\033[?7l\033[3J\033[?1000h\033[?1006h")
    sys.stdout.flush()

    init_mtime = os.path.getmtime(os.path.abspath(__file__)) if os.path.exists(__file__) else 0

    try:
        render()
        while running:
            try:
                cur_mtime = os.path.getmtime(os.path.abspath(__file__))
                if init_mtime and cur_mtime != init_mtime:
                    termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, original_termios)
                    os.execv(sys.executable, [sys.executable] + sys.argv)
            except Exception:
                pass

            wait_t = 0.05 if getattr(render, "_was_locked", False) else 0.5
            rlist, _, _ = select.select([sys.stdin], [], [], wait_t)
            if rlist:
                ch = sys.stdin.read(1)
                if ch == "\x1b":
                    seq = ""
                    while select.select([sys.stdin], [], [], 0.005)[0]:
                        seq += sys.stdin.read(1)
                    if seq in ("[A", "OA") or (seq.startswith("[<64;") and seq.endswith("M")):
                        selected_idx = max(0, selected_idx - 1)
                        scroll_offset = max(0, scroll_offset)
                        render()
                    elif seq in ("[B", "OB") or (seq.startswith("[<65;") and seq.endswith("M")):
                        selected_idx += 1
                        render()
                elif ch in ("k", "K"):
                    selected_idx = max(0, selected_idx - 1)
                    scroll_offset = max(0, scroll_offset)
                    render()
                elif ch in ("j", "J"):
                    selected_idx += 1
                    render()
                elif ch in ("\r", "\n", "o", "O"):
                    open_selected()
                elif ch in ("a", "A"):
                    filter_mine = not filter_mine
                    selected_idx = 0
                    scroll_offset = 0
                    load_cached_issues()
                    threading.Thread(target=refresh_issues_worker, daemon=True).start()
                    render()
                elif ch in ("r", "R"):
                    threading.Thread(target=refresh_issues_worker, daemon=True).start()
                    render()
                elif ch in ("q", "Q"):
                    break
            else:
                render()
    finally:
        cleanup()


if __name__ == "__main__":
    main()
