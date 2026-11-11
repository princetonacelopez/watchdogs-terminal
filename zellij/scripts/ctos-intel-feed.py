#!/usr/bin/env python3
"""
ctos-intel-feed: Watch Dogs ctOS 2.0 // Dedicated Live X (Twitter) Feed & Media Viewer
100% Free & No Cost (uses local Google Chrome x.com session via ctos-x-auth).
Features:
  • Full-panel X.com Feed (FOR_YOU | FOLLOWING | BOOKMARKS)
  • Expanded X Post Card for the selected tweet with FULL multi-paragraph tweet text,
    quoted-tweet box, and full x.com engagement metrics (💬 replies, ↻ reposts, ♥ likes, 👁 views)
  • Inline TrueColor Half-Block (▀) Photo & Video Thumbnail display (plus ctOS Braille Hologram mode)
  • Multi-image carousel ([m] to cycle photos 1/N on multi-photo posts)
  • Full-Pane Reader / Media Zoom mode ([Space] / [f])

Controls:
  [j / k] or [↑ / ↓] : Next / Previous Post
  [t]                : Switch Feed Tab (FOR_YOU -> FOLLOWING -> BOOKMARKS)
  [Space / f]        : Toggle Full-Pane Focus (larger image + longform reader)
  [m]                : Cycle next photo on multi-image posts (1/N)
  [i]                : Cycle Image Renderer (PHOTO -> CTOS_BRAILLE -> OFF)
  [u / d]            : Scroll text up/down on longform posts
  [Enter / o]        : Open post in Google Chrome
  [r]                : Refresh X feed
  [a]                : Re-sync Google Chrome X session (ctos-x-auth)
"""

import base64
import email.utils
import hashlib
import html
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
import textwrap
import threading
import time
import tty
import unicodedata
import urllib.parse

import httpx
from PIL import Image, ImageEnhance, ImageOps

# Watch Dogs ctOS 2.0 TrueColor ANSI Palette
R         = "\033[0m"
B         = "\033[1m"
I         = "\033[3m"

C_CYAN    = "\033[38;2;0;240;255m"     # #00F0FF ctOS Electric Cyan
C_CRIMSON = "\033[38;2;255;0;85m"      # #FF0055 DedSec Intrusion Red
C_MINT    = "\033[38;2;0;255;156m"     # #00FF9C Access Granted Mint
C_AMBER   = "\033[38;2;255;214;0m"     # #FFD600 Profiler Warning Amber
C_PURPLE  = "\033[38;2;214;0;255m"     # #D600FF DedSec Glitch Purple
C_BLUE    = "\033[38;2;0;168;255m"     # #00A8FF ctOS Data Blue
C_WHITE   = "\033[38;2;226;241;255m"   # #E2F1FF Ice White
C_SILVER  = "\033[38;2;180;205;228m"   # #B4CDE4 Secondary Text
C_SLATE   = "\033[38;2;105;130;155m"   # #69829B Muted Metadata
C_GRID    = "\033[38;2;30;46;66m"      # #1E2E42 Hairline Divider
BG_CARD   = "\033[48;2;12;18;28m"      # #0C121C Expanded Post Card BG
BG_TAB    = "\033[48;2;0;240;255m\033[38;2;7;9;14m"

SESSION_FILE    = os.path.expanduser("~/.config/zellij/x_session.json")
X_CACHE_FILE    = "/tmp/ctos_x_feed_v3_cache.json"
MEDIA_CACHE_DIR = "/tmp/ctos_x_media_cache"
X_AUTH_BIN      = os.path.expanduser("~/.local/bin/ctos-x-auth")
FEED_TTL        = 300  # 5 minutes auto-refresh

FEED_MODES = ["FOR_YOU", "FOLLOWING"]
MODE_TO_GQL = {
    "FOR_YOU":   "HomeTimeline",
    "FOLLOWING": "HomeLatestTimeline",
}
IMG_MODES = ["ON", "OFF"]

USER_AGENT = (
    "Mozilla/5.0 (X11; Fedora; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)

FALLBACK_TWEETS = [
    {
        "id": "0",
        "handle": "ctOS_Uplink",
        "name": "ctOS X Feed",
        "reposted_by": "",
        "text": "Loading your live X.com feed...\nPress [r] to refresh or [a] to re-sync your Google Chrome X session.",
        "likes": 0,
        "retweets": 0,
        "replies": 0,
        "views": 0,
        "age": "now",
        "media": [],
        "quoted": None,
        "url": "https://x.com/home",
    }
]

os.makedirs(MEDIA_CACHE_DIR, exist_ok=True)

state_lock        = threading.Lock()
x_feeds           = {m: [] for m in FEED_MODES}
selected_idx      = 0
mode_idx          = 0
img_mode_idx      = 0       # 0=FULL_HD (Full Uncropped TrueColor Solid Block), 1=OFF
focus_mode        = False   # [Space]/[f] expands current post to fill 100% of the pane
media_idx         = 0       # [m] cycles photos 1..N on the selected post
text_scroll       = 0       # [u]/[d] scrolls longform tweet text
is_fetching       = False
running           = True
original_termios  = None

# Rendered ANSI image cache: (url, width, height_rows, mode_str) -> list[str]
rendered_img_cache = {}
downloading_urls   = set()


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


def rel_time(ts: float) -> str:
    diff = max(0, int(time.time() - ts))
    if diff < 60:
        return f"{diff}s"
    elif diff < 3600:
        return f"{diff // 60}m"
    elif diff < 86400:
        return f"{diff // 3600}h"
    else:
        return f"{diff // 86400}d"


def fmt_count(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def parse_twitter_date(created_at: str) -> str:
    if not created_at:
        return ""
    try:
        dt = email.utils.parsedate_to_datetime(created_at)
        return rel_time(dt.timestamp())
    except Exception:
        return ""


def clean_tweet_text(raw_text: str) -> str:
    txt = html.unescape(raw_text or "")
    # Strip t.co media/quote shortlinks
    txt = re.sub(r"https?://t\.co/[A-Za-z0-9]+", "", txt)
    # Normalize multiple blank lines while preserving paragraph newlines!
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in txt.splitlines()]
    cleaned_lines = []
    prev_empty = False
    for ln in lines:
        if not ln:
            if not prev_empty and cleaned_lines:
                cleaned_lines.append("")
            prev_empty = True
        else:
            cleaned_lines.append(ln)
            prev_empty = False
    while cleaned_lines and not cleaned_lines[-1]:
        cleaned_lines.pop()
    return "\n".join(cleaned_lines)


def wrap_Full_text(text: str, width: int) -> list:
    """Wrap full multi-paragraph tweet text strictly to `width` display columns (CJK & Emoji safe)."""
    width = max(10, width)
    out = []
    for para in (text or "").split("\n"):
        if not para.strip():
            if out and out[-1] != "":
                out.append("")
            continue
        cur_line = []
        cur_w = 0
        # Split into tokens (keeping CJK characters individually wrappable and ASCII words grouped)
        tokens = re.findall(r"[A-Za-z0-9_@#/.\-:?!,'\"+]+|\s+|.", para)
        for tok in tokens:
            if tok.isspace():
                if cur_w > 0 and cur_w + 1 <= width:
                    cur_line.append(" ")
                    cur_w += 1
                continue
            tw = str_width(tok)
            if cur_w + tw <= width:
                cur_line.append(tok)
                cur_w += tw
            elif tw <= width:
                if cur_line:
                    out.append("".join(cur_line).rstrip())
                cur_line = [tok]
                cur_w = tw
            else:
                # Token itself is wider than `width` — break character by character
                for ch in tok:
                    cw = char_width(ch)
                    if cur_w + cw > width and cur_line:
                        out.append("".join(cur_line).rstrip())
                        cur_line = [ch]
                        cur_w = cw
                    else:
                        cur_line.append(ch)
                        cur_w += cw
        if cur_line:
            out.append("".join(cur_line).rstrip())
    return out or [""]


def media_cache_path(url: str) -> str:
    h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
    return os.path.join(MEDIA_CACHE_DIR, f"{h}.img")


def download_media_async(url: str):
    if not url:
        return
    path = media_cache_path(url)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return
    with state_lock:
        if url in downloading_urls:
            return
        downloading_urls.add(url)

    def _worker():
        try:
            fetch_url = f"{url}?name=small" if "pbs.twimg.com/media/" in url and "?" not in url else url
            resp = httpx.get(
                fetch_url,
                headers={"User-Agent": USER_AGENT},
                follow_redirects=True,
                timeout=6.0,
            )
            if resp.status_code == 200 and resp.content:
                tmp = f"{path}.tmp.{os.getpid()}.{threading.get_ident()}"
                with open(tmp, "wb") as f:
                    f.write(resp.content)
                os.replace(tmp, path)
        except Exception:
            pass
        finally:
            with state_lock:
                downloading_urls.discard(url)

    threading.Thread(target=_worker, daemon=True).start()


def prepare_kitty_image(url: str, target_cols: int, max_rows: int, mode: str) -> tuple:
    """
    Prepare native Kitty Graphics Protocol (f=100 PNG) payload for real bitmap image rendering
    inside Ghostty + Zellij 0.45.1 (zero character block approximation).
    Returns: (status_str, w_cells, h_cells, pad_left_cols, kitty_escape_str)
    """
    if mode == "OFF" or not url or target_cols < 8 or max_rows < 3:
        return ("OFF", 0, 0, 0, "")

    cache_key = (url, target_cols, max_rows, mode, "v3_kitty_native")
    if cache_key in rendered_img_cache:
        return rendered_img_cache[cache_key]

    path = media_cache_path(url)
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        download_media_async(url)
        return ("LOADING", 0, 1, 0, "")

    try:
        img = Image.open(path).convert("RGB")
        orig_w, orig_h = img.size
        if orig_w <= 0 or orig_h <= 0:
            return ("OFF", 0, 0, 0, "")

        # Compute aspect-preserving cell dimensions (terminal cell aspect ~ 1:2)
        aspect = orig_h / float(orig_w)
        full_rows = max(4, int(round(target_cols * aspect * 0.50)))
        if full_rows <= max_rows:
            w_cells = target_cols
            h_cells = full_rows
        else:
            h_cells = max_rows
            w_cells = max(10, min(target_cols, int(round(h_cells / max(0.05, aspect * 0.50)))))

        pad_left_cols = max(0, (target_cols - w_cells) // 2)

        # Resize to crisp native bitmap pixels (up to 480px wide) and encode as PNG for Kitty Graphics Protocol
        target_px_w = min(orig_w, max(240, w_cells * 12))
        target_px_h = max(1, int(round(target_px_w * aspect)))
        if (target_px_w, target_px_h) != (orig_w, orig_h):
            img_out = img.resize((target_px_w, target_px_h), resample=Image.Resampling.LANCZOS)
        else:
            img_out = img

        bio = io.BytesIO()
        img_out.save(bio, format="PNG", optimize=True)
        b64_data = base64.b64encode(bio.getvalue()).decode("ascii")

        chunks = []
        chunk_size = 4096
        total_len = len(b64_data)
        for i in range(0, total_len, chunk_size):
            part = b64_data[i : i + chunk_size]
            more = 1 if (i + chunk_size < total_len) else 0
            if i == 0:
                chunks.append(
                    f"\033_Ga=T,f=100,t=d,i=11,p=1,c={w_cells},r={h_cells},C=1,q=2,m={more};{part}\033\\"
                )
            else:
                chunks.append(f"\033_Gm={more};{part}\033\\")

        res = ("READY", w_cells, h_cells, pad_left_cols, "".join(chunks))
        rendered_img_cache[cache_key] = res
        return res
    except Exception:
        return ("OFF", 0, 0, 0, "")


def ensure_x_session(force_sync: bool = False) -> dict:
    if not force_sync and os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data.get("auth_token") and data.get("ct0"):
                    return data
        except Exception:
            pass
    if os.path.exists(X_AUTH_BIN):
        try:
            subprocess.run([X_AUTH_BIN, "--quiet"], timeout=12)
            if os.path.exists(SESSION_FILE):
                with open(SESSION_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
    return {}


def extract_media_items(leg: dict) -> list:
    media_out = []
    seen_urls = set()
    raw_media = (
        leg.get("extended_entities", {}).get("media")
        or leg.get("entities", {}).get("media")
        or []
    )
    for m in raw_media:
        m_url = m.get("media_url_https") or m.get("media_url") or ""
        m_type = m.get("type") or "photo"
        if m_url and m_url not in seen_urls:
            seen_urls.add(m_url)
            media_out.append({"type": m_type, "url": m_url})
    return media_out


def extract_tweets_from_graphql(data: dict) -> list:
    tweets = []
    seen_ids = set()

    def extract_single(obj: dict) -> dict:
        t = obj.get("tweet") if obj.get("__typename") == "TweetWithVisibilityResults" else obj
        if not isinstance(t, dict):
            return {}
        leg = t.get("legacy")
        if not isinstance(leg, dict):
            return {}
        core_user = t.get("core", {}).get("user_results", {}).get("result", {})
        u_handle = (
            core_user.get("core", {}).get("screen_name")
            or core_user.get("legacy", {}).get("screen_name")
            or ""
        )
        u_name = (
            core_user.get("core", {}).get("name")
            or core_user.get("legacy", {}).get("name")
            or u_handle
        )
        note_txt = (
            t.get("note_tweet", {})
            .get("note_tweet_results", {})
            .get("result", {})
            .get("text")
        )
        raw_text = note_txt or leg.get("full_text") or ""
        txt = clean_tweet_text(raw_text)
        media = extract_media_items(leg)
        views_str = t.get("views", {}).get("count") or "0"
        try:
            views = int(views_str)
        except ValueError:
            views = 0

        return {
            "id": leg.get("id_str") or t.get("rest_id") or "",
            "handle": u_handle,
            "name": u_name,
            "text": txt,
            "likes": int(leg.get("favorite_count") or 0),
            "retweets": int(leg.get("retweet_count") or 0),
            "replies": int(leg.get("reply_count") or 0),
            "views": views,
            "age": parse_twitter_date(leg.get("created_at") or ""),
            "media": media,
        }

    def parse_tweet_obj(obj: dict, reposted_by: str = ""):
        t = obj.get("tweet") if obj.get("__typename") == "TweetWithVisibilityResults" else obj
        if not isinstance(t, dict):
            return
        leg = t.get("legacy")
        if not isinstance(leg, dict):
            return

        rt_res = leg.get("retweeted_status_result", {}).get("result")
        core_user = t.get("core", {}).get("user_results", {}).get("result", {})
        u_handle = (
            core_user.get("core", {}).get("screen_name")
            or core_user.get("legacy", {}).get("screen_name")
            or ""
        )
        if isinstance(rt_res, dict) and not reposted_by:
            parse_tweet_obj(rt_res, reposted_by=u_handle)
            return

        info = extract_single(t)
        tid = info.get("id")
        if not tid or tid in seen_ids or not info.get("handle") or not info.get("text"):
            return

        seen_ids.add(tid)
        info["reposted_by"] = reposted_by
        info["url"] = f"https://x.com/{info['handle']}/status/{tid}"

        # Extract quoted tweet if present
        q_res = t.get("quoted_status_result", {}).get("result")
        quoted = extract_single(q_res) if isinstance(q_res, dict) else {}
        if quoted.get("handle") and quoted.get("text"):
            info["quoted"] = {
                "handle": quoted["handle"],
                "name": quoted["name"],
                "text": quoted["text"],
                "age": quoted["age"],
            }
            if not info["media"] and quoted.get("media"):
                info["media"] = quoted["media"]
        else:
            info["quoted"] = None

        tweets.append(info)

    def walk(node):
        if isinstance(node, dict):
            tname = node.get("__typename")
            if tname in ("Tweet", "TweetWithVisibilityResults") or (
                "legacy" in node and "core" in node and isinstance(node.get("legacy"), dict)
            ):
                parse_tweet_obj(node)
                return
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return tweets


def fetch_x_mode(mode: str, sess: dict) -> list:
    op = MODE_TO_GQL.get(mode, "HomeTimeline")
    ep = sess.get("endpoints", {}).get(op, {})
    qid = ep.get("queryId")
    features = (
        ep.get("features")
        or sess.get("endpoints", {}).get("HomeTimeline", {}).get("features", {})
    )
    if not qid:
        return []

    bearer = urllib.parse.unquote(sess.get("bearer", ""))
    headers = {
        "User-Agent": USER_AGENT,
        "Authorization": f"Bearer {bearer}",
        "x-csrf-token": sess["ct0"],
        "x-twitter-auth-type": "OAuth2Session",
        "x-twitter-active-user": "yes",
        "x-twitter-client-language": "en",
        "Content-Type": "application/json",
        "Referer": "https://x.com/home",
    }
    cookies = {
        "auth_token": sess["auth_token"],
        "ct0": sess["ct0"],
    }
    if sess.get("twid"):
        cookies["twid"] = sess["twid"]

    if op == "Bookmarks":
        variables = {"count": 25, "includePromotedContent": False}
    else:
        variables = {
            "count": 25,
            "includePromotedContent": False,
            "latestControlAvailable": True,
            "requestContext": "launch",
            "withCommunity": True,
        }

    url = (
        f"https://x.com/i/api/graphql/{qid}/{op}"
        f"?variables={urllib.parse.quote(json.dumps(variables))}"
        f"&features={urllib.parse.quote(json.dumps(features))}"
    )
    resp = httpx.get(url, headers=headers, cookies=cookies, timeout=10.0)
    if resp.status_code in (401, 403, 404):
        raise RuntimeError(f"HTTP_{resp.status_code}")
    resp.raise_for_status()
    return extract_tweets_from_graphql(resp.json())


def prefetch_top_media(items: list, limit: int = 5):
    count = 0
    for it in items:
        for m in it.get("media") or []:
            if m.get("url"):
                download_media_async(m["url"])
                count += 1
                if count >= limit:
                    return


def fetch_all_x_feeds(force_auth_sync: bool = False):
    global is_fetching
    is_fetching = True
    try:
        sess = ensure_x_session(force_sync=force_auth_sync)
        if not sess.get("auth_token"):
            return

        updated_any = False
        for idx, mode in enumerate(FEED_MODES):
            try:
                items = fetch_x_mode(mode, sess)
            except RuntimeError:
                if idx == 0 and not force_auth_sync:
                    sess = ensure_x_session(force_sync=True)
                    try:
                        items = fetch_x_mode(mode, sess)
                    except Exception:
                        items = []
                else:
                    items = []
            except Exception:
                items = []

            if items:
                with state_lock:
                    x_feeds[mode] = items
                if idx == 0:
                    prefetch_top_media(items, limit=6)
                updated_any = True

        if updated_any:
            try:
                with state_lock:
                    cache_payload = {"timestamp": time.time(), "feeds": dict(x_feeds)}
                with open(X_CACHE_FILE, "w", encoding="utf-8") as f:
                    json.dump(cache_payload, f)
            except Exception:
                pass
    finally:
        is_fetching = False


def load_cached_x_feeds() -> bool:
    if os.path.exists(X_CACHE_FILE):
        try:
            with open(X_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            feeds = data.get("feeds", {})
            if isinstance(feeds, dict) and any(feeds.values()):
                with state_lock:
                    for m in FEED_MODES:
                        if feeds.get(m):
                            x_feeds[m] = feeds[m]
                prefetch_top_media(x_feeds.get("FOR_YOU") or [], limit=6)
                return time.time() - data.get("timestamp", 0) < FEED_TTL
        except Exception:
            pass
    return False


def feed_worker_loop():
    fresh = load_cached_x_feeds()
    if not fresh:
        fetch_all_x_feeds(force_auth_sync=False)
    while running:
        for _ in range(FEED_TTL):
            if not running:
                return
            time.sleep(1)
        fetch_all_x_feeds(force_auth_sync=False)


def get_active_tweets() -> list:
    mode = FEED_MODES[mode_idx % len(FEED_MODES)]
    with state_lock:
        items = list(x_feeds.get(mode) or [])
    return items if items else list(FALLBACK_TWEETS)


def open_selected_tweet():
    items = get_active_tweets()
    if items and 0 <= selected_idx < len(items):
        url = items[selected_idx].get("url")
        if url:
            try:
                subprocess.Popen(
                    ["xdg-open", url],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                pass


def render():
    global selected_idx, media_idx, text_scroll

    cols, rows = shutil.get_terminal_size((36, 28))
    cols = max(22, cols)
    rows = max(12, rows)
    inner_w = max(16, cols - 2)

    buf = []

    # 1. TOP X_FEED MODE TABS BAR (FOR YOU | FOLLOWING)
    active_mode = FEED_MODES[mode_idx % len(FEED_MODES)]
    tab_labels = {"FOR_YOU": "FOR YOU", "FOLLOWING": "FOLLOWING"}
    tab_spans = []
    for m in FEED_MODES:
        lbl = tab_labels[m]
        if m == active_mode:
            tab_spans.append(f"{BG_TAB}{B} {lbl} {R}")
        else:
            tab_spans.append(f"{C_SLATE}{lbl}{R}")
    spin = f" {C_AMBER}⟳{R}" if is_fetching else ""
    buf.append(f" {C_CRIMSON}{B}𝕏{R} " + f" {C_GRID}│{R} ".join(tab_spans) + f"{spin}\033[K")
    buf.append(f" {C_GRID}{'━' * inner_w}{R}\033[K")

    tweets = get_active_tweets()
    if tweets:
        selected_idx = max(0, min(selected_idx, len(tweets) - 1))

    # Pre-fetch media for current & next 2 tweets so scrolling feels instant
    for nxt_i in range(selected_idx, min(len(tweets), selected_idx + 3)):
        for m in tweets[nxt_i].get("media") or []:
            if m.get("url"):
                download_media_async(m["url"])

    cur = tweets[selected_idx]
    cur_media = cur.get("media") or []
    img_mode = IMG_MODES[img_mode_idx % len(IMG_MODES)]

    # 2. EXPANDED SELECTED POST CARD (Full Tweet Text + Native Bitmap Image Preview + Engagement Bar)
    reposted = cur.get("reposted_by") or ""
    if reposted:
        buf.append(f"{BG_CARD} {C_MINT}↻ Reposted by @{clip_plain(reposted, inner_w - 16)}{R}\033[K")

    name_str = clip_plain(cur.get("name") or cur.get("handle") or "X", max(8, inner_w - 16))
    handle_str = f"@{cur.get('handle', 'x')}"
    age_str = f"· {cur.get('age')}" if cur.get("age") else ""
    pos_badge = f"[{selected_idx + 1}/{len(tweets)}]"
    buf.append(
        f"{BG_CARD} {C_CYAN}{B}❯ {name_str}{R}{BG_CARD} {C_SLATE}{age_str} {pos_badge}{R}\033[K"
    )
    buf.append(f"{BG_CARD}   {C_BLUE}{clip_plain(handle_str, inner_w - 3)}{R}\033[K")

    # Full wrapped tweet text
    wrapped_lines = wrap_Full_text(cur.get("text") or "", inner_w - 2)
    quoted = cur.get("quoted")
    if quoted and quoted.get("text"):
        wrapped_lines.append("")
        q_head = f"╭ @{quoted.get('handle')} · {quoted.get('age', '')}"
        wrapped_lines.append(clip_plain(q_head, inner_w - 2))
        for q_ln in wrap_Full_text(quoted["text"], inner_w - 4)[:4]:
            wrapped_lines.append(f"│ {q_ln}")

    # Budget vertical rows between Full Text, Native Image, and Upcoming Stream
    avail_for_card = rows - len(buf) - 2 if focus_mode else max(12, int((rows - len(buf) - 2) * 0.78))
    has_media = bool(cur_media) and img_mode != "OFF"
    img_budget = 0
    if has_media:
        img_budget = max(7, min(rows - 7 if focus_mode else 13, avail_for_card - min(len(wrapped_lines), 5) - 2))

    max_txt_lines = max(3, avail_for_card - (img_budget + 1 if has_media else 0) - 1)
    if text_scroll > max(0, len(wrapped_lines) - max_txt_lines):
        text_scroll = max(0, len(wrapped_lines) - max_txt_lines)
    text_scroll = max(0, text_scroll)

    visible_txt = wrapped_lines[text_scroll : text_scroll + max_txt_lines]
    for ln in visible_txt:
        if ln.startswith(("╭ @", "│ ")):
            buf.append(f"{BG_CARD}  {C_PURPLE}{ln}{R}\033[K")
        else:
            buf.append(f"{BG_CARD}  {C_WHITE}{ln}{R}\033[K")

    if len(wrapped_lines) > max_txt_lines:
        more_cnt = len(wrapped_lines) - (text_scroll + len(visible_txt))
        if more_cnt > 0:
            buf.append(f"{BG_CARD}  {C_AMBER}▾ +{more_cnt} more lines ([d/u] scroll text){R}\033[K")

    # Native Bitmap Image / Video Thumbnail Preview via Kitty Graphics Protocol
    kitty_placement_cmd = ""
    img_status = "OFF"
    img_url = ""
    if has_media and img_budget >= 4:
        m_idx = media_idx % len(cur_media)
        m_item = cur_media[m_idx]
        img_url = m_item.get("url", "")
        m_type = m_item.get("type", "photo")
        m_icon = "▶ VIDEO" if m_type in ("video", "animated_gif") else "📷 PHOTO"
        m_count_str = f" [{m_idx + 1}/{len(cur_media)}]" if len(cur_media) > 1 else ""
        m_hint = " [m]Next" if len(cur_media) > 1 else ""
        buf.append(
            f"{BG_CARD}  {C_AMBER}{B}{m_icon}{m_count_str}{R}{BG_CARD} {C_SLATE}[i]IMG:{img_mode}{m_hint}{R}\033[K"
        )
        img_status, w_cells, h_cells, pad_left_cols, kitty_esc = prepare_kitty_image(
            img_url,
            target_cols=max(10, inner_w - 2),
            max_rows=img_budget - 1,
            mode=img_mode,
        )
        if img_status == "LOADING":
            buf.append(f"{BG_CARD}  {C_SLATE}⟳ [ctOS // LOADING IMAGE...]{R}\033[K")
        elif img_status == "READY" and h_cells > 0:
            img_start_row = len(buf) + 1  # 1-indexed terminal row
            img_start_col = 3 + pad_left_cols  # 1-indexed terminal col
            for _ in range(h_cells):
                buf.append(f"{BG_CARD}{' ' * inner_w}{R}\033[K")
            kitty_placement_cmd = f"\033[{img_start_row};{img_start_col}H{kitty_esc}"

    # Engagement metrics bar (💬 replies, ↻ reposts, ♥ likes, 👁 views)
    rep_s = fmt_count(int(cur.get("replies", 0)))
    rt_s  = fmt_count(int(cur.get("retweets", 0)))
    lk_s  = fmt_count(int(cur.get("likes", 0)))
    vw_s  = fmt_count(int(cur.get("views", 0)))
    stats_bar = f" {C_BLUE}💬 {rep_s}{R}{BG_CARD}  {C_MINT}↻ {rt_s}{R}{BG_CARD}  {C_CRIMSON}♥ {lk_s}{R}"
    if cur.get("views"):
        stats_bar += f"{BG_CARD}  {C_SLATE}👁 {vw_s}{R}"
    buf.append(f"{BG_CARD}{stats_bar}\033[K")
    buf.append(f" {C_GRID}{'━' * inner_w}{R}\033[K")

    # 3. UPCOMING FEED STREAM (below the expanded post card)
    rem_rows = rows - len(buf) - 1
    if not focus_mode and rem_rows >= 2:
        next_slots = rem_rows // 2
        for idx in range(selected_idx + 1, min(len(tweets), selected_idx + 1 + next_slots)):
            it = tweets[idx]
            h_str = f"@{it.get('handle', 'x')}"
            a_str = f"·{it.get('age')}" if it.get("age") else ""
            m_tag = " 📷" if it.get("media") else ""
            lk_tag = f"♥{fmt_count(int(it.get('likes', 0)))}"
            meta_w = str_width(a_str) + str_width(m_tag) + str_width(lk_tag)
            max_h = max(6, inner_w - meta_w - 2)
            h_clip = clip_plain(h_str, max_h)
            pad = max(1, inner_w - str_width(h_clip) - meta_w - 1)
            buf.append(
                f" {C_BLUE}{B}{h_clip}{R}{C_SLATE}{a_str}{C_AMBER}{m_tag}{' ' * pad}{C_SLATE}{lk_tag}{R}\033[K"
            )
            buf.append(f"  {C_SILVER}{clip_plain(it.get('text', ''), inner_w - 2)}{R}\033[K")

    while len(buf) < rows - 1:
        buf.append("\033[K")
    hint = clip_plain(" [j/k]Post [t]Tab [Spc]Zoom [i]Img [Enter]Open", cols - 1)
    buf.append(f"{C_SLATE}{hint}{R}\033[K")

    # Check if FaceID modal is currently scanning or waiting for modal exit
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
                    f"{C_CRIMSON}{B} ✖ BIOMETRIC LOCKED {R}"
                    if st_mode == "FAILED"
                    else f"\033[38;2;0;165;200m{B}  SCANNING FACE_ID {R}"
                )
                pad_l = max(0, (cols - 20) // 2)
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
        active_mode,
        selected_idx,
        cur.get("id"),
        media_idx,
        img_mode,
        img_status,
        img_url,
        focus_mode,
        text_scroll,
        is_fetching,
        len(tweets),
    )
    if getattr(render, "_last_sig", None) == frame_sig and "--once" not in sys.argv:
        return
    render._last_sig = frame_sig

    out_str = "\033_Ga=d,d=A,q=2\033\\\033[H\033[?25l" + "\n".join(buf[:rows]) + "\033[J"
    if kitty_placement_cmd and "--no-kitty" not in sys.argv:
        out_str += kitty_placement_cmd
    sys.stdout.write(out_str)
    sys.stdout.flush()


def main():
    global selected_idx, mode_idx, img_mode_idx, focus_mode, media_idx, text_scroll, original_termios

    if "--once" in sys.argv:
        if not load_cached_x_feeds():
            fetch_all_x_feeds(force_auth_sync=False)
        # Wait briefly for top media thumbnail download so --once shows inline photo
        time.sleep(0.8)
        render()
        cleanup()

    t_feed = threading.Thread(target=feed_worker_loop, daemon=True)
    t_feed.start()

    if sys.stdin.isatty():
        try:
            original_termios = termios.tcgetattr(sys.stdin.fileno())
            tty.setcbreak(sys.stdin.fileno())
            sys.stdout.write("\033[?1049h\033[?7l\033[3J\033[?1000h\033[?1006h")
            sys.stdout.flush()
        except Exception:
            original_termios = None

    init_mtime = os.path.getmtime(os.path.abspath(__file__)) if os.path.exists(__file__) else 0
    render()
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
            wait_t = 0.05 if getattr(render, "_was_locked", False) else 0.6
            rlist, _, _ = select.select([sys.stdin], [], [], wait_t)
            if rlist:
                ch = sys.stdin.read(1)
                if ch == "\x1b":
                    seq = ""
                    while select.select([sys.stdin], [], [], 0.005)[0]:
                        seq += sys.stdin.read(1)
                    if seq in ("[A", "OA") or (seq.startswith("[<64;") and seq.endswith("M")):
                        selected_idx = max(0, selected_idx - 1)
                        media_idx = 0
                        text_scroll = 0
                    elif seq in ("[B", "OB") or (seq.startswith("[<65;") and seq.endswith("M")):
                        tweets = get_active_tweets()
                        selected_idx = max(0, min(len(tweets) - 1, selected_idx + 1))
                        media_idx = 0
                        text_scroll = 0
                elif ch in ("k", "K"):
                    selected_idx = max(0, selected_idx - 1)
                    media_idx = 0
                    text_scroll = 0
                elif ch in ("j", "J"):
                    tweets = get_active_tweets()
                    selected_idx = max(0, min(len(tweets) - 1, selected_idx + 1))
                    media_idx = 0
                    text_scroll = 0
                elif ch in ("t", "T"):
                    mode_idx = (mode_idx + 1) % len(FEED_MODES)
                    selected_idx = 0
                    media_idx = 0
                    text_scroll = 0
                elif ch in (" ", "f", "F"):
                    focus_mode = not focus_mode
                elif ch in ("m", "M"):
                    media_idx += 1
                elif ch in ("i", "I"):
                    img_mode_idx = (img_mode_idx + 1) % len(IMG_MODES)
                elif ch in ("d", "D"):
                    text_scroll += 2
                elif ch in ("u", "U"):
                    text_scroll = max(0, text_scroll - 2)
                elif ch in ("r", "R"):
                    threading.Thread(
                        target=fetch_all_x_feeds, kwargs={"force_auth_sync": False}, daemon=True
                    ).start()
                elif ch in ("a", "A"):
                    threading.Thread(
                        target=fetch_all_x_feeds, kwargs={"force_auth_sync": True}, daemon=True
                    ).start()
                elif ch in ("\r", "\n", "o", "O"):
                    open_selected_tweet()
                render()
            else:
                render()
        else:
            time.sleep(1.5)
            render()


if __name__ == "__main__":
    main()
