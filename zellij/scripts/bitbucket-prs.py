#!/usr/bin/env python3
"""
bitbucket-prs: Tokyo Night TUI dashboard widget for Bitbucket active PRs.
Displays user's active pull requests (draft & open) across all projects,
along with the number and names of approvers who approved.
"""

import os
import sys
import tty
import time
import json
import glob
import signal
import termios
import select
import shutil
import urllib.request
import urllib.parse
import subprocess
import threading
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor

# Watch Dogs ctOS 2.0 / DedSec TrueColor ANSI Palette (#00F0FF / #FF0055)
C_RESET   = "\033[0m"
C_BOLD    = "\033[1m"
C_DIM     = "\033[2m"
C_ITALIC  = "\033[3m"
C_REVERSE = "\033[7m"

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

CACHE_FILE = "/tmp/zdev_bitbucket_prs.json"
CACHE_TTL  = 180  # seconds between auto-refreshes (3 minutes to preserve API rate limits)

DEFAULT_WORKSPACE = "webtechit"
DEFAULT_UUID      = "{09f87d99-3b7c-4072-8489-84ffaf896456}"
DEFAULT_AUTHOR    = "Princeton Lopez"

# Global state
prs_lock        = threading.Lock()
cached_prs      = []
selected_idx    = 0
scroll_offset   = 0
is_refreshing   = False
last_status_msg = ""
running         = True
original_termios = None

def get_bitbucket_token():
    """Retrieve Bitbucket Bearer token from env, secrets.env, or ~/.git-credentials."""
    # 1. Environment variable
    token = os.environ.get("BITBUCKET_TOKEN") or os.environ.get("BITBUCKET_BEARER_TOKEN")
    if token:
        return token.strip()

    # 2. Check ~/.config/dev/secrets.env
    secrets_path = os.path.expanduser("~/.config/dev/secrets.env")
    if os.path.exists(secrets_path):
        try:
            with open(secrets_path, "r") as f:
                for line in f:
                    if line.strip().startswith("export BITBUCKET_TOKEN="):
                        val = line.strip().split("=", 1)[1].strip("\"' \t\r\n")
                        if val:
                            return val
        except Exception:
            pass

    # 3. Check ~/.git-credentials
    creds_path = os.path.expanduser("~/.git-credentials")
    if os.path.exists(creds_path):
        try:
            with open(creds_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if "bitbucket.org" in line:
                        parsed = urllib.parse.urlparse(line)
                        pwd = urllib.parse.unquote(parsed.password or "")
                        if pwd:
                            return pwd
        except Exception:
            pass

    return None

def detect_repos():
    """Scan local ~/Projects and current directory for Bitbucket repos."""
    repos = set()
    local_paths = {}
    current_repo = None

    # Check current directory
    try:
        git_dir = subprocess.check_output(
            ["git", "rev-parse", "--git-dir"],
            stderr=subprocess.DEVNULL
        ).decode().strip()
        cfg_path = os.path.join(git_dir, "config")
        if os.path.exists(cfg_path):
            with open(cfg_path, "r") as f:
                for line in f:
                    if "bitbucket.org" in line and (f"{DEFAULT_WORKSPACE}/" in line or f"{DEFAULT_WORKSPACE}:" in line):
                        slug = line.split("/")[-1].replace(".git", "").strip()
                        current_repo = slug
                        repos.add(slug)
                        local_paths[slug] = os.path.abspath(os.path.join(git_dir, ".."))
    except Exception:
        pass

    # Check ~/Projects/*/.git
    for git_cfg in glob.glob(os.path.expanduser("~/Projects/*/.git/config")):
        try:
            p_dir = os.path.dirname(os.path.dirname(git_cfg))
            with open(git_cfg, "r") as f:
                for line in f:
                    if "bitbucket.org" in line and (f"{DEFAULT_WORKSPACE}/" in line or f"{DEFAULT_WORKSPACE}:" in line):
                        slug = line.split("/")[-1].replace(".git", "").strip()
                        repos.add(slug)
                        local_paths[slug] = p_dir
        except Exception:
            pass

    # Standard known active WebIT repos fallback
    fallback_repos = [
        "areal", "buxton-real-estate", "dataonce", "highland-property-website",
        "hodges-real-estate", "listonce", "nelson-alexander", "noel-jones",
        "prd", "property-pass", "rt-edgar-website"
    ]
    for r in fallback_repos:
        repos.add(r)
        if r not in local_paths:
            candidate = os.path.expanduser(f"~/Projects/{r}")
            if os.path.isdir(candidate):
                local_paths[r] = candidate

    return sorted(list(repos)), current_repo, local_paths

def fetch_repo_prs(token, repo, local_path=None):
    """Fetch open pull requests for a given repo authored by the user with comments & conflict checks."""
    results = []
    headers = {"Authorization": f"Bearer {token}"}
    q = f'author.uuid="{DEFAULT_UUID}" AND state="OPEN"'
    query_encoded = urllib.parse.quote(q)
    fields = "values.id,values.title,values.state,values.draft,values.comment_count,values.source.commit.hash,values.destination.commit.hash,values.participants,values.links,values.updated_on"
    url = f"https://api.bitbucket.org/2.0/repositories/{DEFAULT_WORKSPACE}/{repo}/pullrequests?q={query_encoded}&fields={fields}"

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            for pr in data.get("values", []):
                parts = pr.get("participants") or []
                approvers = [
                    p.get("user", {}).get("display_name") or p.get("user", {}).get("nickname") or "Unknown"
                    for p in parts
                    if p.get("approved")
                ]
                pid = pr["id"]
                comments = pr.get("comment_count", 0)
                resolved_comments = 0
                open_comments = 0

                if comments > 0:
                    try:
                        c_url = f"https://api.bitbucket.org/2.0/repositories/{DEFAULT_WORKSPACE}/{repo}/pullrequests/{pid}/comments?fields=values.id,values.parent,values.resolution"
                        c_req = urllib.request.Request(c_url, headers=headers)
                        with urllib.request.urlopen(c_req, timeout=4) as c_resp:
                            c_data = json.loads(c_resp.read().decode("utf-8"))
                            c_vals = c_data.get("values", [])
                            resolved_comments = sum(1 for c in c_vals if "resolution" in c)
                            open_comments = sum(1 for c in c_vals if "resolution" not in c and c.get("parent") is None)
                    except Exception:
                        open_comments = comments

                src = pr.get("source", {}).get("commit", {}).get("hash")
                dst = pr.get("destination", {}).get("commit", {}).get("hash")

                has_conflict = False
                if local_path and src and dst:
                    try:
                        res = subprocess.run(
                            ["git", "-C", local_path, "merge-tree", dst, src],
                            capture_output=True, text=True, timeout=1
                        )
                        if "CONFLICT" in res.stdout or "changed in both" in res.stdout:
                            has_conflict = True
                    except Exception:
                        pass

                results.append({
                    "repo": repo,
                    "id": pid,
                    "title": pr.get("title", f"PR #{pid}").strip(),
                    "draft": pr.get("draft", False) or "[draft]" in pr.get("title", "").lower(),
                    "comments": comments,
                    "open_comments": open_comments,
                    "resolved_comments": resolved_comments,
                    "conflict": has_conflict,
                    "approvers": approvers,
                    "url": pr.get("links", {}).get("html", {}).get("href", f"https://bitbucket.org/{DEFAULT_WORKSPACE}/{repo}/pull-requests/{pid}"),
                    "updated_on": pr.get("updated_on", "")
                })
    except Exception:
        pass
    return results

def refresh_prs_worker():
    """Background worker to fetch all PRs and update cache."""
    global cached_prs, is_refreshing, last_status_msg
    token = get_bitbucket_token()
    if not token:
        last_status_msg = "No Bitbucket token found in ~/.git-credentials"
        return

    is_refreshing = True
    try:
        repos, curr_repo, local_paths = detect_repos()
        all_prs = []

        with ThreadPoolExecutor(max_workers=8) as ex:
            futures = [ex.submit(fetch_repo_prs, token, r, local_paths.get(r)) for r in repos]
            for f in futures:
                try:
                    all_prs.extend(f.result())
                except Exception:
                    pass

        # Sort: PRs for current repo first (if any), then PRs with conflicts, then approvals, then repo, PR id
        def sort_key(pr):
            is_curr = 0 if (curr_repo and pr["repo"] == curr_repo) else 1
            has_conf = 0 if pr.get("conflict") else 1
            has_approvals = 0 if len(pr.get("approvers", [])) > 0 else 1
            return (is_curr, has_conf, has_approvals, -len(pr.get("approvers", [])), pr["repo"], -pr["id"])

        all_prs.sort(key=sort_key)

        with prs_lock:
            # If rate limit or temporary network failure returned 0 PRs but we already have cached PRs, do not wipe cache!
            if not all_prs and cached_prs:
                last_status_msg = f"Refresh failed (retaining {len(cached_prs)} cached PRs)"
            else:
                cached_prs = all_prs
                try:
                    with open(CACHE_FILE, "w") as f:
                        json.dump({"timestamp": time.time(), "prs": all_prs}, f)
                except Exception:
                    pass
                last_status_msg = f"Updated {time.strftime('%I:%M:%S %p')} · {len(all_prs)} active PRs"
    except Exception as e:
        last_status_msg = f"Fetch error: {e}"
    finally:
        is_refreshing = False

def load_cached_prs():
    """Load PRs from disk cache if available."""
    global cached_prs, last_status_msg
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                data = json.load(f)
                cached_prs = data.get("prs", [])
                age = int(time.time() - data.get("timestamp", 0))
                last_status_msg = f"Cached ({age}s ago) · {len(cached_prs)} active PRs"
        except Exception:
            pass

def str_width(s):
    """Calculate visible terminal column width, stripping ANSI and accounting for emojis."""
    clean = re.sub(r'\033\[[0-9;]*[a-zA-Z]', '', s)
    width = 0
    for ch in clean:
        w = unicodedata.east_asian_width(ch)
        if w in ('W', 'F') or ord(ch) >= 0x1F300:
            width += 2
        else:
            width += 1
    return width

def render_box_line(content, cols, left="", right=""):
    return f"{content}\033[K"

def render():
    """Render the Bitbucket PR panel with Tokyo Night borders and styling."""
    global scroll_offset, selected_idx

    cols, rows = shutil.get_terminal_size((70, 14))
    cols = max(30, cols)
    rows = max(6, rows)

    with prs_lock:
        prs = list(cached_prs)
        stat = last_status_msg
        refreshing = is_refreshing

    # Clamp selection
    if prs:
        selected_idx = max(0, min(selected_idx, len(prs) - 1))
    else:
        selected_idx = 0

    # Calculate visible rows for the list
    header_rows = 2  # Top border + column header
    footer_rows = 2  # Bottom info + bottom border
    visible_list_height = max(1, rows - header_rows - footer_rows)

    # Adjust scroll offset to keep selected_idx visible
    if selected_idx < scroll_offset:
        scroll_offset = selected_idx
    elif selected_idx >= scroll_offset + visible_list_height:
        scroll_offset = selected_idx - visible_list_height + 1

    buf = []
    # Cursor home & hide
    buf.append("\033[H\033[?25l")

    # 1. Top border with Watch Dogs ctOS title
    spin = " ⟳" if refreshing else ""
    title_disp = f" {C_CYAN}{C_BOLD}⌁ [ctOS // BITBUCKET_PR_MATRIX]{C_RESET}{C_RED}{C_BOLD} [{len(prs)}]{C_YELLOW}{spin}{C_RESET}{C_MUTED} "
    title_w = str_width(f" ⌁ [ctOS // BITBUCKET_PR_MATRIX] [{len(prs)}]{spin} ")
    pad_len = max(0, cols - 2 - title_w)
    buf.append(f"{title_disp}\033[K")

    if cols < 72:
        c_repo_w  = 11
        c_id_w    = 5
        c_stat_w  = 5
        c_title_w = 14
        c_comm_w  = 4
        c_res_w   = 4
        c_app_w   = 4
        c_conf_w  = 3
        res_hdr   = "RES "
        conf_hdr  = "⚠️ "
    else:
        c_repo_w  = 13
        c_id_w    = 5
        c_stat_w  = 5
        c_title_w = min(16, max(12, cols - 60))
        c_comm_w  = 4
        c_res_w   = 6
        c_app_w   = 4
        c_conf_w  = 8
        res_hdr   = "RESOLV"
        conf_hdr  = "CONFLICT"

    # 2. Column Headers
    h_comm = f"💬{' ' * (c_comm_w - 2)}"
    header_line = f"  {C_MUTED}{'REPO':<{c_repo_w}} {'PR':<{c_id_w}} {'STATUS':<{c_stat_w}} {'TITLE':<{c_title_w}} {h_comm} {res_hdr:<{c_res_w}} {'APPR':<{c_app_w}} {conf_hdr:<{c_conf_w}}{C_RESET}"
    buf.append(render_box_line(header_line, cols))

    # 3. List PR items
    if not prs:
        empty_msg = "  No active PRs in draft/open status" if not refreshing else "  Fetching Bitbucket pull requests..."
        buf.append(render_box_line(f"{C_YELLOW}{empty_msg}{C_RESET}", cols))
        for _ in range(visible_list_height - 1):
            buf.append(render_box_line("", cols))
    else:
        visible_slice = prs[scroll_offset : scroll_offset + visible_list_height]
        for idx_rel, pr in enumerate(visible_slice):
            actual_idx = scroll_offset + idx_rel
            is_selected = (actual_idx == selected_idx)

            cursor = "❯ " if is_selected else "  "
            repo_disp = pr["repo"]
            if len(repo_disp) > c_repo_w:
                repo_disp = repo_disp[:c_repo_w - 2] + ".."
            repo_str = f"{repo_disp:<{c_repo_w}}"

            pr_id_str = f"#{pr['id']:<{c_id_w - 1}}"

            if pr["draft"]:
                stat_tag = f"{C_ORANGE}DRAFT{C_RESET}"
            else:
                stat_tag = f"{C_CYAN}OPEN {C_RESET}"

            # Open/Unresolved comments count
            open_comm = pr.get("open_comments", 0)
            if open_comm > 0:
                comm_disp = f"{C_YELLOW}💬{open_comm:<2}{C_RESET}"
            else:
                comm_disp = f"{C_GRAY}·0  {C_RESET}"

            # Resolved comments count
            res_comm = pr.get("resolved_comments", 0)
            if res_comm > 0:
                if cols >= 72:
                    res_disp = f"{C_GREEN}{C_BOLD}✓ {res_comm:<2}{C_RESET}  "
                else:
                    res_disp = f"{C_GREEN}{C_BOLD}✓{res_comm:<2}{C_RESET} "
            else:
                res_disp = f"{C_GRAY}· 0   {C_RESET}" if cols >= 72 else f"{C_GRAY}·0  {C_RESET}"

            # Approvers count
            approvers = pr.get("approvers", [])
            app_count = len(approvers)
            if app_count >= 2:
                app_disp = f"{C_GREEN}{C_BOLD}✓ {app_count:<2}{C_RESET}"
            elif app_count == 1:
                app_disp = f"{C_YELLOW}✓ {app_count:<2}{C_RESET}"
            else:
                app_disp = f"{C_GRAY}·0  {C_RESET}"

            # Merge Conflict status
            has_conflict = pr.get("conflict", False)
            if cols >= 72:
                if has_conflict:
                    conf_disp = f"{C_RED}{C_BOLD}⚠️ CONFL{C_RESET}"
                else:
                    conf_disp = f"{C_GREEN}clean   {C_RESET}"
            else:
                if has_conflict:
                    conf_disp = f"{C_RED}{C_BOLD}⚠️ {C_RESET}"
                else:
                    conf_disp = f"{C_GRAY}·  {C_RESET}"

            # Decreased title width for full column readability
            title_text = pr["title"]
            if len(title_text) > c_title_w:
                title_disp = title_text[:c_title_w - 2] + ".."
            else:
                title_disp = title_text + (" " * (c_title_w - len(title_text)))

            if is_selected:
                row_content = (
                    f"{C_BG_SEL}{C_BLUE}{C_BOLD}{cursor}{C_PURPLE}{repo_str} "
                    f"{C_CYAN}{pr_id_str} {stat_tag} {C_TEXT}{title_disp} "
                    f"{comm_disp} {res_disp} {app_disp} {conf_disp}{C_RESET}"
                )
            else:
                row_content = (
                    f"{cursor}{C_PURPLE}{repo_str} {C_CYAN}{pr_id_str} "
                    f"{stat_tag} {C_TEXT}{title_disp} "
                    f"{comm_disp} {res_disp} {app_disp} {conf_disp}"
                )

            buf.append(render_box_line(row_content, cols))

        # Fill any extra blank lines
        filled = len(visible_slice)
        for _ in range(visible_list_height - filled):
            buf.append(render_box_line("", cols))

    # 4. Status / Hint Bar
    if prs and 0 <= selected_idx < len(prs):
        sel_pr = prs[selected_idx]
        apps = ", ".join(sel_pr["approvers"]) if sel_pr["approvers"] else "None yet"
        total_c = sel_pr.get("comments", 0)
        open_c = sel_pr.get("open_comments", 0)
        res_c = sel_pr.get("resolved_comments", 0)
        
        c_parts = []
        if open_c > 0:
            c_parts.append(f"{open_c} open")
        if res_c > 0:
            c_parts.append(f"{res_c} resolved")

        if not c_parts:
            comm_info = "💬 0 comments"
        else:
            comm_info = f"💬 {total_c} comments ({', '.join(c_parts)})"

        confl_tag = "⚠️ CONFLICT · " if sel_pr.get("conflict") else ""
        detail = f" {confl_tag}#{sel_pr['id']} {sel_pr['repo']}: {sel_pr['title']} · {comm_info} · Approvers ({len(sel_pr['approvers'])}): {apps}"
    else:
        detail = stat or "Active PRs dashboard"

    vis_d = str_width(detail)
    if vis_d > cols - 2:
        detail = detail[:cols - 5] + "..."
        vis_d = str_width(detail)
    d_pad = max(0, cols - 2 - vis_d)
    buf.append(f"{C_MUTED}{detail}{C_RESET}\033[K")

    # 5. Footer Controls
    hint = " [↑/↓/j/k] Select  [Enter/o] Open Browser  [r] Refresh  [q] Quit"
    if str_width(hint) > cols - 2:
        hint = " [Enter] Open [r] Refresh [q] Quit"
    vis_h = str_width(hint)
    h_pad = max(0, cols - 2 - vis_h)
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
                lbl = f"{C_RED}{C_BOLD} ✖ [ctOS // BITBUCKET_PRS :: LOCKED] {C_RESET}" if st_mode == "FAILED" else f"\033[38;2;0;165;200m{C_BOLD}  [ctOS // BITBUCKET_PRS :: SCANNING FACE_ID] {C_RESET}"
                pad_l = max(0, (cols - 46) // 2)
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

def cleanup(sig=None, frame=None):
    """Restore terminal settings and show cursor before exit."""
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

def open_selected():
    """Open the currently selected PR in the default browser."""
    with prs_lock:
        if cached_prs and 0 <= selected_idx < len(cached_prs):
            url = cached_prs[selected_idx].get("url")
            if url:
                try:
                    subprocess.Popen(
                        ["xdg-open", url],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                except Exception:
                    pass

def main():
    global selected_idx, scroll_offset, running, original_termios

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    load_cached_prs()

    # If --once, fetch or use cache, print formatted table, and exit
    if "--once" in sys.argv:
        if not cached_prs:
            refresh_prs_worker()
        render()
        cleanup()

    # Start background auto-refresh worker
    def auto_refresh_loop():
        while running:
            refresh_prs_worker()
            for _ in range(CACHE_TTL):
                if not running:
                    break
                time.sleep(1)

    t_worker = threading.Thread(target=auto_refresh_loop, daemon=True)
    t_worker.start()

    # Check if standard input is an interactive terminal
    if not sys.stdin.isatty():
        while running:
            render()
            time.sleep(2)
        return

    # Enter raw terminal mode, alternate screen, disable line wrap, enable mouse tracking
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
                if ch == "\x1b":  # Escape sequence
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
                elif ch in ("r", "R"):
                    t_manual = threading.Thread(target=refresh_prs_worker, daemon=True)
                    t_manual.start()
                    render()
                elif ch in ("q", "Q"):
                    break
            else:
                render()
    finally:
        cleanup()

if __name__ == "__main__":
    main()
